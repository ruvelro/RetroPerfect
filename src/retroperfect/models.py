from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Platform(StrEnum):
    NES = "nes"
    FDS = "fds"
    SNES = "snes"
    GB = "gb"
    GBC = "gbc"
    GBA = "gba"
    VB = "vb"
    N64 = "n64"
    NDS = "nds"
    SMS = "sms"
    GG = "gg"
    MD = "md"
    S32X = "32x"
    SG1000 = "sg1000"
    PCE = "pce"
    SGX = "sgx"
    A2600 = "a2600"
    A5200 = "a5200"
    A7800 = "a7800"
    LYNX = "lynx"
    JAGUAR = "jaguar"
    NGP = "ngp"
    NGPC = "ngpc"
    WS = "ws"
    WSC = "wsc"
    COLECO = "colecovision"
    INTV = "intellivision"
    VECTREX = "vectrex"
    ODYSSEY2 = "odyssey2"
    POKEMON_MINI = "pokemon-mini"
    SATELLAVIEW = "satellaview"
    SUFAMI_TURBO = "sufami-turbo"
    EREADER = "ereader"
    PICO = "pico"
    BEENA = "beena"
    DREAMCAST_VMU = "dreamcast-vmu"
    GAMECOM = "gamecom"
    SUPERVISION = "supervision"
    MEGA_DUCK = "mega-duck"
    GAMATE = "gamate"
    GP32 = "gp32"
    LOOPY = "loopy"
    PV1000 = "pv1000"
    ARCADIA = "arcadia-2001"
    CHANNELF = "channel-f"
    SUPERCASSETTE = "super-cassette-vision"
    CREATIVISION = "creativision"
    VSMILE = "vsmile"
    LEAPSTER = "leapster"
    ARDUBOY = "arduboy"
    MSX = "msx"
    MSX2 = "msx2"
    C64 = "c64"
    AMIGA = "amiga"
    ATARI_ST = "atari-st"
    ATARI_8BIT = "atari-8bit"
    CPC = "amstrad-cpc"
    ZX_SPECTRUM = "zx-spectrum"
    APPLE_II = "apple-ii"
    X68000 = "x68000"
    PC88 = "pc-88"
    PC98 = "pc-98"
    TI99 = "ti-99"
    NGAGE = "ngage"
    GIZMONDO = "gizmondo"
    NUON = "nuon"
    IQUE = "ique"
    ZEEBO = "zeebo"
    PIPPIN = "pippin"
    N64DD = "n64dd"
    NDS_DOWNLOAD_PLAY = "nds-download-play"
    DSI = "dsi"
    DSIWARE = "dsiware"
    DSI_CDN = "dsi-cdn"
    N3DS = "n3ds"
    N3DS_DIGITAL = "n3ds-digital"
    N3DS_DLC = "n3ds-dlc"
    N3DS_DEV = "n3ds-dev"
    N3DS_PREINSTALL = "n3ds-preinstall"
    N3DS_CIA = "n3ds-cia"
    GAME_WATCH = "game-watch"
    FAMILY_BASIC = "family-basic"
    FAMICOM_NETWORK = "famicom-network"
    KIOSK_CF = "kiosk-cf"
    MARIO_PHOTOPI = "mario-photopi"
    NINTENDO_MISC = "nintendo-misc"
    PLAY_YAN = "play-yan"
    AMIIBO = "amiibo"
    SWITCH = "switch"
    SWITCH_DIGITAL = "switch-digital"
    SWITCH_DLC = "switch-dlc"
    WII_CDN = "wii-cdn"
    WIIU_CDN = "wiiu-cdn"
    WIIU_DLC = "wiiu-dlc"
    GAMECUBE = "gamecube"
    WII = "wii"
    WIIU = "wiiu"
    PS1 = "ps1"
    PS2 = "ps2"
    PS3 = "ps3"
    PS4_PSN = "ps4-psn"
    PS5_PSN = "ps5-psn"
    PSP = "psp"
    PSP_PSN = "psp-psn"
    PSP_PSN_DECRYPTED = "psp-psn-decrypted"
    PSX2PSP = "psx2psp"
    VITA = "vita"
    VITA_PSN = "vita-psn"
    PS3_PSN = "ps3-psn"
    PS3_PSN_DECRYPTED = "ps3-psn-decrypted"
    PSN_PS1 = "psn-ps1-classics"
    XBOX = "xbox"
    XBOX360 = "xbox360"
    XBOXONE = "xboxone"
    XBOX360_TU = "xbox360-title-updates"
    SEGACD = "segacd"
    SATURN = "saturn"
    DREAMCAST = "dreamcast"
    JAGUAR_CD = "jaguar-cd"
    PCE_CD = "pce-cd"
    THREE_DO = "3do"
    CDI = "cd-i"
    GAME_WAVE = "game-wave"
    OUYA = "ouya"
    ACORN_ARCHIMEDES = "acorn-archimedes"
    ACORN_ATOM = "acorn-atom"
    BBC_MICRO = "bbc-micro"
    ACORN_RISC_PC = "acorn-risc-pc"
    APRICOT_PC = "apricot-pc"
    APF_MP1000 = "apf-mp1000"
    APF_IMAGINATION = "apf-imagination"
    APPLE_I = "apple-i"
    APPLE_II_PLUS = "apple-ii-plus"
    APPLE_IIE = "apple-iie"
    APPLE_IIGS = "apple-iigs"
    MACINTOSH = "macintosh"
    COMMODORE_PLUS4 = "commodore-plus4"
    VIC20 = "vic20"
    C64_PP = "c64-pp"
    C64_TAPES = "c64-tapes"
    ZX_SPECTRUM_PLUS3 = "zx-spectrum-plus3"
    SHARP_X1 = "sharp-x1"
    TELE_NOVA_COMPIS = "telenova-compis"
    TOSHIBA_PASOPIA = "toshiba-pasopia"
    TOSHIBA_VISICOM = "toshiba-visicom"
    YAMAHA_COPERA = "yamaha-copera"
    BALLY_ASTROCADE = "bally-astrocade"
    BALLY_ASTROCADE_TAPES = "bally-astrocade-tapes"
    RCA_STUDIO_II = "rca-studio-ii"
    ENTEX_ADVENTURE = "entex-adventure-vision"
    EPOCH_GAME_POCKET = "epoch-game-pocket"
    NICHIBUTSU_MY_VISION = "nichibutsu-my-vision"
    SETA_ALECK64 = "seta-aleck64"
    BANDAI_DESIGN_MASTER = "bandai-design-master"
    BANDAI_RX78 = "bandai-rx78"
    BENESSE_POCKET_CHALLENGE_V2 = "benesse-pocket-challenge-v2"
    BENESSE_POCKET_CHALLENGE_W = "benesse-pocket-challenge-w"
    VTECH_MOBIGO = "vtech-mobigo"
    NOKIA_NGAGE_2 = "ngage-2"
    MAME = "mame"
    MAME_CHD = "mame-chd"
    MAME_SOFTWARE_LIST = "mame-software-list"
    MAME2003PLUS = "mame2003plus"
    FBNEO = "fbneo"
    FBA = "fba"
    HBMAME = "hbmame"
    NEOGEO_MVS = "neogeo-mvs"
    CPS1 = "cps1"
    CPS2 = "cps2"
    CPS3 = "cps3"
    SEGA_MODEL2 = "sega-model2"
    SEGA_MODEL3 = "sega-model3"
    NAOMI = "naomi"
    ATOMISWAVE = "atomiswave"
    CAVE_ARCADE = "cave-arcade"
    TAITO_F3 = "taito-f3"
    IGS_PGM = "igs-pgm"
    PCFX = "pc-fx"
    NEOGEO_CD = "neogeo-cd"
    WASM4 = "wasm4"
    UZEBOX = "uzebox"
    INTERTON_VC4000 = "interton-vc4000"
    ELEKTOR_TVGC = "elektor-tv-games-computer"


