# Registro de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Las versiones siguen [SemVer](https://semver.org/lang/es/), con la salvedad de
que hasta la 1.0.0 una menor puede traer cambios incompatibles.

La versión vive en `src/retroperfect/__init__.py`, que es de donde la leen
`pyproject.toml` y el workflow de release.

## [Sin publicar]

Auditoría completa del proyecto y corrección de sus hallazgos.

### Corregido

- La versión del paquete estaba en dos sitios y se desincronizó (0.4.0 frente a
  0.6.0): el User-Agent de las descargas anunciaba una versión vieja. Ahora
  `pyproject.toml` la lee del módulo.
- `gamelist.xml` escribía la ruta de cada juego sin su carpeta, así que con la
  salida *organizada* —la de todos los perfiles recomendados— EmulationStation
  y Batocera no encontraban ni un juego. Las entradas planas que dejó el fallo
  se reapuntan al migrar, en vez de duplicar el juego.
- Aplicar un plan sobrescribía en silencio los archivos que ya hubiera en la
  carpeta de salida. Ahora se detiene y lo explica; `--overwrite` (o la casilla
  equivalente en la pestaña Plan) autoriza el reemplazo. Con enlaces duros
  fallaba además a mitad del plan con un error sin capturar.
- Las regiones Korea, Denmark, Norway, Finland, Portugal, Poland, Russia,
  Canada y otras no se reconocían: esas ROMs quedaban como "región desconocida"
  y perdían el 1G1R sin motivo visible. `Multi5`/`M3` tampoco contaban como
  multiidioma, ni dos idiomas cualesquiera (`(Es,Ca)`).
- `--profile` solo aceptaba `default` o la ruta de un archivo, así que los
  perfiles recomendados que anuncia el README y los guardados desde la interfaz
  no se podían usar desde la línea de comandos.
- Las imágenes de disco dentro de un ZIP o un 7z se quedaban sin hash de
  RetroAchievements y salían como incompatibles con logros aunque no lo fueran.
- Dos entradas del DAT que declaran la misma ROM ya no se pisan en el índice: el
  juego con el que casaba un archivo dependía del orden del archivo.
- La aplicación empaquetada escribía su estado en el directorio que heredaba al
  abrirse con doble clic (en macOS, la raíz del disco), donde no tiene permiso.
- Un DAT ilegible o con entidades XML propias salía como traceback.
- En un sistema sin idioma configurado (`LANG=C.UTF-8`, lo habitual en un
  contenedor) la interfaz abría en inglés o en español según la versión de
  Python: la 3.11 interpretaba ese locale como `en_US` y las siguientes no.
  Sin preferencia declarada se usa el idioma de origen.

### Añadido

- **Interfaz en inglés**, además del español: desplegable en la cabecera,
  `--lang` y `RETROPERFECT_LANG`. Las 399 cadenas de la interfaz gráfica están
  traducidas y un test falla si se añade una sin traducir. La línea de comandos
  y los motivos guardados en el manifiesto siguen en español a propósito (ver
  README).
- `retroperfect curate --root ~/roms`: cura un romset de varios sistemas de una
  pasada, deduciendo la plataforma de cada carpeta. Lo que no reconoce no lo
  adivina: lo reporta.
- `export --format pegasus` para Pegasus Frontend, y `thumbnails --retroarch`
  para dejar las carátulas donde RetroArch las busca.
- `retroperfect sync-device --budget 32GB`: llena una SD, una consola o un disco
  con lo que quepa. Es el mismo plan de curación acotado por tamaño, así que
  hereda la verificación y el deshacer; la unidad es el juego entero y uno
  grande que no cabe no corta la lista.
- `plan --containers torrentzip`: ZIP canónico, con las entradas ordenadas, la
  fecha fija del formato y la firma `TORRENTZIPPED-`. El mismo contenido da
  siempre el mismo archivo, así que la colección se puede verificar o compartir
  por hash del contenedor.
- `plan --containers extract|rezip`: curar dentro de los ZIP y 7z. Copiar el
  contenedor se llevaba también los descartes de dentro y no había forma de
  reempaquetar; ahora se puede extraer solo lo que el plan conserva o escribir
  un ZIP por juego con los nombres del DAT. Cada archivo se verifica por MD5
  antes de entrar, y un ZIP de destino con otro contenido no se pisa.
