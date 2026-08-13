from __future__ import annotations

import hashlib
from pathlib import Path

from retroperfect.manifest_io import apply_manifest
from retroperfect.models import ActionMode, Manifest, ManifestEntry, OutputBucket, Platform
from retroperfect.patching import PatchPayload, apply_ips


def test_apply_ips_patch() -> None:
    patch = b"PATCH" + (1).to_bytes(3, "big") + (1).to_bytes(2, "big") + b"A" + b"EOF"
    assert apply_ips(b"abc", patch) == b"aAc"


def test_apply_manifest_patch_entry_verifies_expected_md5(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "Game.nes"
    source.write_bytes(b"abc")
    patched = b"aAc"

    def fake_download_and_apply_patch(data: bytes, patch_url: str):
        assert data == b"abc"
        assert patch_url == "https://example.test/patch.zip"
        return patched, PatchPayload("patch.ips", ".ips", b"")

    monkeypatch.setattr("retroperfect.manifest_io.download_and_apply_patch", fake_download_and_apply_patch)
    manifest = Manifest(
        id="manifest",
        scan_id="scan",
        platform=Platform.NES,
        profile_snapshot={},
        entries=[
            ManifestEntry(
                bucket=OutputBucket.RA,
                action=ActionMode.COPY,
                source_path=str(source),
                destination_path=str(tmp_path / "out" / "Otros" / "RetroAchievements" / "Game RA.nes"),
                rom_id="rom",
                patch_url="https://example.test/patch.zip",
                patch_expected_md5=hashlib.md5(patched).hexdigest(),
            )
        ],
    )
    completed = apply_manifest(manifest, ActionMode.COPY, confirm=True)
    assert "parcheado" in completed[0]
    assert (tmp_path / "out" / "Otros" / "RetroAchievements" / "Game RA.nes").read_bytes() == patched


def test_download_patch_caches_per_url_not_per_filename(tmp_path: Path, monkeypatch) -> None:
    from retroperfect import patching

    monkeypatch.setattr(patching, "data_dir", lambda: tmp_path)
    payloads = {
        "https://example.test/game-a/patch.ips": b"A",
        "https://example.test/game-b/patch.ips": b"B",
    }

    class Response:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(patching.requests, "get", lambda url, timeout: Response(payloads[url]))
    path_a = patching.download_patch("https://example.test/game-a/patch.ips")
    path_b = patching.download_patch("https://example.test/game-b/patch.ips")
    assert path_a != path_b
    assert path_a.read_bytes() == b"A"
    assert path_b.read_bytes() == b"B"
    assert path_a.name == "patch.ips"
    monkeypatch.setattr(patching.requests, "get", lambda url, timeout: (_ for _ in ()).throw(AssertionError("no debe descargar de nuevo")))
    assert patching.download_patch("https://example.test/game-a/patch.ips") == path_a


def _ups_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        chunk = value & 0x7F
        value >>= 7
        if value == 0:
            out.append(chunk | 0x80)
            return bytes(out)
        out.append(chunk)
        value -= 1


def test_apply_ups_patch() -> None:
    import binascii
    import struct

    from retroperfect.patching import apply_ups

    source = b"abcdef"
    target = b"aXcdeF"
    body = b"UPS1" + _ups_varint(len(source)) + _ups_varint(len(target))
    # bloque 1: saltar 1, XOR en offset 1
    body += _ups_varint(1) + bytes([ord("b") ^ ord("X")]) + b"\x00"
    # bloque 2: el terminador anterior dejó el puntero en 3; saltar 2 hasta offset 5
    body += _ups_varint(2) + bytes([ord("f") ^ ord("F")]) + b"\x00"
    body += struct.pack("<II", binascii.crc32(source) & 0xFFFFFFFF, binascii.crc32(target) & 0xFFFFFFFF)
    patch = body + struct.pack("<I", binascii.crc32(body) & 0xFFFFFFFF)
    assert apply_ups(source, patch) == target


def test_apply_ups_rejects_wrong_source() -> None:
    import binascii
    import struct

    import pytest

    from retroperfect.patching import apply_ups

    source = b"abcdef"
    body = b"UPS1" + _ups_varint(6) + _ups_varint(6) + struct.pack("<II", binascii.crc32(source) & 0xFFFFFFFF, binascii.crc32(source) & 0xFFFFFFFF)
    patch = body + struct.pack("<I", binascii.crc32(body) & 0xFFFFFFFF)
    with pytest.raises(ValueError, match="CRC de ROM origen"):
        apply_ups(b"otra-rom", patch)


def test_apply_xdelta_roundtrip(tmp_path: Path) -> None:
    import pyxdelta

    from retroperfect.patching import apply_xdelta

    source = b"hola mundo " * 200
    target = b"hola MUNDO " * 200 + b"cola nueva"
    src = tmp_path / "src.bin"
    dst = tmp_path / "dst.bin"
    patch = tmp_path / "p.xdelta"
    src.write_bytes(source)
    dst.write_bytes(target)
    assert pyxdelta.run(str(src), str(dst), str(patch))
    assert apply_xdelta(source, patch.read_bytes()) == target
