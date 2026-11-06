"""Filas y formateadores de la GUI.

Son funciones puras, sin widgets ni estado: construyen lo que el usuario lee
para decidir qué conserva y qué pierde. Se prueban con escaneos y manifiestos
de verdad, no con dobles, porque lo que se quiere comprobar es justamente que
derivan bien de ellos.
"""
from __future__ import annotations

import binascii
import hashlib
from datetime import UTC, datetime
from pathlib import Path

from retroperfect.coverage import build_coverage
from retroperfect.dat import DatIndex, parse_dat
from retroperfect.gui_rows import (
    _bucket_divergence_rows,
    _coverage_kind,
    _coverage_rows,
    _coverage_status,
    _coverage_variant_rows,
    _coverage_visual,
    _diagnostic_rows,
    _duplicate_rows,
    _export_tree_rows,
    _output_label,
    _patch_queue_rows,
    _profile_from_controls,
    _ra_conflict_rows,
    _rom_summary_key,
    _scan_group_sample,
    _unmatched_rows,
    _variant_status,
    _variant_visual,
)
from retroperfect.models import ActionMode, ExportLayout, OutputBucket, Platform, ProfileOutput, SelectionProfile
from retroperfect.rules import build_manifest
from retroperfect.scanner import scan_directory


def _dat(path: Path, juegos: dict[str, bytes]) -> Path:
    lineas = ['<?xml version="1.0"?>', "<datafile>", "<header><name>Prueba</name></header>"]
    for nombre, data in juegos.items():
        lineas.append(
            f'<game name="{nombre}"><description>{nombre}</description>'
            f'<rom name="{nombre}.nes" size="{len(data)}" crc="{binascii.crc32(data) & 0xFFFFFFFF:08x}" '
            f'md5="{hashlib.md5(data).hexdigest()}" sha1="{hashlib.sha1(data).hexdigest()}"/></game>'
        )
    lineas.append("</datafile>")
    path.write_text("\n".join(lineas), encoding="utf-8")
    return path


def _escenario(tmp_path: Path, en_dat: dict[str, bytes], en_disco: dict[str, bytes] | None = None):
    """Devuelve (scan, catalog, manifest) con un plan 1G1R ya calculado."""
    dat = _dat(tmp_path / "nes.xml", en_dat)
    roms = tmp_path / "roms"
    roms.mkdir(exist_ok=True)
    for nombre, data in (en_disco if en_disco is not None else en_dat).items():
        (roms / f"{nombre}.nes").write_bytes(data)
    catalog = parse_dat(dat)
    scan = scan_directory(roms, Platform.NES, dat_index=DatIndex(catalog), dat_path=dat)
    profile = SelectionProfile(outputs=[ProfileOutput(bucket=OutputBucket.MAIN)])
    manifest = build_manifest(scan, profile, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.COPY)
    return scan, catalog, manifest


# --- cobertura ---------------------------------------------------------------


def test_las_filas_de_cobertura_dicen_que_se_guarda_y_que_se_pierde(tmp_path: Path) -> None:
    juegos = {"Juego (Europe)": b"EU", "Juego (USA)": b"US"}
    scan, catalog, manifest = _escenario(tmp_path, juegos)
    summary = build_coverage(scan, catalog, manifest)

    filas = _coverage_rows(summary, "all", scan, manifest)

    assert len(filas) == 1, "las dos regiones son variantes del mismo juego"
    fila = filas[0]
    assert fila["status"] == "Se guardará"
    assert fila["visual"] == "green"
    assert fila["kind"] == "keep"
    assert fila["variants"] == "DAT 2 · ROM 2 · Match 2"
    assert "🇪🇺" in str(fila["rom_regions"])


def test_las_filas_de_cobertura_filtran_por_modo(tmp_path: Path) -> None:
    scan, catalog, manifest = _escenario(tmp_path, {"Tengo (Europe)": b"EU", "Falta (Europe)": b"NO"}, en_disco={"Tengo (Europe)": b"EU"})
    summary = build_coverage(scan, catalog, manifest)

    assert [fila["title"] for fila in _coverage_rows(summary, "missing", scan, manifest)] == ["Falta"]
    assert [fila["title"] for fila in _coverage_rows(summary, "matched", scan, manifest)] == ["Tengo"]
    assert len(_coverage_rows(summary, "all", scan, manifest)) == 2


