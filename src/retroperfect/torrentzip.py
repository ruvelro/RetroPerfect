"""ZIP canónico al estilo TorrentZip: los mismos bytes para el mismo contenido.

Un ZIP normal guarda la fecha de cada archivo y el orden en que se añadieron,
así que dos personas con las mismas ROMs obtienen ZIP distintos y sus hashes no
se parecen en nada. TorrentZip fija esas dos cosas para que el archivo sea
reproducible: así una colección curada se puede verificar, compartir o
deduplicar por hash del contenedor, que es la razón de que el mundillo lo use.

Las reglas que se aplican:

- Las entradas van ordenadas por nombre en minúsculas.
- Todas llevan la fecha fija 1996-12-24 23:32, que es la que marca el formato.
- Deflate al máximo, sin entradas de directorio ni campos extra.
- El comentario del archivo es `TORRENTZIPPED-XXXXXXXX`, donde XXXXXXXX es el
  CRC32 del directorio central: es la firma que permite a otras herramientas
  reconocerlo sin descomprimir nada.

Lo que esto garantiza: el mismo contenido produce el mismo archivo byte a byte,
y la firma es válida y comprobable. Lo que **no** se promete es que el archivo
sea idéntico al que generaría la herramienta `trrntzip` original, porque
`zipfile` escribe a su manera algunos campos de versión que el formato no fija.
"""
from __future__ import annotations

import binascii
import zipfile
from pathlib import Path

# La fecha que marca el formato para todas las entradas.
TORRENTZIP_DATE = (1996, 12, 24, 23, 32, 0)
SIGNATURE_PREFIX = b"TORRENTZIPPED-"
SIGNATURE_LENGTH = len(SIGNATURE_PREFIX) + 8


def write_torrentzip(path: Path, members: list[tuple[str, bytes]]) -> None:
    """Escribe `path` como ZIP canónico con esos miembros (nombre, contenido)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as nuevo:
        # Se reserva el comentario ya con su longitud final: el directorio
        # central no depende de él, así que luego solo hay que sellar el CRC.
        nuevo.comment = SIGNATURE_PREFIX + b"0" * 8
        for nombre, datos in sorted(members, key=lambda item: item[0].lower()):
            info = zipfile.ZipInfo(nombre, date_time=TORRENTZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0
            info.create_system = 0  # MS-DOS, como marca el formato
            nuevo.writestr(info, datos, compresslevel=9)
    _stamp_signature(path)


def _stamp_signature(path: Path) -> None:
    """Sella en el comentario el CRC32 del directorio central."""
    datos = bytearray(path.read_bytes())
    inicio, longitud = _central_directory(datos)
    firma = f"{binascii.crc32(bytes(datos[inicio : inicio + longitud])) & 0xFFFFFFFF:08X}".encode()
    comentario = len(datos) - 8
    datos[comentario:] = firma
    path.write_bytes(bytes(datos))


def _central_directory(datos: bytearray) -> tuple[int, int]:
    """Posición y tamaño del directorio central, según el final del archivo."""
    eocd = datos.rfind(b"PK\x05\x06")
    if eocd < 0 or eocd + 22 > len(datos):
        raise ValueError("ZIP sin fin de directorio central: no se puede sellar.")
    longitud = int.from_bytes(datos[eocd + 12 : eocd + 16], "little")
    inicio = int.from_bytes(datos[eocd + 16 : eocd + 20], "little")
    return inicio, longitud


def signature(path: Path) -> str | None:
    """Firma TorrentZip del archivo, o None si no la lleva."""
    with zipfile.ZipFile(path) as leido:
        comentario = leido.comment
    if not comentario.startswith(SIGNATURE_PREFIX) or len(comentario) != SIGNATURE_LENGTH:
        return None
    return comentario.decode("ascii", errors="replace")


def is_torrentzipped(path: Path) -> bool:
    """True si el archivo lleva una firma TorrentZip que cuadra con su contenido.

    Se recalcula el CRC del directorio central: una firma que no corresponde es
    peor que ninguna, porque invita a confiar en un archivo que ha cambiado.
    """
    try:
        firma = signature(path)
    except (OSError, zipfile.BadZipFile):
        return False
    if firma is None:
        return False
    datos = bytearray(path.read_bytes())
    try:
        inicio, longitud = _central_directory(datos)
    except ValueError:
        return False
    esperado = f"{binascii.crc32(bytes(datos[inicio : inicio + longitud])) & 0xFFFFFFFF:08X}"
    return firma[len(SIGNATURE_PREFIX) :] == esperado
