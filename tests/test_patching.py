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
