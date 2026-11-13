"""Lectura de .torrent, selección de archivos en qBittorrent y recogida agnóstica de cliente."""
from __future__ import annotations

import binascii
import hashlib
from pathlib import Path

import pytest
import requests

from retroperfect import rom_sources
from retroperfect.dat import DatIndex, parse_logiqx_dat
from retroperfect.download_plan import build_download_plan
from retroperfect.downloader import collect_downloads
from retroperfect.models import OutputBucket, Platform, ProfileOutput, SelectionProfile
from retroperfect.rom_sources import RomSource, resolve_source
from retroperfect.torrent import TorrentError, read_torrent
from retroperfect.torrent_client import PRIORITY_NORMAL, PRIORITY_SKIP, QBittorrentClient, TorrentClientError, queue_plan, wanted_paths

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


# --- cliente HTTP de qBittorrent ---------------------------------------------


class _RespuestaFalsa:
    def __init__(self, text: str = "", status_code: int = 200, payload: object = None) -> None:
        self.text = text
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _SesionFalsa:
    """Registra las peticiones y devuelve lo que se le diga, por ruta."""

    def __init__(self, respuestas: dict[str, object] | None = None) -> None:
        self.respuestas = respuestas or {}
        self.peticiones: list[tuple[str, str, dict]] = []

    def _responder(self, metodo: str, url: str, kwargs: dict) -> _RespuestaFalsa:
        self.peticiones.append((metodo, url, kwargs))
        for ruta, respuesta in self.respuestas.items():
            if url.endswith(ruta):
                if isinstance(respuesta, Exception):
                    raise respuesta
                return respuesta  # type: ignore[return-value]
        return _RespuestaFalsa()

    def post(self, url: str, **kwargs) -> _RespuestaFalsa:
        return self._responder("POST", url, kwargs)

    def get(self, url: str, **kwargs) -> _RespuestaFalsa:
        return self._responder("GET", url, kwargs)


def _cliente(respuestas: dict[str, object] | None = None, **kwargs) -> QBittorrentClient:
    client = QBittorrentClient(**kwargs)
    client.session = _SesionFalsa(respuestas)  # type: ignore[assignment]
    return client


