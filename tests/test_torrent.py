"""Lectura de .torrent, selección de archivos en qBittorrent y recogida agnóstica de cliente."""
from __future__ import annotations

import binascii
import hashlib
from pathlib import Path

import pytest

from retroperfect import rom_sources
from retroperfect.dat import DatIndex, parse_logiqx_dat
from retroperfect.download_plan import build_download_plan
from retroperfect.downloader import collect_downloads
from retroperfect.models import OutputBucket, Platform, ProfileOutput, SelectionProfile
from retroperfect.rom_sources import RomSource, resolve_source
from retroperfect.torrent import TorrentError, read_torrent
from retroperfect.torrent_client import PRIORITY_NORMAL, PRIORITY_SKIP, TorrentClientError, queue_plan, wanted_paths

PROFILE = SelectionProfile(name="test", outputs=[ProfileOutput(bucket=OutputBucket.MAIN, strict_1g1r=True, region_priority=["Europe", "USA", "Japan"])])


# --- bencode -----------------------------------------------------------------


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
        return b"d" + b"".join(_bencode(k) + _bencode(v) for k, v in value.items()) + b"e"
    raise TypeError(type(value))


def _torrent(tmp_path: Path, name: str, files: dict[str, int]) -> Path:
    info = {
        b"name": name.encode(),
        b"piece length": 262144,
        b"pieces": b"\x00" * 20,
        b"files": [{b"length": size, b"path": [part.encode() for part in path.split("/")]} for path, size in files.items()],
    }
    path = tmp_path / f"{name}.torrent"
    path.write_bytes(_bencode({b"announce": b"udp://tracker.test:80", b"info": info}))
    return path


def _single_file_torrent(tmp_path: Path, name: str, size: int) -> Path:
    info = {b"name": name.encode(), b"piece length": 262144, b"pieces": b"\x00" * 20, b"length": size}
    path = tmp_path / "single.torrent"
    path.write_bytes(_bencode({b"info": info}))
    return path


def test_reads_the_file_list_of_a_multi_file_torrent(tmp_path: Path) -> None:
    path = _torrent(tmp_path, "NES Set", {"Metroid (Europe).nes": 100, "sub/Contra (USA).nes": 200})

    info = read_torrent(path)

    assert info.name == "NES Set"
    assert info.total_size == 300
    assert [(f.index, f.path, f.name, f.length) for f in info.files] == [
        (0, "Metroid (Europe).nes", "Metroid (Europe).nes", 100),
        (1, "sub/Contra (USA).nes", "Contra (USA).nes", 200),
    ]


def test_reads_a_single_file_torrent(tmp_path: Path) -> None:
    info = read_torrent(_single_file_torrent(tmp_path, "Metroid (Europe).nes", 4096))
    assert [f.path for f in info.files] == ["Metroid (Europe).nes"]
    assert info.total_size == 4096


def test_infohash_is_the_sha1_of_the_raw_info_block(tmp_path: Path) -> None:
    path = _torrent(tmp_path, "Set", {"a.nes": 1})
    raw = path.read_bytes()
    start = raw.index(b"4:infod") + len(b"4:info")
    expected = hashlib.sha1(raw[start:-1]).hexdigest()

    assert read_torrent(path).info_hash == expected


def test_rejects_a_file_that_is_not_a_torrent(tmp_path: Path) -> None:
    bad = tmp_path / "cualquiera.torrent"
    bad.write_bytes(b"esto no es bencode")
    with pytest.raises(TorrentError):
        read_torrent(bad)


def test_rejects_a_torrent_without_files(tmp_path: Path) -> None:
    path = tmp_path / "vacio.torrent"
    path.write_bytes(_bencode({b"info": {b"name": b"x", b"piece length": 1, b"files": []}}))
    with pytest.raises(TorrentError, match="ningún archivo"):
        read_torrent(path)


# --- El torrent como fuente ---------------------------------------------------


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr(rom_sources, "config_dir", lambda: config)
    monkeypatch.setattr(rom_sources, "data_dir", lambda: config)
    return config


def _dat(tmp_path: Path, games: dict[str, bytes]) -> Path:
    entries = [
        f'<game name="{name}"><description>{name}</description>'
        f'<rom name="{name}.nes" size="{len(payload)}" crc="{binascii.crc32(payload) & 0xFFFFFFFF:08x}" '
        f'md5="{hashlib.md5(payload).hexdigest()}" sha1="{hashlib.sha1(payload).hexdigest()}"/></game>'
        for name, payload in games.items()
    ]
    dat = tmp_path / "nes.xml"
    dat.write_text("<datafile><header><name>NES</name></header>" + "".join(entries) + "</datafile>", encoding="utf-8")
    return dat


