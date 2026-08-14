from __future__ import annotations

import binascii
import hashlib
import json
from pathlib import Path

import pytest

from retroperfect import rom_sources
from retroperfect.dat import DatIndex, parse_logiqx_dat
from retroperfect.download_plan import build_download_plan, resolve_remote_files
from retroperfect.downloader import run_download_plan
from retroperfect.models import OutputBucket, Platform, ProfileOutput, SelectionProfile
from retroperfect.rom_sources import RemoteFile, RomSource, add_rom_source, list_rom_sources, remove_rom_source, resolve_source
from retroperfect.scanner import scan_directory

PROFILE = SelectionProfile(name="test", outputs=[ProfileOutput(bucket=OutputBucket.MAIN, strict_1g1r=True, region_priority=["Europe", "USA", "Japan"])])


def _dat(tmp_path: Path, games: dict[str, bytes]) -> Path:
    entries = []
    for name, payload in games.items():
        entries.append(
            f'<game name="{name}"><description>{name}</description>'
            f'<rom name="{name}.nes" size="{len(payload)}" crc="{binascii.crc32(payload) & 0xFFFFFFFF:08x}" '
            f'md5="{hashlib.md5(payload).hexdigest()}" sha1="{hashlib.sha1(payload).hexdigest()}"/></game>'
        )
    dat = tmp_path / "nes.xml"
    dat.write_text("<datafile><header><name>NES</name></header>" + "".join(entries) + "</datafile>", encoding="utf-8")
    return dat


def _clone_dat(tmp_path: Path, parent: tuple[str, bytes], clones: list[tuple[str, bytes]]) -> Path:
    """DAT con un único grupo parent/clone, que es como No-Intro expresa las variantes de un juego."""

    def game(name: str, payload: bytes, cloneof: str | None = None) -> str:
        attr = f' cloneof="{cloneof}"' if cloneof else ""
        return (
            f'<game name="{name}"{attr}><description>{name}</description>'
            f'<rom name="{name}.nes" size="{len(payload)}" md5="{hashlib.md5(payload).hexdigest()}"/></game>'
        )

    body = game(*parent) + "".join(game(name, payload, parent[0]) for name, payload in clones)
    dat = tmp_path / "clones.xml"
    dat.write_text(f"<datafile><header><name>NES</name></header>{body}</datafile>", encoding="utf-8")
    return dat