def test_el_cliente_no_se_autentica_si_no_hay_credenciales(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con la Web UI abierta en local no hacen falta, y pedirlas sobraría."""
    monkeypatch.delenv("RETROPERFECT_QBT_USER", raising=False)
    monkeypatch.delenv("RETROPERFECT_QBT_PASS", raising=False)
    client = _cliente()

    client.login()

    assert client.session.peticiones == []  # type: ignore[attr-defined]


def test_el_cliente_toma_las_credenciales_del_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    """No se guardan en ningún archivo: es la política del módulo."""
    monkeypatch.setenv("RETROPERFECT_QBT_USER", "yo")
    monkeypatch.setenv("RETROPERFECT_QBT_PASS", "secreto")
    client = _cliente({"auth/login": _RespuestaFalsa(text="Ok.")})

    client.login()

    metodo, url, kwargs = client.session.peticiones[0]  # type: ignore[attr-defined]
    assert (metodo, url) == ("POST", "http://127.0.0.1:8080/api/v2/auth/login")
    assert kwargs["data"] == {"username": "yo", "password": "secreto"}


def test_el_cliente_avisa_si_rechazan_las_credenciales() -> None:
    client = _cliente({"auth/login": _RespuestaFalsa(text="Fails.")}, username="yo", password="mal")

    with pytest.raises(TorrentClientError, match="rechazó las credenciales"):
        client.login()


def test_el_cliente_explica_un_403_en_vez_de_soltar_el_http() -> None:
    client = _cliente({"torrents/filePrio": _RespuestaFalsa(status_code=403)})

    with pytest.raises(TorrentClientError, match="¿Hace falta usuario y contraseña?"):
        client.set_priorities("abc", [0], PRIORITY_SKIP)


def test_el_cliente_explica_que_no_hay_nadie_escuchando() -> None:
    client = _cliente({"app/version": requests.ConnectionError("rechazada")})

    with pytest.raises(TorrentClientError, match="No se pudo contactar con qBittorrent"):
        client.version()

    client = _cliente({"torrents/add": requests.ConnectionError("rechazada")})
    torrent = Path(__file__)
    with pytest.raises(TorrentClientError, match="No se pudo contactar con qBittorrent"):
        client.add_torrent(torrent)


def test_el_cliente_normaliza_la_url_base() -> None:
    client = _cliente({}, base_url="http://nas.local:9000/")

    client.version()

    _metodo, url, _kwargs = client.session.peticiones[0]  # type: ignore[attr-defined]
    assert url == "http://nas.local:9000/api/v2/app/version"


def test_anadir_un_torrent_lo_deja_en_pausa(tmp_path: Path) -> None:
    """Hay que poder deseleccionar archivos ANTES de que empiece a bajar."""
    torrent = tmp_path / "set.torrent"
    torrent.write_bytes(b"d4:infod4:name3:Setee")
    client = _cliente()

    client.add_torrent(torrent, save_path="/descargas")

    _metodo, url, kwargs = client.session.peticiones[0]  # type: ignore[attr-defined]
    assert url.endswith("torrents/add")
    assert kwargs["data"]["paused"] == "true"
    assert kwargs["data"]["stopped"] == "true", "qBittorrent 5.x usa 'stopped'"
    assert kwargs["data"]["savepath"] == "/descargas"
    assert "torrents" in kwargs["files"]


def test_no_se_mandan_prioridades_vacias() -> None:
    client = _cliente()

    client.set_priorities("abc", [], PRIORITY_SKIP)

    assert client.session.peticiones == []  # type: ignore[attr-defined]


def test_las_prioridades_van_en_una_sola_peticion() -> None:
    client = _cliente()

    client.set_priorities("abc", [0, 2, 5], PRIORITY_SKIP)

    _metodo, _url, kwargs = client.session.peticiones[0]  # type: ignore[attr-defined]
    assert kwargs["data"]["id"] == "0|2|5"
    assert kwargs["data"]["priority"] == PRIORITY_SKIP


def test_arrancar_prueba_los_dos_nombres_del_endpoint() -> None:
    """`start` en qBittorrent 5.x, `resume` en 4.x."""
    client = _cliente({"torrents/start": _RespuestaFalsa(status_code=404)})

    client.start("abc")

    rutas = [url.rsplit("/api/v2/", 1)[1] for _m, url, _k in client.session.peticiones]  # type: ignore[attr-defined]
    assert rutas == ["torrents/start", "torrents/resume"]


def test_si_ningun_endpoint_de_arranque_vale_se_dice() -> None:
    client = _cliente({"torrents/start": _RespuestaFalsa(status_code=404), "torrents/resume": _RespuestaFalsa(status_code=404)})

    with pytest.raises(TorrentClientError, match="No se pudo reanudar"):
        client.start("abc")


def test_la_lista_de_archivos_llega_como_lista() -> None:
    client = _cliente({"torrents/files": _RespuestaFalsa(payload=[{"index": 0, "name": "Set/a.nes"}])})

    assert client.files("abc") == [{"index": 0, "name": "Set/a.nes"}]


def test_queue_avisa_si_qbittorrent_no_devuelve_los_archivos(isolated_config: Path, tmp_path: Path) -> None:
    payload = b"METROID-ROM"
    dat = _dat(tmp_path, {"Metroid (Europe)": payload})
    torrent = _torrent(tmp_path, "Set", {"Metroid (Europe).nes": len(payload)})
    plan = _plan_for(tmp_path, dat, torrent)

    with pytest.raises(TorrentClientError, match="no devuelve su lista de archivos"):
        queue_plan(plan, torrent, client=_FakeQBittorrent([]))  # type: ignore[arg-type]


def test_queue_puede_dejar_el_torrent_sin_arrancar(isolated_config: Path, tmp_path: Path) -> None:
    payload = b"METROID-ROM"
    dat = _dat(tmp_path, {"Metroid (Europe)": payload})
    torrent = _torrent(tmp_path, "Set", {"Metroid (Europe).nes": len(payload)})
    plan = _plan_for(tmp_path, dat, torrent)
    client = _FakeQBittorrent([{"index": 0, "name": "Set/Metroid (Europe).nes"}])

    queue_plan(plan, torrent, client=client, start=False)  # type: ignore[arg-type]

    assert client.added
    assert not client.started


def test_queue_tolera_un_torrent_de_un_solo_archivo_sin_carpeta(isolated_config: Path, tmp_path: Path) -> None:
    """En los de un archivo qBittorrent no antepone la carpeta del torrent."""
    payload = b"METROID-ROM"
    dat = _dat(tmp_path, {"Metroid (Europe)": payload})
    torrent = _torrent(tmp_path, "Set", {"Metroid (Europe).nes": len(payload)})
    plan = _plan_for(tmp_path, dat, torrent)
    client = _FakeQBittorrent([{"index": 0, "name": "Metroid (Europe).nes"}])

    assert queue_plan(plan, torrent, client=client) == {"seleccionados": 1, "descartados": 0}  # type: ignore[arg-type]
