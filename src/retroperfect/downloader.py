"""Ejecución de un plan de descarga: bajar, verificar contra el DAT e instalar.

Nada entra en el romset sin pasar por el DAT. Lo descargado aterriza en un área
de trabajo (.retroperfect/downloads), se escanea con el mismo motor que el resto
de la app y solo se mueve al destino si el hash cuadra; si no, va a quarantine/
con el motivo, que es más útil que borrarlo a ciegas.
"""
from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from .dat import DatIndex
from .download_plan import DownloadCandidate, DownloadPlan, group_key
from .http import session
from .models import Platform
from .paths import project_state_dir
from .rom_sources import read_zip_member
from .scanner import scan_file

ProgressCallback = Callable[[dict[str, object]], None]
CancelCheck = Callable[[], bool]

CHUNK_SIZE = 1024 * 1024

# Los espejos públicos cortan las descargas agresivas: una conexión, y si el
# servidor responde 429 se respeta su Retry-After en vez de insistir.
MAX_RATE_LIMIT_WAIT_SECONDS = 120
RATE_LIMIT_RETRIES = 3

STATUS_LABELS = {
    "ok": "Descargado y verificado",
    "present": "Ya estaba en el destino",
    "mismatch": "No coincide con el DAT (en cuarentena)",
    "error": "Error de descarga",
    "cancelled": "Cancelado",
    "delegated": "Lo descarga tu cliente de torrent",
    "incomplete": "Aún no ha terminado de descargarse",
    "absent": "No aparece en la carpeta de descargas",
}


class DownloadOutcome(BaseModel):
    title: str
    file_name: str
    status: str
    detail: str = ""
    path: str | None = None
    bytes_downloaded: int = 0

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)


class DownloadReport(BaseModel):
    outcomes: list[DownloadOutcome] = Field(default_factory=list)

    @property
    def downloaded(self) -> int:
        return sum(1 for item in self.outcomes if item.status == "ok")

    @property
    def failed(self) -> int:
        return sum(1 for item in self.outcomes if item.status in {"error", "mismatch"})

    @property
    def total_bytes(self) -> int:
        return sum(item.bytes_downloaded for item in self.outcomes)


def staging_dir(base: Path | None = None) -> Path:
    path = project_state_dir(base) / "downloads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def quarantine_dir(base: Path | None = None) -> Path:
    path = staging_dir(base) / "quarantine"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_download_plan(
    plan: DownloadPlan,
    destination: Path,
    *,
    dat_index: DatIndex | None = None,
    verify: bool = True,
    progress: ProgressCallback | None = None,
    cancelled: CancelCheck | None = None,
    state_base: Path | None = None,
) -> DownloadReport:
    """Descarga cada candidato del plan, lo verifica contra el DAT y lo instala en destination."""
    destination.mkdir(parents=True, exist_ok=True)
    staging = staging_dir(state_base)
    report = DownloadReport()
    total = len(plan.candidates)

    for index, candidate in enumerate(plan.candidates, start=1):
        if cancelled and cancelled():
            report.outcomes.append(DownloadOutcome(title=candidate.title, file_name=candidate.file_name, status="cancelled"))
            break
        if progress:
            progress({"phase": "download", "current": index, "total": total, "title": candidate.title, "file": candidate.file_name})
        target = destination / candidate.file_name
        if target.exists():
            report.outcomes.append(
                DownloadOutcome(title=candidate.title, file_name=candidate.file_name, status="present", detail="Ya existe un archivo con ese nombre en el destino.", path=str(target))
            )
            continue
        report.outcomes.append(
            _process_candidate(
                candidate,
                target=target,
                staging=staging,
                dat_index=dat_index if verify else None,
                platform=plan.platform,
                cancelled=cancelled,
                state_base=state_base,
            )
        )

    if progress:
        progress({"phase": "done", "current": total, "total": total, "title": "", "file": ""})
    return report


