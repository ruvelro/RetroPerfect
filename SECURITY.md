# Seguridad

## Qué versiones reciben arreglos

La última publicada en [Releases](https://github.com/ruvelro/RetroPerfect/releases).
El proyecto es anterior a la 1.0.0 y no se mantienen ramas de versiones viejas.

## Cómo avisar de un problema

Usa el [aviso privado de GitHub](https://github.com/ruvelro/RetroPerfect/security/advisories/new).
No abras un issue público para algo explotable.

Si no puedes usar esa vía, abre un issue diciendo solo que has encontrado algo y
pidiendo un canal privado, sin detalles.

## Qué cuenta como vulnerabilidad aquí

RetroPerfect es una herramienta local que lee archivos de terceros (DATs y
romsets descargados de internet) y escribe en carpetas del usuario. Interesa
especialmente:

- **Escritura fuera de las carpetas previstas.** Nombres de archivo que vienen de
  una fuente remota (metadatos de archive.org, el índice de un ZIP, la lista de
  archivos de un `.torrent`) se reducen a su nombre base, y las rutas de lectura
  se comprueban contra la carpeta de descargas. Si encuentras una vía para
  escribir o leer fuera, es un fallo de seguridad.
- **Archivos de entrada hostiles.** Un DAT, un ZIP, un 7z, un `.torrent` o una
  imagen de disco malformados no deben agotar la memoria ni ejecutar nada. Los
  DAT con entidades XML propias se rechazan y las entradas 7z se extraen por
  tandas acotadas, pero el resto de lectores puede tener huecos.
- **Pérdida de datos.** Cualquier camino por el que se borre o sobrescriba un
  archivo del usuario sin pasar por el manifiesto, la verificación por hash y la
  papelera.
- **Filtración de credenciales.** La clave de API de RetroAchievements se guarda
  con permisos `0600` y se oculta en los mensajes de error; las de qBittorrent
  solo viven en variables de entorno. Si aparecen en un log, en un informe o en
  una URL, avisa.

## Lo que ya se sabe y no es un fallo

- **La interfaz no tiene usuarios ni contraseñas.** Está pensada para escuchar
  solo en `127.0.0.1`. Publicarla en la red exige pasar `--allow-remote`, y ahí
  cualquiera que llegue al puerto puede explorar carpetas y borrar archivos: es
  la consecuencia de activarlo, no un fallo.
- **Los binarios no están firmados ni notarizados.** De ahí los avisos de macOS
  y Windows en la primera ejecución. Firmar cuesta entre 99 y 400 $ al año.
- **El contenido de las fuentes que configure el usuario es su responsabilidad.**
  El programa verifica cada archivo contra el DAT, pero no juzga su legalidad.
