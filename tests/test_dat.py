import zipfile
from pathlib import Path

from retroperfect.dat import DatIndex, parse_clrmamepro_dat, parse_logiqx_dat
from retroperfect.dat_manager import compare_dats, download_and_import_url, import_dat_file, inspect_dat, suggest_dat_for_source, validate_setup


def test_parse_parent_clone_dat(tmp_path: Path) -> None:
    dat = tmp_path / "nes.xml"
    dat.write_text(
        """<?xml version="1.0"?>
<datafile>
  <header><name>Nintendo - Nintendo Entertainment System</name><description>NES</description></header>
  <game name="Game (USA)"><description>Game (USA)</description><release name="Game" region="USA"/><rom name="Game (USA).nes" size="4" crc="adf3f363" md5="81dc9bdb52d04dc20036dbd8313ed055" sha1="7110eda4d09e062aa5e4a390b0a572ac0d2c0220"/></game>
  <game name="Game (Europe)" cloneof="Game (USA)"><description>Game (Europe)</description><release name="Game" region="Europe"/><rom name="Game (Europe).nes" size="4" crc="adf3f363" md5="81dc9bdb52d04dc20036dbd8313ed055" sha1="7110eda4d09e062aa5e4a390b0a572ac0d2c0220"/></game>
</datafile>""",
        encoding="utf-8",
    )
    catalog = parse_logiqx_dat(dat)
    assert catalog.name == "Nintendo - Nintendo Entertainment System"
    assert catalog.games[1].cloneof == "Game (USA)"
    assert catalog.games[1].releases == ["Europe"]
    assert DatIndex(catalog).match("adf3f363", "81dc9bdb52d04dc20036dbd8313ed055", "7110eda4d09e062aa5e4a390b0a572ac0d2c0220", 4)


def test_parse_clrmamepro_dat(tmp_path: Path) -> None:
    dat = tmp_path / "nes.dat"
    dat.write_text(
        """clrmamepro (
    name "Nintendo - Nintendo Entertainment System"
    description "NES"
)
game (
    name "Game (USA)"
    region "USA"
    rom ( name "Game (USA).nes" size 4 crc ADF3F363 md5 81DC9BDB52D04DC20036DBD8313ED055 sha1 7110EDA4D09E062AA5E4A390B0A572AC0D2C0220 )
)""",
        encoding="utf-8",
    )
    catalog = parse_clrmamepro_dat(dat)
    assert catalog.name == "Nintendo - Nintendo Entertainment System"
    assert catalog.games[0].releases == ["USA"]
    assert catalog.games[0].roms[0].crc32 == "adf3f363"


def test_dat_regions_are_inferred_from_names(tmp_path: Path) -> None:
    dat = tmp_path / "nes.dat"
    dat.write_text(
        """clrmamepro ( name "NES" )
game (
    name "Game (Europe)"
    rom ( name "Game (Europe).nes" size 4 crc ADF3F363 )
)""",
        encoding="utf-8",
    )
    catalog = parse_clrmamepro_dat(dat)
    assert catalog.games[0].releases == ["Europe"]


def test_headered_dat_is_marked_recommended(tmp_path: Path) -> None:
    dat = tmp_path / "Nintendo - Nintendo Entertainment System (Headered).dat"
    dat.write_text(
        """<datafile><header><name>NES Headered</name></header><game name="Game (USA)"><rom name="Game (USA).nes" size="20" crc="1234" header="4E 45 53 1A 00 00 00 00 00 00 00 00 00 00 00 00"/></game></datafile>""",
        encoding="utf-8",
    )
    metadata = inspect_dat(dat)
    assert metadata.header_mode == "headered"
    assert metadata.recommended is True


def test_import_dat_zip_and_compare(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setattr("retroperfect.dat_sources.data_dir", lambda: data_dir)
    dat_body = """clrmamepro ( name "NES" )
game (
    name "Game (USA)"
    rom ( name "Game (USA).nes" size 4 crc ADF3F363 md5 81DC9BDB52D04DC20036DBD8313ED055 sha1 7110EDA4D09E062AA5E4A390B0A572AC0D2C0220 )
)"""
    zip_path = tmp_path / "dom.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("Nintendo - Nintendo Entertainment System.dat", dat_body)
    imported = import_dat_file(zip_path)
    assert len(imported) == 1
    assert imported[0].games == 1
    assert imported[0].roms == 1
    comparison = compare_dats(Path(imported[0].path), Path(imported[0].path))
    assert comparison.common_games == 1
    assert comparison.common_roms == 1
    assert validate_setup(tmp_path, zip_path, None) == []


def test_download_and_import_url(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setattr("retroperfect.dat_sources.data_dir", lambda: data_dir)

    class Response:
        content = b"""clrmamepro ( name "NES" )
game (
    name "Game (USA)"
    rom ( name "Game (USA).nes" size 4 crc ADF3F363 )
)"""

        @staticmethod
        def raise_for_status() -> None:
            return None

        headers = {}

    monkeypatch.setattr("retroperfect.dat_sources.requests.get", lambda *args, **kwargs: Response())
    imported = download_and_import_url("https://example.test/nes.dat")
    assert imported[0].name == "NES"
    assert imported[0].games == 1


def test_suggest_dat_for_source_prefers_unheadered_when_source_says_unheadered(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setattr("retroperfect.dat_sources.data_dir", lambda: data_dir)
    headered = tmp_path / "Nintendo - Nintendo Entertainment System (Headered).dat"
    headered.write_text(
        """<datafile><header><name>NES Headered</name></header><game name="Game (USA)"><rom name="Game (USA).nes" size="20" crc="1234" header="4E 45 53 1A 00 00 00 00 00 00 00 00 00 00 00 00"/></game></datafile>""",
        encoding="utf-8",
    )
    unheadered = tmp_path / "Nintendo - Nintendo Entertainment System (Unheadered).dat"
    unheadered.write_text(
        """clrmamepro ( name "NES Unheadered" )
game ( name "Game (USA)" rom ( name "Game (USA).unh" size 4 crc ADF3F363 ) )""",
        encoding="utf-8",
    )
    import_dat_file(headered)
    import_dat_file(unheadered)
    suggestion = suggest_dat_for_source(tmp_path / "Nintendo - Nintendo Entertainment System (Unheadered)")
    assert suggestion is not None
    assert suggestion.header_mode == "unheadered"


def test_crc_match_requires_matching_size(tmp_path: Path) -> None:
    dat = tmp_path / "nes.xml"
    dat.write_text(
        """<datafile>
  <header><name>NES</name></header>
  <game name="Game (USA)"><rom name="Game (USA).nes" size="4" crc="adf3f363"/></game>
  <game name="Other (USA)"><rom name="Other (USA).nes" crc="deadbeef"/></game>
</datafile>""",
        encoding="utf-8",
    )
    index = DatIndex(parse_logiqx_dat(dat))
    md5 = "0" * 32
    sha1 = "0" * 40
    assert index.match("adf3f363", md5, sha1, 4) is not None
    assert index.match("adf3f363", md5, sha1, 5) is None
    assert index.match("deadbeef", md5, sha1, 123) is not None
