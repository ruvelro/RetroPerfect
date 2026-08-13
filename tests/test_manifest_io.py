from pathlib import Path

import pytest

from retroperfect.manifest_io import apply_manifest, report_manifest
from retroperfect.models import ActionMode, Manifest, ManifestEntry, OutputBucket, Platform


def test_apply_requires_confirmation(tmp_path: Path) -> None:
    src = tmp_path / "a.nes"
    src.write_bytes(b"rom")
    manifest = Manifest(
        id="m",
        scan_id="s",
        platform=Platform.NES,
        profile_snapshot={},
        entries=[ManifestEntry(bucket=OutputBucket.MAIN, action=ActionMode.COPY, source_path=str(src), destination_path=str(tmp_path / "out" / "a.nes"), rom_id="r")],
    )
    with pytest.raises(RuntimeError):
        apply_manifest(manifest, ActionMode.COPY)


def test_report_formats(tmp_path: Path) -> None:
    manifest = Manifest(
        id="m",
        scan_id="s",
        platform=Platform.NES,
        profile_snapshot={},
        entries=[ManifestEntry(bucket=OutputBucket.MAIN, action=ActionMode.COPY, source_path="a.nes", destination_path="out/a.nes", rom_id="r")],
    )
    for fmt in ["json", "csv", "html"]:
        path = report_manifest(manifest, tmp_path / f"report.{fmt}", fmt)
        assert path.exists()


def test_apply_uses_entry_action_and_rejects_mismatched_mode(tmp_path: Path) -> None:
    src = tmp_path / "a.nes"
    src.write_bytes(b"rom")
    destination = tmp_path / "out" / "a.nes"
    manifest = Manifest(
        id="m",
        scan_id="s",
        platform=Platform.NES,
        profile_snapshot={},
        entries=[ManifestEntry(bucket=OutputBucket.MAIN, action=ActionMode.COPY, source_path=str(src), destination_path=str(destination), rom_id="r")],
    )
    with pytest.raises(RuntimeError, match="planificó"):
        apply_manifest(manifest, ActionMode.DELETE, confirm=True)
    assert src.exists()
    completed = apply_manifest(manifest, confirm=True)
    assert destination.exists()
    assert src.exists()
    assert completed == [f"copied {src} -> {destination}"]


def test_apply_delete_manifest_removes_only_planned_sources(tmp_path: Path) -> None:
    keep = tmp_path / "keep.nes"
    drop = tmp_path / "drop.nes"
    keep.write_bytes(b"keep")
    drop.write_bytes(b"drop")
    manifest = Manifest(
        id="m",
        scan_id="s",
        platform=Platform.NES,
        profile_snapshot={},
        entries=[ManifestEntry(bucket=OutputBucket.MAIN, action=ActionMode.DELETE, source_path=str(drop), rom_id="r")],
    )
    apply_manifest(manifest, confirm=True)
    assert keep.exists()
    assert not drop.exists()
