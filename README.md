# RetroPerfect

[![CI](https://github.com/ruvelro/RetroPerfect/actions/workflows/ci.yml/badge.svg)](https://github.com/ruvelro/RetroPerfect/actions/workflows/ci.yml)

**RetroPerfect** te ayuda a convertir una colección de ROMs desordenada en una colección perfecta: verificada contra DATs oficiales (No-Intro, Redump, MAME, FBNeo), sin duplicados, con la mejor versión de cada juego según tus preferencias de región e idioma, y preparada para [RetroAchievements](https://retroachievements.org).

Funciona en local, con interfaz gráfica y línea de comandos. **No incluye ni enlaza ROMs**: trabaja con los archivos que ya tienes y, si configuras tus propias fuentes, puede completar lo que falte descargándolo de ellas y verificándolo contra el DAT antes de tocar tu colección.

![Estado](https://img.shields.io/badge/estado-en%20desarrollo-yellow) ![Python](https://img.shields.io/badge/python-3.11%2B-blue)

---

## ¿Qué hace?

- **Escanea** tu colección (archivos sueltos, ZIP y 7z) y la identifica por hash contra un DAT oficial: sabrás qué tienes de verdad, no lo que dicen los nombres de archivo.
- **Audita** con `verify`: juegos que te faltan, archivos que no pertenecen al set, ROMs mal nombradas y duplicados.
- **Cura** con perfiles 1G1R (*1 Game 1 ROM*): de 5 copias de un juego (Japón, USA, Europa, beta, hack...) conserva solo la que prefieras, con reglas de prioridad por región e idioma explicables — cada decisión viene con su motivo.
- **RetroAchievements**: marca qué ROMs de tu colección son compatibles con logros, y si una no lo es, puede localizar y aplicar el parche oficial automáticamente.
- **Aplica el plan con red de seguridad**: verificación MD5 byte a byte de cada archivo copiado o movido, comprobaciones previas de espacio y colisiones, y papelera restaurable en vez de borrados.
- **Completa lo que falta** desde las fuentes que tú configures (tu NAS, un ítem de archive.org, un índice HTTP): descarga solo los juegos ausentes según el DAT y tu perfil, y verifica cada archivo por hash antes de instalarlo. RetroPerfect no trae ninguna fuente preconfigurada.

## Seguridad ante todo

Tu colección son años de trabajo. RetroPerfect está diseñado para no perder nunca un archivo:

| Protección | Qué hace |
|---|---|
| **Plan revisable** | Nada se toca sin un manifiesto que puedes inspeccionar antes de aplicar |
| **Verificación MD5** | Cada copia/movimiento se verifica byte a byte contra el original |
| **Detección de cambios** | Si un archivo cambió desde el escaneo, la operación se detiene |
| **Preflight** | Comprueba espacio en disco, orígenes desaparecidos y colisiones antes de empezar |
| **Papelera** | "Borrar" mueve a `.retroperfect/trash/` con restauración en un comando |
| **Journal** | Cada aplicación queda registrada en `.retroperfect/applied/` (incluidos los fallos parciales) |

## Instalación

Hay dos formas. Si ya tienes Python, la segunda es más cómoda porque no da ningún aviso de seguridad.

### Opción A · Descargar la app (sin Python)

Descarga el ZIP de tu sistema desde **[Releases](https://github.com/ruvelro/RetroPerfect/releases)** y sigue los pasos de tu sistema. La primera vez macOS y Windows piden autorizar la app: es porque no está firmada digitalmente (firmar cuesta entre 99 y 400 $ al año, ver [Hoja de ruta](#hoja-de-ruta)). No es un problema de la app.

<details open>
<summary><b>🍎 macOS</b> · primera vez: 4 clics</summary>

1. Descomprime el ZIP y arrastra **RetroPerfect.app** a tu carpeta de Aplicaciones.
2. Doble clic. Aparecerá el aviso *"No se ha abierto RetroPerfect. Apple no ha podido verificar…"*.
   👉 Pulsa **Aceptar**. **Nunca pulses "Trasladar a la Papelera"**: eso borra la app.
3. Abre **Ajustes del Sistema → Privacidad y seguridad** y baja hasta el aviso *"Se ha bloqueado el uso de RetroPerfect…"*. Pulsa **Abrir de todos modos**.
4. Confirma con Touch ID o tu contraseña y pulsa **Abrir**.

Listo: se abre la interfaz en tu navegador. A partir de ahí, doble clic normal y sin avisos.

*Atajo si usas la Terminal:* `xattr -dr com.apple.quarantine` seguido de un espacio y la carpeta arrastrada desde el Finder. Hace lo mismo en un paso.

*¿Por qué?* macOS marca con "cuarentena" todo lo descargado. Levantar esa marca automáticamente requiere notarizar la app con una cuenta de desarrollador de Apple de pago (99 $/año) que este proyecto no tiene.

</details>

<details>
<summary><b>🪟 Windows</b> · primera vez: 2 clics</summary>

1. Clic derecho en el ZIP → **Extraer todo**.
2. Doble clic en **RetroPerfect.exe**.
3. Si aparece *"Windows protegió tu PC"*, pulsa **Más información** → **Ejecutar de todas formas**.

Si tu antivirus se queja, es un falso positivo habitual con aplicaciones Python empaquetadas; puedes comprobar el código fuente completo en este repositorio.

</details>

<details>
<summary><b>🐧 Linux</b> · directo, sin avisos</summary>

```bash
unzip RetroPerfect-linux.zip
cd RetroPerfect
chmod +x RetroPerfect   # solo si tu descompresor perdió los permisos
./RetroPerfect
```

Necesita **glibc 2.35 o superior** (Ubuntu 22.04+, Debian 12+, Fedora 36+). Si ves un error tipo `GLIBC_2.xx not found`, tu distribución es más antigua: usa la Opción B.

</details>

### Opción B · Instalar con Python (3.11 o superior)

Un comando, sin avisos de seguridad en ningún sistema:

```bash
pip install git+https://github.com/ruvelro/RetroPerfect
retroperfect gui
```

Si usas [pipx](https://pipx.pypa.io), `pipx install git+https://github.com/ruvelro/RetroPerfect` lo deja aislado y con el comando `retroperfect` disponible en todo el sistema.

### Cerrar la aplicación

RetroPerfect es un servidor local, así que cerrar la pestaña del navegador no basta por sí solo. Tienes dos formas, y ninguna necesita el Monitor de Actividad ni el Administrador de tareas:

- **Botón "Salir"** arriba a la derecha: cierra el programa del todo. Si hay un escaneo o una copia en marcha, avisa antes de cortarla.
- **Automático**: si cierras la pestaña y no vuelves, la aplicación se apaga sola al cabo de un minuto. Nunca lo hace mientras haya una operación en curso.

Si la lanzas desde la terminal con `retroperfect gui`, el apagado automático viene desactivado (para que no se cierre sola mientras trasteas) y puedes activarlo con `--exit-on-idle`.

### Para desarrollar (3.11 o superior)

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

### Mantener los DATs al día

Los DATs cambian cuando No-Intro añade o corrige dumps. RetroPerfect re-descarga los DATs instalados de fuentes directas y te dice qué cambió:

```bash
retroperfect dat-update
```

La GUI avisa en **Biblioteca DAT** cuando algún DAT lleva más de 7 días sin refrescar. Para automatizarlo, prográmalo con cron (o el Programador de tareas de Windows):

```bash
# Cada lunes a las 8:00, desde la carpeta del proyecto
0 8 * * 1 cd /ruta/a/tu/coleccion && /ruta/al/venv/bin/retroperfect dat-update
```

### Descargar lo que falta

RetroPerfect **no incluye ningún catálogo de ROMs ni enlaza a espejos**: las fuentes las configuras tú y respondes de lo que descargas. Lo que aporta la herramienta es saber *qué* te falta y verificar *qué* ha llegado: cruza tus fuentes con el DAT y con tu perfil, descarga solo los juegos ausentes (una variante por grupo 1G1R, no el set entero) y comprueba el hash de cada archivo antes de instalarlo en el romset. Lo que no cuadra con el DAT acaba en `.retroperfect/downloads/quarantine/` con el motivo, nunca en tu colección.

Hay tres tipos de fuente:

| Tipo | Origen | Notas |
| --- | --- | --- |
| `archive_org` | identificador o URL de un ítem de archive.org | trae tamaño y md5/crc32, así que el emparejamiento es por hash |
| `http_index` | URL de un autoíndice de Apache/nginx | empareja por nombre; la verificación sigue siendo por hash tras descargar |
| `local_dir` | carpeta local, NAS o unidad de red montada | ideal para restaurar desde tu propia copia de seguridad |
| `zip_index` | ruta o URL de un ZIP que contiene el set | lee su índice **sin descargarlo entero** y extrae solo los juegos que faltan |

```bash
# Registra una fuente (aquí, tu backup en el NAS)
retroperfect rom-source-add --id nas --label "Backup NAS" --kind local_dir \
  --location /Volumes/nas/roms/nes --platform nes

retroperfect rom-sources                      # lista las fuentes configuradas
retroperfect rom-source-toggle nas --disable  # silencia un espejo caído sin borrarlo

# Simula: qué falta y de dónde saldría (no descarga nada)
retroperfect download --platform nes --dat nes.dat --scan .retroperfect/scans/latest.json

# Descarga, verifica contra el DAT e instala en el romset
retroperfect download --platform nes --dat nes.dat --scan .retroperfect/scans/latest.json \
  --dest ./romset --confirm
```

Sin `--confirm` solo se muestra el plan. `--all-variants` desactiva el filtro del perfil y planifica todas las variantes del DAT; `--limit N` acota la tanda; `--refresh` fuerza releer los índices remotos (se cachean 12 h). Las descargas HTTP se reanudan solas si se cortan, y respetan el `Retry-After` del servidor.

En la GUI, todo esto vive en la pestaña **Descargar**: gestiona las fuentes, muestra el plan con una etiqueta de cómo se emparejó cada archivo (por hash, por nombre exacto o aproximado), lista aparte los juegos que ninguna fuente ofrece, y permite marcar filas para bajar solo esas.

#### Sets empaquetados en un solo ZIP

Muchos sets se distribuyen como un único ZIP enorme. El tipo `zip_index` no lo descarga: el índice de un ZIP vive al final del archivo, así que con unas pocas peticiones de rango se obtiene la lista de lo que contiene y luego solo los bytes del juego que falta. Sobre un ZIP real de 112 MB en archive.org, listar sus 329 entradas y extraer un archivo transfirió **0,29 MB, el 0,26% del total**.

Además, el índice de un ZIP guarda el CRC32 de cada entrada, así que el emparejamiento con el DAT sale **por hash** en vez de por nombre, que es la diferencia entre "creo que es este" y "es este".

```bash
retroperfect rom-source-add --id set --label "Set completo" --kind zip_index \
  --location https://ejemplo.org/nes-set.zip --platform nes
```

Requiere que el servidor admita descargas parciales (`Accept-Ranges: bytes`); si no, lo dice claramente en vez de bajarse el archivo entero por sorpresa. Con un ZIP en disco o en el NAS funciona igual pasando su ruta.

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

**Hashes RetroAchievements soportados**: cartuchos (hash directo), NES/FDS/SNES/Lynx/Atari 7800/PC Engine (descarte de cabeceras), N64 (normalización de endianness), Nintendo DS (cabecera + ARM9 + ARM7 + icono), arcade (por nombre de set) y sistemas de disco — PSX (ejecutable de SYSTEM.CNF), Sega CD/Saturn (cabecera del disco) y PSP (PARAM.SFO + EBOOT.BIN) sobre imágenes `.iso`, `.bin` y `.cue`. CHD, GDI multipista y CDI quedan pendientes.

## Parches soportados

IPS, BPS, UPS, PPF 2.0/3.0 y xdelta/VCDIFF, sueltos o dentro de ZIP, con verificación de CRC/MD5 del resultado. (APS y RUP todavía no.)

## Aplicación de escritorio

Cada tag `v*` publica automáticamente los paquetes de Windows, macOS y Linux en [Releases](https://github.com/ruvelro/RetroPerfect/releases): un `.app` en macOS y una carpeta con el ejecutable en el resto. Para construirlo localmente:

```bash
./scripts/build-app.sh
```

## Desarrollo

```bash
pip install -e ".[dev]"
pytest -q            # 108 tests
ruff check src tests # lint
mypy                 # type-checking estricto en verde
```

La CI ejecuta las tres cosas en Python 3.11, 3.12 y 3.13.

## Hoja de ruta

**Distribución más cómoda** (evita los avisos de seguridad de la primera ejecución):

- **Publicar en PyPI** para que baste `pipx install retroperfect`, sin clonar ni pegar URLs de GitHub. Requiere una cuenta de PyPI y un token guardado como secreto del repositorio; el workflow de publicación se añadiría al de release.
- **Tap de Homebrew** (`brew install ruvelro/retroperfect/retroperfect`), como fórmula de Python: al compilarse en local no pasa por Gatekeeper, así que no da ningún aviso y sirve para macOS y Linux. Lo natural es hacerlo después de PyPI, porque entonces la fórmula se genera casi sola con `brew update-python-resources`. Entrar en el repositorio oficial de Homebrew exige unos mínimos de popularidad, así que el primer paso es un tap propio.
- **Firmar y notarizar los binarios** eliminaría los avisos de macOS y Windows, pero es la única vía de pago: unos 99 $/año en Apple y entre 200 y 400 $/año un certificado para Windows.

**Funcionalidad**: hash de RetroAchievements para CHD y CDI (falta un lector mantenido de esos formatos), parches RUP, y firma de los binarios en la propia CI.

## Aviso

RetroPerfect no incluye, distribuye ni enlaza ROMs, y no trae ninguna fuente de descarga preconfigurada. Está pensado para gestionar copias de seguridad de tu propia colección. Los DATs se descargan de fuentes públicas (espejo Libretro) o los importas tú desde DAT-o-MATIC/Redump. Si usas la pestaña Descargar, las fuentes las añades tú y eres responsable de que su contenido sea legal en tu jurisdicción.