def test_un_juego_que_falta_se_marca_en_rojo_y_explica_por_que(tmp_path: Path) -> None:
    scan, catalog, manifest = _escenario(tmp_path, {"Falta (Europe)": b"NO"}, en_disco={})
    fila = build_coverage(scan, catalog, manifest).rows[0]

    assert _coverage_kind(fila) == "missing_romset"
    assert _coverage_status(fila) == "Falta en romset"
    assert _coverage_visual(fila) == "red"
    assert "📭" in _coverage_rows(build_coverage(scan, catalog, manifest), "missing", scan, manifest)[0]["reason"]


def test_un_archivo_fuera_del_dat_se_distingue_de_uno_que_falta(tmp_path: Path) -> None:
    scan, catalog, manifest = _escenario(tmp_path, {"Conocido (Europe)": b"OK"}, en_disco={"Conocido (Europe)": b"OK", "Desconocido (Europe)": b"??"})
    filas = {fila["title"]: fila for fila in _coverage_rows(build_coverage(scan, catalog, manifest), "all", scan, manifest)}

    assert filas["Desconocido"]["kind"] == "outside_dat"
    assert filas["Desconocido"]["status"] == "Fuera del DAT"
    assert "❌" in str(filas["Desconocido"]["reason"])


def test_las_variantes_de_cobertura_listan_cada_archivo(tmp_path: Path) -> None:
    scan, catalog, manifest = _escenario(tmp_path, {"Juego (Europe)": b"EU", "Juego (USA)": b"US"})

    filas = _coverage_variant_rows(scan, catalog, manifest, "all")

    assert len(filas) == 2
    assert {fila["status"] for fila in filas} == {"Se guardará", "Se perderá"}


def test_los_hashes_fuera_del_dat_salen_con_su_sugerencia(tmp_path: Path) -> None:
    scan, _catalog, _manifest = _escenario(tmp_path, {"Conocido (Europe)": b"OK"}, en_disco={"Conocido (Europe)": b"OK", "Raro (Europe)": b"??"})

    filas = _unmatched_rows(scan)

    assert [fila["type"] for fila in filas] == ["Hash fuera del DAT"]
    assert "Raro" in str(filas[0]["file"])
    assert "headered" in str(filas[0]["suggestion"])
    assert _unmatched_rows(None) == []


def test_los_duplicados_distinguen_hash_identico_de_variante(tmp_path: Path) -> None:
    scan, _catalog, _manifest = _escenario(
        tmp_path,
        {"Juego (Europe)": b"MISMO", "Juego (USA)": b"OTRO"},
        en_disco={"Juego (Europe)": b"MISMO", "Juego (Europe) (Copia)": b"MISMO", "Juego (USA)": b"OTRO"},
    )

    tipos = {fila["kind"] for fila in _duplicate_rows(scan)}

    assert tipos == {"Hash idéntico", "Variantes 1G1R"}
    assert _duplicate_rows(None) == []


def test_los_diagnosticos_se_pasan_a_filas(tmp_path: Path) -> None:
    from retroperfect.diagnostics import DiagnosticRow

    filas = _diagnostic_rows([DiagnosticRow(status="WARN", item="Algo", detail="pasa", recommendation="arréglalo")])

    assert filas == [{"status": "WARN", "item": "Algo", "detail": "pasa", "recommendation": "arréglalo"}]


# --- decisiones --------------------------------------------------------------


def test_la_divergencia_entre_main_y_ra_se_explica(tmp_path: Path) -> None:
    scan, _catalog, _manifest = _escenario(tmp_path, {"Juego (Europe)": b"EU"})
    profile = SelectionProfile(
        outputs=[ProfileOutput(bucket=OutputBucket.MAIN), ProfileOutput(bucket=OutputBucket.RA, require_ra=True)]
    )
    manifest = build_manifest(scan, profile, [OutputBucket.MAIN, OutputBucket.RA], output_dir=tmp_path / "out", action=ActionMode.COPY)

    filas = _bucket_divergence_rows(scan, manifest)

    assert filas, "un juego sin variante RA tiene que aparecer como divergencia"
    assert filas[0]["main"].endswith("Juego (Europe).nes")
    assert filas[0]["ra"] in {"", "—"} or "Juego" in filas[0]["ra"]


def test_el_arbol_de_salida_cuenta_los_archivos_por_carpeta(tmp_path: Path) -> None:
    scan, _catalog, _manifest = _escenario(tmp_path, {"Juego (Europe)": b"EU", "Otro (USA)": b"US"})
    profile = SelectionProfile(export_layout=ExportLayout.ORGANIZED, outputs=[ProfileOutput(bucket=OutputBucket.MAIN)])
    manifest = build_manifest(scan, profile, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.COPY)

    filas = _export_tree_rows(manifest, str(tmp_path / "out"))

    carpetas = {str(fila["folder"]): fila for fila in filas}
    assert "EUR" in carpetas and "USA" in carpetas
    assert carpetas["EUR"]["files"] == 1
    assert sum(int(fila["files"]) for fila in filas) == 2


