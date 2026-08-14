"""Lectura de un ZIP remoto por rangos, contra un servidor HTTP de verdad."""
from __future__ import annotations

import re
import socketserver
import threading
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from retroperfect.remote_zip import HttpRangeReader, RangeNotSupportedError
from retroperfect.rom_sources import read_zip_member

RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")


@contextmanager
def _serve(payload: bytes, *, support_ranges: bool = True) -> Iterator[tuple[str, dict[str, int]]]:
    """Sirve `payload` y contabiliza cuántos bytes se han pedido en total."""
    stats = {"bytes": 0, "requests": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            stats["requests"] += 1
            requested = self.headers.get("Range")
            match = RANGE_RE.search(requested or "") if support_ranges else None
            if match:
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else len(payload) - 1
                end = min(end, len(payload) - 1)
                chunk = payload[start : end + 1]
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(payload)}")
            else:
                chunk = payload
                self.send_response(200)
            stats["bytes"] += len(chunk)
            self.send_header("Content-Length", str(len(chunk)))
            self.send_header("Accept-Ranges", "bytes" if support_ranges else "none")
            self.end_headers()
            self.wfile.write(chunk)

        def log_message(self, *args: object) -> None:
            return

    class Server(ThreadingHTTPServer):
        # HTTPServer.server_bind resuelve el FQDN del host, y ese DNS inverso
        # tarda decenas de segundos en entornos sin resolutor. No hace falta.
        def server_bind(self) -> None:
            socketserver.TCPServer.server_bind(self)
            self.server_name = "127.0.0.1"
            self.server_port = self.server_address[1]

    server = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/set.zip", stats
    finally:
        server.shutdown()
        server.server_close()


def _big_zip(tmp_path: Path) -> tuple[Path, bytes]:
    """ZIP con relleno de sobra para que bajarlo entero se note."""
    wanted = b"METROID-ROM-DATA"
    path = tmp_path / "set.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(40):
            # Incompresible a propósito: si no, el ZIP entero sería diminuto.
            archive.writestr(f"relleno-{index}.bin", bytes(range(256)) * 400)
        archive.writestr("Metroid (Europe).nes", wanted)
    return path, wanted


def test_reads_the_index_without_downloading_the_whole_archive(tmp_path: Path) -> None:
    path, _ = _big_zip(tmp_path)
    payload = path.read_bytes()
    with _serve(payload) as (url, stats):
        with zipfile.ZipFile(HttpRangeReader(url)) as archive:  # type: ignore[arg-type]
            names = archive.namelist()

        assert "Metroid (Europe).nes" in names
        assert len(names) == 41
        # Lo que importa: se ha leído una fracción, no el archivo entero.
        assert stats["bytes"] < len(payload) / 4, f"leídos {stats['bytes']} de {len(payload)}"


def test_extracts_one_member_without_downloading_the_whole_archive(tmp_path: Path) -> None:
    path, wanted = _big_zip(tmp_path)
    payload = path.read_bytes()
    with _serve(payload) as (url, stats):
        assert read_zip_member(url, "Metroid (Europe).nes") == wanted
        assert stats["bytes"] < len(payload) / 4, f"leídos {stats['bytes']} de {len(payload)}"


def test_reader_reports_the_total_size(tmp_path: Path) -> None:
    path, _ = _big_zip(tmp_path)
    payload = path.read_bytes()
    with _serve(payload) as (url, _stats):
        assert HttpRangeReader(url).size == len(payload)


def test_reader_seeks_from_the_end(tmp_path: Path) -> None:
    payload = b"0123456789" * 100
    with _serve(payload) as (url, _stats):
        reader = HttpRangeReader(url)
        reader.seek(-10, 2)
        assert reader.read(10) == payload[-10:]
        reader.seek(5)
        assert reader.read(4) == payload[5:9]
        assert reader.tell() == 9


def test_server_without_range_support_fails_clearly(tmp_path: Path) -> None:
    with _serve(b"contenido", support_ranges=False) as (url, _stats), pytest.raises(RangeNotSupportedError, match="descargas parciales"):
        HttpRangeReader(url)
