# RetroPerfect

RetroPerfect curates retro ROM collections from verified DAT metadata and configurable profiles. The first MVP supports NES/Famicom, No-Intro LogiqX XML DAT files, loose `.nes` files, `.zip` archives, and RetroAchievements-aware output planning.

## Install for development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## CLI

```bash
retroperfect scan --platform nes --input ./roms --dat ./Nintendo-NES-ParentClone.xml
retroperfect sync-ra --platform nes --username YOUR_RA_USER --api-key YOUR_RA_KEY
retroperfect plan --scan .retroperfect/scans/latest.json --profile default --outputs main,ra --output-dir ./curated
retroperfect apply --manifest .retroperfect/manifests/latest.json --mode copy --confirm
retroperfect report --manifest .retroperfect/manifests/latest.json --format html
```

## GUI

```bash
retroperfect gui
```

The GUI runs locally and uses the same core as the CLI.

## Safety

RetroPerfect never downloads ROMs. Destructive actions are executed only from a saved manifest and require explicit confirmation.

