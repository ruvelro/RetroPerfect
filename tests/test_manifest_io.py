from pathlib import Path

import pytest

from retroperfect.manifest_io import apply_manifest, blocking_issues, preflight_manifest, report_manifest
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


def test_apply_delete_moves_to_trash_by_default(tmp_path: Path) -> None:
    keep = tmp_path / "keep.nes"
    drop = tmp_path / "drop.nes"
    keep.write_bytes(b"keep")
    drop.write_bytes(b"drop")
    trash = tmp_path / "trash"
    manifest = Manifest(
        id="m",
        scan_id="s",
        platform=Platform.NES,
        profile_snapshot={},
        entries=[ManifestEntry(bucket=OutputBucket.MAIN, action=ActionMode.DELETE, source_path=str(drop), rom_id="r")],
    )
    completed = apply_manifest(manifest, confirm=True, trash_dir=trash)
    assert keep.exists()
    assert not drop.exists()
    trashed = list(trash.rglob("drop.nes"))
    assert len(trashed) == 1
    assert trashed[0].read_bytes() == b"drop"
    assert "papelera" in completed[0]


def test_apply_hard_delete_removes_file(tmp_path: Path) -> None:
    drop = tmp_path / "drop.nes"
    drop.write_bytes(b"drop")
    manifest = Manifest(
        id="m",
        scan_id="s",
        platform=Platform.NES,
        profile_snapshot={},
        entries=[ManifestEntry(bucket=OutputBucket.MAIN, action=ActionMode.DELETE, source_path=str(drop), rom_id="r")],
    )
    completed = apply_manifest(manifest, confirm=True, hard_delete=True, trash_dir=tmp_path / "trash")
    assert not drop.exists()
    assert not (tmp_path / "trash").exists()
    assert "definitivo" in completed[0]


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


def _copy_entry(src: Path, dest: Path) -> ManifestEntry:
    return ManifestEntry(bucket=OutputBucket.MAIN, action=ActionMode.COPY, source_path=str(src), destination_path=str(dest), rom_id=str(src))


def test_preflight_detects_missing_source_and_collisions(tmp_path: Path) -> None:
    from retroperfect.manifest_io import preflight_manifest

    existing_a = tmp_path / "a.nes"
    existing_b = tmp_path / "b.nes"
    existing_a.write_bytes(b"A")
    existing_b.write_bytes(b"B")
    shared_dest = tmp_path / "out" / "same.nes"
    manifest = Manifest(
        id="m",
        scan_id="s",
        platform=Platform.NES,
        profile_snapshot={},
        entries=[
            _copy_entry(existing_a, shared_dest),
            _copy_entry(existing_b, shared_dest),
            _copy_entry(tmp_path / "missing.nes", tmp_path / "out" / "missing.nes"),
        ],
    )
    issues = preflight_manifest(manifest)
    assert any("Colisión de destino" in issue for issue in issues)
    assert any("Origen no encontrado" in issue for issue in issues)
    with pytest.raises(RuntimeError, match="No se puede aplicar"):
        apply_manifest(manifest, confirm=True)


def test_preflight_detects_insufficient_space(tmp_path: Path, monkeypatch) -> None:
    import collections

    from retroperfect import manifest_io

    src = tmp_path / "a.nes"
    src.write_bytes(b"X" * 1024)
    manifest = Manifest(
        id="m",
        scan_id="s",
        platform=Platform.NES,
        profile_snapshot={},
        entries=[_copy_entry(src, tmp_path / "out" / "a.nes")],
    )
    usage = collections.namedtuple("usage", "total used free")
    monkeypatch.setattr(manifest_io.shutil, "disk_usage", lambda path: usage(2048, 2000, 48))
    issues = manifest_io.preflight_manifest(manifest)
    assert any("Espacio insuficiente" in issue for issue in issues)


