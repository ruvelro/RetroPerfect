"""Caché persistente de hashes de escaneo, indexada por contenedor, entrada, plataforma, tamaño y mtime."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .models import Platform, RomHash

# Sube cuando cambie la forma de lo que se guarda en `hashes`. Una caché con
# otra versión se descarta entera: re-hashear es lento, pero servir hashes que
# ya no significan lo mismo es peor, y antes una entrada ilegible rompía el
# escaneo en vez de recalcularse.
CACHE_SCHEMA_VERSION = 1


class ScanHashCache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        stored = int(self.conn.execute("PRAGMA user_version").fetchone()[0])
        if stored != CACHE_SCHEMA_VERSION:
            self.conn.execute("DROP TABLE IF EXISTS file_hashes")
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
        # El valor es una constante del módulo, no entra nada de fuera: PRAGMA
        # no admite parámetros enlazados.
        self.conn.execute(f"PRAGMA user_version = {CACHE_SCHEMA_VERSION}")

    def get(self, container: str, inner: str | None, platform: Platform, size: int, mtime_ns: int) -> RomHash | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT size, mtime_ns, hashes FROM file_hashes WHERE container = ? AND inner = ? AND platform = ?",
                (container, inner or "", platform.value),
            ).fetchone()
        if row is None or int(row[0]) != size or int(row[1]) != mtime_ns:
            return None
        try:
            return RomHash.model_validate_json(row[2])
        except ValueError:
            # Una entrada que ya no encaja con el modelo se recalcula; no puede
            # tumbar el escaneo de una colección entera.
            return None

    def put(self, container: str, inner: str | None, platform: Platform, size: int, mtime_ns: int, hashes: RomHash) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO file_hashes(container, inner, platform, size, mtime_ns, hashes) VALUES (?, ?, ?, ?, ?, ?)",
                (container, inner or "", platform.value, size, mtime_ns, hashes.model_dump_json()),
            )

    def count(self) -> int:
        with self.lock:
            return int(self.conn.execute("SELECT COUNT(*) FROM file_hashes").fetchone()[0])

    def export_rows(self) -> list[dict]:
        """Todas las entradas, para guardarlas fuera o llevarlas a otro sitio."""
        with self.lock:
            filas = self.conn.execute("SELECT container, inner, platform, size, mtime_ns, hashes FROM file_hashes ORDER BY container, inner").fetchall()
        return [
            {"container": fila[0], "inner": fila[1], "platform": fila[2], "size": int(fila[3]), "mtime_ns": int(fila[4]), "hashes": fila[5]}
            for fila in filas
        ]

    def import_rows(self, rows: list[dict], rebase: tuple[str, str] | None = None) -> int:
        """Inserta entradas exportadas y devuelve cuántas entraron.

        `rebase` reescribe el principio de la ruta del contenedor, que es lo que
        hace falta cuando la colección entera cambia de sitio (otro punto de
        montaje, otra letra de unidad): mover archivos dentro del mismo sistema
        de archivos conserva el mtime, así que la caché sigue valiendo y no hay
        que rehashear nada.
        """
        viejo, nuevo = rebase if rebase else ("", "")
        entradas = 0
        with self.lock:
            for fila in rows:
                container = str(fila["container"])
                if viejo and container.startswith(viejo):
                    container = nuevo + container[len(viejo) :]
                self.conn.execute(
                    "INSERT OR REPLACE INTO file_hashes(container, inner, platform, size, mtime_ns, hashes) VALUES (?, ?, ?, ?, ?, ?)",
                    (container, str(fila.get("inner") or ""), str(fila["platform"]), int(fila["size"]), int(fila["mtime_ns"]), str(fila["hashes"])),
                )
                entradas += 1
            self.conn.commit()
        return entradas

    def usable_rows(self) -> int:
        """Entradas que seguirían valiendo: el archivo está y no ha cambiado.

        Sirve para decir si una caché importada va a servir de algo antes de
        lanzar un escaneo de horas.
        """
        utiles = 0
        for fila in self.export_rows():
            ruta = Path(fila["container"])
            try:
                stat = ruta.stat()
            except OSError:
                continue
            # En un contenedor el tamaño guardado es el de la entrada, no el del
            # archivo: ahí lo que valida es el mtime del contenedor.
            mismo_tamano = bool(fila["inner"]) or stat.st_size == fila["size"]
            if mismo_tamano and stat.st_mtime_ns == fila["mtime_ns"]:
                utiles += 1
        return utiles

    def clear(self) -> int:
        """Vacía la caché y devuelve cuántas entradas había."""
        with self.lock:
            habia = int(self.conn.execute("SELECT COUNT(*) FROM file_hashes").fetchone()[0])
            self.conn.execute("DELETE FROM file_hashes")
            self.conn.commit()
            self.conn.execute("VACUUM")
        return habia

    def close(self) -> None:
        with self.lock:
            self.conn.commit()
            self.conn.close()
