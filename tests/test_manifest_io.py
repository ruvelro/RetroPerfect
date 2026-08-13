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