def test_apply_writes_journal(tmp_path: Path) -> None:
    import json

    src = tmp_path / "a.nes"
    src.write_bytes(b"rom")
    journal = tmp_path / "applied"
    manifest = Manifest(
        id="m-journal",
        scan_id="s",
        platform=Platform.NES,
        profile_snapshot={},
        entries=[_copy_entry(src, tmp_path / "out" / "a.nes")],
    )
    apply_manifest(manifest, confirm=True, journal_dir=journal)
    entries = list(journal.glob("*.json"))
    assert len(entries) == 1
    payload = json.loads(entries[0].read_text(encoding="utf-8"))
    assert payload["manifest_id"] == "m-journal"
    assert len(payload["operations"]) == 1
    assert "copiado" in payload["operations"][0]
    assert "error" not in payload


def test_apply_journal_records_partial_failure(tmp_path: Path) -> None:
    import hashlib
    import json

    good = tmp_path / "good.nes"
    bad = tmp_path / "bad.nes"
    good.write_bytes(b"ok")
    bad.write_bytes(b"contenido-cambiado")
    journal = tmp_path / "applied"
    manifest = Manifest(
        id="m-fallo",
        scan_id="s",
        platform=Platform.NES,
        profile_snapshot={},
        entries=[
            _copy_entry(good, tmp_path / "out" / "good.nes"),
            ManifestEntry(
                bucket=OutputBucket.MAIN,
                action=ActionMode.COPY,
                source_path=str(bad),
                source_md5=hashlib.md5(b"contenido-original").hexdigest(),
                destination_path=str(tmp_path / "out" / "bad.nes"),
                rom_id="bad",
            ),
        ],
    )
    with pytest.raises(RuntimeError):
        apply_manifest(manifest, confirm=True, journal_dir=journal)
    payload = json.loads(next(iter(journal.glob("*.json"))).read_text(encoding="utf-8"))
    assert len(payload["operations"]) == 1
    assert "cambió desde el escaneo" in payload["error"]


def _manifiesto_copia(src: Path, destino: Path, action: ActionMode = ActionMode.COPY) -> Manifest:
    import hashlib

    return Manifest(
        id="m",
        scan_id="s",
        platform=Platform.NES,
        profile_snapshot={},
        entries=[
            ManifestEntry(
                bucket=OutputBucket.MAIN,
                action=action,
                source_path=str(src),
                source_md5=hashlib.md5(src.read_bytes()).hexdigest(),
                destination_path=str(destino),
                rom_id="r",
            )
        ],
    )


def test_apply_no_pisa_un_destino_distinto(tmp_path: Path) -> None:
    """La salida puede tener archivos del usuario: antes se sobrescribían sin avisar."""
    src = tmp_path / "a.nes"
    src.write_bytes(b"rom-nueva")
    destino = tmp_path / "out" / "a.nes"
    destino.parent.mkdir()
    destino.write_bytes(b"algo-que-ya-estaba")
    manifest = _manifiesto_copia(src, destino)

    assert any("El destino ya existe" in issue for issue in preflight_manifest(manifest))
    with pytest.raises(RuntimeError, match="El destino ya existe"):
        apply_manifest(manifest, confirm=True)
    assert destino.read_bytes() == b"algo-que-ya-estaba", "se pisó un archivo ajeno"


def test_apply_no_pisa_un_destino_del_mismo_tamano(tmp_path: Path) -> None:
    """El preflight compara tamaños; el contenido lo confirma el MD5 al aplicar."""
    src = tmp_path / "a.nes"
    src.write_bytes(b"rom-nueva")
    destino = tmp_path / "out" / "a.nes"
    destino.parent.mkdir()
    destino.write_bytes(b"otra-roms")  # mismo tamaño, contenido distinto
    manifest = _manifiesto_copia(src, destino)

    assert preflight_manifest(manifest) == []
    with pytest.raises(RuntimeError, match="ya existe con otro contenido"):
        apply_manifest(manifest, confirm=True)
    assert destino.read_bytes() == b"otra-roms", "se pisó un archivo ajeno del mismo tamaño"


