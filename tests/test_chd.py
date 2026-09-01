"""Soporte CHD de CD (chd.py + matching por sha1 de pista).

El fixture tests/data/psx.chd (750 bytes) se generó con chdman a partir de la
imagen PSX sintética de test_disc (_psx_image + _raw_wrap como MODE1/2352):

    chdman createcd -i game.cue -o psx.chd

Las constantes de abajo son los valores de esa imagen; si _psx_image cambia,
hay que regenerar el fixture y recalcularlas.
"""
from __future__ import annotations

from pathlib import Path

from retroperfect.chd import ChdDiscImage, chd_available, chd_track_sha1s
from retroperfect.dat import DatIndex
from retroperfect.disc import DiscError, disc_ra_md5, psx_ra_md5
from retroperfect.models import DatCatalog, DatGame, DatRom, Platform, RomHash
from retroperfect.scanner import scan_directory, scan_file

FIXTURE = Path(__file__).parent / "data" / "psx.chd"
# sha1 del .bin original (la pista 1), tal y como lo listaría un DAT de Redump
TRACK_SHA1 = "84c1ab1aefe67764ea646098843a7c21bb3ee337"
TRACK_SIZE = 61152
RA_MD5 = "246ff0bb6076e2ff7d90b0b54d7efe83"


def _redump_style_index() -> DatIndex:
    game = DatGame(name="Juego (Europe)", description="Juego (Europe)")
    game.roms.append(DatRom(name="Juego (Europe).cue", size=98, crc32="11111111", md5="1" * 32, sha1="1" * 40))
    game.roms.append(DatRom(name="Juego (Europe).bin", size=TRACK_SIZE, crc32="22222222", md5="2" * 32, sha1=TRACK_SHA1))
    return DatIndex(DatCatalog(games=[game]))


def _hashes(track_sha1s: list[str] | None) -> RomHash:
    return RomHash(crc32="0" * 8, md5="0" * 32, sha1="0" * 40, size=750, track_sha1s=track_sha1s)


def test_chdimage_disponible() -> None:
    assert chd_available()


def test_track_sha1s_son_los_del_bin_original() -> None:
    assert chd_track_sha1s(FIXTURE) == [TRACK_SHA1]


def test_chd_disc_image_lee_iso9660_y_hash_ra() -> None:
    with ChdDiscImage(FIXTURE) as disc:
        assert b"BOOT = cdrom:" in disc.read_file("SYSTEM.CNF")
        assert psx_ra_md5(disc) == RA_MD5
    assert disc_ra_md5(FIXTURE, "psx") == RA_MD5


def test_chd_corrupto_degrada_sin_romper(tmp_path: Path) -> None:
    broken = tmp_path / "roto.chd"
    broken.write_bytes(b"esto no es un CHD")
    assert chd_track_sha1s(broken) is None
    assert disc_ra_md5(broken, "psx") is None
    try:
        ChdDiscImage(broken)
        raise AssertionError("Debió lanzar DiscError")
    except DiscError:
        pass


def test_dat_index_casa_por_sha1_de_pista() -> None:
    index = _redump_style_index()
    game = index.match_any(_hashes([TRACK_SHA1]))
    assert game is not None and game.name == "Juego (Europe)"
    # sin orden: la clave es el multiconjunto de pistas
    two_tracks = DatGame(name="Dos pistas")
    two_tracks.roms.append(DatRom(name="a.bin", size=1, crc32=None, md5=None, sha1="a" * 40))
    two_tracks.roms.append(DatRom(name="b.bin", size=1, crc32=None, md5=None, sha1="b" * 40))
    index2 = DatIndex(DatCatalog(games=[two_tracks]))
    assert index2.match_any(_hashes(["b" * 40, "a" * 40])) is two_tracks
    # un subconjunto de pistas no basta
    assert index2.match_any(_hashes(["a" * 40])) is None


def test_scan_file_identifica_chd_contra_el_dat(tmp_path: Path) -> None:
    chd = tmp_path / "Juego (Europe).chd"
    chd.write_bytes(FIXTURE.read_bytes())
    roms = scan_file(chd, Platform.PS1, _redump_style_index())
    assert len(roms) == 1
    rom = roms[0]
    assert rom.dat_game is not None and rom.dat_game.name == "Juego (Europe)"
    assert rom.hashes.track_sha1s == [TRACK_SHA1]
    assert rom.hashes.ra_md5 == RA_MD5


def test_scan_cachea_los_sha1_de_pista(tmp_path: Path) -> None:
    roms_dir = tmp_path / "roms"
    roms_dir.mkdir()
    (roms_dir / "Juego (Europe).chd").write_bytes(FIXTURE.read_bytes())
    cache_path = tmp_path / "cache.sqlite"
    first = scan_directory(roms_dir, Platform.PS1, _redump_style_index(), hash_cache=cache_path)
    second = scan_directory(roms_dir, Platform.PS1, _redump_style_index(), hash_cache=cache_path)
    for result in (first, second):
        assert result.roms[0].dat_game is not None
        assert result.roms[0].hashes.track_sha1s == [TRACK_SHA1]
