from __future__ import annotations

import binascii
import hashlib
from pathlib import Path

from retroperfect.dat import DatIndex, parse_logiqx_dat
from retroperfect.models import Platform
from retroperfect.scanner import scan_directory
from retroperfect.verify import verify_collection


def _dat_for(tmp_path: Path, games: dict[str, bytes]) -> Path:
    entries = []
    for name, payload in games.items():
        entries.append(
            f'<game name="{name}"><description>{name}</description>'
            f'<rom name="{name}.nes" size="{len(payload)}" crc="{binascii.crc32(payload) & 0xFFFFFFFF:08x}" '
            f'md5="{hashlib.md5(payload).hexdigest()}" sha1="{hashlib.sha1(payload).hexdigest()}"/></game>'
        )
    dat = tmp_path / "nes.xml"
    dat.write_text("<datafile><header><name>NES</name></header>" + "".join(entries) + "</datafile>", encoding="utf-8")
    return dat


def test_verify_reports_missing_unmatched_misnamed_and_duplicates(tmp_path: Path) -> None:
    dat = _dat_for(tmp_path / ".", {"Correcto (Europe)": b"OK", "Perdido (USA)": b"MISSING"})
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "Correcto (Europe).nes").write_bytes(b"OK")
    (roms / "nombre-raro.nes").write_bytes(b"OK")  # coincide por hash pero mal nombrado (y duplicado)
    (roms / "Desconocido (Japan).nes").write_bytes(b"???")

    catalog = parse_logiqx_dat(dat)
    scan = scan_directory(roms, Platform.NES, dat_index=DatIndex(catalog), dat_path=dat)
    report = verify_collection(scan, catalog)

    assert report.missing == 1
    assert report.unmatched == 1
    assert report.misnamed == 1
    assert report.duplicates == 1
    assert not report.clean
    statuses = {issue.status for issue in report.issues}
    assert statuses == {"FALTA", "SIN DAT", "MAL NOMBRADO", "DUPLICADO"}


def test_verify_clean_collection(tmp_path: Path) -> None:
    dat = _dat_for(tmp_path, {"Correcto (Europe)": b"OK"})
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "Correcto (Europe).nes").write_bytes(b"OK")
    catalog = parse_logiqx_dat(dat)
    scan = scan_directory(roms, Platform.NES, dat_index=DatIndex(catalog), dat_path=dat)
    report = verify_collection(scan, catalog)
    assert report.clean
    assert report.matched_games == 1