def test_apply_dos_veces_el_mismo_plan_no_duplica_trabajo(tmp_path: Path) -> None:
    src = tmp_path / "a.nes"
    src.write_bytes(b"rom-data")
    destino = tmp_path / "out" / "a.nes"
    manifest = _manifiesto_copia(src, destino)

    assert "md5 verificado" in apply_manifest(manifest, confirm=True)[0]
    segunda = apply_manifest(manifest, confirm=True)

    assert preflight_manifest(manifest) == []
    assert "ya estaba aplicado" in segunda[0]


def test_apply_con_overwrite_reemplaza_el_destino(tmp_path: Path) -> None:
    src = tmp_path / "a.nes"
    src.write_bytes(b"rom-nueva")
    destino = tmp_path / "out" / "a.nes"
    destino.parent.mkdir()
    destino.write_bytes(b"version-vieja-distinta")
    manifest = _manifiesto_copia(src, destino)

    assert blocking_issues(manifest, overwrite=True) == []
    apply_manifest(manifest, confirm=True, overwrite=True)

    assert destino.read_bytes() == b"rom-nueva"


def test_apply_con_enlace_duro_sobre_un_destino_ya_enlazado(tmp_path: Path) -> None:
    """`os.link` no sobrescribe: fallaba con FileExistsError a mitad del plan."""
    src = tmp_path / "a.nes"
    src.write_bytes(b"rom-data")
    destino = tmp_path / "out" / "a.nes"
    destino.parent.mkdir()
    destino.hardlink_to(src)
    manifest = _manifiesto_copia(src, destino)

    completed = apply_manifest(manifest, confirm=True, link=True)

    assert "ya estaba aplicado" in completed[0]


def test_apply_de_un_movimiento_ya_hecho_deja_el_origen_intacto(tmp_path: Path) -> None:
    src = tmp_path / "a.nes"
    src.write_bytes(b"rom-data")
    destino = tmp_path / "out" / "a.nes"
    destino.parent.mkdir()
    destino.write_bytes(b"rom-data")
    manifest = _manifiesto_copia(src, destino, action=ActionMode.MOVE)

    completed = apply_manifest(manifest, confirm=True)

    assert src.exists(), "un destino ya aplicado no autoriza a borrar el origen"
    assert "se deja intacto" in completed[0]


def test_preflight_no_pide_espacio_para_lo_que_ya_esta_aplicado(tmp_path: Path, monkeypatch) -> None:
    import shutil

    src = tmp_path / "a.nes"
    src.write_bytes(b"x" * 1024)
    destino = tmp_path / "out" / "a.nes"
    destino.parent.mkdir()
    destino.write_bytes(b"x" * 1024)
    manifest = _manifiesto_copia(src, destino)
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: shutil._ntuple_diskusage(1024, 1024, 0))

    assert preflight_manifest(manifest) == [], "repetir un plan ya aplicado no necesita espacio nuevo"


def _escaneo_de_un_juego_de_varias_pistas(pistas: int = 6):
    from retroperfect.models import DatGame, DatRom, DetectedMetadata, RomHash, ScannedRom, ScanResult

    game = DatGame(
        name="Juego (Europe)",
        description="Juego (Europe)",
        roms=[DatRom(name=f"Juego (Europe) (Track {i}).bin", size=1024, crc32="aabbccdd", md5="0" * 32, sha1="1" * 40) for i in range(1, pistas + 1)],
    )
    roms = [
        ScannedRom(
            id=f"rom{i}",
            source_path=f"/roms/t{i}.bin",
            container_path=f"/roms/t{i}.bin",
            platform=Platform.PS1,
            hashes=RomHash(crc32="aabbccdd", md5="0" * 32, sha1="1" * 40, size=1024),
            dat_game=game,
            metadata=DetectedMetadata(title="Juego", regions=["Europe"], part=f"disc {i}"),
        )
        for i in range(1, pistas + 1)
    ]
    return ScanResult(id="scan", platform=Platform.PS1, input_path="/roms", roms=roms)


