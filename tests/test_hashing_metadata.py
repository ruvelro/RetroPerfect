import hashlib

from retroperfect.hashing import hash_bytes, nes_ra_hash
from retroperfect.metadata import parse_no_intro_name


def test_nes_ra_hash_ignores_ines_header() -> None:
    payload = b"actual-rom-data"
    data = b"NES\x1a" + bytes(12) + payload
    assert nes_ra_hash(data) == hashlib.md5(payload).hexdigest()
    assert hash_bytes(data).md5 != nes_ra_hash(data)


def test_parse_no_intro_metadata() -> None:
    metadata = parse_no_intro_name("Example Game (Spain) (En,Es) (Rev 2) (Beta).nes")
    assert metadata.title == "Example Game"
    assert "Spain" in metadata.regions
    assert "English" in metadata.languages
    assert "Spanish" in metadata.languages
    assert metadata.revision == 2
    assert "Beta" in metadata.tags


def test_parse_more_no_intro_metadata_shapes() -> None:
    metadata = parse_no_intro_name("Example (Europe) (En,Fr,De,Es,It) (Rev A) (Virtual Console).nes")
    assert "Europe" in metadata.regions
    assert "Multi" in metadata.languages
    assert "Spanish" in metadata.languages
    assert metadata.revision == 1
    assert "Virtual Console" in metadata.tags


def test_parse_no_intro_v_revision_without_space() -> None:
    metadata = parse_no_intro_name("Family BASIC (Japan) (v2.1).nes")
    assert metadata.version == "2.1"
    assert metadata.revision == 1


def test_hash_stream_matches_in_memory_hashing() -> None:
    import io

    from retroperfect.hashing import hash_bytes, hash_stream
    from retroperfect.models import Platform

    data = bytes(range(256)) * 5000
    streamed = hash_stream(io.BytesIO(data))
    in_memory = hash_bytes(data, Platform.MD)
    assert streamed == in_memory


def test_scan_streams_large_direct_files(tmp_path, monkeypatch) -> None:
    import zipfile

    from retroperfect import scanner
    from retroperfect.models import Platform

    monkeypatch.setattr(scanner, "STREAM_THRESHOLD_BYTES", 1)
    payload = b"SEGA" * 100
    (tmp_path / "Game (Europe).md").write_bytes(payload)
    with zipfile.ZipFile(tmp_path / "Game (USA).zip", "w") as archive:
        archive.writestr("Game (USA).md", payload)
    scan = scanner.scan_directory(tmp_path, Platform.MD)
    assert len(scan.roms) == 2
    for rom in scan.roms:
        assert rom.hashes.size == len(payload)
        assert rom.hashes.md5 == rom.hashes.payload_md5


def test_ra_payloads_strip_platform_headers() -> None:
    from retroperfect.hashing import hash_bytes
    from retroperfect.models import Platform

    cases = [
        (Platform.FDS, b"FDS\x1a" + bytes(12), b"disk-data"),
        (Platform.LYNX, b"LYNX\x00" + bytes(59), b"lynx-data"),
        (Platform.A7800, b"\x01ATARI7800" + bytes(118), b"a78-data"),
        (Platform.PCE, bytes(512), b"P" * (128 * 1024)),
    ]
    for platform, header, payload in cases:
        hashes = hash_bytes(header + payload, platform)
        assert hashes.ra_hash == hashlib.md5(payload).hexdigest(), platform
        # sin cabecera, el hash RA es el del archivo completo
        bare = hash_bytes(payload, platform)
        assert bare.ra_hash == hashlib.md5(payload).hexdigest(), platform


def test_nds_ra_hash_uses_header_arm_and_icon() -> None:
    from retroperfect.hashing import hash_bytes, nds_ra_payload
    from retroperfect.models import Platform

    header = bytearray(0x160)
    arm9 = b"9" * 0x40
    arm7 = b"7" * 0x20
    icon = b"I" * 0xA00
    arm9_offset = 0x160
    arm7_offset = arm9_offset + len(arm9)
    icon_offset = arm7_offset + len(arm7)
    header[0x20:0x24] = arm9_offset.to_bytes(4, "little")
    header[0x2C:0x30] = len(arm9).to_bytes(4, "little")
    header[0x30:0x34] = arm7_offset.to_bytes(4, "little")
    header[0x3C:0x40] = len(arm7).to_bytes(4, "little")
    header[0x68:0x6C] = icon_offset.to_bytes(4, "little")
    rom = bytes(header) + arm9 + arm7 + icon + b"resto-del-cartucho" * 100

    expected = hashlib.md5(bytes(header) + arm9 + arm7 + icon).hexdigest()
    assert nds_ra_payload(rom) == bytes(header) + arm9 + arm7 + icon
    hashes = hash_bytes(rom, Platform.NDS)
    assert hashes.ra_hash == expected
    assert hashes.ra_hash != hashes.md5