def collect_downloads(
    plan: DownloadPlan,
    source_dir: Path,
    destination: Path,
    *,
    dat_index: DatIndex | None = None,
    progress: ProgressCallback | None = None,
    state_base: Path | None = None,
) -> DownloadReport:
    """Recoge de la carpeta de un cliente de torrent lo que ya esté completo.

    Verifica contra el DAT y **copia** al romset en vez de mover: si se moviera,
    el cliente daría el archivo por perdido y dejaría de sembrarlo.
    """
    destination.mkdir(parents=True, exist_ok=True)
    report = DownloadReport()
    total = len(plan.candidates)

    for index, candidate in enumerate(plan.candidates, start=1):
        if progress:
            progress({"phase": "collect", "current": index, "total": total, "title": candidate.title, "file": candidate.file_name})
        target = destination / candidate.file_name
        if target.exists():
            report.outcomes.append(
                DownloadOutcome(title=candidate.title, file_name=candidate.file_name, status="present", detail="Ya existe en el destino.", path=str(target))
            )
            continue
        found = _locate_download(source_dir, candidate)
        if found is None:
            report.outcomes.append(DownloadOutcome(title=candidate.title, file_name=candidate.file_name, status="absent"))
            continue
        if candidate.size and found.stat().st_size != candidate.size:
            report.outcomes.append(
                DownloadOutcome(
                    title=candidate.title,
                    file_name=candidate.file_name,
                    status="incomplete",
                    detail=f"{found.stat().st_size} de {candidate.size} bytes.",
                    path=str(found),
                )
            )
            continue
        problem = _verify_against_dat(found, candidate, dat_index, plan.platform) if dat_index else None
        if problem:
            report.outcomes.append(DownloadOutcome(title=candidate.title, file_name=candidate.file_name, status="mismatch", detail=problem, path=str(found)))
            continue
        shutil.copy2(found, target)
        report.outcomes.append(
            DownloadOutcome(title=candidate.title, file_name=candidate.file_name, status="ok", path=str(target), bytes_downloaded=target.stat().st_size)
        )

    if progress:
        progress({"phase": "done", "current": total, "total": total, "title": "", "file": ""})
    return report


def _locate_download(source_dir: Path, candidate: DownloadCandidate) -> Path | None:
    """Busca el archivo en la carpeta del cliente, con o sin la carpeta del torrent.

    No hace falta filtrar los archivos a medias: los que preasignan tamaño los
    caza la verificación contra el DAT, y los demás no llegan al tamaño esperado.
    """
    candidates = []
    if candidate.inner_path:
        candidates.append(source_dir / candidate.inner_path)
    candidates.append(source_dir / candidate.file_name)
    for path in candidates:
        if path.is_file():
            return path
    # Algunos clientes guardan todo plano, o dentro de una carpeta con otro nombre.
    matches = [path for path in source_dir.rglob(candidate.file_name) if path.is_file()]
    if matches:
        return matches[0]
    return None


def _process_candidate(
    candidate: DownloadCandidate,
    *,
    target: Path,
    staging: Path,
    dat_index: DatIndex | None,
    platform: Platform,
    cancelled: CancelCheck | None,
    state_base: Path | None,
) -> DownloadOutcome:
    staged = staging / candidate.file_name
    if candidate.container == "torrent":
        return DownloadOutcome(
            title=candidate.title,
            file_name=candidate.file_name,
            status="delegated",
            detail="Añádelo a tu cliente y luego recoge lo descargado con `torrent-collect`.",
        )
    try:
        if candidate.inner_path and candidate.container == "zip":
            downloaded = _extract_member(candidate.url, candidate.inner_path, staged)
        else:
            downloaded = _fetch(candidate.url, staged, cancelled=cancelled)
    except _Cancelled:
        return DownloadOutcome(title=candidate.title, file_name=candidate.file_name, status="cancelled")
    except Exception as exc:
        return DownloadOutcome(title=candidate.title, file_name=candidate.file_name, status="error", detail=str(exc))

    if dat_index is not None:
        problem = _verify_against_dat(staged, candidate, dat_index, platform)
        if problem:
            quarantined = quarantine_dir(state_base) / candidate.file_name
            shutil.move(str(staged), str(quarantined))
            return DownloadOutcome(
                title=candidate.title,
                file_name=candidate.file_name,
                status="mismatch",
                detail=problem,
                path=str(quarantined),
                bytes_downloaded=downloaded,
            )

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staged), str(target))
    return DownloadOutcome(title=candidate.title, file_name=candidate.file_name, status="ok", path=str(target), bytes_downloaded=downloaded)