def test_sin_conflictos_ra_la_tabla_sale_vacia(tmp_path: Path) -> None:
    scan, _catalog, manifest = _escenario(tmp_path, {"Juego (Europe)": b"EU"})

    assert _ra_conflict_rows(scan, manifest) == []
    assert _patch_queue_rows(manifest) == []


def test_la_muestra_de_la_prueba_segura_acota_los_grupos(tmp_path: Path) -> None:
    juegos = {f"Juego {i} (Europe)": f"ROM{i}".encode() for i in range(6)}
    scan, _catalog, _manifest = _escenario(tmp_path, juegos)

    muestra = _scan_group_sample(scan, 2)

    assert muestra is not None
    assert len({_rom_summary_key(rom) for rom in muestra.roms}) == 2
    assert _scan_group_sample(None, 2) is None


def test_las_etiquetas_de_salida_y_estado_cubren_sus_combinaciones() -> None:
    assert _output_label(True, True) == "main, RA"
    assert _output_label(True, False) == "main"
    assert _output_label(False, True) == "RA"
    assert _output_label(False, False) == "Plan no creado"

    assert _variant_status(in_dat=True, will_keep_main=True, will_keep_ra=False, planned=True) == "Se guardará"
    assert _variant_status(in_dat=True, will_keep_main=False, will_keep_ra=False, planned=True) == "Se perderá"
    assert _variant_status(in_dat=True, will_keep_main=False, will_keep_ra=False, planned=False) == "Coincide con DAT"
    assert _variant_status(in_dat=False, will_keep_main=False, will_keep_ra=False, planned=False) == "Fuera del DAT"
    assert _variant_visual("keep") == "green"
    assert _variant_visual("drop") == "yellow"
    assert _variant_visual("missing_romset") == "red"
    assert _variant_visual("cualquier-otra") == "neutral"


def test_el_perfil_se_reconstruye_desde_los_controles_de_la_interfaz() -> None:
    """La pestaña Perfil escribe en un diccionario de widgets; de ahí sale el
    perfil con el que se cura, así que la traducción tiene que ser exacta."""

    class Control:
        def __init__(self, value: object) -> None:
            self.value = value

    controls = {
        "profile_name": Control("mío"),
        "export_layout": Control(ExportLayout.ORGANIZED.value),
        "auto_patch_ra": Control(True),
        "main_enabled": Control(True),
        "main_require_ra": Control(False),
        "main_strict_1g1r": Control(True),
        "main_prefer_ra": Control(True),
        "main_regions": Control(["Spain", "Europe"]),
        "main_languages": Control(["Spanish"]),
        "main_tags": Control(["Beta"]),
        "main_newest": Control(False),
        "ra_enabled": Control(True),
        "ra_strict_1g1r": Control(False),
        "ra_regions": Control(["USA"]),
        "ra_languages": Control(["English"]),
        "ra_tags": Control([]),
        "ra_newest": Control(True),
    }

    profile = _profile_from_controls(controls)

    assert profile.name == "mío"
    assert profile.export_layout == ExportLayout.ORGANIZED
    assert profile.auto_patch_ra is True
    main = next(output for output in profile.outputs if output.bucket == OutputBucket.MAIN)
    assert main.region_priority == ["Spain", "Europe"]
    assert main.tag_excludes == ["Beta"]
    assert main.strict_1g1r is True
    assert main.prefer_newest_revision is False
    ra = next(output for output in profile.outputs if output.bucket == OutputBucket.RA)
    assert ra.require_ra is True
    assert ra.region_priority == ["USA"]


# --- catálogo de plataformas y formateadores ---------------------------------


def test_las_pestanas_del_catalogo_reparten_todas_las_plataformas() -> None:
    """Cada pestaña filtra por marca o tipo; si una condición se solapa o deja
    un hueco, hay plataformas que no se ven en ninguna."""
    from retroperfect.gui_rows import _platform_card_rows_for_tab
    from retroperfect.gui_rows.platform import _platform_tab_matches
    from retroperfect.platforms import list_platforms

    pestanas = ["Nintendo", "Sega", "Atari", "NEC", "Sony", "Microsoft", "Apple", "Commodore", "Arcade", "SNK/Bandai", "Discos/Digital", "Ordenadores", "Otras", "Especiales"]
    todas = _platform_card_rows_for_tab("Todas")

    assert len(todas) == len(list_platforms())
    sin_pestana = [spec.short_name for spec in list_platforms() if not any(_platform_tab_matches(spec, tab) for tab in pestanas)]
    assert sin_pestana == [], f"{len(sin_pestana)} plataforma(s) no salen en ninguna pestaña: {sin_pestana[:5]}"


