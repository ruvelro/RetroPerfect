from __future__ import annotations

import json
from pathlib import Path

import yaml

from .models import ExportLayout, OutputBucket, ProfileOutput, SelectionProfile
from .paths import config_dir

DEFAULT_PROFILE = SelectionProfile(
    name="default",
    outputs=[
        ProfileOutput(bucket=OutputBucket.MAIN, require_ra=False, strict_1g1r=True, tag_excludes=[]),
        ProfileOutput(bucket=OutputBucket.RA, require_ra=True, strict_1g1r=False, tag_excludes=[]),
    ],
)


RECOMMENDED_PROFILES: dict[str, SelectionProfile] = {
    "1G1R puro": SelectionProfile(
        name="1G1R puro",
        export_layout=ExportLayout.ORGANIZED,
        outputs=[
            ProfileOutput(bucket=OutputBucket.MAIN, require_ra=False, strict_1g1r=True, prefer_ra_compatible=True, region_priority=["Spain", "Europe", "World", "USA", "Japan"], language_priority=["Spanish", "English", "Multi"]),
        ],
    ),
    "1G1R + RA": SelectionProfile(
        name="1G1R + RA",
        export_layout=ExportLayout.ORGANIZED,
        auto_patch_ra=True,
        outputs=[
            ProfileOutput(bucket=OutputBucket.MAIN, require_ra=False, strict_1g1r=True, region_priority=["Spain", "Europe", "World", "USA", "Japan"], language_priority=["Spanish", "English", "Multi"]),
            ProfileOutput(bucket=OutputBucket.RA, require_ra=True, strict_1g1r=False, region_priority=["Spain", "Europe", "World", "USA", "Japan"], language_priority=["Spanish", "English", "Multi"]),
        ],
    ),
    "España/Europa": SelectionProfile(
        name="España/Europa",
        export_layout=ExportLayout.ORGANIZED,
        outputs=[
            ProfileOutput(bucket=OutputBucket.MAIN, require_ra=False, strict_1g1r=True, prefer_ra_compatible=True, region_priority=["Spain", "Europe", "World", "USA", "Japan"], language_priority=["Spanish", "Multi", "English"]),
            ProfileOutput(bucket=OutputBucket.RA, require_ra=True, strict_1g1r=False, region_priority=["Spain", "Europe", "World", "USA", "Japan"], language_priority=["Spanish", "Multi", "English"]),
        ],
    ),
    "USA-first": SelectionProfile(
        name="USA-first",
        export_layout=ExportLayout.ORGANIZED,
        outputs=[
            ProfileOutput(bucket=OutputBucket.MAIN, require_ra=False, strict_1g1r=True, prefer_ra_compatible=True, region_priority=["USA", "World", "Europe", "Spain", "Japan"], language_priority=["English", "Multi", "Spanish"]),
            ProfileOutput(bucket=OutputBucket.RA, require_ra=True, strict_1g1r=False, region_priority=["USA", "World", "Europe", "Spain", "Japan"], language_priority=["English", "Multi", "Spanish"]),
        ],
    ),
    "Arcade seguro": SelectionProfile(
        name="Arcade seguro",
        export_layout=ExportLayout.ORGANIZED,
        outputs=[
            ProfileOutput(bucket=OutputBucket.MAIN, require_ra=False, strict_1g1r=False, tag_excludes=[]),
        ],
    ),
    "Arcade preferir parent": SelectionProfile(
        name="Arcade preferir parent",
        export_layout=ExportLayout.ORGANIZED,
        outputs=[
            ProfileOutput(bucket=OutputBucket.MAIN, require_ra=False, strict_1g1r=True, region_priority=["World", "USA", "Europe", "Japan"], language_priority=["English", "Multi", "Japanese"], tag_excludes=[]),
        ],
    ),
}


def load_profile(profile: str | Path) -> SelectionProfile:
    if str(profile) == "default":
        return DEFAULT_PROFILE
    path = Path(profile)
    data = yaml.safe_load(path.read_text()) if path.suffix.lower() in {".yaml", ".yml"} else json.loads(path.read_text())
    return SelectionProfile.model_validate(data)


def save_profile(profile: SelectionProfile, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".yaml", ".yml"}:
        path.write_text(yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
    else:
        path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")


def profiles_dir() -> Path:
    path = config_dir() / "profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def profile_path(name: str) -> Path:
    safe = "".join(ch for ch in name.strip().lower().replace(" ", "-") if ch.isalnum() or ch in {"-", "_"})
    return profiles_dir() / f"{safe or 'profile'}.yaml"


def save_named_profile(profile: SelectionProfile) -> Path:
    path = profile_path(profile.name)
    save_profile(profile, path)
    return path


def list_profiles() -> dict[str, Path]:
    profiles = {"default": Path("default")}
    for path in sorted(profiles_dir().glob("*.y*ml")):
        try:
            profile = load_profile(path)
            profiles[profile.name] = path
        except Exception:
            profiles[path.stem] = path
    return profiles


def list_recommended_profiles() -> dict[str, SelectionProfile]:
    return {name: profile.model_copy(deep=True) for name, profile in RECOMMENDED_PROFILES.items()}