class OutputBucket(StrEnum):
    MAIN = "main"
    RA = "ra"


class ActionMode(StrEnum):
    COPY = "copy"
    MOVE = "move"
    DELETE = "delete"


class ExportLayout(StrEnum):
    BUCKETS = "buckets"
    ORGANIZED = "organized"


class RomHash(BaseModel):
    crc32: str
    md5: str
    sha1: str
    size: int
    ra_hash: str | None = None
    payload_crc32: str | None = None
    payload_md5: str | None = None
    payload_sha1: str | None = None
    payload_size: int | None = None


class DatRom(BaseModel):
    name: str
    size: int | None = None
    crc32: str | None = None
    md5: str | None = None
    sha1: str | None = None
    header: str | None = None


class DatGame(BaseModel):
    name: str
    dat_id: str | None = None
    description: str | None = None
    cloneof: str | None = None
    roms: list[DatRom] = Field(default_factory=list)
    releases: list[str] = Field(default_factory=list)

    @property
    def group_key(self) -> str:
        return self.cloneof or self.name


class DatCatalog(BaseModel):
    name: str | None = None
    description: str | None = None
    games: list[DatGame] = Field(default_factory=list)


class DetectedMetadata(BaseModel):
    title: str
    regions: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    version: str | None = None
    revision: int = 0
    tags: list[str] = Field(default_factory=list)