def _verify_against_dat(path: Path, candidate: DownloadCandidate, dat_index: DatIndex, platform: Platform) -> str | None:
    """Devuelve None si el archivo contiene el juego esperado, o el motivo del rechazo."""
    try:
        roms = scan_file(path, platform, dat_index)
    except Exception as exc:
        return f"No se pudo leer el archivo descargado: {exc}"
    if not roms:
        return "El archivo no contiene ninguna ROM reconocible para esta plataforma."
    matched = [rom for rom in roms if rom.dat_game]
    if not matched:
        return "Ningún hash del archivo aparece en el DAT (descarga corrupta o versión distinta)."
    groups = {group_key(rom.dat_game) for rom in matched if rom.dat_game}
    if candidate.group_key not in groups:
        return f"El archivo verifica contra el DAT, pero corresponde a otro juego: {', '.join(sorted(groups))}."
    return None


def _extract_member(container: str, inner_path: str, destination: Path) -> int:
    """Saca un miembro del ZIP contenedor; en remoto solo se piden sus bytes."""
    data = read_zip_member(container, inner_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return len(data)


def _fetch(url: str, destination: Path, cancelled: CancelCheck | None = None) -> int:
    if "://" not in url or url.startswith("file://"):
        return _copy_local(url, destination, cancelled)
    return _download_http(url, destination, cancelled)


def _copy_local(url: str, destination: Path, cancelled: CancelCheck | None) -> int:
    source = Path(url[7:] if url.startswith("file://") else url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    copied = 0
    with source.open("rb") as reader, destination.open("wb") as writer:
        while chunk := reader.read(CHUNK_SIZE):
            if cancelled and cancelled():
                raise _Cancelled
            writer.write(chunk)
            copied += len(chunk)
    return copied


def _download_http(url: str, destination: Path, cancelled: CancelCheck | None) -> int:
    """Descarga en streaming a un .part reanudable con Range."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_suffix(destination.suffix + ".part")
    resume_from = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}

    response = _get_with_rate_limit(url, headers)
    if resume_from and response.status_code != 206:
        # El servidor ignoró el Range: se empieza de cero en vez de concatenar basura.
        resume_from = 0
        part.unlink(missing_ok=True)

    written = resume_from
    with part.open("ab" if resume_from else "wb") as fh:
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            if cancelled and cancelled():
                raise _Cancelled
            if chunk:
                fh.write(chunk)
                written += len(chunk)
    part.replace(destination)
    return written - resume_from


def _get_with_rate_limit(url: str, headers: dict[str, str]):
    """La sesión compartida no reintenta los 429 a propósito; aquí sí, respetando Retry-After."""
    for attempt in range(RATE_LIMIT_RETRIES):
        response = session().get(url, headers=headers, stream=True, timeout=60)
        if response.status_code != 429:
            response.raise_for_status()
            return response
        response.close()
        if attempt == RATE_LIMIT_RETRIES - 1:
            break
        time.sleep(_retry_after(response.headers.get("retry-after"), attempt))
    raise RuntimeError("El servidor está limitando las descargas (429). Inténtalo más tarde.")


def _retry_after(header: str | None, attempt: int) -> float:
    fallback = min(2.0 * (attempt + 1), MAX_RATE_LIMIT_WAIT_SECONDS)
    if not header or not header.strip().isdigit():
        return fallback
    return min(float(header.strip()), MAX_RATE_LIMIT_WAIT_SECONDS)


class _Cancelled(Exception):
    """Cancelación pedida por quien invoca; no es un error de descarga."""