- `retroperfect rename`: arregla donde están los archivos que no se llaman como
  dice el DAT. El nombre sale de la entrada que casa con el hash de cada
  archivo, se conserva la extensión, nada se sobrescribe y los que viven dentro
  de un ZIP se omiten diciéndolo. También en la pestaña Verificar.
- `retroperfect scan-diff`: compara dos escaneos y, sobre todo, señala los
  archivos cuyo hash cambió sin cambiar de nombre.
- `retroperfect undo`: invierte una aplicación registrada en el journal, sin
  tocar nada que se haya cambiado después. También en la pestaña Actividad.
- `retroperfect cache-export`, `cache-import` (con `--rebase` para una colección
  que cambia de sitio) y `cache-clear`.
- `export --format gamelist --thumbnails <carpeta>` enlaza las carátulas ya
  descargadas en el `gamelist.xml`.
- `retroperfect --version` y `retroperfect doctor`, que resume el estado de la
  instalación para pegarlo en un informe de fallo.
- El escaneo y la aplicación se pueden cancelar desde la interfaz, entre
  archivos y nunca a mitad de uno, con barra de progreso al aplicar.
- Una aplicación interrumpida se puede retomar: lo ya hecho se omite en vez de
  bloquear el plan entero con "Origen no encontrado".
- La descarga comprueba que lo planificado cabe en el destino antes de empezar.
- `--allow-remote`: la interfaz no pide credenciales, así que publicarla en la
  red exige decirlo explícitamente.
- `RETROPERFECT_HOME` para fijar la carpeta de trabajo.

### Cambiado

- Leer un DAT de 40.000 juegos pasa de 21 s y 134 MB a 7 s y 88 MB.
- El escaneo guardado pesa 3,2 veces menos: los juegos del DAT se escriben una
  vez y no una por ROM. Los escaneos del formato anterior se siguen leyendo.
- Normalizar la endianness de una ROM de N64 es 133 veces más rápido.
- Una consulta a la caché de RetroAchievements por plataforma en vez de una por
  ROM, y una lectura de la tabla de parches por plan en vez de una por grupo.
- Los 7z se extraen por tandas con un presupuesto de memoria.
- La salida de la línea de comandos y los motivos de cada decisión están
  íntegramente en español.
- Los nombres de archivo que vienen de una fuente remota se reducen a su nombre
  base, y los DAT con entidades XML propias se rechazan.

## [0.6.0] y [0.5.0] — versionadas pero sin publicar

El número se subió en el código y nunca se etiquetó, así que no hay release ni
paquete de estas dos. Lo que traen: exportación a frontends (`.lpl` de RetroArch
y `gamelist.xml`), carátulas de Libretro, `fixdat`, playlists `.m3u` y enlaces
duros al aplicar, el tratamiento del juego como unidad (los discos y los
archivos de un mismo juego dejan de competir en el 1G1R), soporte de CHD de CD
verificado por pistas, y la preparación de la publicación en PyPI con Trusted
Publishing.

## [0.4.0] — 2026-08-14

- El torrent como fuente de romsets, con qBittorrent integrado y cualquier otro
  cliente por igual.

## [0.3.1] — 2026-08-14

- El ZIP como fuente, leyendo su índice por rangos sin descargarlo entero.

## [0.3.0] — 2026-08-14

- Descarga de romsets desde fuentes que configura el usuario, verificando cada
  archivo contra el DAT antes de instalarlo.
- Selección de filas, fuentes que se pueden silenciar y User-Agent derivado de
  la versión.

## [0.2.2] — 2026-08-14

- La aplicación se puede cerrar desde su propia interfaz, que es la única vía en
  el `.app` de macOS.

## [0.2.1] — 2026-08-14

- macOS se empaqueta como `.app`; se amplía la compatibilidad en Linux y se
  reescribe la guía de instalación.

## [0.2.0] — 2026-08-13

- Pestaña Verificar en la interfaz.
- Actualizador de DATs instalados, con aviso de antigüedad.

## [0.1.0] — 2026-08-13

Primera versión pública: escaneo por hash contra DATs de No-Intro, Redump, MAME
y FBNeo, curación 1G1R con perfiles explicables, soporte de RetroAchievements,
parches IPS/BPS/UPS/APS/PPF/xdelta, papelera restaurable, journal de cada
aplicación, informes en JSON/CSV/HTML y paquetes de escritorio para Windows,
macOS y Linux.
