"""Tests de la CLI Typer: comandos destructivos, flujo principal, DAT y fuentes.

Todos los tests corren en un `tmp_path` con el cwd cambiado y con `config_dir`/
`data_dir` redirigidos: ni la colección ni la configuración reales del usuario se
tocan, y no se hace ni una petición de red.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from retroperfect import dat_sources, downloader, patching, profile, ra, remote_zip, rom_sources
from retroperfect.cli import app
from retroperfect.models import ActionMode, Manifest, ManifestEntry, OutputBucket, Platform

runner = CliRunner()


# --- Fixtures y helpers ------------------------------------------------------


@pytest.fixture
def entorno(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Aísla cwd, configuración de usuario y caché de datos. Devuelve el cwd del test."""
    config = tmp_path / "config"
    data = tmp_path / "data"
    work = tmp_path / "work"
    for path in (config, data, work):
        path.mkdir(parents=True)
    for module in (rom_sources, profile, ra):
        monkeypatch.setattr(module, "config_dir", lambda: config)
    for module in (rom_sources, ra, dat_sources, patching):
        monkeypatch.setattr(module, "data_dir", lambda: data)
    # Rich recorta las celdas al ancho del terminal; sin esto las tablas salen truncadas.
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.chdir(work)
    return work


@pytest.fixture(autouse=True)
def sin_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """Red cortada: cualquier comando que intente salir a internet falla el test."""

    def _prohibido(*args: object, **kwargs: object) -> None:
        raise AssertionError("Un test de la CLI ha intentado usar la red.")

    for module in (rom_sources, dat_sources, patching, ra):
        monkeypatch.setattr(module, "http_get", _prohibido)
    for module in (downloader, remote_zip):
        monkeypatch.setattr(module, "session", _prohibido)


def _dat(path: Path, games: dict[str, bytes], name: str = "NES") -> Path:
    """DAT Logiqx mínimo: un juego por entrada, con crc/md5/sha1 reales del payload."""
    entries = "".join(
        f'<game name="{game}"><description>{game}</description>'
        f'<release name="{game}" region="Europe"/>'
        f'<rom name="{game}.nes" size="{len(payload)}" crc="{binascii.crc32(payload) & 0xFFFFFFFF:08x}" '
        f'md5="{hashlib.md5(payload).hexdigest()}" sha1="{hashlib.sha1(payload).hexdigest()}"/></game>'
        for game, payload in games.items()
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"<datafile><header><name>{name}</name></header>{entries}</datafile>", encoding="utf-8")
    return path


