from __future__ import annotations

import hashlib

from retroperfect.hashing import hash_bytes
from retroperfect.models import Platform
from retroperfect.platforms import list_platforms, platform_spec


def test_platform_registry_has_visual_and_dat_metadata() -> None:
    specs = list_platforms()
    assert len(specs) >= 170
    for spec in specs:
        assert spec.icon
        assert spec.name
        assert spec.brand
        assert spec.generation
        assert spec.kind
        assert spec.rom_extensions
        assert spec.dat_aliases
        assert spec.dat_recommended


def test_game_boy_uses_direct_hash_payload() -> None:
    data = b"GBDATA"
    hashes = hash_bytes(data, Platform.GB)
    assert hashes.md5 == hashlib.md5(data).hexdigest()
    assert hashes.payload_md5 == hashes.md5


def test_snes_copier_header_is_ignored_for_payload_match() -> None:
    payload = b"S" * 2048
    data = b"\0" * 512 + payload
    hashes = hash_bytes(data, Platform.SNES)
    assert hashes.md5 != hashes.payload_md5
    assert hashes.payload_md5 == hashlib.md5(payload).hexdigest()


def test_n64_byteswapped_payload_normalizes_to_big_endian() -> None:
    big_endian = b"\x80\x37\x12\x40ABCD"
    byte_swapped = b"\x37\x80\x40\x12BADC"
    hashes = hash_bytes(byte_swapped, Platform.N64)
    assert hashes.payload_md5 == hashlib.md5(big_endian).hexdigest()
    assert platform_spec(Platform.N64).complexity == "especial"


def test_registry_includes_arcade_and_disc_families() -> None:
    assert platform_spec(Platform.MAME).kind == "arcade"
    assert platform_spec(Platform.FBNEO).dat_family == "fbneo"
    assert platform_spec(Platform.PS1).dat_family == "redump"
    assert platform_spec(Platform.SWITCH).kind == "digital"


def test_ra_console_ids_match_official_systems() -> None:
    expected = {
        Platform.FDS: 81,
        Platform.VB: 28,
        Platform.A7800: 51,
        Platform.INTV: 45,
        Platform.VECTREX: 46,
        Platform.POKEMON_MINI: 24,
        Platform.SEGACD: 9,
        Platform.SATURN: 39,
        Platform.DREAMCAST: 40,
        Platform.GAMECUBE: 16,
        Platform.WII: 19,
        Platform.PS2: 21,
        Platform.THREE_DO: 43,
        Platform.PCE_CD: 76,
        Platform.SGX: 8,
        Platform.NGPC: 14,
        Platform.JAGUAR_CD: 77,
        Platform.DSI: 78,
        Platform.MAME: 27,
        Platform.FBNEO: 27,
    }
    for platform, console_id in expected.items():
        assert platform_spec(platform).ra_console_id == console_id
        assert platform_spec(platform).ra_active


def test_inactive_ra_systems_are_labeled_but_not_hidden() -> None:
    assert platform_spec(Platform.C64).ra_console_id == 30
    assert not platform_spec(Platform.C64).ra_active
    assert platform_spec(Platform.C64).ra_label == "RA inactivo"