def _scan_of(tmp_path: Path, files: dict[str, bytes], dat: Path):
    roms = tmp_path / "roms"
    roms.mkdir(exist_ok=True)
    for name, payload in files.items():
        (roms / name).write_bytes(payload)
    return scan_directory(roms, Platform.NES, dat_index=DatIndex(parse_logiqx_dat(dat)), dat_path=dat)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Aísla el registro de fuentes y la caché de índices del entorno real del usuario."""
    config = tmp_path / "config"
    data = tmp_path / "data"
    config.mkdir()
    data.mkdir()
    monkeypatch.setattr(rom_sources, "config_dir", lambda: config)
    monkeypatch.setattr(rom_sources, "data_dir", lambda: data)
    return config


# --- Registro de fuentes -----------------------------------------------------


def test_rom_sources_registry_roundtrip(isolated_config: Path) -> None:
    assert list_rom_sources() == []
    add_rom_source(RomSource(id="nas", label="Mi NAS", kind="local_dir", location="/mnt/roms", platform="nes"))
    add_rom_source(RomSource(id="otra", label="Otra", kind="local_dir", location="/mnt/x", platform="snes"))

    assert {source.id for source in list_rom_sources()} == {"nas", "otra"}
    assert [source.id for source in list_rom_sources("nes")] == ["nas"]
    assert remove_rom_source("nas")
    assert not remove_rom_source("nas")
    assert [source.id for source in list_rom_sources()] == ["otra"]


def test_rom_source_without_platform_applies_to_all(isolated_config: Path) -> None:
    add_rom_source(RomSource(id="global", label="Global", kind="local_dir", location="/mnt/roms"))
    assert [source.id for source in list_rom_sources("megadrive")] == ["global"]


# --- Resolvers ---------------------------------------------------------------


def test_local_dir_source_lists_files(isolated_config: Path, tmp_path: Path) -> None:
    folder = tmp_path / "mirror"
    folder.mkdir()
    (folder / "Juego (Europe).nes").write_bytes(b"AAA")
    (folder / ".oculto").write_bytes(b"x")
    source = RomSource(id="local", label="Local", kind="local_dir", location=str(folder))

    index = resolve_source(source)
    assert [file.name for file in index.files] == ["Juego (Europe).nes"]
    assert index.files[0].size == 3


def test_archive_org_source_parses_metadata(isolated_config: Path, monkeypatch) -> None:
    payload = {
        "files": [
            {"name": "Juego (Europe).zip", "size": "1024", "md5": "abc", "crc32": "1a2b3c", "format": "ZIP"},
            {"name": "item_meta.xml", "format": "Metadata"},
        ]
    }

    class _Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return payload

    monkeypatch.setattr(rom_sources, "http_get", lambda url, **kwargs: _Response())
    index = resolve_source(RomSource(id="ia", label="IA", kind="archive_org", location="https://archive.org/details/mi-item"))

    assert len(index.files) == 1
    file = index.files[0]
    assert file.name == "Juego (Europe).zip"
    assert file.url == "https://archive.org/download/mi-item/Juego%20%28Europe%29.zip"
    assert file.size == 1024
    assert file.crc32 == "1a2b3c"


def test_http_index_source_parses_links(isolated_config: Path, monkeypatch) -> None:
    html = """
    <html><body>
      <a href="../">Parent directory</a>
      <a href="subcarpeta/">subcarpeta/</a>
      <a href="Juego%20(Europe).zip">Juego (Europe).zip</a>
      <a href="?C=N;O=D">ordenar</a>
      <a href="https://otro-host/x.zip">externo</a>
    </body></html>
    """

    class _Response:
        text = html

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(rom_sources, "http_get", lambda url, **kwargs: _Response())
    index = resolve_source(RomSource(id="idx", label="Idx", kind="http_index", location="https://ejemplo.test/nes"))

    assert [file.name for file in index.files] == ["Juego (Europe).zip"]
    assert index.files[0].url == "https://ejemplo.test/nes/Juego%20(Europe).zip"


def test_index_cache_avoids_refetch(isolated_config: Path, tmp_path: Path) -> None:
    folder = tmp_path / "mirror"
    folder.mkdir()
    (folder / "Uno.nes").write_bytes(b"A")
    source = RomSource(id="local", label="Local", kind="local_dir", location=str(folder))

    resolve_source(source)
    (folder / "Dos.nes").write_bytes(b"B")
    assert len(resolve_source(source).files) == 1
    assert len(resolve_source(source, refresh=True).files) == 2


def test_resolve_remote_files_collects_errors(isolated_config: Path) -> None:
    files, errors = resolve_remote_files([RomSource(id="roto", label="Roto", kind="local_dir", location="/no/existe")])
    assert files == {}
    assert errors and "Roto" in errors[0]


# --- Plan --------------------------------------------------------------------


def test_plan_only_targets_games_missing_from_the_scan(tmp_path: Path) -> None:
    dat = _dat(tmp_path, {"Tengo (Europe)": b"HAVE", "Falta (Europe)": b"MISS"})
    scan = _scan_of(tmp_path, {"Tengo (Europe).nes": b"HAVE"}, dat)
    remote = {"src": [RemoteFile(name="Tengo (Europe).nes", url="/m/1"), RemoteFile(name="Falta (Europe).nes", url="/m/2", size=4)]}

    plan = build_download_plan(parse_logiqx_dat(dat), scan, PROFILE, remote, platform=Platform.NES)

    assert [candidate.title for candidate in plan.candidates] == ["Falta"]
    assert plan.present_groups == 1
    assert plan.total_bytes == 4


def test_plan_matches_by_hash_over_name(tmp_path: Path) -> None:
    payload = b"MISS"
    dat = _dat(tmp_path, {"Falta (Europe)": payload})
    remote = {
        "src": [
            RemoteFile(name="nombre-ilegible-0001.bin", url="/m/hash", md5=hashlib.md5(payload).hexdigest()),
            RemoteFile(name="Falta (Europe).nes", url="/m/name"),
        ]
    }

    plan = build_download_plan(parse_logiqx_dat(dat), None, PROFILE, remote, platform=Platform.NES)

    assert len(plan.candidates) == 1
    assert plan.candidates[0].confidence == "hash"
    assert plan.candidates[0].url == "/m/hash"


def test_plan_matches_crc32_without_leading_zeros(tmp_path: Path) -> None:
    payload = b"MISS"
    dat = _dat(tmp_path, {"Falta (Europe)": payload})
    crc = f"{binascii.crc32(payload) & 0xFFFFFFFF:08x}".lstrip("0")
    remote = {"src": [RemoteFile(name="cualquiera.bin", url="/m/crc", crc32=crc)]}

    plan = build_download_plan(parse_logiqx_dat(dat), None, PROFILE, remote, platform=Platform.NES)
    assert plan.candidates[0].confidence == "hash"


def test_plan_without_profile_filter_keeps_every_variant(tmp_path: Path) -> None:
    dat = _clone_dat(tmp_path, parent=("Juego (Europe)", b"EU"), clones=[("Juego (USA)", b"US"), ("Juego (Japan)", b"JP")])
    catalog = parse_logiqx_dat(dat)
    remote = {
        "src": [
            RemoteFile(name="Juego (Europe).nes", url="/m/eu"),
            RemoteFile(name="Juego (USA).nes", url="/m/us"),
            RemoteFile(name="Juego (Japan).nes", url="/m/jp"),
        ]
    }

    filtered = build_download_plan(catalog, None, PROFILE, remote, platform=Platform.NES)
    assert [candidate.url for candidate in filtered.candidates] == ["/m/eu"]

    everything = build_download_plan(catalog, None, PROFILE, remote, platform=Platform.NES, apply_profile=False)
    assert {candidate.url for candidate in everything.candidates} == {"/m/eu"}
    assert everything.dat_groups == 1


def test_plan_region_priority_decides_the_winner_of_a_clone_group(tmp_path: Path) -> None:
    dat = _clone_dat(tmp_path, parent=("Juego (Japan)", b"JP"), clones=[("Juego (USA)", b"US"), ("Juego (Europe)", b"EU")])
    catalog = parse_logiqx_dat(dat)
    remote = {
        "src": [
            RemoteFile(name="Juego (Japan).nes", url="/m/jp"),
            RemoteFile(name="Juego (USA).nes", url="/m/us"),
            RemoteFile(name="Juego (Europe).nes", url="/m/eu"),
        ]
    }

    europe_first = build_download_plan(catalog, None, PROFILE, remote, platform=Platform.NES)
    assert [candidate.url for candidate in europe_first.candidates] == ["/m/eu"]

    japan_profile = SelectionProfile(name="jp", outputs=[ProfileOutput(bucket=OutputBucket.MAIN, strict_1g1r=True, region_priority=["Japan", "USA", "Europe"])])
    japan_first = build_download_plan(catalog, None, japan_profile, remote, platform=Platform.NES)
    assert [candidate.url for candidate in japan_first.candidates] == ["/m/jp"]


def test_plan_skips_variants_excluded_by_strict_1g1r(tmp_path: Path) -> None:
    dat = _dat(tmp_path, {"Juego (Europe) (Beta)": b"BETA"})
    remote = {"src": [RemoteFile(name="Juego (Europe) (Beta).nes", url="/m/beta")]}

    plan = build_download_plan(parse_logiqx_dat(dat), None, PROFILE, remote, platform=Platform.NES)
    assert plan.candidates == []
    assert plan.filtered_by_profile == 1


def test_plan_reports_games_no_source_offers(tmp_path: Path) -> None:
    dat = _dat(tmp_path, {"Inencontrable (Europe)": b"X"})
    plan = build_download_plan(parse_logiqx_dat(dat), None, PROFILE, {"src": []}, platform=Platform.NES)

    assert plan.candidates == []
    assert [missing.title for missing in plan.unavailable] == ["Inencontrable"]


def test_plan_downloads_one_file_per_clone_group(tmp_path: Path) -> None:
    dat = _clone_dat(tmp_path, parent=("Juego (Europe)", b"EU"), clones=[("Juego (USA)", b"US")])
    remote = {"src": [RemoteFile(name="Juego (Europe).nes", url="/m/eu"), RemoteFile(name="Juego (USA).nes", url="/m/us")]}

    plan = build_download_plan(parse_logiqx_dat(dat), None, PROFILE, remote, platform=Platform.NES)
    assert len(plan.candidates) == 1
    assert plan.candidates[0].url == "/m/eu"


def test_plan_treats_a_clone_group_as_covered_when_any_variant_is_present(tmp_path: Path) -> None:
    dat = _clone_dat(tmp_path, parent=("Juego (Europe)", b"EU"), clones=[("Juego (USA)", b"US")])
    scan = _scan_of(tmp_path, {"Juego (USA).nes": b"US"}, dat)
    remote = {"src": [RemoteFile(name="Juego (Europe).nes", url="/m/eu")]}

    plan = build_download_plan(parse_logiqx_dat(dat), scan, PROFILE, remote, platform=Platform.NES)
    assert plan.candidates == []
    assert plan.present_groups == 1


# --- Descarga ----------------------------------------------------------------


def test_download_verifies_and_installs(tmp_path: Path) -> None:
    payload = b"MISS"
    dat = _dat(tmp_path, {"Falta (Europe)": payload})
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    (mirror / "Falta (Europe).nes").write_bytes(payload)
    catalog = parse_logiqx_dat(dat)
    remote = {"src": [RemoteFile(name="Falta (Europe).nes", url=str(mirror / "Falta (Europe).nes"), size=len(payload))]}
    plan = build_download_plan(catalog, None, PROFILE, remote, platform=Platform.NES)

    dest = tmp_path / "romset"
    report = run_download_plan(plan, dest, dat_index=DatIndex(catalog), state_base=tmp_path)

    assert report.downloaded == 1
    assert report.failed == 0
    assert (dest / "Falta (Europe).nes").read_bytes() == payload
    assert report.total_bytes == len(payload)


def test_download_quarantines_content_that_fails_the_dat(tmp_path: Path) -> None:
    dat = _dat(tmp_path, {"Falta (Europe)": b"GOOD"})
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    (mirror / "Falta (Europe).nes").write_bytes(b"CORRUPTO")
    catalog = parse_logiqx_dat(dat)
    remote = {"src": [RemoteFile(name="Falta (Europe).nes", url=str(mirror / "Falta (Europe).nes"))]}
    plan = build_download_plan(catalog, None, PROFILE, remote, platform=Platform.NES)

    dest = tmp_path / "romset"
    report = run_download_plan(plan, dest, dat_index=DatIndex(catalog), state_base=tmp_path)

    assert report.downloaded == 0
    assert report.failed == 1
    assert report.outcomes[0].status == "mismatch"
    assert not (dest / "Falta (Europe).nes").exists()
    assert Path(report.outcomes[0].path or "").exists()
    assert "quarantine" in (report.outcomes[0].path or "")


def test_download_rejects_a_file_that_is_another_game(tmp_path: Path) -> None:
    dat = _dat(tmp_path, {"Quiero (Europe)": b"WANT", "Otro (Europe)": b"OTHER"})
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    # El espejo sirve el contenido equivocado bajo el nombre correcto.
    (mirror / "Quiero (Europe).nes").write_bytes(b"OTHER")
    catalog = parse_logiqx_dat(dat)
    remote = {"src": [RemoteFile(name="Quiero (Europe).nes", url=str(mirror / "Quiero (Europe).nes"))]}
    plan = build_download_plan(catalog, None, PROFILE, remote, platform=Platform.NES)
    plan.candidates = [candidate for candidate in plan.candidates if candidate.title == "Quiero"]

    report = run_download_plan(plan, tmp_path / "romset", dat_index=DatIndex(catalog), state_base=tmp_path)

    assert report.outcomes[0].status == "mismatch"
    assert "otro juego" in report.outcomes[0].detail


def test_download_skips_files_already_in_destination(tmp_path: Path) -> None:
    payload = b"MISS"
    dat = _dat(tmp_path, {"Falta (Europe)": payload})
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    (mirror / "Falta (Europe).nes").write_bytes(payload)
    catalog = parse_logiqx_dat(dat)
    remote = {"src": [RemoteFile(name="Falta (Europe).nes", url=str(mirror / "Falta (Europe).nes"))]}
    plan = build_download_plan(catalog, None, PROFILE, remote, platform=Platform.NES)

    dest = tmp_path / "romset"
    dest.mkdir()
    (dest / "Falta (Europe).nes").write_bytes(payload)
    report = run_download_plan(plan, dest, dat_index=DatIndex(catalog), state_base=tmp_path)

    assert report.outcomes[0].status == "present"
    assert report.total_bytes == 0


def test_download_stops_when_cancelled(tmp_path: Path) -> None:
    dat = _dat(tmp_path, {"Uno (Europe)": b"UNO", "Dos (Europe)": b"DOS"})
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    (mirror / "Uno (Europe).nes").write_bytes(b"UNO")
    (mirror / "Dos (Europe).nes").write_bytes(b"DOS")
    catalog = parse_logiqx_dat(dat)
    remote = {
        "src": [
            RemoteFile(name="Uno (Europe).nes", url=str(mirror / "Uno (Europe).nes")),
            RemoteFile(name="Dos (Europe).nes", url=str(mirror / "Dos (Europe).nes")),
        ]
    }
    plan = build_download_plan(catalog, None, PROFILE, remote, platform=Platform.NES)

    report = run_download_plan(plan, tmp_path / "romset", dat_index=DatIndex(catalog), state_base=tmp_path, cancelled=lambda: True)
    assert report.outcomes[0].status == "cancelled"
    assert len(report.outcomes) == 1


def test_download_resumes_a_partial_http_file(tmp_path: Path, monkeypatch) -> None:
    from retroperfect import downloader

    payload = b"0123456789"
    dat = _dat(tmp_path, {"Falta (Europe)": payload})
    catalog = parse_logiqx_dat(dat)
    staging = downloader.staging_dir(tmp_path)
    (staging / "Falta (Europe).nes.part").write_bytes(payload[:4])
    seen: dict[str, str] = {}

    class _Response:
        status_code = 206

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int = 0):
            yield payload[4:]

        def close(self) -> None:
            return None

    class _Session:
        def get(self, url, headers=None, **kwargs):
            seen.update(headers or {})
            return _Response()

    monkeypatch.setattr(downloader, "session", lambda: _Session())
    remote = {"src": [RemoteFile(name="Falta (Europe).nes", url="https://ejemplo.test/rom.nes")]}
    plan = build_download_plan(catalog, None, PROFILE, remote, platform=Platform.NES)

    dest = tmp_path / "romset"
    report = run_download_plan(plan, dest, dat_index=DatIndex(catalog), state_base=tmp_path)

    assert seen.get("Range") == "bytes=4-"
    assert report.downloaded == 1
    assert (dest / "Falta (Europe).nes").read_bytes() == payload


def test_download_restarts_when_server_ignores_range(tmp_path: Path, monkeypatch) -> None:
    from retroperfect import downloader

    payload = b"0123456789"
    dat = _dat(tmp_path, {"Falta (Europe)": payload})
    catalog = parse_logiqx_dat(dat)
    staging = downloader.staging_dir(tmp_path)
    (staging / "Falta (Europe).nes.part").write_bytes(b"BASURA")

    class _Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int = 0):
            yield payload

    class _Session:
        def get(self, url, headers=None, **kwargs):
            return _Response()

    monkeypatch.setattr(downloader, "session", lambda: _Session())
    remote = {"src": [RemoteFile(name="Falta (Europe).nes", url="https://ejemplo.test/rom.nes")]}
    plan = build_download_plan(catalog, None, PROFILE, remote, platform=Platform.NES)

    dest = tmp_path / "romset"
    report = run_download_plan(plan, dest, dat_index=DatIndex(catalog), state_base=tmp_path)

    assert report.downloaded == 1
    assert (dest / "Falta (Europe).nes").read_bytes() == payload


def test_download_reports_http_errors_without_touching_destination(tmp_path: Path, monkeypatch) -> None:
    from retroperfect import downloader

    dat = _dat(tmp_path, {"Falta (Europe)": b"MISS"})
    catalog = parse_logiqx_dat(dat)

    class _Session:
        def get(self, url, headers=None, **kwargs):
            raise RuntimeError("conexión rechazada")

    monkeypatch.setattr(downloader, "session", lambda: _Session())
    remote = {"src": [RemoteFile(name="Falta (Europe).nes", url="https://ejemplo.test/rom.nes")]}
    plan = build_download_plan(catalog, None, PROFILE, remote, platform=Platform.NES)

    dest = tmp_path / "romset"
    report = run_download_plan(plan, dest, dat_index=DatIndex(catalog), state_base=tmp_path)

    assert report.outcomes[0].status == "error"
    assert "conexión rechazada" in report.outcomes[0].detail
    assert not any(dest.iterdir())


def test_index_cache_file_is_written(isolated_config: Path, tmp_path: Path) -> None:
    folder = tmp_path / "mirror"
    folder.mkdir()
    (folder / "Uno.nes").write_bytes(b"A")
    resolve_source(RomSource(id="local", label="Local", kind="local_dir", location=str(folder)))
    cache = rom_sources.index_cache_path("local")
    assert cache.exists()
    assert json.loads(cache.read_text(encoding="utf-8"))["files"][0]["name"] == "Uno.nes"


def test_plan_groups_regional_variants_even_without_parent_clone(tmp_path: Path) -> None:
    """Los DAT sin parent/clone (espejos clrmamepro) no deben esquivar el filtro 1G1R."""
    dat = _dat(tmp_path, {"Juego (Europe)": b"EU", "Juego (USA)": b"US", "Juego (Japan)": b"JP"})
    remote = {
        "src": [
            RemoteFile(name="Juego (Europe).nes", url="/m/eu"),
            RemoteFile(name="Juego (USA).nes", url="/m/us"),
            RemoteFile(name="Juego (Japan).nes", url="/m/jp"),
        ]
    }

    plan = build_download_plan(parse_logiqx_dat(dat), None, PROFILE, remote, platform=Platform.NES)
    assert [candidate.url for candidate in plan.candidates] == ["/m/eu"]
    assert plan.dat_groups == 1


def test_plan_counts_a_title_present_in_another_region_as_covered(tmp_path: Path) -> None:
    dat = _dat(tmp_path, {"Juego (Europe)": b"EU", "Juego (USA)": b"US"})
    scan = _scan_of(tmp_path, {"Juego (USA).nes": b"US"}, dat)
    remote = {"src": [RemoteFile(name="Juego (Europe).nes", url="/m/eu")]}

    plan = build_download_plan(parse_logiqx_dat(dat), scan, PROFILE, remote, platform=Platform.NES)
    assert plan.candidates == []
    assert plan.present_groups == 1
