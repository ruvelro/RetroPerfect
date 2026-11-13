# Cómo contribuir

Gracias por querer echar una mano. Esto no es un formulario: es lo que hace
falta saber para que un cambio entre sin romper colecciones de nadie.

## Lo primero: el proyecto no distribuye ROMs

RetroPerfect no incluye, enlaza ni trae preconfigurada ninguna fuente de ROMs, y
no va a hacerlo. Un *pull request* que añada un catálogo de espejos, un enlace a
un sitio de descargas o una fuente por defecto se cierra sin más discusión:
convertiría una herramienta neutral en un cliente de piratería y expondría el
repositorio. Las fuentes las configura quien usa el programa, y responde de su
contenido.

## Montar el entorno

```bash
git clone https://github.com/ruvelro/RetroPerfect.git
cd RetroPerfect
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Hace falta Python 3.11 o superior.

## Antes de abrir un PR

Las tres cosas que ejecuta la CI, en este orden:

```bash
ruff check src tests
```

```bash
mypy
```

```bash
pytest -q --cov=retroperfect --cov-fail-under=80
```

La cobertura tiene una puerta al 80 %. Está por debajo de la real a propósito:
es una red contra retrocesos, no un número que perseguir en cada cambio.

Y una cuarta que no está en la CI y es la que más fallos ha destapado en este
proyecto: **probar a mano lo que has tocado**. Varios de los errores más
importantes pasaron la suite en verde y solo aparecieron al abrir la interfaz o
al ejecutar el comando de verdad.

## Lo que se espera de un cambio

- **Un test que falle antes y pase después.** Si el cambio corrige algo, el test
  tiene que fijar el comportamiento correcto, no el que había.
- **Comentarios que expliquen el *por qué*.** El código ya dice *qué* hace. Lo
  que no se puede recuperar leyéndolo es la razón: qué se intentó antes, qué
  rompió, qué decisión se tomó. Hay bastantes ejemplos en el código.
- **Nada que toque archivos sin plan previo.** Toda operación destructiva pasa
  por un manifiesto revisable, verificación por hash y papelera restaurable. Un
  cambio que salte ese camino no entra.
- **Español.** El código, los comentarios, los mensajes al usuario y los tests
  están en español. Los nombres de las cosas del dominio (DAT, 1G1R, parent/clone,
  headered) se dejan como se llaman en el mundillo.

## Rendimiento

`tests/test_performance.py` mide **trabajo** (consultas, extracciones,
expresiones regulares, bytes) y no tiempo, porque los umbrales de reloj aquí son
inestables. Si optimizas algo, deja un candado de ese estilo; si un cambio tuyo
lo rompe, es que ha vuelto a hacer el trabajo que se había quitado.

## Informar de un fallo

Pega la salida de `retroperfect doctor`: trae versión, sistema, carpetas,
formatos soportados y configuración, que es lo primero que hace falta para
reproducir cualquier cosa. No incluye tu clave de API.

Si el fallo tiene que ver con una colección concreta, di la plataforma, de dónde
viene el DAT y el nombre exacto de los archivos implicados (no hace falta
mandarlos).
