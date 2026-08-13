from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from .metadata import parse_no_intro_name
from .models import Platform, ScanResult
from .paths import config_dir, data_dir
from .platforms import platform_spec


RA_API_ROOT = "https://retroachievements.org/API"
RA_DEFAULT_REQUEST_DELAY_SECONDS = 1.0


@dataclass(frozen=True)
class RaPatchCandidate:
    game_id: int
    title: str | None
    md5: str
    hash_name: str | None
    labels: list[str]
    patch_url: str


def credentials_path() -> Path:
    return config_dir() / "ra_credentials.json"


def save_credentials(username: str, api_key: str) -> Path:
    path = credentials_path()
    path.write_text(json.dumps({"username": username, "api_key": api_key}, indent=2), encoding="utf-8")
    path.chmod(0o600)
    return path


def load_credentials(username: str | None = None, api_key: str | None = None) -> tuple[str, str]:
    if username and api_key:
        return username, api_key
    path = credentials_path()
    if not path.exists():
        raise RuntimeError("RetroAchievements credentials are missing. Provide --username and --api-key once.")
    data = json.loads(path.read_text(encoding="utf-8"))
    return username or data["username"], api_key or data["api_key"]


def cache_path() -> Path:
    return data_dir() / "ra_cache.sqlite3"


