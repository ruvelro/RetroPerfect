"""Caché persistente de hashes de escaneo, indexada por contenedor, entrada, plataforma, tamaño y mtime."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .models import Platform, RomHash


class ScanHashCache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS file_hashes (
                container TEXT NOT NULL,
                inner TEXT NOT NULL DEFAULT '',
                platform TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                hashes TEXT NOT NULL,
                PRIMARY KEY (container, inner, platform)
            )
            """
        )

    def get(self, container: str, inner: str | None, platform: Platform, size: int, mtime_ns: int) -> RomHash | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT size, mtime_ns, hashes FROM file_hashes WHERE container = ? AND inner = ? AND platform = ?",
                (container, inner or "", platform.value),
            ).fetchone()
        if row is None or int(row[0]) != size or int(row[1]) != mtime_ns:
            return None
        return RomHash.model_validate_json(row[2])

    def put(self, container: str, inner: str | None, platform: Platform, size: int, mtime_ns: int, hashes: RomHash) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO file_hashes(container, inner, platform, size, mtime_ns, hashes) VALUES (?, ?, ?, ?, ?, ?)",
                (container, inner or "", platform.value, size, mtime_ns, hashes.model_dump_json()),
            )

    def close(self) -> None:
        with self.lock:
            self.conn.commit()
            self.conn.close()