def test_el_catalogo_filtra_por_tipo_generacion_y_busqueda() -> None:
    from retroperfect.gui_rows import _platform_card_rows_for_tab

    nintendo = _platform_card_rows_for_tab("Nintendo")
    assert nintendo and {fila["brand"] for fila in nintendo} == {"Nintendo"}

    cartuchos = _platform_card_rows_for_tab("Nintendo", kind="sobremesa")
    assert cartuchos and {fila["kind"] for fila in cartuchos} == {"sobremesa"}
    assert len(cartuchos) < len(nintendo)

    buscado = _platform_card_rows_for_tab("Todas", query="  GAME   boy  ")
    assert buscado, "la búsqueda tiene que ignorar mayúsculas y espacios de sobra"
    assert all("game boy" in " ".join(str(valor) for valor in fila.values()).casefold() for fila in buscado)
    assert _platform_card_rows_for_tab("Todas", query="esto-no-existe") == []


def test_las_filas_de_dats_instalados_traducen_la_plataforma(tmp_path: Path, monkeypatch) -> None:
    from retroperfect.dat_manager import DatMetadata
    from retroperfect.gui_rows import _dat_rows
    from retroperfect.gui_rows import platform as platform_rows

    dats = [
        DatMetadata(id="a", name="NES DAT", platform="nes", source="libretro", format="logiqx", games=3, roms=3, parent_clone=True, header_mode="none", recommended=True, regions=["Europe"], path="/x/nes.dat", imported_at=datetime.now(UTC)),
        DatMetadata(id="b", name="Suelto", platform=None, source="import", format="logiqx", games=1, roms=1, parent_clone=False, header_mode="none", recommended=False, regions=[], path="/x/otro.dat", imported_at=datetime.now(UTC)),
    ]
    monkeypatch.setattr(platform_rows, "list_installed_dats", lambda: dats)

    filas = _dat_rows()

    assert [fila["platform"] for fila in filas] == ["NES / Famicom", "Sin detectar"]
    assert [fila["pc"] for fila in filas] == ["sí", "no"]
    assert [fila["recommended"] for fila in filas] == ["sí", "no"]
    # Filtrado por plataforma: el DAT sin detectar acompaña siempre.
    assert len(_dat_rows(Platform.NES)) == 2
    assert [fila["name"] for fila in _dat_rows(Platform.SNES)] == ["Suelto"]


def test_las_banderas_de_region_marcan_lo_que_no_conocen() -> None:
    from retroperfect.gui_rows import _flag_regions

    assert _flag_regions(["Spain", "Japan"]) == "🇪🇸 Spain, 🇯🇵 Japan"
    assert _flag_regions(["Korea"]).startswith("🇰🇷")
    assert "🏳️ Poland" in _flag_regions(["Poland"]), "una región sin bandera se nombra igual"
    assert _flag_regions([]) == ""


def test_el_icono_ra_distingue_compatible_de_parcheable(tmp_path: Path) -> None:
    from retroperfect.gui_rows import _ra_icon

    scan, _catalog, _manifest = _escenario(tmp_path, {"Juego (Europe)": b"EU"})
    rom = scan.roms[0]

    assert _ra_icon(rom) == ""
    rom.ra_game_id = 7
    assert _ra_icon(rom) == "🏆"
    rom.ra_labels = ["RAPatches"]
    assert _ra_icon(rom) == "🏆 🩹"
    rom.ra_labels = []
    rom.ra_patch_url = "https://ejemplo.org/p.zip"
    assert _ra_icon(rom) == "🏆 🩹"


def test_el_estado_de_la_cache_ra_se_resume_para_la_cabecera(tmp_path: Path, monkeypatch) -> None:
    from retroperfect.gui_rows import _ra_status_label
    from retroperfect.gui_rows import platform as platform_rows

    monkeypatch.setattr(platform_rows, "ra_cache_count", lambda _platform: 120)
    monkeypatch.setattr(platform_rows, "ra_sync_status", lambda _platform: {"cached_games": 40, "detailed_games": 10, "remaining_details": 30, "hashes_at": "2026-11-05", "details_at": "nunca"})

    etiqueta = _ra_status_label(Platform.NES)

    assert "120 hashes / 40 juegos" in etiqueta
    assert "pendientes 30" in etiqueta
    assert "detalles nunca" in etiqueta