def test_torrent_source_lists_its_files(isolated_config: Path, tmp_path: Path) -> None:
    path = _torrent(tmp_path, "Set", {"Metroid (Europe).nes": 100})

    index = resolve_source(RomSource(id="t", label="T", kind="torrent", location=str(path)))

    assert [(f.name, f.inner_path, f.container, f.size) for f in index.files] == [("Metroid (Europe).nes", "Metroid (Europe).nes", "torrent", 100)]


def test_the_app_does_not_try_to_download_a_torrent_itself(isolated_config: Path, tmp_path: Path) -> None:
    from retroperfect.downloader import run_download_plan

    payload = b"METROID"
    dat = _dat(tmp_path, {"Metroid (Europe)": payload})
    path = _torrent(tmp_path, "Set", {"Metroid (Europe).nes": len(payload)})
    remote = {"t": resolve_source(RomSource(id="t", label="T", kind="torrent", location=str(path))).files}
    plan = build_download_plan(parse_logiqx_dat(dat), None, PROFILE, remote, platform=Platform.NES)

    report = run_download_plan(plan, tmp_path / "romset", dat_index=DatIndex(parse_logiqx_dat(dat)), state_base=tmp_path)

    assert report.outcomes[0].status == "delegated"
    assert "cliente" in report.outcomes[0].detail


# --- Recogida desde la carpeta del cliente (cualquier cliente) ----------------


def _plan_for(tmp_path: Path, dat: Path, torrent: Path):
    remote = {"t": resolve_source(RomSource(id="t", label="T", kind="torrent", location=str(torrent))).files}
    return build_download_plan(parse_logiqx_dat(dat), None, PROFILE, remote, platform=Platform.NES)


def test_collect_verifies_and_copies_without_moving(isolated_config: Path, tmp_path: Path) -> None:
    payload = b"METROID-ROM"
    dat = _dat(tmp_path, {"Metroid (Europe)": payload})
    torrent = _torrent(tmp_path, "Set", {"Metroid (Europe).nes": len(payload)})
    downloads = tmp_path / "descargas"
    downloads.mkdir()
    (downloads / "Metroid (Europe).nes").write_bytes(payload)

    plan = _plan_for(tmp_path, dat, torrent)
    dest = tmp_path / "romset"
    report = collect_downloads(plan, downloads, dest, dat_index=DatIndex(parse_logiqx_dat(dat)))

    assert report.downloaded == 1
    assert (dest / "Metroid (Europe).nes").read_bytes() == payload
    # Copiado, no movido: el cliente sigue sembrando.
    assert (downloads / "Metroid (Europe).nes").exists()


def test_collect_finds_files_inside_the_torrent_folder(isolated_config: Path, tmp_path: Path) -> None:
    payload = b"METROID-ROM"
    dat = _dat(tmp_path, {"Metroid (Europe)": payload})
    torrent = _torrent(tmp_path, "Set", {"roms/Metroid (Europe).nes": len(payload)})
    downloads = tmp_path / "descargas"
    (downloads / "roms").mkdir(parents=True)
    (downloads / "roms" / "Metroid (Europe).nes").write_bytes(payload)

    report = collect_downloads(_plan_for(tmp_path, dat, torrent), downloads, tmp_path / "romset", dat_index=DatIndex(parse_logiqx_dat(dat)))
    assert report.downloaded == 1


def test_collect_skips_a_file_still_downloading(isolated_config: Path, tmp_path: Path) -> None:
    payload = b"METROID-ROM"
    dat = _dat(tmp_path, {"Metroid (Europe)": payload})
    torrent = _torrent(tmp_path, "Set", {"Metroid (Europe).nes": len(payload)})
    downloads = tmp_path / "descargas"
    downloads.mkdir()
    (downloads / "Metroid (Europe).nes").write_bytes(payload[:4])

    report = collect_downloads(_plan_for(tmp_path, dat, torrent), downloads, tmp_path / "romset", dat_index=DatIndex(parse_logiqx_dat(dat)))

    assert report.outcomes[0].status == "incomplete"
    assert not (tmp_path / "romset" / "Metroid (Europe).nes").exists()


