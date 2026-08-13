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
    assert completed == [f"copiado {src} -> {destination} (md5 verificado)"]


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


def test_save_scan_prunes_old_history(tmp_path: Path) -> None:
    import os

    from retroperfect.models import ScanResult
    from retroperfect.storage import save_scan

    for index in range(5):
        scan = ScanResult(id=f"scan-{index}", platform=Platform.NES, input_path=".")
        path = save_scan(scan, state_dir=tmp_path, keep=3)
        stamp = 1_000_000 + index
        os.utime(path, (stamp, stamp))
    scans_dir = tmp_path / "scans"
    names = sorted(item.name for item in scans_dir.glob("*.json"))
    assert names == ["latest.json", "scan-2.json", "scan-3.json", "scan-4.json"]


def test_apply_verifies_copied_content(tmp_path: Path) -> None:
    import hashlib

    src = tmp_path / "a.nes"
    payload = b"rom-data"
    src.write_bytes(payload)
    destination = tmp_path / "out" / "a.nes"
    manifest = Manifest(
        id="m",
        scan_id="s",
        platform=Platform.NES,
        profile_snapshot={},
        entries=[
            ManifestEntry(
                bucket=OutputBucket.MAIN,
                action=ActionMode.COPY,
                source_path=str(src),
                source_md5=hashlib.md5(payload).hexdigest(),
                destination_path=str(destination),
                rom_id="r",
            )
        ],
    )
    completed = apply_manifest(manifest, confirm=True)
    assert destination.read_bytes() == payload
    assert "md5 verificado" in completed[0]


def test_apply_detects_source_changed_since_scan(tmp_path: Path) -> None:
    import hashlib

    src = tmp_path / "a.nes"
    src.write_bytes(b"contenido-modificado-despues-del-escaneo")
    manifest = Manifest(
        id="m",
        scan_id="s",
        platform=Platform.NES,
        profile_snapshot={},
        entries=[
            ManifestEntry(
                bucket=OutputBucket.MAIN,
                action=ActionMode.COPY,
                source_path=str(src),
                source_md5=hashlib.md5(b"contenido-original").hexdigest(),
                destination_path=str(tmp_path / "out" / "a.nes"),
                rom_id="r",
            )
        ],
    )
    with pytest.raises(RuntimeError, match="cambió desde el escaneo"):
        apply_manifest(manifest, confirm=True)