def test_el_escaneo_guarda_cada_juego_del_dat_una_sola_vez(tmp_path: Path) -> None:
    """Cada ROM llevaba dentro la entrada completa del DAT, con TODAS las ROMs
    del juego: un juego de diez pistas la repetía diez veces."""
    import json

    from retroperfect.storage import save_scan

    scan = _escaneo_de_un_juego_de_varias_pistas()

    ruta = save_scan(scan, state_dir=tmp_path)
    payload = json.loads(ruta.read_text(encoding="utf-8"))

    assert len(payload["dat_games"]) == 1
    assert [fila["dat_game_ref"] for fila in payload["roms"]] == [0] * 6
    assert "dat_game" not in payload["roms"][0]
    assert ruta.stat().st_size < len(scan.model_dump_json(indent=2))


def test_el_escaneo_guardado_se_recupera_igual(tmp_path: Path) -> None:
    from retroperfect.storage import load_scan, save_scan

    scan = _escaneo_de_un_juego_de_varias_pistas()

    recuperado = load_scan(save_scan(scan, state_dir=tmp_path))

    assert recuperado.model_dump() == scan.model_dump()
    assert recuperado.roms[0].dat_game is not None
    assert len(recuperado.roms[3].dat_game.roms) == 6


def test_los_escaneos_del_formato_anterior_siguen_cargando(tmp_path: Path) -> None:
    """El usuario tiene escaneos guardados de versiones anteriores."""
    from retroperfect.storage import load_scan

    scan = _escaneo_de_un_juego_de_varias_pistas()
    viejo = tmp_path / "viejo.json"
    viejo.write_text(scan.model_dump_json(indent=2), encoding="utf-8")

    assert load_scan(viejo).model_dump() == scan.model_dump()


def test_latest_sigue_siendo_un_escaneo_completo(tmp_path: Path) -> None:
    """Es la ruta que el README dice pasar a los comandos."""
    from retroperfect.storage import load_scan, save_scan

    scan = _escaneo_de_un_juego_de_varias_pistas()
    save_scan(scan, state_dir=tmp_path)

    assert load_scan(tmp_path / "scans" / "latest.json").model_dump() == scan.model_dump()


def test_aplicar_informa_del_progreso_de_cada_operacion(tmp_path: Path) -> None:
    """Copiar cientos de GB no puede ser una barra que no se mueve."""
    fuentes = []
    entradas = []
    for i in range(3):
        src = tmp_path / f"rom{i}.nes"
        src.write_bytes(f"ROM{i}".encode())
        fuentes.append(src)
        entradas.append(
            ManifestEntry(
                bucket=OutputBucket.MAIN,
                action=ActionMode.COPY,
                source_path=str(src),
                destination_path=str(tmp_path / "out" / f"rom{i}.nes"),
                rom_id=f"r{i}",
            )
        )
    manifest = Manifest(id="m", scan_id="s", platform=Platform.NES, profile_snapshot={}, entries=entradas)
    avisos: list[dict] = []

    apply_manifest(manifest, confirm=True, progress=avisos.append)

    assert [aviso["current"] for aviso in avisos if aviso["phase"] == "apply"] == [1, 2, 3]
    assert avisos[-1]["phase"] == "done"


def test_aplicar_se_puede_cancelar_entre_operaciones(tmp_path: Path) -> None:
    """Se corta entre archivos, nunca a mitad de uno: no deja copias truncadas."""
    entradas = []
    for i in range(4):
        src = tmp_path / f"rom{i}.nes"
        src.write_bytes(f"ROM{i}".encode())
        entradas.append(
            ManifestEntry(
                bucket=OutputBucket.MAIN,
                action=ActionMode.COPY,
                source_path=str(src),
                destination_path=str(tmp_path / "out" / f"rom{i}.nes"),
                rom_id=f"r{i}",
            )
        )
    manifest = Manifest(id="m", scan_id="s", platform=Platform.NES, profile_snapshot={}, entries=entradas)
    hechas: list[int] = []

    def cancelar_tras_dos() -> bool:
        hechas.append(1)
        return len(hechas) > 2

    completed = apply_manifest(manifest, confirm=True, cancelled=cancelar_tras_dos)

    assert sum(1 for linea in completed if linea.startswith("copiado")) == 2
    assert any("cancelado por el usuario" in linea for linea in completed)
    assert sorted(item.name for item in (tmp_path / "out").iterdir()) == ["rom0.nes", "rom1.nes"]


