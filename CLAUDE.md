# Integracion_Termo_Solar

Repositorio de la integración custom de Home Assistant "Termo Solar"
(dominio `termo_solar`) de Maxi: decide cuándo calentar el termo eléctrico
(sol que sobra → Valle → respaldo de la tarde). Sustituye a las
automatizaciones del termo. Es la **fuente de verdad** del código y la
fuente desde la que HACS la instala.

Es **público** a propósito, porque HACS no lee repos privados. Por eso:

- **Nunca** subir datos reales de casa (consumos, horarios, precios). Las
  pruebas y la documentación usan valores inventados.
- Las comprobaciones con datos reales se hacen en el scratchpad de la sesión.

## Entorno

- Repo local: `~/Downloads/GitHub/Integracion_Termo_Solar`
- HA real por Samba: `/Volumes/config` (cómo montarlo, en la skill
  `home-assistant-casa`).
- Esta sesión puede hacer `git push` directamente (credenciales de `gh`,
  cuenta MaxiBass); el flujo y las reglas están en `~/.claude/CLAUDE.md`.
  Antes, revisar que el diff no lleve datos personales: el repo es público.
- **HACS sigue commits, no versiones** (no hay releases): para instalar sin
  la interfaz, `update.install` sobre la entidad `update.*` de la
  integración con `version` = hash **corto** del commit.

## Estructura

```
custom_components/termo_solar/
  plan.py         la decisión (sin Home Assistant): decidir(), previsión
  gestor.py       lee entradas, llama a plan, manda al interruptor, aprende, disco
  __init__.py     alta y baja de la entrada
  sensor.py       estado, motivo, energía, temperatura a la ducha, aprendido
  binary_sensor.py  «Orden de calentar»
  switch.py       «Control» (apagado = simulación)
  number.py, time.py  ajustes del día a día
  entity.py       base de las entidades y dispositivo
  config_flow.py  alta y Configurar (solo las entidades de origen)
  diagnostics.py  diagnóstico descargable
  strings.json, translations/, icons.json
  brand/          icono propio (HA lo lee de aquí al arrancar)
docs/DECISIONES.md  por qué es así; NO va en custom_components
docs/icono/generar.py  dibuja brand/icon.png e icon@2x.png
tests/test_termo_solar.py
```

## Antes de tocar nada, lee `docs/DECISIONES.md`

- No cambiar los `entity_id` ni los `unique_id` (§8).
- El objetivo sale del ayudante de Maxi si está configurado (§7): no
  duplicarlo.
- Los umbrales del ICP y de la sonda atascada (§3) son decisión de Maxi.
- Cualquier cosa que encienda el termo exige dato de la sonda.
- Lo aprendido vive en `.storage/termo_solar` (§5).

## Flujo para editar

1. Editar en el repo, dentro de `custom_components/termo_solar/`.
2. Pasar las pruebas (abajo).
3. Commit y push (revisando antes el diff, ver `~/.claude/CLAUDE.md`).
4. Subir la `version` de `manifest.json` cuando esté listo para probar.
5. Actualizar desde HACS (o `update.install`) y reiniciar HA (preguntando).

No copiar directamente en `/Volumes/config/custom_components/termo_solar`
sin editar antes en el repo.

## Pruebas

```bash
python3 -m venv /tmp/hav
/tmp/hav/bin/pip install homeassistant==2026.11.0 pillow
/tmp/hav/bin/python tests/test_termo_solar.py
```

El venv de `/tmp` lo borra a medias la limpieza de macOS; si `import
homeassistant` falla, recrearlo con `python3 -m venv --clear /tmp/hav`.
