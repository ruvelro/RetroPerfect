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
    assert "patched" in completed[0]
    assert (tmp_path / "out" / "Otros" / "RetroAchievements" / "Game RA.nes").read_bytes() == patched
