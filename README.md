# RetroPerfect

[![CI](https://github.com/ruvelro/RetroPerfect/actions/workflows/ci.yml/badge.svg)](https://github.com/ruvelro/RetroPerfect/actions/workflows/ci.yml)

**RetroPerfect** te ayuda a convertir una colección de ROMs desordenada en una colección perfecta: verificada contra DATs oficiales (No-Intro, Redump, MAME, FBNeo), sin duplicados, con la mejor versión de cada juego según tus preferencias de región e idioma, y preparada para [RetroAchievements](https://retroachievements.org).

Funciona en local, con interfaz gráfica y línea de comandos, y **nunca descarga ROMs**: trabaja únicamente con los archivos que ya tienes.

![Estado](https://img.shields.io/badge/estado-en%20desarrollo-yellow) ![Python](https://img.shields.io/badge/python-3.11%2B-blue)

---

## ¿Qué hace?

- **Escanea** tu colección (archivos sueltos, ZIP y 7z) y la identifica por hash contra un DAT oficial: sabrás qué tienes de verdad, no lo que dicen los nombres de archivo.
- **Audita** con `verify`: juegos que te faltan, archivos que no pertenecen al set, ROMs mal nombradas y duplicados.
- **Cura** con perfiles 1G1R (*1 Game 1 ROM*): de 5 copias de un juego (Japón, USA, Europa, beta, hack...) conserva solo la que prefieras, con reglas de prioridad por región e idioma explicables — cada decisión viene con su motivo.
- **RetroAchievements**: marca qué ROMs de tu colección son compatibles con logros, y si una no lo es, puede localizar y aplicar el parche oficial automáticamente.
- **Aplica el plan con red de seguridad**: verificación MD5 byte a byte de cada archivo copiado o movido, comprobaciones previas de espacio y colisiones, y papelera restaurable en vez de borrados.

## Seguridad ante todo

Tu colección son años de trabajo. RetroPerfect está diseñado para no perder nunca un archivo:

| Protección | Qué hace |
|---|---|
| **Plan revisable** | Nada se toca sin un manifiesto que puedes inspeccionar antes de aplicar |
| **Verificación MD5** | Cada copia/movimiento se verifica byte a byte contra el original |
| **Detección de cambios** | Si un archivo cambió desde el escaneo, la operación se detiene |
| **Preflight** | Comprueba espacio en disco, orígenes desaparecidos y colisiones antes de empezar |
| **Papelera** | "Borrar" mueve a `.retroperfect/trash/` con restauración en un comando |

## Instalación

Necesitas Python 3.11 o superior.

```bash
git clone https://github.com/ruvelro/RetroPerfect.git
cd RetroPerfect
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Inicio rápido (interfaz gráfica)

```bash
retroperfect gui
```

Se abre en `http://127.0.0.1:8080` y te guía por pestañas: **Plataforma** → **Setup** (origen, DAT y salida) → **Perfil** → **Escaneo** → **Decisiones** → **Plan** → aplicar. Cada pestaña se desbloquea cuando la anterior está lista.

## Inicio rápido (línea de comandos)

```bash
# 1. Descarga un DAT (espejo Libretro) o importa el tuyo de DAT-o-MATIC
retroperfect dat-download --source libretro-nes-nointro

# 2. Escanea tu colección
retroperfect scan --platform nes --input ~/roms/nes

# 3. ¿Cómo está mi colección? (no toca nada)
retroperfect verify --platform nes --input ~/roms/nes --dat ruta/al/dat.xml

# 4. Crea el plan de curación y revísalo
retroperfect plan --scan .retroperfect/scans/latest.json --output-dir ~/roms-curadas
retroperfect report --manifest .retroperfect/manifests/latest.json --format html

# 5. Aplica (verificación MD5 incluida)
retroperfect apply --manifest .retroperfect/manifests/latest.json --confirm
```

### RetroAchievements

Necesitas tu [clave de API de RetroAchievements](https://retroachievements.org/controlpanel.php) (gratuita).

```bash
# Cachea los hashes oficiales de la plataforma (una vez)
retroperfect sync-ra --platform nes --username TU_USUARIO --api-key TU_CLAVE

# Localiza parches oficiales (labels y URLs) para juegos no compatibles
retroperfect sync-ra-details --platform nes
```

A partir de ahí, cada escaneo marca las ROMs compatibles, y los perfiles con salida `ra` pueden exigir compatibilidad o generar la versión parcheada automáticamente.

### Papelera

```bash
retroperfect trash-list                    # sesiones de borrado, con tamaño
retroperfect trash-restore 20260813-181500 # restaura a las rutas originales
retroperfect trash-empty --confirm         # vaciado definitivo
```

## Conceptos en 60 segundos

- **DAT**: catálogo oficial de hashes de un sistema (No-Intro para cartuchos, Redump para discos, MAME/FBNeo para arcade). Es la "verdad" contra la que se verifica todo.
- **1G1R**: de cada juego, una sola ROM. RetroPerfect agrupa las variantes (por Parent/Clone del DAT o por título) y elige la mejor según tu perfil.
- **Perfil**: tus reglas — prioridad de regiones (`Spain > Europe > World > USA > Japan`), de idiomas, exclusión de betas/hacks/bad dumps, preferencia por revisiones nuevas... Hay perfiles recomendados listos para usar.
- **Salidas**: `main` (tu colección 1G1R) y `ra` (variantes compatibles con RetroAchievements). Con el layout *organizado*, la salida se estructura en carpetas `EUR/`, `USA/`, `JPN/`, `Otros/...`.
- **Manifiesto**: el plan de operaciones (copiar/mover/borrar) que revisas antes de aplicar. Se guarda en `.retroperfect/manifests/`.

## Plataformas

Más de 190 sistemas catalogados, desde NES hasta Dreamcast, pasando por ordenadores clásicos (Amiga, MSX, ZX Spectrum...), portátiles y arcade (MAME, FBNeo, CPS, Neo Geo...). Cada plataforma incluye su DAT recomendado, extensiones esperadas y diagnósticos específicos (cabeceras NES, endianness N64, variantes A78/BIN, sets arcade con parents/clones/BIOS/CHD).

**Hashes RetroAchievements soportados**: cartuchos (hash directo), NES/FDS/SNES/Lynx/Atari 7800/PC Engine (descarte de cabeceras), N64 (normalización de endianness), Nintendo DS (cabecera + ARM9 + ARM7 + icono) y arcade (por nombre de set). Los sistemas de disco (PSX, Sega CD, Saturn...) aún no calculan hash RA.

## Parches soportados

IPS, BPS, UPS y xdelta/VCDIFF, sueltos o dentro de ZIP, con verificación de CRC/MD5 del resultado. (PPF, APS y RUP todavía no.)

## Aplicación de escritorio

```bash
./scripts/build-app.sh
```

Genera un ejecutable único con PyInstaller (`dist/RetroPerfect`). Experimental.

## Desarrollo

```bash
pip install -e ".[dev]"
pytest -q            # 87 tests
ruff check src tests # lint
mypy                 # type-checking estricto en verde
```

La CI ejecuta las tres cosas en Python 3.11, 3.12 y 3.13.

## Aviso

RetroPerfect no descarga, incluye ni enlaza ROMs. Está pensado para gestionar copias de seguridad de tu propia colección. Los DATs se descargan de fuentes públicas (espejo Libretro) o los importas tú desde DAT-o-MATIC/Redump.