class ScannedRom(BaseModel):
    id: str
    source_path: str
    container_path: str
    inner_path: str | None = None
    platform: Platform
    hashes: RomHash
    dat_game: DatGame | None = None
    metadata: DetectedMetadata
    ra_game_id: int | None = None
    ra_title: str | None = None
    ra_hash_name: str | None = None
    ra_labels: list[str] = Field(default_factory=list)
    ra_patch_url: str | None = None

    @property
    def group_key(self) -> str:
        if self.dat_game:
            return self.dat_game.group_key
        return self.metadata.title


class ScanResult(BaseModel):
    id: str
    platform: Platform
    input_path: str
    dat_path: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    roms: list[ScannedRom] = Field(default_factory=list)
    unmatched_files: list[str] = Field(default_factory=list)


class ProfileOutput(BaseModel):
    bucket: OutputBucket
    require_ra: bool = False
    strict_1g1r: bool = False
    prefer_ra_compatible: bool = False
    region_priority: list[str] = Field(default_factory=lambda: ["Spain", "Europe", "World", "USA", "Japan"])
    language_priority: list[str] = Field(default_factory=lambda: ["Spanish", "English", "Multi"])
    tag_excludes: list[str] = Field(default_factory=list)
    prefer_newest_revision: bool = True


class SelectionProfile(BaseModel):
    name: str = "default"
    export_layout: ExportLayout = ExportLayout.BUCKETS
    auto_patch_ra: bool = False
    outputs: list[ProfileOutput] = Field(
        default_factory=lambda: [
            ProfileOutput(bucket=OutputBucket.MAIN),
            ProfileOutput(bucket=OutputBucket.RA, require_ra=True),
        ]
    )


class CandidateDecision(BaseModel):
    rom_id: str
    source_path: str
    kept: bool
    reasons: list[str] = Field(default_factory=list)


class ManifestEntry(BaseModel):
    bucket: OutputBucket
    action: ActionMode
    source_path: str
    source_inner_path: str | None = None
    source_md5: str | None = None
    destination_path: str | None = None
    rom_id: str
    dat_name: str | None = None
    ra_game_id: int | None = None
    patch_url: str | None = None
    patch_expected_md5: str | None = None
    patch_name: str | None = None
    explanation: list[str] = Field(default_factory=list)


class Manifest(BaseModel):
    id: str
    scan_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    platform: Platform
    profile_snapshot: dict[str, Any]
    entries: list[ManifestEntry] = Field(default_factory=list)
    discarded: list[CandidateDecision] = Field(default_factory=list)


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