def _roms(directory: Path, files: dict[str, bytes]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, payload in files.items():
        (directory / name).write_bytes(payload)
    return directory


def _manifiesto(path: Path, entries: list[ManifestEntry]) -> Path:
    manifest = Manifest(id="m-cli", scan_id="s-cli", platform=Platform.NES, profile_snapshot={}, entries=entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return path


def _entrada_copia(source: Path, destination: Path, source_md5: str | None = None) -> ManifestEntry:
    return ManifestEntry(
        bucket=OutputBucket.MAIN,
        action=ActionMode.COPY,
        source_path=str(source),
        destination_path=str(destination),
        source_md5=source_md5,
        rom_id=source.name,
    )


def _entrada_borrado(source: Path) -> ManifestEntry:
    return ManifestEntry(bucket=OutputBucket.MAIN, action=ActionMode.DELETE, source_path=str(source), rom_id=source.name)


def _bencode(value: object) -> bytes:
    if isinstance(value, int):
        return b"i%de" % value
    if isinstance(value, bytes):
        return b"%d:%s" % (len(value), value)
    if isinstance(value, str):
        return _bencode(value.encode())
    if isinstance(value, list):
        return b"l" + b"".join(_bencode(item) for item in value) + b"e"
    if isinstance(value, dict):
        return b"d" + b"".join(_bencode(key) + _bencode(item) for key, item in value.items()) + b"e"
    raise TypeError(type(value))


def _torrent(path: Path, name: str, files: dict[str, int]) -> Path:
    info = {
        b"name": name.encode(),
        b"piece length": 262144,
        b"pieces": b"\x00" * 20,
        b"files": [{b"length": size, b"path": [part.encode() for part in inner.split("/")]} for inner, size in files.items()],
    }
    path.write_bytes(_bencode({b"announce": b"udp://tracker.test:80", b"info": info}))
    return path


def _sesiones_papelera(work: Path) -> list[Path]:
    trash = work / ".retroperfect" / "trash"
    return sorted(item for item in trash.iterdir() if item.is_dir()) if trash.exists() else []


# --- apply: el comando más destructivo ---------------------------------------


def test_apply_sin_confirm_no_copia_nada(entorno: Path) -> None:
    origen = _roms(entorno / "roms", {"Juego (Europe).nes": b"ROM"}) / "Juego (Europe).nes"
    destino = entorno / "out" / "Juego (Europe).nes"
    manifest = _manifiesto(entorno / "plan.json", [_entrada_copia(origen, destino)])

    result = runner.invoke(app, ["apply", "--manifest", str(manifest)])

    assert result.exit_code != 0
    assert not destino.exists()
    assert not destino.parent.exists()
    assert origen.read_bytes() == b"ROM"


def test_apply_con_confirm_copia_y_verifica(entorno: Path) -> None:
    payload = b"ROM-VERIFICABLE"
    origen = _roms(entorno / "roms", {"Juego (Europe).nes": payload}) / "Juego (Europe).nes"
    destino = entorno / "out" / "Juego (Europe).nes"
    manifest = _manifiesto(entorno / "plan.json", [_entrada_copia(origen, destino, hashlib.md5(payload).hexdigest())])

    result = runner.invoke(app, ["apply", "--manifest", str(manifest), "--confirm"])

    assert result.exit_code == 0, result.output
    assert destino.read_bytes() == payload
    assert origen.exists()  # copy, no move
    assert "md5 verificado" in result.output
    # Queda constancia en el diario del proyecto, no en el del usuario.
    assert list((entorno / ".retroperfect" / "applied").glob("*.json"))


def test_apply_rechaza_un_modo_distinto_al_planificado(entorno: Path) -> None:
    origen = _roms(entorno / "roms", {"Juego (Europe).nes": b"ROM"}) / "Juego (Europe).nes"
    destino = entorno / "out" / "Juego (Europe).nes"
    manifest = _manifiesto(entorno / "plan.json", [_entrada_copia(origen, destino)])

    result = runner.invoke(app, ["apply", "--manifest", str(manifest), "--mode", "move", "--confirm"])

    assert result.exit_code != 0
    assert origen.exists()
    assert not destino.exists()


def test_apply_aborta_si_el_origen_cambio_desde_el_escaneo(entorno: Path) -> None:
    origen = _roms(entorno / "roms", {"Juego (Europe).nes": b"CONTENIDO-NUEVO"}) / "Juego (Europe).nes"
    destino = entorno / "out" / "Juego (Europe).nes"
    md5_viejo = hashlib.md5(b"CONTENIDO-VIEJO").hexdigest()
    manifest = _manifiesto(entorno / "plan.json", [_entrada_copia(origen, destino, md5_viejo)])

    result = runner.invoke(app, ["apply", "--manifest", str(manifest), "--confirm"])

    assert result.exit_code != 0
    assert origen.exists()


def test_apply_falla_si_falta_el_manifiesto(entorno: Path) -> None:
    result = runner.invoke(app, ["apply", "--manifest", str(entorno / "no-existe.json")])

    assert result.exit_code == 2
    assert "no-existe.json" in result.output


def test_apply_borrado_mueve_a_la_papelera_del_proyecto(entorno: Path) -> None:
    sobra = _roms(entorno / "roms", {"Sobra (Japan).nes": b"SOBRA"}) / "Sobra (Japan).nes"
    manifest = _manifiesto(entorno / "plan.json", [_entrada_borrado(sobra)])

    result = runner.invoke(app, ["apply", "--manifest", str(manifest), "--confirm"])

    assert result.exit_code == 0, result.output
    assert not sobra.exists()
    sesiones = _sesiones_papelera(entorno)
    assert len(sesiones) == 1
    assert (sesiones[0] / "Sobra (Japan).nes").read_bytes() == b"SOBRA"


# --- Papelera ----------------------------------------------------------------


def test_trash_list_sin_papelera(entorno: Path) -> None:
    result = runner.invoke(app, ["trash-list"])

    assert result.exit_code == 0
    assert "vacía" in result.output


def test_trash_list_muestra_la_sesion_creada_por_apply(entorno: Path) -> None:
    sobra = _roms(entorno / "roms", {"Sobra (Japan).nes": b"SOBRA"}) / "Sobra (Japan).nes"
    manifest = _manifiesto(entorno / "plan.json", [_entrada_borrado(sobra)])
    runner.invoke(app, ["apply", "--manifest", str(manifest), "--confirm"])

    result = runner.invoke(app, ["trash-list"])

    assert result.exit_code == 0
    assert _sesiones_papelera(entorno)[0].name in result.output


def test_trash_restore_devuelve_el_archivo_a_su_ruta_original(entorno: Path) -> None:
    sobra = _roms(entorno / "roms", {"Sobra (Japan).nes": b"SOBRA"}) / "Sobra (Japan).nes"
    manifest = _manifiesto(entorno / "plan.json", [_entrada_borrado(sobra)])
    runner.invoke(app, ["apply", "--manifest", str(manifest), "--confirm"])
    sesion = _sesiones_papelera(entorno)[0].name

    result = runner.invoke(app, ["trash-restore", sesion])

    assert result.exit_code == 0, result.output
    assert sobra.read_bytes() == b"SOBRA"
    assert _sesiones_papelera(entorno) == []


def test_trash_restore_de_una_sesion_inexistente_falla(entorno: Path) -> None:
    result = runner.invoke(app, ["trash-restore", "20200101-000000"])

    assert result.exit_code != 0


def test_trash_empty_sin_confirm_no_borra_nada(entorno: Path) -> None:
    sobra = _roms(entorno / "roms", {"Sobra (Japan).nes": b"SOBRA"}) / "Sobra (Japan).nes"
    manifest = _manifiesto(entorno / "plan.json", [_entrada_borrado(sobra)])
    runner.invoke(app, ["apply", "--manifest", str(manifest), "--confirm"])

    result = runner.invoke(app, ["trash-empty"])

    assert result.exit_code == 1
    assert "irreversible" in result.output
    assert (_sesiones_papelera(entorno)[0] / "Sobra (Japan).nes").exists()


def test_trash_empty_con_confirm_vacia_la_papelera(entorno: Path) -> None:
    sobra = _roms(entorno / "roms", {"Sobra (Japan).nes": b"SOBRA"}) / "Sobra (Japan).nes"
    manifest = _manifiesto(entorno / "plan.json", [_entrada_borrado(sobra)])
    runner.invoke(app, ["apply", "--manifest", str(manifest), "--confirm"])

    result = runner.invoke(app, ["trash-empty", "--confirm"])

    assert result.exit_code == 0, result.output
    assert "1 archivos" in result.output
    assert _sesiones_papelera(entorno) == []


# --- Flujo principal: scan / plan / report -----------------------------------


def test_scan_guarda_el_resultado_en_el_estado_del_proyecto(entorno: Path) -> None:
    roms = _roms(entorno / "roms", {"Juego (Europe).nes": b"ROM", "Otro (USA).nes": b"OTRO"})

    result = runner.invoke(app, ["scan", "--platform", "nes", "--input", str(roms), "--no-annotate-ra"])

    assert result.exit_code == 0, result.output
    assert "Scan Summary" in result.output
    latest = entorno / ".retroperfect" / "scans" / "latest.json"
    assert json.loads(latest.read_text(encoding="utf-8"))["roms"]


def test_scan_con_dat_empareja_las_roms(entorno: Path) -> None:
    payload = b"ROM"
    roms = _roms(entorno / "roms", {"Juego (Europe).nes": payload})
    dat = _dat(entorno / "nes.xml", {"Juego (Europe)": payload})

    result = runner.invoke(app, ["scan", "--platform", "nes", "--input", str(roms), "--dat", str(dat), "--no-annotate-ra"])

    assert result.exit_code == 0, result.output
    scan = json.loads((entorno / ".retroperfect" / "scans" / "latest.json").read_text(encoding="utf-8"))
    assert scan["roms"][0]["dat_game"]["name"] == "Juego (Europe)"
    assert scan["dat_path"] == str(dat)


def test_scan_rechaza_una_plataforma_desconocida(entorno: Path) -> None:
    roms = _roms(entorno / "roms", {"Juego (Europe).nes": b"ROM"})

    result = runner.invoke(app, ["scan", "--platform", "gameboy-color-2", "--input", str(roms)])

    assert result.exit_code == 2
    assert "no soportada" in result.output.lower()


def test_plan_genera_un_manifiesto_a_partir_del_escaneo(entorno: Path) -> None:
    payload = b"ROM"
    roms = _roms(entorno / "roms", {"Juego (Europe).nes": payload})
    dat = _dat(entorno / "nes.xml", {"Juego (Europe)": payload})
    runner.invoke(app, ["scan", "--input", str(roms), "--dat", str(dat), "--no-annotate-ra"])
    scan = entorno / ".retroperfect" / "scans" / "latest.json"

    result = runner.invoke(app, ["plan", "--scan", str(scan), "--outputs", "main", "--output-dir", str(entorno / "out")])

    assert result.exit_code == 0, result.output
    manifest = json.loads((entorno / ".retroperfect" / "manifests" / "latest.json").read_text(encoding="utf-8"))
    assert [entry["bucket"] for entry in manifest["entries"]] == ["main"]
    assert manifest["entries"][0]["action"] == "copy"


def test_plan_respeta_manifest_out_y_la_accion_pedida(entorno: Path) -> None:
    payload = b"ROM"
    roms = _roms(entorno / "roms", {"Juego (Europe).nes": payload})
    dat = _dat(entorno / "nes.xml", {"Juego (Europe)": payload})
    runner.invoke(app, ["scan", "--input", str(roms), "--dat", str(dat), "--no-annotate-ra"])
    destino = entorno / "planes" / "mi-plan.json"

    result = runner.invoke(
        app,
        [
            "plan",
            "--scan", str(entorno / ".retroperfect" / "scans" / "latest.json"),
            "--outputs", "main",
            "--output-dir", str(entorno / "out"),
            "--action", "move",
            "--manifest-out", str(destino),
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(destino.read_text(encoding="utf-8"))["entries"][0]["action"] == "move"


def test_plan_falla_si_el_escaneo_no_existe(entorno: Path) -> None:
    result = runner.invoke(app, ["plan", "--scan", str(entorno / "nada.json")])

    assert result.exit_code == 2


@pytest.mark.parametrize("formato", ["html", "json", "csv"])
def test_report_escribe_el_informe_en_el_formato_pedido(entorno: Path, formato: str) -> None:
    origen = _roms(entorno / "roms", {"Juego (Europe).nes": b"ROM"}) / "Juego (Europe).nes"
    manifest = _manifiesto(entorno / "plan.json", [_entrada_copia(origen, entorno / "out" / "Juego (Europe).nes")])
    salida = entorno / f"informe.{formato}"

    result = runner.invoke(app, ["report", "--manifest", str(manifest), "--format", formato, "--output", str(salida)])

    assert result.exit_code == 0, result.output
    assert salida.exists()
    assert "Juego (Europe).nes" in salida.read_text(encoding="utf-8")


def test_report_usa_la_ruta_por_defecto_del_proyecto(entorno: Path) -> None:
    origen = _roms(entorno / "roms", {"Juego (Europe).nes": b"ROM"}) / "Juego (Europe).nes"
    manifest = _manifiesto(entorno / "plan.json", [_entrada_copia(origen, entorno / "out" / "Juego (Europe).nes")])

    result = runner.invoke(app, ["report", "--manifest", str(manifest)])

    assert result.exit_code == 0, result.output
    assert (entorno / ".retroperfect" / "reports" / "m-cli.html").exists()


def test_report_rechaza_un_formato_desconocido(entorno: Path) -> None:
    origen = _roms(entorno / "roms", {"Juego (Europe).nes": b"ROM"}) / "Juego (Europe).nes"
    manifest = _manifiesto(entorno / "plan.json", [_entrada_copia(origen, entorno / "out" / "Juego (Europe).nes")])

    result = runner.invoke(app, ["report", "--manifest", str(manifest), "--format", "pdf"])

    assert result.exit_code != 0


# --- verify ------------------------------------------------------------------


def test_verify_de_una_coleccion_completa_sale_con_cero(entorno: Path) -> None:
    payload = b"ROM"
    roms = _roms(entorno / "roms", {"Juego (Europe).nes": payload})
    dat = _dat(entorno / "nes.xml", {"Juego (Europe)": payload})

    result = runner.invoke(app, ["verify", "--input", str(roms), "--dat", str(dat)])

    assert result.exit_code == 0, result.output
    assert "sin incidencias" in result.output


def test_verify_con_faltantes_sale_con_codigo_uno(entorno: Path) -> None:
    roms = _roms(entorno / "roms", {"Juego (Europe).nes": b"ROM"})
    dat = _dat(entorno / "nes.xml", {"Juego (Europe)": b"ROM", "Perdido (Europe)": b"FALTA"})

    result = runner.invoke(app, ["verify", "--input", str(roms), "--dat", str(dat)])

    assert result.exit_code == 1
    assert "Incidencias" in result.output
    assert "FALTA" in result.output


def test_verify_en_json_guarda_el_informe_y_sigue_fallando(entorno: Path) -> None:
    roms = _roms(entorno / "roms", {"Juego (Europe).nes": b"ROM"})
    dat = _dat(entorno / "nes.xml", {"Juego (Europe)": b"ROM", "Perdido (Europe)": b"FALTA"})
    salida = entorno / "verify.json"

    result = runner.invoke(app, ["verify", "--input", str(roms), "--dat", str(dat), "--format", "json", "--output", str(salida)])

    assert result.exit_code == 1
    assert json.loads(salida.read_text(encoding="utf-8"))["missing"] == 1


def test_verify_exige_un_dat(entorno: Path) -> None:
    roms = _roms(entorno / "roms", {"Juego (Europe).nes": b"ROM"})

    result = runner.invoke(app, ["verify", "--input", str(roms)])

    assert result.exit_code == 2


# --- validate ----------------------------------------------------------------


def test_validate_sin_argumentos_pide_origen_y_dat(entorno: Path) -> None:
    result = runner.invoke(app, ["validate"])

    assert result.exit_code == 0
    assert "origen" in result.output
    assert "DAT" in result.output


def test_validate_con_origen_y_dat_correctos_no_reporta_nada(entorno: Path) -> None:
    payload = b"ROM"
    roms = _roms(entorno / "roms", {"Juego (Europe).nes": payload})
    dat = _dat(entorno / "nes.xml", {"Juego (Europe)": payload})

    result = runner.invoke(app, ["validate", "--input", str(roms), "--dat", str(dat), "--output-dir", str(entorno / "out")])

    assert result.exit_code == 0, result.output
    assert "ready" in result.output


def test_validate_detecta_rutas_inexistentes(entorno: Path) -> None:
    result = runner.invoke(app, ["validate", "--input", str(entorno / "no-hay"), "--dat", str(entorno / "no-dat.xml")])

    assert result.exit_code == 0
    assert "El origen seleccionado no existe" in result.output
    assert "El DAT seleccionado no existe" in result.output


# --- DAT: import / list / compare --------------------------------------------


def test_dat_import_registra_el_dat_y_dat_list_lo_muestra(entorno: Path) -> None:
    dat = _dat(entorno / "nes.xml", {"Juego (Europe)": b"ROM"})

    importado = runner.invoke(app, ["dat-import", str(dat)])
    assert importado.exit_code == 0, importado.output
    assert "Imported" in importado.output

    listado = runner.invoke(app, ["dat-list"])
    assert listado.exit_code == 0, listado.output
    assert "NES" in listado.output


def test_dat_import_acepta_un_zip_con_varios_dats(entorno: Path) -> None:
    uno = _dat(entorno / "uno.xml", {"Uno (Europe)": b"1"}, name="Uno")
    dos = _dat(entorno / "dos.xml", {"Dos (Europe)": b"2"}, name="Dos")
    paquete = entorno / "dats.zip"
    with zipfile.ZipFile(paquete, "w") as archive:
        archive.write(uno, "uno.xml")
        archive.write(dos, "dos.xml")

    result = runner.invoke(app, ["dat-import", str(paquete)])

    assert result.exit_code == 0, result.output
    assert result.output.count("Imported") == 2


def test_dat_import_falla_si_el_archivo_no_existe(entorno: Path) -> None:
    result = runner.invoke(app, ["dat-import", str(entorno / "no-existe.dat")])

    assert result.exit_code == 2


def test_dat_list_sin_dats_instalados_no_falla(entorno: Path) -> None:
    result = runner.invoke(app, ["dat-list"])

    assert result.exit_code == 0
    assert "Installed DATs" in result.output


def test_dat_compare_resume_los_juegos_comunes_y_exclusivos(entorno: Path) -> None:
    izquierda = _dat(entorno / "izq.xml", {"Comun (Europe)": b"C", "Solo Izq (Europe)": b"I"})
    derecha = _dat(entorno / "der.xml", {"Comun (Europe)": b"C", "Solo Der (Europe)": b"D"})

    result = runner.invoke(app, ["dat-compare", str(izquierda), str(derecha)])

    assert result.exit_code == 0, result.output
    assert "Common games" in result.output
    assert "Left-only games" in result.output


def test_dat_download_sin_argumentos_solo_lista_las_fuentes_online(entorno: Path) -> None:
    result = runner.invoke(app, ["dat-download", "--platform", "nes"])

    assert result.exit_code == 0, result.output
    assert "Online DAT Sources" in result.output
    assert "libretro-nes-nointro" in result.output


def test_dat_download_con_una_fuente_desconocida_falla(entorno: Path) -> None:
    result = runner.invoke(app, ["dat-download", "--source", "fuente-que-no-existe"])

    assert result.exit_code != 0


def test_dat_update_sin_dats_de_fuentes_directas_no_hace_nada(entorno: Path) -> None:
    result = runner.invoke(app, ["dat-update"])

    assert result.exit_code == 0, result.output
    assert "No hay DATs instalados" in result.output


def test_dat_compare_falla_si_un_dat_no_existe(entorno: Path) -> None:
    izquierda = _dat(entorno / "izq.xml", {"Comun (Europe)": b"C"})

    result = runner.invoke(app, ["dat-compare", str(izquierda), str(entorno / "no-existe.xml")])

    assert result.exit_code == 2


# --- Fuentes de romsets ------------------------------------------------------


def test_rom_sources_vacio_sugiere_como_anadir_una(entorno: Path) -> None:
    result = runner.invoke(app, ["rom-sources"])

    assert result.exit_code == 0
    assert "rom-source-add" in result.output
    assert "archive_org" in result.output


def test_rom_source_add_list_toggle_y_remove(entorno: Path) -> None:
    espejo = (entorno / "espejo")
    espejo.mkdir()

    add = runner.invoke(app, ["rom-source-add", "--id", "nas", "--label", "Mi NAS", "--kind", "local_dir", "--location", str(espejo), "--platform", "nes"])
    assert add.exit_code == 0, add.output
    assert "Fuente añadida" in add.output

    listado = runner.invoke(app, ["rom-sources"])
    assert listado.exit_code == 0
    assert "Mi NAS" in listado.output

    apagar = runner.invoke(app, ["rom-source-toggle", "nas", "--disable"])
    assert apagar.exit_code == 0, apagar.output
    assert "Desactivada" in apagar.output
    assert rom_sources.list_rom_sources()[0].enabled is False

    encender = runner.invoke(app, ["rom-source-toggle", "nas", "--enable"])
    assert encender.exit_code == 0
    assert rom_sources.list_rom_sources()[0].enabled is True

    borrar = runner.invoke(app, ["rom-source-remove", "nas"])
    assert borrar.exit_code == 0, borrar.output
    assert rom_sources.list_rom_sources() == []


def test_rom_source_add_rechaza_un_tipo_desconocido(entorno: Path) -> None:
    result = runner.invoke(app, ["rom-source-add", "--id", "x", "--label", "X", "--kind", "ftp", "--location", "/tmp"])

    assert result.exit_code == 2
    assert "no soportado" in result.output.lower()
    assert rom_sources.list_rom_sources() == []


def test_rom_source_add_rechaza_una_plataforma_desconocida(entorno: Path) -> None:
    result = runner.invoke(app, ["rom-source-add", "--id", "x", "--label", "X", "--kind", "local_dir", "--location", "/tmp", "--platform", "atari-9999"])

    assert result.exit_code == 2
    assert rom_sources.list_rom_sources() == []


def test_rom_source_toggle_de_un_id_inexistente_falla(entorno: Path) -> None:
    result = runner.invoke(app, ["rom-source-toggle", "fantasma"])

    assert result.exit_code == 2


def test_rom_source_remove_de_un_id_inexistente_sale_con_codigo_uno(entorno: Path) -> None:
    result = runner.invoke(app, ["rom-source-remove", "fantasma"])

    assert result.exit_code == 1
    assert "No existe" in result.output


# --- download ----------------------------------------------------------------


def test_download_sin_fuentes_configuradas_sale_con_error(entorno: Path) -> None:
    dat = _dat(entorno / "nes.xml", {"Juego (Europe)": b"ROM"})

    result = runner.invoke(app, ["download", "--dat", str(dat)])

    assert result.exit_code == 1
    assert "rom-source-add" in result.output


def test_download_sin_confirm_solo_simula(entorno: Path) -> None:
    payload = b"FALTA"
    dat = _dat(entorno / "nes.xml", {"Falta (Europe)": payload})
    espejo = _roms(entorno / "espejo", {"Falta (Europe).nes": payload})
    runner.invoke(app, ["rom-source-add", "--id", "local", "--label", "Espejo", "--kind", "local_dir", "--location", str(espejo), "--platform", "nes"])
    destino = entorno / "romset"

    result = runner.invoke(app, ["download", "--dat", str(dat), "--dest", str(destino)])

    assert result.exit_code == 0, result.output
    assert "Simulación" in result.output
    assert "Falta" in result.output
    assert not destino.exists()


def test_download_con_confirm_verifica_e_instala(entorno: Path) -> None:
    payload = b"FALTA"
    dat = _dat(entorno / "nes.xml", {"Falta (Europe)": payload})
    espejo = _roms(entorno / "espejo", {"Falta (Europe).nes": payload})
    runner.invoke(app, ["rom-source-add", "--id", "local", "--label", "Espejo", "--kind", "local_dir", "--location", str(espejo), "--platform", "nes"])
    destino = entorno / "romset"

    result = runner.invoke(app, ["download", "--dat", str(dat), "--dest", str(destino), "--confirm"])

    assert result.exit_code == 0, result.output
    assert (destino / "Falta (Europe).nes").read_bytes() == payload
    assert "Descargados 1" in result.output


def test_download_con_confirm_pero_sin_dest_es_un_error_de_uso(entorno: Path) -> None:
    payload = b"FALTA"
    dat = _dat(entorno / "nes.xml", {"Falta (Europe)": payload})
    espejo = _roms(entorno / "espejo", {"Falta (Europe).nes": payload})
    runner.invoke(app, ["rom-source-add", "--id", "local", "--label", "Espejo", "--kind", "local_dir", "--location", str(espejo), "--platform", "nes"])

    result = runner.invoke(app, ["download", "--dat", str(dat), "--confirm"])

    assert result.exit_code == 2
    assert "--dest" in result.output


def test_download_avisa_cuando_la_unica_fuente_esta_desactivada(entorno: Path) -> None:
    dat = _dat(entorno / "nes.xml", {"Falta (Europe)": b"FALTA"})
    espejo = _roms(entorno / "espejo", {"Falta (Europe).nes": b"FALTA"})
    runner.invoke(app, ["rom-source-add", "--id", "local", "--label", "Espejo", "--kind", "local_dir", "--location", str(espejo), "--platform", "nes"])
    runner.invoke(app, ["rom-source-toggle", "local", "--disable"])

    result = runner.invoke(app, ["download", "--dat", str(dat)])

    assert result.exit_code == 1
    assert "rom-source-toggle" in result.output


def test_download_reporta_una_fuente_rota(entorno: Path) -> None:
    dat = _dat(entorno / "nes.xml", {"Falta (Europe)": b"FALTA"})
    runner.invoke(app, ["rom-source-add", "--id", "roto", "--label", "Roto", "--kind", "local_dir", "--location", str(entorno / "no-existe"), "--platform", "nes"])

    result = runner.invoke(app, ["download", "--dat", str(dat)])

    assert result.exit_code == 1
    assert "Fuente no disponible" in result.output


# --- torrent -----------------------------------------------------------------


def test_torrent_queue_en_dry_run_no_toca_el_cliente(entorno: Path) -> None:
    payload = b"FALTA"
    dat = _dat(entorno / "nes.xml", {"Falta (Europe)": payload})
    torrent = _torrent(entorno / "set.torrent", "NES Set", {"Falta (Europe).nes": len(payload)})

    result = runner.invoke(app, ["torrent-queue", "--torrent", str(torrent), "--dat", str(dat), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "NES Set" in result.output
    assert "Simulación" in result.output
    assert "Falta" in result.output


def test_torrent_collect_copia_al_romset_lo_ya_descargado(entorno: Path) -> None:
    payload = b"FALTA"
    dat = _dat(entorno / "nes.xml", {"Falta (Europe)": payload})
    torrent = _torrent(entorno / "set.torrent", "NES Set", {"Falta (Europe).nes": len(payload)})
    descargas = _roms(entorno / "descargas" / "NES Set", {"Falta (Europe).nes": payload})
    destino = entorno / "romset"

    result = runner.invoke(
        app,
        ["torrent-collect", "--torrent", str(torrent), "--dat", str(dat), "--downloads", str(descargas.parent), "--dest", str(destino)],
    )

    assert result.exit_code == 0, result.output
    assert (destino / "Falta (Europe).nes").read_bytes() == payload
    # Se copia, no se mueve: el cliente sigue sembrando desde su carpeta.
    assert (descargas / "Falta (Europe).nes").exists()
    assert "Instalados 1" in result.output


def test_torrent_collect_avisa_de_una_descarga_incompleta(entorno: Path) -> None:
    payload = b"FALTA"
    dat = _dat(entorno / "nes.xml", {"Falta (Europe)": payload})
    torrent = _torrent(entorno / "set.torrent", "NES Set", {"Falta (Europe).nes": len(payload)})
    descargas = _roms(entorno / "descargas" / "NES Set", {"Falta (Europe).nes": b"FA"})
    destino = entorno / "romset"

    result = runner.invoke(
        app,
        ["torrent-collect", "--torrent", str(torrent), "--dat", str(dat), "--downloads", str(descargas.parent), "--dest", str(destino)],
    )

    assert result.exit_code == 0, result.output
    assert not (destino / "Falta (Europe).nes").exists()
    assert "Instalados 0" in result.output


def test_torrent_queue_falla_si_el_torrent_no_existe(entorno: Path) -> None:
    dat = _dat(entorno / "nes.xml", {"Falta (Europe)": b"FALTA"})

    result = runner.invoke(app, ["torrent-queue", "--torrent", str(entorno / "no.torrent"), "--dat", str(dat)])

    assert result.exit_code == 2


# --- RetroAchievements (con el cliente HTTP sustituido) ----------------------


def test_sync_ra_pasa_credenciales_y_resume_lo_cacheado(entorno: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from retroperfect import cli

    llamadas: list[tuple[Platform, str | None, str | None]] = []

    def _fake_sync(platform: Platform, username: str | None = None, api_key: str | None = None) -> int:
        llamadas.append((platform, username, api_key))
        return 42

    monkeypatch.setattr(cli, "sync_ra_hashes", _fake_sync)

    result = runner.invoke(app, ["sync-ra", "--platform", "snes", "--username", "yo", "--api-key", "secreto"])

    assert result.exit_code == 0, result.output
    assert llamadas == [(Platform.SNES, "yo", "secreto")]
    assert "42" in result.output


def test_sync_ra_details_reporta_los_hashes_actualizados(entorno: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from retroperfect import cli

    monkeypatch.setattr(cli, "sync_ra_patch_details", lambda platform, username=None, api_key=None, limit=None: 7)

    result = runner.invoke(app, ["sync-ra-details", "--platform", "nes", "--limit", "7"])

    assert result.exit_code == 0, result.output
    assert "7" in result.output


def test_sync_ra_rechaza_una_plataforma_desconocida(entorno: Path) -> None:
    result = runner.invoke(app, ["sync-ra", "--platform", "nes-2"])

    assert result.exit_code == 2


# --- gui ---------------------------------------------------------------------


def test_gui_arranca_el_servidor_con_los_parametros_dados(entorno: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from retroperfect import gui

    llamadas: list[dict[str, object]] = []
    monkeypatch.setattr(gui, "run", lambda **kwargs: llamadas.append(kwargs))

    result = runner.invoke(app, ["gui", "--host", "0.0.0.0", "--port", "9999", "--exit-on-idle"])

    assert result.exit_code == 0, result.output
    assert llamadas == [{"host": "0.0.0.0", "port": 9999, "exit_on_idle": True}]


# --- Ayuda y registro de comandos --------------------------------------------


TODOS_LOS_COMANDOS = [
    "scan", "sync-ra", "sync-ra-details", "plan", "apply", "report", "verify",
    "dat-import", "dat-download", "dat-update", "dat-list", "dat-compare",
    "rom-sources", "rom-source-add", "rom-source-toggle", "rom-source-remove",
    "download", "torrent-queue", "torrent-collect", "validate",
    "trash-list", "trash-restore", "trash-empty", "gui",
]


def test_la_ayuda_general_registra_todos_los_comandos(entorno: Path) -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for comando in TODOS_LOS_COMANDOS:
        assert comando in result.output


@pytest.mark.parametrize("comando", TODOS_LOS_COMANDOS)
def test_cada_comando_tiene_ayuda_propia(entorno: Path, comando: str) -> None:
    result = runner.invoke(app, [comando, "--help"])

    assert result.exit_code == 0, result.output