def test_nds_ra_hash_falls_back_on_malformed_header() -> None:
    from retroperfect.hashing import hash_bytes, nds_ra_payload
    from retroperfect.models import Platform

    truncated = bytes(0x100)  # más corto que la cabecera NDS
    assert nds_ra_payload(truncated) is None
    hashes = hash_bytes(truncated, Platform.NDS)
    assert hashes.ra_md5 is None
    assert hashes.ra_hash == hashes.md5

    out_of_bounds = bytearray(0x160)
    out_of_bounds[0x20:0x24] = (0x10000).to_bytes(4, "little")  # ARM9 fuera del archivo
    out_of_bounds[0x2C:0x30] = (0x40).to_bytes(4, "little")
    assert nds_ra_payload(bytes(out_of_bounds)) is None


def test_arcade_ra_hash_is_set_name_md5(tmp_path) -> None:
    import zipfile

    from retroperfect.hashing import arcade_ra_md5
    from retroperfect.models import Platform
    from retroperfect.scanner import scan_directory

    with zipfile.ZipFile(tmp_path / "SFA3.zip", "w") as archive:
        archive.writestr("sfa3.key", b"contenido")
    scan = scan_directory(tmp_path, Platform.MAME)
    assert len(scan.roms) == 1
    assert scan.roms[0].hashes.ra_hash == arcade_ra_md5("sfa3")
    assert scan.roms[0].hashes.ra_hash == hashlib.md5(b"sfa3").hexdigest()


def test_se_reconocen_las_regiones_de_los_catalogos_completos() -> None:
    """Una región sin reconocer no es cosmética: deja la ROM como "región
    desconocida" y la hace perder el 1G1R sin motivo visible."""
    from retroperfect.metadata import parse_no_intro_name

    esperado = {
        "Juego (Korea).zip": ["Korea"],
        "Juego (Denmark).zip": ["Denmark"],
        "Juego (Norway).zip": ["Norway"],
        "Juego (Finland).zip": ["Finland"],
        "Juego (Portugal).zip": ["Portugal"],
        "Juego (Russia).zip": ["Russia"],
        "Juego (Poland).zip": ["Poland"],
        "Juego (Latin America).zip": ["Latin America"],
        "Juego (UK).zip": ["UK"],
        "Juego (Canada).zip": ["Canada"],
    }
    for nombre, regiones in esperado.items():
        assert parse_no_intro_name(nombre).regions == regiones, nombre


def test_las_regiones_que_usa_la_curacion_son_todas_detectables() -> None:
    """EUROPEAN_REGIONS y REGION_FOLDERS decidían carpeta y prioridad con
    regiones que el parser no podía producir, así que eran código muerto."""
    from retroperfect.metadata import REGION_ALIASES
    from retroperfect.rules import EUROPEAN_REGIONS, REGION_FOLDERS

    detectables = set(REGION_ALIASES.values())
    assert (EUROPEAN_REGIONS | set(REGION_FOLDERS)) <= detectables


def test_multi5_y_sus_variantes_cuentan_como_multiidioma() -> None:
    from retroperfect.metadata import parse_no_intro_name

    for nombre in ["Juego (Europe) (Multi5).zip", "Juego (Europe) (Multi 3).zip", "Juego (Europe) (M5).zip"]:
        assert parse_no_intro_name(nombre).languages == ["Multi"], nombre


def test_dos_idiomas_cualesquiera_marcan_multiidioma() -> None:
    """La regla contaba una lista de códigos escrita a mano, así que una
    edición en español y catalán se quedaba sin marcar."""
    from retroperfect.metadata import parse_no_intro_name

    assert parse_no_intro_name("Juego (Spain) (Es,Ca).zip").languages == ["Spanish", "Catalan", "Multi"]
    assert parse_no_intro_name("Juego (Europe) (En,Fr,De).zip").languages == ["English", "French", "German", "Multi"]
    assert parse_no_intro_name("Juego (Europe) (En).zip").languages == ["English"]


def test_el_filtro_previo_de_etiquetas_no_cambia_lo_que_se_detecta() -> None:
    """El bucle de 28 expresiones por nombre dominaba la carga de un DAT, pero
    un nombre puede llevar varias etiquetas y unas contienen a otras."""
    from retroperfect.metadata import parse_no_intro_name

    assert parse_no_intro_name("Juego (Europe).zip").tags == []
    assert parse_no_intro_name("Juego (Europe) (Beta).zip").tags == ["Beta"]
    sueltas = parse_no_intro_name("Juego (Hack, Translation).zip").tags
    assert set(sueltas) == {"Hack", "Translation"}
    solapadas = parse_no_intro_name("Juego (Nintendo Switch Online).zip").tags
    assert "Nintendo Switch Online" in solapadas and "Switch Online" in solapadas