def init_cache(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or cache_path())
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ra_hashes (
            platform TEXT NOT NULL,
            hash TEXT NOT NULL,
            game_id INTEGER NOT NULL,
            title TEXT,
            hash_name TEXT,
            labels TEXT,
            patch_url TEXT,
            PRIMARY KEY (platform, hash)
        )
        """
    )
    _ensure_column(conn, "ra_hashes", "hash_name", "TEXT")
    _ensure_column(conn, "ra_hashes", "labels", "TEXT")
    _ensure_column(conn, "ra_hashes", "patch_url", "TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ra_sync_meta (
            platform TEXT NOT NULL,
            kind TEXT NOT NULL,
            synced_at TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (platform, kind)
        )
        """
    )
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _store_sync_meta(conn: sqlite3.Connection, platform: Platform, kind: str, count: int) -> None:
    conn.execute(
        """
        INSERT INTO ra_sync_meta(platform, kind, synced_at, count) VALUES (?, ?, ?, ?)
        ON CONFLICT(platform, kind) DO UPDATE SET
            synced_at = excluded.synced_at,
            count = excluded.count
        """,
        (platform.value, kind, datetime.now(timezone.utc).isoformat(timespec="seconds"), count),
    )


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        query.append((key, "[hidden]" if key.lower() in {"y", "z"} else value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _request_json(endpoint: str, params: dict[str, object], *, max_retries: int = 6) -> object:
    url = f"{RA_API_ROOT}/{endpoint}"
    last_status = None
    for attempt in range(max_retries + 1):
        response = requests.get(url, params=params, timeout=60)
        last_status = response.status_code
        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            try:
                wait = float(retry_after) if retry_after else RA_DEFAULT_REQUEST_DELAY_SECONDS * (attempt + 2)
            except ValueError:
                wait = RA_DEFAULT_REQUEST_DELAY_SECONDS * (attempt + 2)
            if attempt >= max_retries:
                raise RuntimeError("RetroAchievements ha limitado temporalmente las peticiones. Espera unos minutos y reanuda; la caché conservará lo ya guardado.")
            time.sleep(min(wait, 60))
            continue
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(f"RetroAchievements devolvió HTTP {response.status_code} para {_safe_url(response.url)}") from exc
        return response.json()
    raise RuntimeError(f"No se pudo consultar RetroAchievements. Último estado HTTP: {last_status}.")


def sync_ra_hashes(platform: Platform, username: str | None = None, api_key: str | None = None) -> int:
    user, key = load_credentials(username, api_key)
    save_credentials(user, key)
    spec = platform_spec(platform)
    if spec.ra_console_id is None:
        raise RuntimeError(f"{spec.short_name} no tiene soporte RetroAchievements configurado todavia.")
    console_id = spec.ra_console_id
    rows = _request_json("API_GetGameList.php", {"z": user, "y": key, "i": console_id, "f": 1, "h": 1})
    conn = init_cache()
    count = 0
    with conn:
        for row in rows:
            game_id = int(row.get("ID") or row.get("GameID"))
            title = row.get("Title")
            hashes: Iterable[str] = row.get("Hashes") or row.get("MD5") or []
            if isinstance(hashes, str):
                hashes = [hashes]
            for hash_value in hashes:
                conn.execute(
                    """
                    INSERT INTO ra_hashes(platform, hash, game_id, title) VALUES (?, ?, ?, ?)
                    ON CONFLICT(platform, hash) DO UPDATE SET
                        game_id = excluded.game_id,
                        title = excluded.title
                    """,
                    (platform.value, hash_value.lower(), game_id, title),
                )
                count += 1
        _store_sync_meta(conn, platform, "hashes", count)
    conn.close()
    return count


def sync_ra_patch_details(
    platform: Platform,
    username: str | None = None,
    api_key: str | None = None,
    game_ids: Iterable[int] | None = None,
    limit: int | None = None,
    cache: Path | None = None,
    progress: Callable[[dict[str, int]], None] | None = None,
    request_delay: float | None = None,
) -> int:
    _user, key = load_credentials(username, api_key)
    conn = init_cache(cache)
    if game_ids is None:
        rows = conn.execute(
            """
            SELECT game_id
            FROM ra_hashes
            WHERE platform = ?
            GROUP BY game_id
            ORDER BY
                MAX(CASE WHEN
                    (hash_name IS NOT NULL AND hash_name != '')
                    OR (labels IS NOT NULL AND labels != '')
                    OR (patch_url IS NOT NULL AND patch_url != '')
                THEN 1 ELSE 0 END) ASC,
                game_id ASC
            """,
            (platform.value,),
        ).fetchall()
        game_ids = [int(row[0]) for row in rows]
    ids = list(dict.fromkeys(int(game_id) for game_id in game_ids))
    if limit is not None:
        ids = ids[:limit]
    updated = 0
    total = len(ids)
    if progress:
        progress({"current": 0, "total": total, "updated": 0})
    with conn:
        for index, game_id in enumerate(ids, start=1):
            payload = _request_json("API_GetGameHashes.php", {"y": key, "i": game_id})
            rows = payload.get("Results") or payload.get("results") or []
            for row in rows:
                md5 = (row.get("MD5") or row.get("md5") or "").lower()
                if not md5:
                    continue
                labels = row.get("Labels") or row.get("labels") or []
                if isinstance(labels, str):
                    labels = [labels]
                patch_url = row.get("PatchUrl") or row.get("patchUrl")
                hash_name = row.get("Name") or row.get("name")
                conn.execute(
                    """
                    UPDATE ra_hashes
                    SET hash_name = ?, labels = ?, patch_url = ?
                    WHERE platform = ? AND hash = ?
                    """,
                    (hash_name, json.dumps(labels), patch_url, platform.value, md5),
                )
                updated += 1
            if progress:
                progress({"current": index, "total": total, "updated": updated})
            time.sleep(request_delay if request_delay is not None else RA_DEFAULT_REQUEST_DELAY_SECONDS)
        _store_sync_meta(conn, platform, "details", updated)
    conn.close()
    return updated


def annotate_scan_with_ra(scan: ScanResult, cache: Path | None = None) -> ScanResult:
    conn = init_cache(cache)
    for rom in scan.roms:
        if not rom.hashes.ra_hash:
            continue
        row = conn.execute(
            "SELECT game_id, title, hash_name, labels, patch_url FROM ra_hashes WHERE platform = ? AND hash = ?",
            (rom.platform.value, rom.hashes.ra_hash.lower()),
        ).fetchone()
        if row:
            rom.ra_game_id = int(row[0])
            rom.ra_title = row[1]
            rom.ra_hash_name = row[2]
            rom.ra_labels = json.loads(row[3]) if row[3] else []
            rom.ra_patch_url = row[4]
    conn.close()
    return scan


def ra_cache_count(platform: Platform, cache: Path | None = None) -> int:
    conn = init_cache(cache)
    row = conn.execute("SELECT COUNT(*) FROM ra_hashes WHERE platform = ?", (platform.value,)).fetchone()
    conn.close()
    return int(row[0] if row else 0)


def ra_cached_game_count(platform: Platform, cache: Path | None = None) -> int:
    conn = init_cache(cache)
    row = conn.execute("SELECT COUNT(DISTINCT game_id) FROM ra_hashes WHERE platform = ?", (platform.value,)).fetchone()
    conn.close()
    return int(row[0] if row else 0)


def ra_detailed_game_count(platform: Platform, cache: Path | None = None) -> int:
    conn = init_cache(cache)
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT game_id)
        FROM ra_hashes
        WHERE platform = ? AND (
            hash_name IS NOT NULL AND hash_name != ''
            OR labels IS NOT NULL AND labels != ''
            OR patch_url IS NOT NULL AND patch_url != ''
        )
        """,
        (platform.value,),
    ).fetchone()
    conn.close()
    return int(row[0] if row else 0)


def ra_sync_status(platform: Platform, cache: Path | None = None) -> dict[str, str | int]:
    conn = init_cache(cache)
    rows = conn.execute(
        "SELECT kind, synced_at, count FROM ra_sync_meta WHERE platform = ?",
        (platform.value,),
    ).fetchall()
    conn.close()
    status: dict[str, str | int] = {}
    for kind, synced_at, count in rows:
        status[f"{kind}_at"] = synced_at
        status[f"{kind}_count"] = int(count)
    cached_games = ra_cached_game_count(platform, cache)
    detailed_games = ra_detailed_game_count(platform, cache)
    status["cached_games"] = cached_games
    status["detailed_games"] = detailed_games
    status["remaining_details"] = max(0, cached_games - detailed_games)
    return status


def find_ra_patch_candidates(platform: Platform, title: str, cache: Path | None = None) -> list[RaPatchCandidate]:
    normalized_title = _normalize_title(title)
    conn = init_cache(cache)
    rows = conn.execute(
        """
        SELECT game_id, title, hash, hash_name, labels, patch_url
        FROM ra_hashes
        WHERE platform = ? AND patch_url IS NOT NULL AND patch_url != ''
        ORDER BY title, hash_name
        """,
        (platform.value,),
    ).fetchall()
    conn.close()
    candidates: list[RaPatchCandidate] = []
    for row in rows:
        labels = json.loads(row[4]) if row[4] else []
        hash_title = parse_no_intro_name(row[3]).title if row[3] else ""
        if normalized_title not in {_normalize_title(row[1] or ""), _normalize_title(hash_title)}:
            continue
        candidates.append(
            RaPatchCandidate(
                game_id=int(row[0]),
                title=row[1],
                md5=row[2],
                hash_name=row[3],
                labels=labels,
                patch_url=row[5],
            )
        )
    return candidates


def _normalize_title(title: str) -> str:
    return " ".join(title.casefold().replace("-", " ").replace("_", " ").split())