def test_collect_quarantines_content_that_fails_the_dat(isolated_config: Path, tmp_path: Path) -> None:
    payload = b"METROID-ROM"
    dat = _dat(tmp_path, {"Metroid (Europe)": payload})
    torrent = _torrent(tmp_path, "Set", {"Metroid (Europe).nes": len(payload)})
    downloads = tmp_path / "descargas"
    downloads.mkdir()
    # Mismo tamaño, contenido distinto: solo lo caza el DAT.
    (downloads / "Metroid (Europe).nes").write_bytes(b"X" * len(payload))

    report = collect_downloads(_plan_for(tmp_path, dat, torrent), downloads, tmp_path / "romset", dat_index=DatIndex(parse_logiqx_dat(dat)))

    assert report.outcomes[0].status == "mismatch"
    assert not (tmp_path / "romset" / "Metroid (Europe).nes").exists()


def test_collect_reports_what_has_not_arrived_yet(isolated_config: Path, tmp_path: Path) -> None:
    payload = b"METROID-ROM"
    dat = _dat(tmp_path, {"Metroid (Europe)": payload})
    torrent = _torrent(tmp_path, "Set", {"Metroid (Europe).nes": len(payload)})
    downloads = tmp_path / "descargas"
    downloads.mkdir()

    report = collect_downloads(_plan_for(tmp_path, dat, torrent), downloads, tmp_path / "romset", dat_index=DatIndex(parse_logiqx_dat(dat)))
    assert report.outcomes[0].status == "absent"


# --- qBittorrent --------------------------------------------------------------


class _FakeQBittorrent:
    """Imita lo justo de la Web API v2 para comprobar la selección de archivos."""

    def __init__(self, entries: list[dict]) -> None:
        self.entries = entries
        self.priorities: dict[int, int] = {}
        self.added = False
        self.started = False

    def login(self) -> None:
        return None

    def add_torrent(self, torrent_path: Path, save_path: str | None = None) -> None:
        self.added = True
        self.save_path = save_path

    def files(self, info_hash: str) -> list[dict]:
        return self.entries

    def set_priorities(self, info_hash: str, indices: list[int], priority: int) -> None:
        for index in indices:
            self.priorities[index] = priority

    def start(self, info_hash: str) -> None:
        self.started = True


def test_queue_selects_only_the_missing_files(isolated_config: Path, tmp_path: Path) -> None:
    faltante, presente = b"METROID-ROM", b"CONTRA-ROM"
    dat = _dat(tmp_path, {"Metroid (Europe)": faltante, "Contra (Europe)": presente})
    torrent = _torrent(tmp_path, "Set", {"Metroid (Europe).nes": len(faltante), "Contra (Europe).nes": len(presente)})

    # Plan acotado a mano al juego que falta, como haría un escaneo previo.
    plan = _plan_for(tmp_path, dat, torrent)
    plan.candidates = [c for c in plan.candidates if c.title == "Metroid"]

    client = _FakeQBittorrent([
        {"index": 0, "name": "Set/Metroid (Europe).nes"},
        {"index": 1, "name": "Set/Contra (Europe).nes"},
    ])
    result = queue_plan(plan, torrent, client=client)  # type: ignore[arg-type]

    assert client.added and client.started
    assert result == {"seleccionados": 1, "descartados": 1}
    assert client.priorities == {0: PRIORITY_NORMAL, 1: PRIORITY_SKIP}


def test_queue_refuses_when_the_plan_has_nothing_from_this_torrent(isolated_config: Path, tmp_path: Path) -> None:
    payload = b"METROID-ROM"
    dat = _dat(tmp_path, {"Metroid (Europe)": payload})
    torrent = _torrent(tmp_path, "Set", {"Metroid (Europe).nes": len(payload)})
    plan = _plan_for(tmp_path, dat, torrent)
    plan.candidates = []

    with pytest.raises(TorrentClientError, match="ningún archivo"):
        queue_plan(plan, torrent, client=_FakeQBittorrent([]))  # type: ignore[arg-type]


def test_wanted_paths_ignores_candidates_from_other_sources(isolated_config: Path, tmp_path: Path) -> None:
    payload = b"METROID-ROM"
    dat = _dat(tmp_path, {"Metroid (Europe)": payload})
    torrent = _torrent(tmp_path, "Set", {"Metroid (Europe).nes": len(payload)})
    plan = _plan_for(tmp_path, dat, torrent)

    assert wanted_paths(plan, str(torrent)) == {"Metroid (Europe).nes"}
    assert wanted_paths(plan, "/otro/sitio.torrent") == set()
