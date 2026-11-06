"""Deshacer una aplicación a partir del journal.

Había journal y papelera, pero nada que los usara. La regla que se comprueba en
casi todos estos tests: no se borra ni se pisa nada que no hayamos escrito.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from retroperfect.manifest_io import apply_manifest
from retroperfect.models import ActionMode, Manifest, ManifestEntry, OutputBucket, Platform
from retroperfect.undoing import apply_undo, latest_journal, list_journals, plan_undo


def _manifest(entries: list[ManifestEntry]) -> Manifest:
    return Manifest(id="m", scan_id="s", platform=Platform.NES, profile_snapshot={}, entries=entries)


def _copia(src: Path, dest: Path) -> ManifestEntry:
    return ManifestEntry(
        bucket=OutputBucket.MAIN,
        action=ActionMode.COPY,
        source_path=str(src),
        source_md5=hashlib.md5(src.read_bytes()).hexdigest(),
        destination_path=str(dest),
        rom_id="r",
    )


def _aplicar(manifest: Manifest, tmp_path: Path, **kwargs) -> Path:
    apply_manifest(manifest, confirm=True, journal_dir=tmp_path / "applied", **kwargs)
    journal = latest_journal(tmp_path / "applied")
    assert journal is not None
    return journal


def test_deshacer_una_copia_borra_lo_que_se_copio(tmp_path: Path) -> None:
    src = tmp_path / "rom.nes"
    src.write_bytes(b"ROM")
    dest = tmp_path / "out" / "rom.nes"
    journal = _aplicar(_manifest([_copia(src, dest)]), tmp_path)

    plan = plan_undo(journal)
    log = apply_undo(plan)

    assert [step.action for step in plan.steps] == ["borrar"]
    assert not dest.exists()
    assert src.read_bytes() == b"ROM", "el original no se toca"
    assert log[0].startswith("borrado ")


def test_deshacer_un_movimiento_devuelve_el_archivo_a_su_sitio(tmp_path: Path) -> None:
    src = tmp_path / "roms" / "rom.nes"
    src.parent.mkdir()
    src.write_bytes(b"ROM")
    dest = tmp_path / "out" / "rom.nes"
    entrada = _copia(src, dest).model_copy(update={"action": ActionMode.MOVE})
    journal = _aplicar(_manifest([entrada]), tmp_path)
    assert not src.exists()

    apply_undo(plan_undo(journal))

    assert src.read_bytes() == b"ROM"
    assert not dest.exists()


def test_deshacer_un_borrado_lo_saca_de_la_papelera(tmp_path: Path) -> None:
    sobra = tmp_path / "roms" / "sobra.nes"
    sobra.parent.mkdir()
    sobra.write_bytes(b"SOBRA")
    manifest = _manifest([ManifestEntry(bucket=OutputBucket.MAIN, action=ActionMode.DELETE, source_path=str(sobra), rom_id="r")])
    journal = _aplicar(manifest, tmp_path, trash_dir=tmp_path / "trash")
    assert not sobra.exists()

    apply_undo(plan_undo(journal))

    assert sobra.read_bytes() == b"SOBRA"


def test_no_se_borra_un_archivo_que_el_usuario_cambio_despues(tmp_path: Path) -> None:
    """Puede haberlo parcheado o reemplazado: deshacer no es una excusa para
    tirar trabajo ajeno."""
    src = tmp_path / "rom.nes"
    src.write_bytes(b"ROM")
    dest = tmp_path / "out" / "rom.nes"
    journal = _aplicar(_manifest([_copia(src, dest)]), tmp_path)
    dest.write_bytes(b"LO HE CAMBIADO YO")

    plan = plan_undo(journal)
    log = apply_undo(plan)

    assert not plan.steps[0].can_apply
    assert "ha cambiado desde que se aplicó" in plan.steps[0].skipped_reason
    assert dest.read_bytes() == b"LO HE CAMBIADO YO"
    assert log[0].startswith("omitido ")


def test_no_se_pisa_un_archivo_que_ya_ocupa_el_sitio_original(tmp_path: Path) -> None:
    src = tmp_path / "roms" / "rom.nes"
    src.parent.mkdir()
    src.write_bytes(b"ROM")
    dest = tmp_path / "out" / "rom.nes"
    entrada = _copia(src, dest).model_copy(update={"action": ActionMode.MOVE})
    journal = _aplicar(_manifest([entrada]), tmp_path)
    src.write_bytes(b"OTRA COSA MIA")

    plan = plan_undo(journal)
    apply_undo(plan)

    assert "no se sobrescribe" in plan.steps[0].skipped_reason
    assert src.read_bytes() == b"OTRA COSA MIA"
    assert dest.exists(), "lo movido se queda donde está hasta que el usuario decida"


def test_un_archivo_que_ya_no_esta_se_omite(tmp_path: Path) -> None:
    src = tmp_path / "rom.nes"
    src.write_bytes(b"ROM")
    dest = tmp_path / "out" / "rom.nes"
    journal = _aplicar(_manifest([_copia(src, dest)]), tmp_path)
    dest.unlink()

    plan = plan_undo(journal)

    assert "ya no está" in plan.steps[0].skipped_reason


def test_deshacer_avisa_de_lo_que_no_se_puede_recuperar(tmp_path: Path) -> None:
    sobra = tmp_path / "sobra.nes"
    sobra.write_bytes(b"SOBRA")
    manifest = _manifest([ManifestEntry(bucket=OutputBucket.MAIN, action=ActionMode.DELETE, source_path=str(sobra), rom_id="r")])
    journal = _aplicar(manifest, tmp_path, hard_delete=True)

    plan = plan_undo(journal)
    log = apply_undo(plan)

    assert plan.hard_deleted == 1
    assert plan.steps == []
    assert "no se pueden recuperar" in log[-1]


def test_las_operaciones_se_deshacen_en_orden_inverso(tmp_path: Path) -> None:
    """Lo último que se hizo es lo primero que hay que deshacer."""
    entradas = []
    for indice in range(3):
        src = tmp_path / f"rom{indice}.nes"
        src.write_bytes(f"ROM{indice}".encode())
        entradas.append(_copia(src, tmp_path / "out" / f"rom{indice}.nes").model_copy(update={"rom_id": f"r{indice}"}))
    journal = _aplicar(_manifest(entradas), tmp_path)

    plan = plan_undo(journal)

    assert [Path(step.path).name for step in plan.steps] == ["rom2.nes", "rom1.nes", "rom0.nes"]


def test_tambien_se_borran_las_playlists_que_escribio_el_plan(tmp_path: Path) -> None:
    from retroperfect.models import ManifestPlaylist

    src = tmp_path / "d1.bin"
    src.write_bytes(b"D1")
    dest = tmp_path / "out" / "d1.bin"
    manifest = _manifest([_copia(src, dest)])
    manifest.playlists = [ManifestPlaylist(path=str(tmp_path / "out" / "Juego.m3u"), title="Juego", entries=["d1.bin", "d2.bin"])]
    journal = _aplicar(manifest, tmp_path)
    assert (tmp_path / "out" / "Juego.m3u").exists()

    apply_undo(plan_undo(journal))

    assert not (tmp_path / "out" / "Juego.m3u").exists()


def test_un_journal_de_una_version_anterior_lo_dice(tmp_path: Path) -> None:
    """Los journals viejos solo guardan texto: deshacer leyendo prosa sería
    exactamente el acoplamiento que se quiere evitar."""
    viejo = tmp_path / "20260101-000000-m.json"
    viejo.write_text(json.dumps({"manifest_id": "m", "operations": ["copiado a -> b"]}), encoding="utf-8")

    with pytest.raises(ValueError, match="versión anterior"):
        plan_undo(viejo)


def test_los_journals_se_listan_del_mas_reciente_al_mas_antiguo(tmp_path: Path) -> None:
    carpeta = tmp_path / "applied"
    carpeta.mkdir()
    for nombre in ["20260101-000000-m.json", "20260301-000000-m.json", "20260201-000000-m.json"]:
        (carpeta / nombre).write_text("{}", encoding="utf-8")

    assert [item.name for item in list_journals(carpeta)][0] == "20260301-000000-m.json"
    assert latest_journal(carpeta) is not None
    assert latest_journal(tmp_path / "no-existe") is None