def test_un_plan_cancelado_no_escribe_playlists_a_medias(tmp_path: Path) -> None:
    """Un .m3u que liste discos que no se han copiado es peor que no tenerlo."""
    from retroperfect.models import ManifestPlaylist

    src = tmp_path / "d1.bin"
    src.write_bytes(b"D1")
    manifest = Manifest(
        id="m",
        scan_id="s",
        platform=Platform.PS1,
        profile_snapshot={},
        entries=[
            ManifestEntry(bucket=OutputBucket.MAIN, action=ActionMode.COPY, source_path=str(src), destination_path=str(tmp_path / "out" / "d1.bin"), rom_id="r")
        ],
        playlists=[ManifestPlaylist(path=str(tmp_path / "out" / "Juego.m3u"), title="Juego", entries=["d1.bin", "d2.bin"])],
    )

    apply_manifest(manifest, confirm=True, cancelled=lambda: True)

    assert not (tmp_path / "out" / "Juego.m3u").exists()


def test_una_aplicacion_interrumpida_se_puede_retomar(tmp_path: Path) -> None:
    """En cuanto un `move` se completaba, el preflight cortaba con "Origen no
    encontrado" y el plan entero quedaba bloqueado."""
    entradas = []
    for i in range(3):
        src = tmp_path / f"rom{i}.nes"
        src.write_bytes(f"ROM{i}".encode())
        entradas.append(
            ManifestEntry(
                bucket=OutputBucket.MAIN,
                action=ActionMode.MOVE,
                source_path=str(src),
                destination_path=str(tmp_path / "out" / f"rom{i}.nes"),
                rom_id=f"r{i}",
            )
        )
    manifest = Manifest(id="m", scan_id="s", platform=Platform.NES, profile_snapshot={}, entries=entradas)
    hechas: list[int] = []

    apply_manifest(manifest, confirm=True, cancelled=lambda: bool(hechas.append(1)) or len(hechas) > 1)
    assert sorted(item.name for item in (tmp_path / "out").iterdir()) == ["rom0.nes"]

    completed = apply_manifest(manifest, confirm=True)

    assert preflight_manifest(manifest) == [], "el plan a medias no debe quedar bloqueado"
    assert any("ya estaba hecha" in linea for linea in completed)
    assert sorted(item.name for item in (tmp_path / "out").iterdir()) == ["rom0.nes", "rom1.nes", "rom2.nes"]


def test_un_borrado_ya_hecho_no_bloquea_el_resto_del_plan(tmp_path: Path) -> None:
    sobra = tmp_path / "sobra.nes"
    queda = tmp_path / "queda.nes"
    queda.write_bytes(b"QUEDA")
    manifest = Manifest(
        id="m",
        scan_id="s",
        platform=Platform.NES,
        profile_snapshot={},
        entries=[
            ManifestEntry(bucket=OutputBucket.MAIN, action=ActionMode.DELETE, source_path=str(sobra), rom_id="r1"),
            ManifestEntry(bucket=OutputBucket.MAIN, action=ActionMode.DELETE, source_path=str(queda), rom_id="r2"),
        ],
    )

    assert preflight_manifest(manifest) == []
    completed = apply_manifest(manifest, confirm=True, trash_dir=tmp_path / "papelera")

    assert any("ya estaba hecha" in linea for linea in completed)
    assert not queda.exists()


def test_un_origen_que_falta_de_verdad_sigue_avisando(tmp_path: Path) -> None:
    """Retomar no puede volverse una excusa para no avisar de lo que falta."""
    manifest = Manifest(
        id="m",
        scan_id="s",
        platform=Platform.NES,
        profile_snapshot={},
        entries=[
            ManifestEntry(
                bucket=OutputBucket.MAIN,
                action=ActionMode.COPY,
                source_path=str(tmp_path / "no-existe.nes"),
                destination_path=str(tmp_path / "out" / "no-existe.nes"),
                rom_id="r",
            )
        ],
    )

    assert any("Origen no encontrado" in issue for issue in preflight_manifest(manifest))
