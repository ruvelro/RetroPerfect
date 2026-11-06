"""RetroPerfect package."""

# Única fuente de verdad de la versión: hatchling la lee de aquí (`dynamic`
# en pyproject.toml) y el workflow de release comprueba el tag contra ella.
# Tenerla también en pyproject hacía que se desincronizaran, y el User-Agent
# de las descargas —que sale de este valor— se quedaba en una versión vieja.
__version__ = "0.6.0"
