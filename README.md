# RetroPerfect

[![CI](https://github.com/ruvelro/RetroPerfect/actions/workflows/ci.yml/badge.svg)](https://github.com/ruvelro/RetroPerfect/actions/workflows/ci.yml)

**RetroPerfect** te ayuda a convertir una colección de ROMs desordenada en una colección perfecta: verificada contra DATs oficiales (No-Intro, Redump, MAME, FBNeo), sin duplicados, con la mejor versión de cada juego según tus preferencias de región e idioma, y preparada para [RetroAchievements](https://retroachievements.org).

Funciona en local, con interfaz gráfica y línea de comandos. **No incluye ni enlaza ROMs**: trabaja con los archivos que ya tienes y, si configuras tus propias fuentes, puede completar lo que falte descargándolo de ellas y verificándolo contra el DAT antes de tocar tu colección.

![Estado](https://img.shields.io/badge/estado-en%20desarrollo-yellow) ![Python](https://img.shields.io/badge/python-3.11%2B-blue)

---

## ¿Qué hace?

- **Escanea** tu colección (archivos sueltos, ZIP y 7z) y la identifica por hash contra un DAT oficial: sabrás qué tienes de verdad, no lo que dicen los nombres de archivo.
- **Audita** con `verify`: juegos que te faltan, archivos que no pertenecen al set, ROMs mal nombradas, duplicados y sets mixtos (el disco 1 de una región junto al disco 2 de otra).
- **Cura** con perfiles 1G1R (*1 Game 1 ROM*): de 5 copias de un juego (Japón, USA, Europa, beta, hack...) conserva solo la que prefieras, con reglas de prioridad por región e idioma explicables — cada decisión viene con su motivo.
- **RetroAchievements**: marca qué ROMs de tu colección son compatibles con logros, y si una no lo es, puede localizar y aplicar el parche oficial automáticamente.
- **Aplica el plan con red de seguridad**: verificación MD5 byte a byte de cada archivo copiado o movido, comprobaciones previas de espacio y colisiones, y papelera restaurable en vez de borrados.
- **Prepara la colección para jugarla**: exporta la playlist de RetroArch (`.lpl`) o el `gamelist.xml` de EmulationStation/Batocera con el nombre del DAT y el CRC ya verificados, y descarga las carátulas oficiales de Libretro.
- **Completa lo que falta** desde las fuentes que tú configures (tu NAS, un ítem de archive.org, un índice HTTP): descarga solo los juegos ausentes según el DAT y tu perfil, y verifica cada archivo por hash antes de instalarlo. RetroPerfect no trae ninguna fuente preconfigurada.

## Seguridad ante todo

Tu colección son años de trabajo. RetroPerfect está diseñado para no perder nunca un archivo:

| Protección | Qué hace |
|---|---|
| **Plan revisable** | Nada se toca sin un manifiesto que puedes inspeccionar antes de aplicar |
| **Verificación MD5** | Cada copia/movimiento se verifica byte a byte contra el original |
| **Detección de cambios** | Si un archivo cambió desde el escaneo, la operación se detiene |
| **Preflight** | Comprueba espacio en disco, orígenes desaparecidos y colisiones antes de empezar |
| **Destino intacto** | Si en la salida ya hay un archivo distinto con ese nombre, se detiene en vez de pisarlo (`--overwrite` para reemplazarlo); si es el mismo, se omite, así que repetir un plan no duplica trabajo |
| **Papelera** | "Borrar" mueve a `.retroperfect/trash/` con restauración en un comando |
| **Journal** | Cada aplicación queda registrada en `.retroperfect/applied/` (incluidos los fallos parciales) |
| **Se puede retomar** | Si cortas una aplicación a medias (o falla), al volver a aplicar se omite lo que ya estaba hecho en vez de bloquearse |
| **Cancelable** | El escaneo y la aplicación se cortan desde la interfaz entre archivos, nunca a mitad de uno: no quedan copias truncadas |

Si el romset y la carpeta de salida están en la misma unidad, `apply --link` crea **enlaces duros** en vez de copiar: la colección curada no ocupa espacio extra (útil sobre todo con las salidas `main` y `ra`, que suelen compartir archivos). Se sigue comprobando que el origen no cambió desde el escaneo; lo que no hay es copia que verificar, porque el archivo es el mismo. Si las carpetas están en unidades distintas, se copia con normalidad.

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

### Dónde guarda su estado

RetroPerfect trabaja sobre una carpeta `.retroperfect/` (escaneos, planes, caché de hashes, papelera e informes) dentro del directorio desde el que lo lanzas, que es lo natural si usas la terminal en la carpeta de tu colección.

La **app de escritorio** no tiene ese directorio: al abrirla con doble clic hereda uno que no eliges tú (en macOS, la raíz del disco), así que usa una carpeta propia dentro de los datos de la aplicación. El botón **Abrir carpeta del proyecto**, en la pestaña Actividad, te lleva a ella.

Si quieres fijarla a mano —para tener varias colecciones separadas, o para que la app trabaje donde tú digas— usa la variable `RETROPERFECT_HOME`:

```bash
RETROPERFECT_HOME=~/colecciones/nes retroperfect scan --platform nes --input ~/roms/nes
```

### Idioma

La interfaz está en español y en inglés. Se elige en el desplegable de la
cabecera, con la variable `RETROPERFECT_LANG`, o al arrancar:

```bash
retroperfect gui --lang en
```

Sin indicar nada usa el idioma del sistema y, si no lo reconoce, el español.
Cambiar el idioma recarga la página: la interfaz se construye una sola vez, así
que traducir en caliente cada elemento ya dibujado sería mucho más código para
el mismo resultado.

**Qué está traducido y qué no**: la interfaz gráfica, completa (hay un test que
falla si se añade un texto sin traducir). La línea de comandos sigue en español,
porque su ayuda se construye al importar el módulo y habría que fijar el idioma
antes de eso. Y los motivos de cada decisión que se guardan en el manifiesto se
quedan en español a propósito: son **datos**, no presentación — un plan escrito
en un idioma y leído en otro dejaría de cuadrar. Traducirlos bien pide guardar
un código de motivo junto al texto, que es un cambio del modelo.

### Exponerla en la red

La interfaz es local y **no pide credenciales**: quien llegue al puerto puede explorar tus carpetas con el selector de archivos y borrar archivos. Por eso solo escucha en `127.0.0.1`, y publicarla en la red exige decirlo explícitamente:

```bash
retroperfect gui --host 0.0.0.0 --allow-remote
```

Sin `--allow-remote` no arranca y explica por qué. Hazlo solo en una red en la que confíes.

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

# 3b. Nota de salud, cobertura y avisos, todo junto
retroperfect audit --platform nes --input ~/roms/nes --dat ruta/al/dat.xml

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

Hay cinco tipos de fuente:

| Tipo | Origen | Notas |
| --- | --- | --- |
| `archive_org` | identificador o URL de un ítem de archive.org | trae tamaño y md5/crc32, así que el emparejamiento es por hash |
| `http_index` | URL de un autoíndice de Apache/nginx | empareja por nombre; la verificación sigue siendo por hash tras descargar |
| `local_dir` | carpeta local, NAS o unidad de red montada | ideal para restaurar desde tu propia copia de seguridad |
| `zip_index` | ruta o URL de un ZIP que contiene el set | lee su índice **sin descargarlo entero** y extrae solo los juegos que faltan |
| `torrent` | archivo `.torrent` | la descarga la hace tu cliente; RetroPerfect elige qué archivos y verifica lo que llega |

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

Antes de empezar se comprueba que lo planificado cabe en el destino. Sin `--confirm` solo se muestra el plan. `--all-variants` desactiva el filtro del perfil y planifica todas las variantes del DAT; `--limit N` acota la tanda; `--refresh` fuerza releer los índices remotos (se cachean 12 h). Las descargas HTTP se reanudan solas si se cortan, y respetan el `Retry-After` del servidor.

En la GUI, todo esto vive en la pestaña **Descargar**: gestiona las fuentes, muestra el plan con una etiqueta de cómo se emparejó cada archivo (por hash, por nombre exacto o aproximado), lista aparte los juegos que ninguna fuente ofrece, y permite marcar filas para bajar solo esas.

#### Sets empaquetados en un solo ZIP

Muchos sets se distribuyen como un único ZIP enorme. El tipo `zip_index` no lo descarga: el índice de un ZIP vive al final del archivo, así que con unas pocas peticiones de rango se obtiene la lista de lo que contiene y luego solo los bytes del juego que falta. Sobre un ZIP real de 112 MB en archive.org, listar sus 329 entradas y extraer un archivo transfirió **0,29 MB, el 0,26% del total**.

Además, el índice de un ZIP guarda el CRC32 de cada entrada, así que el emparejamiento con el DAT sale **por hash** en vez de por nombre, que es la diferencia entre "creo que es este" y "es este".

```bash
retroperfect rom-source-add --id set --label "Set completo" --kind zip_index \
  --location https://ejemplo.org/nes-set.zip --platform nes
```

Requiere que el servidor admita descargas parciales (`Accept-Ranges: bytes`); si no, lo dice claramente en vez de bajarse el archivo entero por sorpresa. Con un ZIP en disco o en el NAS funciona igual pasando su ruta.

#### Torrent

Un `.torrent` lleva dentro su lista de archivos, así que sirve de índice sin descargar nada ni conectarse a nadie. Y BitTorrent permite descargar solo algunos archivos de un torrent, que es exactamente lo que hace falta.

RetroPerfect **no descarga el torrent**: eso lo hace tu cliente. Lo que aporta es elegir qué archivos y verificar lo que llega.

```bash
# Ver qué archivos del torrent te faltan (no toca nada)
retroperfect torrent-queue --torrent set.torrent --dat nes.dat --scan .retroperfect/scans/latest.json

# Con qBittorrent: lo añade con solo esos archivos seleccionados
retroperfect torrent-queue --torrent set.torrent --dat nes.dat \
  --scan .retroperfect/scans/latest.json --queue

# Con cualquier cliente: cuando termine, verifica y copia al romset
retroperfect torrent-collect --torrent set.torrent --dat nes.dat \
  --downloads ~/Descargas/torrents --dest ./romset
```

Con **qBittorrent** la selección es automática vía su Web API (actívala en sus ajustes). Con **cualquier otro cliente** —Transmission, Deluge, rTorrent…— el flujo es el mismo: `torrent-queue` te dice qué archivos marcar, los marcas a mano, y `torrent-collect` hace el resto sin saber ni preguntar quién lo descargó. Si tu qBittorrent pide credenciales, pásalas por las variables `RETROPERFECT_QBT_USER` y `RETROPERFECT_QBT_PASS`; no se guardan en ningún archivo.

En la **interfaz gráfica** no hace falta la terminal: al registrar una fuente de tipo `torrent` aparece el panel **Torrent** al final de la pestaña Descargar, con los mismos dos pasos — seleccionar en qBittorrent los archivos que te faltan y, cuando tu cliente termine, recoger lo descargado verificándolo contra el DAT.

Dos detalles que conviene saber:

- **No apuntes tu cliente al romset.** `torrent-collect` **copia**, no mueve, precisamente para que el cliente siga sembrando desde su carpeta, y para que en tu colección solo entre lo verificado. Los archivos a medias se detectan por tamaño y los que no cuadran con el DAT no pasan.
- Un torrent se divide en **piezas** de tamaño fijo, y una pieza puede cruzar dos archivos. Si una ROM que quieres comparte pieza con una que no, bajarás de propina ese trozo del vecino. Poco, pero no exactamente cero.

### Un romset de varios sistemas, de una pasada

Todo el flujo asumía una plataforma por comando, así que una colección con nueve
sistemas eran nueve invocaciones. `curate` recorre las carpetas del romset,
deduce la plataforma de cada una por su nombre, busca el DAT instalado que le
corresponde y hace el trabajo de siempre con cada una:

```bash
retroperfect curate --root ~/roms --output-dir ~/roms-curadas --confirm
```

Reconoce los nombres habituales (`nes`, `SFC`, `psx`, `megadrive`, `Sega Genesis`,
`Arcade`...), y lo que **no** reconoce no lo adivina: una carpeta con un nombre
que no cuadra, o una plataforma sin DAT instalado, se reporta diciendo por qué
en vez de curarse con el DAT equivocado. Cada sistema va a su subcarpeta de la
salida, y `--platforms nes,snes` acota la pasada.

### Curar dentro de los ZIP

Copiar un contenedor se lleva también lo que haya dentro. Si tu ZIP trae las tres
regiones de un juego, con el 1G1R te quedas con una… y las tres viajan igual. Por
eso `plan` acepta `--containers`:

| Modo | Qué hace |
|---|---|
| `keep` (por defecto) | Copia el contenedor tal cual, como siempre |
| `extract` | Saca del contenedor solo lo que el plan conserva, como archivo suelto |
| `rezip` | Escribe un ZIP nuevo por juego, con solo sus archivos y los nombres del DAT |
| `torrentzip` | Igual, pero **canónico**: el mismo contenido da siempre el mismo archivo |

```bash
retroperfect plan --scan .retroperfect/scans/latest.json --output-dir ~/roms-curadas \
  --containers rezip
```

Con `rezip`, un juego de varios archivos (un `.cue` y sus pistas) va entero a su
ZIP, y **dentro los nombres son los del DAT**: es lo que hace que dos
colecciones curadas con el mismo DAT salgan iguales. También sirve al revés,
para comprimir una colección de archivos sueltos.

Cada archivo se verifica por MD5 **antes** de entrar en el ZIP nuevo, así que un
contenedor que haya cambiado desde el escaneo detiene el plan en vez de colarse
dentro; si el ZIP de destino ya existe con otro contenido, no se pisa. En la
interfaz es un desplegable en la pestaña **Plan**.

### Arreglar los nombres

`verify` te dice qué archivos no se llaman como dice el DAT; esto los arregla
donde están, sin mover nada:

```bash
retroperfect rename --platform nes --input ~/roms/nes --dat nes.dat --confirm
```

Sin `--confirm` solo lista qué cambiaría. El nombre sale de la entrada del DAT
que casa con el **hash** de cada archivo, así que cada pista de un juego de
varios discos recibe el suyo. **La extensión no se toca** (un `.chd` no pasa a
llamarse `.bin`), nada se sobrescribe, y los que están dentro de un ZIP se
omiten diciéndolo: habría que reempaquetar el contenedor. En la interfaz vive en
la pestaña **Verificar**, al lado de donde se reportan.

### Llenar una SD, una consola o un disco

«Llena esta tarjeta de 32 GB con lo mejor que tengo»:

```bash
retroperfect sync-device --scan .retroperfect/scans/latest.json \
  --dest /Volumes/SDCARD --budget 32GB --confirm
```

No es un camino aparte: es **el mismo plan de curación, acotado por tamaño**.
Por eso hereda todo lo que ya había — 1G1R con motivos explicables, carpetas por
región, playlists de varios discos, verificación por MD5, omitir lo que ya está
y deshacer.

Dos detalles que lo hacen útil de verdad:

- **La unidad es el juego, no el archivo.** Un juego de tres discos entra con los
  tres o no entra: medio juego ocupa sitio y no se puede terminar.
- **Un juego grande que no cabe no corta la lista**: se salta y se sigue con el
  siguiente, así que un solo juego de 8 GB no te deja la tarjeta medio vacía.

`--order` decide quién entra primero: `size` (los pequeños, para que caigan más
juegos; es el valor por defecto), `name` o `ra` (primero los que tienen logros).
El presupuesto admite `32GB` y `32GiB` porque las tarjetas se venden en GB
decimales y el sistema las mide en GiB. En la interfaz está al final de la
pestaña **Plan**.

### Qué ha cambiado en mi colección

```bash
retroperfect scan-diff --before .retroperfect/scans/<id>.json
```

Compara dos escaneos. Lo que importa aquí no son las altas y las bajas, que se
ven mirando la carpeta, sino los archivos **cuyo hash cambió sin cambiar de
nombre**: corrupción en disco, una descarga que pisó otra, un parche aplicado
por error. Eso es lo que nadie nota. Un archivo que solo cambió de sitio se
reporta como movido, no como alta más baja.

### Deshacer

```bash
retroperfect undo            # qué se desharía
retroperfect undo --confirm  # hacerlo
```

Toma la última aplicación registrada y la invierte al revés: borra lo que se
copió, devuelve lo que se movió y saca de la papelera lo que se borró. **No se
toca nada que hayas cambiado después**: cada operación guarda el MD5 de lo que
escribió y, si el archivo ya no es ese, se omite y se dice. Lo borrado con
`--hard-delete` no se puede recuperar, y también se dice. En la interfaz está en
la pestaña **Actividad**, junto a la papelera.

### La caché de hashes

Re-escanear cientos de GB cuesta horas, así que la caché se puede salvar:

```bash
retroperfect cache-export --output cache.json
retroperfect cache-import cache.json
retroperfect cache-clear --confirm
```

Si la colección cambia de unidad o de punto de montaje, `--rebase` reapunta las
rutas sin rehashear nada (mover dentro del mismo sistema de archivos conserva la
fecha de modificación, que es lo que valida la caché):

```bash
retroperfect cache-import cache.json --rebase /Volumes/viejo=/Volumes/nuevo
```

Por lo mismo, llevarse la caché a **otra máquina** con otras rutas no sirve de
nada: el propio comando te dice cuántas entradas puede reutilizar.

### Llevarla al emulador

Cuando la colección está curada, el último paso es que tu frontend la vea bien. RetroPerfect escribe directamente lo que consume, con el nombre que dice el DAT y el CRC que ya calculó, en vez de dejar que el frontend la re-escanee con su propia base de datos:

```bash
# Playlist de RetroArch (los juegos de varios discos se listan por su .m3u)
retroperfect export --platform ps1 --scan .retroperfect/scans/latest.json \
  --manifest .retroperfect/manifests/latest.json --format lpl

# gamelist.xml de EmulationStation / Batocera
retroperfect export --platform ps1 --scan .retroperfect/scans/latest.json \
  --manifest .retroperfect/manifests/latest.json --format gamelist --output ~/roms/psx/gamelist.xml

# metadata.pegasus.txt de Pegasus Frontend (el de muchas portátiles caseras)
retroperfect export --platform ps1 --scan .retroperfect/scans/latest.json \
  --manifest .retroperfect/manifests/latest.json --format pegasus
```

Con `--thumbnails <carpeta>` el `gamelist.xml` enlaza además la carátula de cada juego, emparejada por el nombre exacto del DAT.

El `gamelist.xml` **se fusiona, nunca se sobrescribe**: ahí viven tus favoritos y tus horas jugadas, que RetroPerfect no puede recuperar si los pierde. Sin `--manifest` se listan las rutas actuales; con él, las de la colección curada.

### Carátulas

```bash
retroperfect thumbnails --platform ps1 --dat psx.dat --scan .retroperfect/scans/latest.json --dest ~/thumbnails
```

No es scraping: los thumbnails de Libretro están nombrados **exactamente** igual que las entradas de No-Intro y Redump, así que el emparejamiento es por nombre exacto del DAT, sin clave de API, sin cuenta y sin adivinar títulos parecidos. Lo que Libretro no tenga se reporta como `ausente`; nunca se descarga una carátula aproximada. Con `--kinds boxart,snap,title` bajas también capturas y pantallas de título, y con `--manifest` solo las de lo que tu plan conserva. `--retroarch` las guarda dentro de la subcarpeta del sistema, que es donde RetroArch las busca.

### Lo que te falta, en un DAT

```bash
retroperfect fixdat --platform ps1 --dat psx.dat --scan .retroperfect/scans/latest.json
```

Genera un DAT con **solo lo que te falta** (y de los juegos a medias, solo las ROMs ausentes): es el formato de intercambio del mundillo, para pasárselo a otra herramienta o a quien pueda completarte el set.

### Papelera

```bash
retroperfect trash-list                    # sesiones de borrado, con tamaño
retroperfect trash-restore 20260813-181500 # restaura a las rutas originales
retroperfect trash-empty --confirm         # vaciado definitivo
```

En la interfaz gráfica, la papelera vive al final de la pestaña **Actividad** (no en Plan: restaurar es recuperarse de algo ya hecho, así que no exige tener el Setup validado ni un escaneo). Selecciona la sesión y pulsa *Restaurar sesión*; lo que no se pueda devolver porque el original ya existe se avisa en el registro en vez de pisarlo.

### Si algo va mal

```bash
retroperfect doctor
```

Resume en una tabla la versión, el sistema, dónde escribe, qué formatos puede
leer (CHD, 7z, xdelta) y qué tienes configurado. Es lo primero que hace falta
para reproducir un fallo, y se puede pegar tal cual en un issue: no incluye tu
clave de API. `retroperfect --version` da solo el número.

## Conceptos en 60 segundos

- **DAT**: catálogo oficial de hashes de un sistema (No-Intro para cartuchos, Redump para discos, MAME/FBNeo para arcade). Es la "verdad" contra la que se verifica todo.
- **1G1R**: de cada juego, una sola *variante*. RetroPerfect agrupa las variantes (por Parent/Clone del DAT o por título) y elige la mejor según tu perfil.
- **Juegos de varias piezas**: un juego de Redump son varios archivos (un `.cue` y sus `.bin`) y puede ocupar varios discos. Elegir una variante se lleva **todos** sus archivos y **todos** sus discos; los discos no compiten entre sí. Si a tu región preferida le falta un disco pero otra está completa, se queda la completa: mezclar discos de regiones distintas suele impedir que el juego arranque.
- **Playlists `.m3u`**: los juegos de varios discos se exportan con su playlist, en orden. No es cosmético: los emuladores guardan la partida contra el nombre del `.m3u`, así que sin ella cada disco tiene su propio save y el juego no se puede terminar. Aparecen en el plan y se pueden revisar antes de aplicar.
- **Perfil**: tus reglas — prioridad de regiones (`Spain > Europe > World > USA > Japan`), de idiomas, exclusión de betas/hacks/bad dumps, preferencia por revisiones nuevas... Hay perfiles recomendados listos para usar (`--profile "1G1R + RA"`, `--profile "España/Europa"`...), y `--profile` también acepta el nombre de uno guardado o la ruta de un `.yaml`/`.json`.
- **Salidas**: `main` (tu colección 1G1R) y `ra` (variantes compatibles con RetroAchievements). Con el layout *organizado*, la salida se estructura en carpetas `EUR/`, `USA/`, `JPN/`, `Otros/...`.
- **Manifiesto**: el plan de operaciones (copiar/mover/borrar) que revisas antes de aplicar. Se guarda en `.retroperfect/manifests/`.

## Plataformas

Más de 190 sistemas catalogados, desde NES hasta Dreamcast, pasando por ordenadores clásicos (Amiga, MSX, ZX Spectrum...), portátiles y arcade (MAME, FBNeo, CPS, Neo Geo...). Cada plataforma incluye su DAT recomendado, extensiones esperadas y diagnósticos específicos (cabeceras NES, endianness N64, variantes A78/BIN, sets arcade con parents/clones/BIOS/CHD).

**Hashes RetroAchievements soportados**: cartuchos (hash directo), NES/FDS/SNES/Lynx/Atari 7800/PC Engine (descarte de cabeceras), N64 (normalización de endianness), Nintendo DS (cabecera + ARM9 + ARM7 + icono), arcade (por nombre de set) y sistemas de disco — PSX (ejecutable de SYSTEM.CNF), Sega CD/Saturn (cabecera del disco) y PSP (PARAM.SFO + EBOOT.BIN) sobre imágenes `.iso`, `.bin`, `.cue` y `.chd` de CD. Los CHD de GDI (Dreamcast) o DVD, los GDI multipista y el formato CDI quedan pendientes.

**CHD**: un CHD de CD se identifica contra el DAT por el sha1 de cada pista (los mismos que lista Redump, sin descomprimirlo a disco), así que `verify` y la curación 1G1R lo tratan como a cualquier `.bin/.cue` — y el hash de RetroAchievements se calcula leyendo sus sectores directamente.

## Parches soportados

IPS, BPS, UPS, APS, PPF 2.0/3.0 y xdelta/VCDIFF, sueltos o dentro de ZIP, con verificación de CRC/MD5 del resultado. (RUP todavía no.)

## Aplicación de escritorio

Cada tag `v*` publica automáticamente los paquetes de Windows, macOS y Linux en [Releases](https://github.com/ruvelro/RetroPerfect/releases): un `.app` en macOS y una carpeta con el ejecutable en el resto. Para construirlo localmente:

```bash
./scripts/build-app.sh
```

## Desarrollo

```bash
pip install -e ".[dev]"
pytest -q            # 596 tests
ruff check src tests # lint
mypy                 # type-checking estricto en verde
```

La CI ejecuta las tres cosas en Python 3.11, 3.12, 3.13 y 3.14, con una puerta
de cobertura al 80 % (la real está en el 82 %). Si prefieres que salte antes del
commit, `pip install pre-commit && pre-commit install` deja las mismas
comprobaciones enganchadas.

Cómo contribuir y qué se espera de un cambio: [CONTRIBUTING.md](CONTRIBUTING.md).
Historial de versiones: [CHANGELOG.md](CHANGELOG.md). Para avisar de un problema
de seguridad: [SECURITY.md](SECURITY.md).

## Hoja de ruta

**Distribución más cómoda** (evita los avisos de seguridad de la primera ejecución):

- **Publicar en PyPI** para que baste `pipx install retroperfect`, sin clonar ni pegar URLs de GitHub. El workflow de publicación ya está en el release (vía *Trusted Publishing*, sin tokens); solo falta registrar el publicador de confianza en pypi.org y crear el environment `pypi` en GitHub. Desde ese momento, cada tag `v*` publica también en PyPI.
- **Tap de Homebrew** (`brew install ruvelro/retroperfect/retroperfect`), como fórmula de Python: al compilarse en local no pasa por Gatekeeper, así que no da ningún aviso y sirve para macOS y Linux. Lo natural es hacerlo después de PyPI, porque entonces la fórmula se genera casi sola con `brew update-python-resources`. Entrar en el repositorio oficial de Homebrew exige unos mínimos de popularidad, así que el primer paso es un tap propio.
- **Firmar y notarizar los binarios** eliminaría los avisos de macOS y Windows, pero es la única vía de pago: unos 99 $/año en Apple y entre 200 y 400 $/año un certificado para Windows.

**Funcionalidad**: los CHD de GDI (Dreamcast) y de DVD (PS2/PSP) cuando [chdimage](https://pypi.org/project/chdimage/) los soporte upstream. CDI sigue sin lector mantenido. También: parches RUP y firma de los binarios en la propia CI.

## Aviso

RetroPerfect no incluye, distribuye ni enlaza ROMs, y no trae ninguna fuente de descarga preconfigurada. Está pensado para gestionar copias de seguridad de tu propia colección. Los DATs se descargan de fuentes públicas (espejo Libretro) o los importas tú desde DAT-o-MATIC/Redump. Si usas la pestaña Descargar, las fuentes las añades tú y eres responsable de que su contenido sea legal en tu jurisdicción.
