"""Pruebas de Termo Solar. Se ejecutan sin pytest:

    /tmp/hav/bin/python tests/test_termo_solar.py

Tres bloques: los ficheros estáticos, la decisión pura (`plan.py`) con casos
hechos a mano, y un Home Assistant real (el del venv) en un directorio
temporal con la integración enlazada en `custom_components/`. Las entradas
son estados puestos a mano y el reloj de la integración se mueve desde la
prueba.

Todos los valores son inventados (termo de 2000 W, 4000 W contratados):
este repositorio es público.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import json
import logging
import shutil
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
BASE = RAIZ / "custom_components" / "termo_solar"
DOMINIO = "termo_solar"
MADRID = ZoneInfo("Europe/Madrid")

fallos: list[str] = []


def comprobar(condicion: bool, etiqueta: str) -> None:
    if condicion:
        print(f"  OK    {etiqueta}")
    else:
        print(f"  FALLO {etiqueta}")
        fallos.append(etiqueta)


def casi(a: float, b: float, tolerancia: float = 1e-3) -> bool:
    return abs(a - b) <= tolerancia


SENSORES = ("estado", "motivo", "energia_necesaria", "temperatura_ducha", "excedente",
            "sol_sobrante", "energia_hoy", "kwh_por_grado", "consumo_casa")
NUMEROS = ("objetivo", "maxima_solar", "minima_ducha", "potencia", "margen_prevision")
HORAS = ("hora_ducha", "hora_respaldo", "fin_valle")
ENTIDADES = (
    [f"sensor.termo_solar_{k}" for k in SENSORES]
    + [f"number.termo_solar_{k}" for k in NUMEROS]
    + [f"time.termo_solar_{k}" for k in HORAS]
    + ["binary_sensor.termo_solar_orden", "switch.termo_solar_control"]
)


# ── Ficheros estáticos ───────────────────────────────────────────────


def test_ficheros() -> None:
    print("\nManifest, traducciones e icono")
    manifest = json.loads((BASE / "manifest.json").read_text("utf-8"))
    comprobar(
        "github.com/MaxiBass/" in manifest.get("documentation", "") and "issue_tracker" in manifest,
        "manifest apunta al repo (documentation, issue_tracker)",
    )
    comprobar(manifest.get("single_config_entry") is True, "una sola entrada por instalación")
    comprobar(manifest.get("requirements") == [], "sin dependencias externas")

    es = json.loads((BASE / "translations" / "es.json").read_text("utf-8"))
    en = json.loads((BASE / "translations" / "en.json").read_text("utf-8"))
    cadenas = json.loads((BASE / "strings.json").read_text("utf-8"))

    def claves(d: dict, prefijo: str = "") -> set[str]:
        salida = set()
        for k, v in d.items():
            salida |= claves(v, f"{prefijo}{k}.") if isinstance(v, dict) else {f"{prefijo}{k}"}
        return salida

    comprobar(claves(es) == claves(en), "es.json y en.json tienen las mismas claves")
    comprobar(es == cadenas, "strings.json coincide con es.json")
    comprobar(es != en, "en.json no es una copia de es.json")

    iconos = json.loads((BASE / "icons.json").read_text("utf-8"))["entity"]
    esperado = {
        "sensor": set(SENSORES), "number": set(NUMEROS), "time": set(HORAS),
        "binary_sensor": {"orden"}, "switch": {"control"},
    }
    comprobar(
        {d: set(v) for d, v in iconos.items()} == {d: set(v) for d, v in es["entity"].items()} == esperado,
        "cada entidad tiene nombre e icono",
    )
    from custom_components.termo_solar import plan
    from custom_components.termo_solar.const import AJUSTES_POR_DEFECTO, FUENTES, NUMEROS as LIMITES

    comprobar(set(es["entity"]["sensor"]["estado"]["state"]) == set(plan.ACCIONES),
              "todos los estados del sensor «Estado» están traducidos")
    campos = set(es["config"]["step"]["user"]["data"])
    comprobar(campos == set(FUENTES) | {"capacidad_bateria"} == set(es["options"]["step"]["init"]["data"]),
              "el formulario tiene texto para cada campo, en el alta y en Configurar")
    comprobar(all(LIMITES[k][0] <= AJUSTES_POR_DEFECTO[k] <= LIMITES[k][1] for k in LIMITES),
              "los valores por defecto caben en los límites de sus entidades")
    hacs = json.loads((RAIZ / "hacs.json").read_text("utf-8"))
    comprobar(bool(hacs.get("homeassistant")), "hacs.json indica la versión mínima de HA")

    from PIL import Image

    tamanos = {}
    for nombre in ("icon.png", "icon@2x.png"):
        ruta = BASE / "brand" / nombre
        tamanos[nombre] = Image.open(ruta).size if ruta.exists() else None
    comprobar(tamanos == {"icon.png": (256, 256), "icon@2x.png": (512, 512)},
              f"icono propio en brand/ con los tamaños de HA {tamanos}")


# ── La decisión pura ─────────────────────────────────────────────────


def _hora(texto: str, dia: str = "2026-11-18") -> datetime:
    """Hora local de Madrid (el 18/11/2026 es miércoles)."""
    return datetime.fromisoformat(f"{dia}T{texto}").replace(tzinfo=MADRID)


def _tramos(kw: float, desde: int = 8, hasta: int = 18, dia: str = "2026-11-18"):
    """Previsión plana de `kw` en medias horas entre dos horas."""
    return [(_hora(f"{h:02d}:{m:02d}", dia), kw) for h in range(desde, hasta) for m in (0, 30)]


def test_plan() -> None:
    from custom_components.termo_solar import plan
    from custom_components.termo_solar.plan import Ajustes, Lectura, Memoria, decidir

    def ajustes(**cambios) -> Ajustes:
        base = dict(objetivo=50.0, maxima_solar=60.0, minima_ducha=40.0, potencia=2000.0,
                    margen_prevision=15.0, capacidad_bateria=10.0)
        return Ajustes(**{**base, **cambios})

    def lectura(hora: str, **cambios) -> Lectura:
        base = dict(temperatura=30.0, encendido=False, fv=0.0, consumo=300.0, soc=50.0,
                    periodo="llano", laborable=True, kwh_por_grado=0.1)
        return Lectura(ahora=_hora(hora), **{**base, **cambios})

    print("\nDecisión: lo imprescindible")
    d = decidir(lectura("12:00", temperatura=None, fv=5000.0), ajustes(), Memoria())
    comprobar(d.accion == plan.SIN_DATOS and not d.calentar, "sin sonda no se calienta, aunque sobre sol")
    m = Memoria()
    decidir(lectura("12:00", fv=5000.0, red_conectada=False), ajustes(), m)
    d = decidir(lectura("12:03", fv=5000.0, red_conectada=False), ajustes(), m)
    comprobar(d.accion == plan.ESPERANDO and not d.calentar and "red" in d.motivo, "sin red eléctrica no se enciende")
    comprobar(casi(plan.temperatura_prevista(50.0, 3), 22 + 28 * 2.718281828 ** (-0.054)),
              "el agua parada pierde el 1,8 % por hora de lo que le saca al ambiente")
    comprobar(plan.temperatura_prevista(50.0, -2) == 50.0 and plan.temperatura_prevista(20.0, 5) == 20.0,
              "la previsión no inventa: ni hacia atrás ni por debajo del ambiente")

    print("\nDecisión: sol")
    m, a = Memoria(), ajustes()
    d = decidir(lectura("12:00", fv=2500.0), a, m)
    comprobar(d.accion == plan.ESPERANDO and d.datos["excedente"] == 2200 and "dos minutos" in d.motivo,
              "con excedente recién aparecido espera a que aguante")
    d = decidir(lectura("12:01:30", fv=2500.0), a, m)
    comprobar(not d.calentar, "a los 90 s todavía no enciende")
    d = decidir(lectura("12:02", fv=2500.0), a, m)
    comprobar(d.accion == plan.SOL and d.calentar and d.consigna == 50.0,
              "a los 2 min enciende con sol, hasta el objetivo (la batería no está llena)")
    d = decidir(lectura("12:02:30", fv=2500.0, consumo=2300.0, encendido=True), a, m)
    comprobar(d.calentar and d.datos["excedente"] == 2200,
              "el consumo del propio termo no cuenta como consumo de la casa")
    # Nube: de 12:03 a 12:07.
    for hora in ("12:03", "12:05", "12:06:30"):
        d = decidir(lectura(hora, fv=500.0, consumo=2300.0, encendido=True), a, m)
    comprobar(d.calentar, "una nube de 3 min y medio no apaga un termo que lleva menos de 5 min encendido")
    d = decidir(lectura("12:07", fv=500.0, consumo=2300.0, encendido=True), a, m)
    comprobar(d.accion == plan.ESPERANDO and not d.calentar, "sin sol 3 min y con 5 min encendido, apaga")
    decidir(lectura("12:07:30", fv=2500.0), a, m)
    d = decidir(lectura("12:09:30", fv=2500.0), a, m)
    comprobar(not d.calentar and "espera" in d.motivo, "vuelve el sol, pero no reenciende antes de 5 min")
    d = decidir(lectura("12:12", fv=2500.0), a, m)
    comprobar(d.accion == plan.SOL and d.calentar, "pasados 5 min apagado, vuelve a encender con sol")
    d = decidir(lectura("12:40", fv=2500.0, consumo=2300.0, encendido=True, temperatura=50.0), a, m)
    comprobar(not d.calentar, "al llegar al objetivo para (batería sin llenar: ese sol es para ella)")
    d = decidir(lectura("12:45", fv=2500.0, temperatura=48.5), a, m)
    comprobar(not d.calentar and "no hace falta" in d.motivo, "no reenciende por 1,5 °C (histéresis de 3)")

    m = Memoria()
    decidir(lectura("13:00", fv=2500.0, temperatura=52.0, soc=98.0), a, m)
    d = decidir(lectura("13:02", fv=2500.0, temperatura=52.0, soc=98.0), a, m)
    comprobar(d.accion == plan.SOL and d.consigna == 60.0,
              "con la batería llena sigue con sol hasta la máxima (se iba a exportar)")
    d = decidir(lectura("13:30", fv=2500.0, consumo=2300.0, encendido=True, temperatura=60.0, soc=98.0), a, m)
    comprobar(not d.calentar, "y para en la máxima")
    m = Memoria()
    decidir(lectura("13:00", fv=2500.0, temperatura=52.0, soc=None), ajustes(capacidad_bateria=0.0), m)
    d = decidir(lectura("13:02", fv=2500.0, temperatura=52.0, soc=None), ajustes(capacidad_bateria=0.0), m)
    comprobar(d.consigna == 60.0, "sin batería, todo el sol que sobra va hasta la máxima")
    m = Memoria()
    decidir(lectura("12:00", fv=None), a, m)
    d = decidir(lectura("12:05", fv=None), a, m)
    comprobar(not d.calentar and "Faltan datos" in d.motivo, "sin dato de las placas no hay modo sol")

    print("\nDecisión: previsión del día")
    l = lectura("05:00", periodo="valle", prevision=_tramos(1.0))
    p = plan.prevision_del_dia(l, a, 2.0)
    comprobar(p["decision"] == plan.VALLE and casi(p["sol_kwh"], 8.5) and casi(p["casa_kwh"], 4.0)
              and casi(p["hueco_bateria_kwh"], 5.0) and casi(p["sobra_kwh"], -2.5),
              "10 kWh previstos − 15 % − 4 de casa − 5 de batería − 2 de termo: no sobra → Valle")
    p = plan.prevision_del_dia(lectura("05:00", prevision=_tramos(3.0)), a, 2.0)
    comprobar(p["decision"] == plan.SOL and casi(p["horas_con_sol"], 8.0), "con 3 kW todo el día sobra → sol")
    p = plan.prevision_del_dia(lectura("05:00", prevision=_tramos(2.2)), a, 2.0)
    comprobar(p["decision"] == plan.VALLE and p["sobra_kwh"] > 0 and p["horas_con_sol"] == 0,
              "sobra energía pero ninguna media hora cubre el termo entero → Valle")
    p = plan.prevision_del_dia(lectura("05:00", prevision=_tramos(3.0, 16, 18)), a, 2.0)
    comprobar(p["horas_con_sol"] == 0, "el sol posterior a la hora del respaldo no cuenta como potencia")
    p = plan.prevision_del_dia(lectura("12:00", prevision=_tramos(3.0)), a, 2.0)
    comprobar(casi(p["sol_kwh"], 3.0 * 0.85 * 6), "solo cuenta el sol que queda desde ahora")
    p = plan.prevision_del_dia(lectura("05:00", prevision=_tramos(3.0, dia="2026-11-19")), a, 2.0)
    comprobar(p["sol_kwh"] == 0, "los tramos de otro día no cuentan")
    p = plan.prevision_del_dia(lectura("05:00", prevision_kwh=20.0), a, 2.0)
    comprobar(p["decision"] == plan.SOL and casi(p["sol_kwh"], 17.0) and casi(p["casa_kwh"], 3.2),
              "sin tramos usa el total del día y el consumo de 9 a 17")
    p = plan.prevision_del_dia(lectura("05:00"), a, 2.0)
    comprobar(p["decision"] == plan.VALLE and "no hay previsión" in p["motivo"], "sin previsión, Valle")
    perfil = [400.0] * 24
    perfil[12] = 1400.0
    p = plan.prevision_del_dia(lectura("05:00", prevision=_tramos(3.0), perfil_casa=perfil), a, 2.0)
    comprobar(casi(p["casa_kwh"], 5.0) and casi(p["horas_con_sol"], 7.0),
              "usa el consumo aprendido de cada hora (una hora cara quita sol al termo)")

    print("\nDecisión: Valle")
    mala = _tramos(1.0)
    m = Memoria()
    d = decidir(lectura("03:00", periodo="valle", prevision=mala), a, m)
    comprobar(not d.calentar and "prevision" not in d.datos, "5 h antes del fin del Valle aún no decide")
    d = decidir(lectura("04:30", periodo="valle", prevision=mala), a, m)
    comprobar(not d.calentar and "06:44" in d.motivo and d.datos["prevision"]["decision"] == plan.VALLE,
              "decide Valle y espera a lo más tarde posible (2 kWh a 2 kW + 10 % + 10 min → 06:44)")
    d = decidir(lectura("06:43", periodo="valle", prevision=mala), a, m)
    comprobar(not d.calentar, "a las 06:43 aún espera")
    d = decidir(lectura("06:44", periodo="valle", prevision=mala), a, m)
    comprobar(d.accion == plan.VALLE and d.calentar and d.consigna == 50.0, "a las 06:44 calienta en Valle")
    d = decidir(lectura("07:00", periodo="valle", prevision=_tramos(3.0), encendido=True, consumo=2300.0), a, m)
    comprobar(d.accion == plan.VALLE and d.calentar, "una previsión mejor a medias no lo corta: lo empezado se acaba")
    d = decidir(lectura("07:50", periodo="valle", prevision=mala, encendido=True, temperatura=50.0), a, m)
    comprobar(not d.calentar, "para al llegar al objetivo")
    m = Memoria()
    decidir(lectura("07:00", periodo="valle", prevision=mala), a, m)
    d = decidir(lectura("08:00", periodo="llano", prevision=mala, encendido=True, temperatura=40.0), a, m)
    comprobar(not d.calentar, "para al acabar el Valle aunque no haya llegado")
    m = Memoria()
    d = decidir(lectura("07:30", periodo="valle", prevision=_tramos(3.0)), a, m)
    comprobar(not d.calentar and d.motivo.startswith("No se calienta en Valle"), "si va a sobrar sol, no calienta en Valle")
    d = decidir(lectura("07:30", periodo="valle"), a, Memoria())
    comprobar(d.accion == plan.VALLE, "sin previsión, calienta en Valle")
    d = decidir(lectura("07:30", periodo="valle", prevision=mala, laborable=False), a, Memoria())
    comprobar(not d.calentar, "un festivo no calienta de madrugada (todo el día es Valle)")
    d = decidir(lectura("07:30", periodo="llano", prevision=mala), a, Memoria())
    comprobar(not d.calentar, "si el sensor no dice Valle, no hay modo Valle")
    d = decidir(lectura("07:30", periodo="valle", prevision=mala, temperatura=48.0), a, Memoria())
    comprobar(not d.calentar, "con el agua a 2 °C del objetivo no merece la pena")

    print("\nDecisión: respaldo de la tarde")
    d = decidir(lectura("15:59", temperatura=35.0), a, Memoria())
    comprobar(not d.calentar, "antes de la hora del respaldo no actúa")
    m = Memoria()
    d = decidir(lectura("16:00", temperatura=35.0), a, m)
    comprobar(d.accion == plan.RESPALDO and d.calentar and d.consigna == 50.0 and d.datos["prevista_ducha"] < 40,
              "a la hora del respaldo, si a la ducha no llega al mínimo, calienta con la red")
    d = decidir(lectura("17:00", temperatura=45.0, encendido=True), a, m)
    comprobar(d.calentar, "sigue hasta el objetivo, no solo hasta el mínimo")
    d = decidir(lectura("18:00", temperatura=47.0, encendido=True, periodo="punta"), a, m)
    comprobar(not d.calentar, "al entrar la Punta, para")
    m = Memoria()
    decidir(lectura("16:00", temperatura=35.0), a, m)
    d = decidir(lectura("17:10", temperatura=50.0, encendido=True), a, m)
    comprobar(not d.calentar, "para al llegar al objetivo")
    d = decidir(lectura("16:30", temperatura=35.0, periodo="punta"), a, Memoria())
    comprobar(not d.calentar and "Punta" in d.motivo, "en Punta no hay respaldo, y lo dice")
    d = decidir(lectura("16:30", temperatura=42.0), a, Memoria())
    comprobar(not d.calentar, "si a la ducha va a haber más del mínimo, no calienta")
    d = decidir(lectura("19:05", temperatura=30.0), a, Memoria())
    comprobar(not d.calentar, "pasada la hora de la ducha no empieza un respaldo")
    d = decidir(lectura("16:30", temperatura=35.0, periodo="valle", laborable=False), a, Memoria())
    comprobar(d.accion == plan.RESPALDO, "en festivo el respaldo completa con la red (a precio Valle)")

    print("\nDecisión: potencia contratada")
    m = Memoria()
    d = decidir(lectura("16:00", temperatura=35.0, red=3000.0, contratada=4000.0), a, m)
    comprobar(d.accion == plan.PAUSA_ICP and not d.calentar and m.modo == plan.RESPALDO,
              "no arranca si red + termo pasa de 1,1 veces la contratada")
    decidir(lectura("16:05", temperatura=35.0, red=2000.0, contratada=4000.0), a, m)
    d = decidir(lectura("16:06", temperatura=35.0, red=2000.0, contratada=4000.0), a, m)
    comprobar(d.accion == plan.PAUSA_ICP, "cuando cabe, espera 2 min antes de volver")
    d = decidir(lectura("16:07", temperatura=35.0, red=2000.0, contratada=4000.0), a, m)
    comprobar(d.accion == plan.RESPALDO and d.calentar, "a los 2 min de caber, vuelve")
    d = decidir(lectura("16:08", temperatura=36.0, encendido=True, red=4500.0, contratada=4000.0), a, m)
    comprobar(d.calentar, "una sobrecarga moderada (1,125) se aguanta…")
    d = decidir(lectura("16:17:30", temperatura=37.0, encendido=True, red=4500.0, contratada=4000.0), a, m)
    comprobar(d.calentar, "…menos de 10 min")
    d = decidir(lectura("16:18", temperatura=37.0, encendido=True, red=4500.0, contratada=4000.0), a, m)
    comprobar(d.accion == plan.PAUSA_ICP and not d.calentar, "a los 10 min de sobrecarga moderada, pausa")
    m = Memoria()
    decidir(lectura("16:00", temperatura=35.0, red=500.0, contratada=4000.0), a, m)
    d = decidir(lectura("16:01", temperatura=35.0, encendido=True, red=6100.0, contratada=4000.0), a, m)
    comprobar(d.accion == plan.PAUSA_ICP, "por encima de 1,5 veces la contratada, pausa al instante")
    d = decidir(lectura("16:02", temperatura=35.0, encendido=True, red=6100.0, contratada=4000.0), a, m)
    d = decidir(lectura("16:30", temperatura=35.0, encendido=True, red=1000.0, contratada=4000.0), a, m)
    comprobar(d.accion == plan.PAUSA_ICP, "no da por bueno el hueco mientras el termo siga encendido")
    d = decidir(lectura("18:00", temperatura=35.0, red=3000.0, contratada=4000.0, periodo="punta"), a, m)
    comprobar(d.accion == plan.ESPERANDO and not m.pausa_icp, "si el modo se acaba, la pausa también")
    d = decidir(lectura("16:00", temperatura=35.0, red=3000.0, contratada=None), a, Memoria())
    comprobar(d.calentar, "sin potencia contratada no hay vigilancia del ICP")

    print("\nDecisión: sonda atascada y encendido a mano")
    m = Memoria()
    cambio = _hora("16:00")
    decidir(lectura("16:00", temperatura=35.0, temperatura_cambio=cambio), a, m)
    d = decidir(lectura("16:59", temperatura=35.0, temperatura_cambio=cambio, encendido=True), a, m)
    comprobar(d.calentar, "59 min sin cambiar la sonda aún no es avería")
    d = decidir(lectura("17:00", temperatura=35.0, temperatura_cambio=cambio, encendido=True), a, m)
    comprobar(d.accion == plan.SONDA and not d.calentar, "una hora calentando sin que cambie la sonda: se da por atascada")
    d = decidir(lectura("17:05", temperatura=35.0, temperatura_cambio=cambio), a, m)
    comprobar(d.accion == plan.SONDA, "y sigue así mientras no cambie")
    d = decidir(lectura("17:06", temperatura=35.4, temperatura_cambio=_hora("17:06")), a, m)
    comprobar(d.accion == plan.RESPALDO, "en cuanto la sonda cambia, vuelve a lo suyo")

    m = Memoria()
    d = decidir(lectura("21:00", temperatura=55.0, encendido=True, control=True, manual=True), a, m)
    comprobar(d.accion == plan.MANUAL and d.calentar and d.consigna == 60.0,
              "un encendido a mano se respeta hasta la máxima")
    d = decidir(lectura("21:20", temperatura=60.0, encendido=True, control=True, manual=True), a, m)
    comprobar(not d.calentar, "al llegar a la máxima, lo apaga")
    d = decidir(lectura("21:00", temperatura=55.0, encendido=True, control=False, manual=True), a, Memoria())
    comprobar(d.accion == plan.ESPERANDO, "en simulación no hay «manual»: el termo lo llevan otros")

    print("\nDecisión: la memoria se guarda y se recupera")
    m = Memoria()
    decidir(lectura("16:00", temperatura=35.0), a, m)
    copia = Memoria.desde_dict(json.loads(json.dumps(m.a_dict())))
    comprobar(copia.modo == plan.RESPALDO and copia.calentando and copia.encendido_en == m.encendido_en,
              "la memoria sobrevive a pasar por JSON (modo, estado y horas)")
    comprobar(Memoria.desde_dict({"modo": "sol", "inventada": 1, "encendido_en": "no es una hora"}).modo == "sol",
              "una memoria guardada con claves raras no rompe el arranque")


# ── Home Assistant real ──────────────────────────────────────────────


class _Registros(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.mensajes: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.mensajes.append(f"{record.name}: {record.getMessage()}")


class Reloj:
    def __init__(self, inicio: datetime) -> None:
        self.t = inicio


async def _arrancar_hass(directorio: Path):
    from homeassistant import bootstrap, config_entries, core, loader
    from homeassistant.core_config import async_process_ha_core_config
    from homeassistant.setup import async_setup_component

    hass = core.HomeAssistant(str(directorio))
    loader.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await loader.async_get_custom_components(hass)
    assert await bootstrap.async_load_base_functionality(hass)
    for dominio in bootstrap.CORE_INTEGRATIONS:
        assert await async_setup_component(hass, dominio, {}), dominio
    await async_process_ha_core_config(hass, {"time_zone": "Europe/Madrid"})
    hass.set_state(core.CoreState.running)
    return hass


TERMO = "input_boolean.termo"
FUENTES = {
    "interruptor": "switch.termo_boiler",
    "temperatura": "sensor.termo_boiler_temperature",
    "fv": "sensor.deye_pv_total_power",
    "consumo": "sensor.deye_load_power",
    "red": "sensor.deye_grid_ct_power",
    "contratada": "sensor.potencia_contratada_actual",
    "soc": "sensor.deye_battery_soc",
    "periodo": "sensor.periodo_tarifario",
    "laborable": "binary_sensor.dia_laborable",
    "prevision": "sensor.solcast_pv_forecast_pronostico_hoy",
    "red_conectada": "binary_sensor.deye_grid_connected",
}


async def _recorrido(directorio: Path) -> None:
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    import custom_components.termo_solar.gestor as modulo_gestor
    from custom_components.termo_solar import plan

    registros = _Registros()
    logging.getLogger().addHandler(registros)
    hass = await _arrancar_hass(directorio)
    reloj = Reloj(_hora("11:00"))
    modulo_gestor._ahora = lambda: reloj.t

    # Un interruptor de mentira: los servicios cambian su estado y se cuentan.
    ordenes: list[str] = []

    async def _servicio(llamada) -> None:
        ordenes.append(llamada.service)
        for entity_id in llamada.data["entity_id"] if isinstance(llamada.data["entity_id"], list) else [llamada.data["entity_id"]]:
            hass.states.async_set(entity_id, "on" if llamada.service == "turn_on" else "off")

    # En `input_boolean`, que la integración no carga: `switch` es de verdad
    # (lo usa el interruptor «Control»).
    hass.services.async_register("input_boolean", "turn_on", _servicio)
    hass.services.async_register("input_boolean", "turn_off", _servicio)

    def fuente(clave: str, valor, unidad: str | None = None, **atributos) -> None:
        if unidad:
            atributos["unit_of_measurement"] = unidad
        hass.states.async_set(FUENTES[clave], str(valor), atributos)

    def estado(entity_id: str):
        return hass.states.get(entity_id)

    def gestor():
        return hass.config_entries.async_entries(DOMINIO)[0].runtime_data

    async def avanzar(minutos: float) -> None:
        """Pasa el tiempo de 30 en 30 s, como el ciclo real."""
        for _ in range(round(minutos * 2)):
            reloj.t += timedelta(seconds=30)
            gestor().async_actualizar()
            await hass.async_block_till_done()

    async def ajustar(dominio: str, clave: str, valor) -> None:
        campo = "time" if dominio == "time" else "value"
        await hass.services.async_call(
            dominio, "set_value", {"entity_id": f"{dominio}.termo_solar_{clave}", campo: valor}, blocking=True
        )

    try:
        fuente("interruptor", "off")
        hass.states.async_set(TERMO, "off")
        fuente("temperatura", 30.0, "°C")
        fuente("fv", 0, "W")
        fuente("consumo", 300, "W")
        fuente("red", 300, "W")
        fuente("contratada", 4000, "W")
        fuente("soc", 50, "%")
        fuente("periodo", "Llano")
        fuente("laborable", "on")
        fuente("red_conectada", "on")
        fuente("prevision", 10.0, "kWh", detailedForecast=[
            {"period_start": inicio.isoformat(), "pv_estimate": kw} for inicio, kw in _tramos(1.0)
        ])
        await hass.async_block_till_done()

        print("\n  · alta por el formulario")
        flujo = await hass.config_entries.flow.async_init(DOMINIO, context={"source": "user"})
        sugeridos = {str(k): (k.description or {}).get("suggested_value") for k in flujo["data_schema"].schema}
        comprobar(all(sugeridos.get(k) == v for k, v in FUENTES.items()),
                  "el formulario sale relleno con las entidades de casa que existen")
        # El termo de la prueba es el interruptor de mentira.
        FUENTES["interruptor"] = TERMO
        datos = {**FUENTES, "capacidad_bateria": 10.0}
        r = await hass.config_entries.flow.async_configure(flujo["flow_id"], {**datos, "fv": FUENTES["consumo"]})
        comprobar(r["type"] == "form" and r["errors"] == {"base": "misma_entidad"}, "no admite la misma entidad en dos campos")
        sin_contratada = {k: v for k, v in datos.items() if k != "contratada"}
        r = await hass.config_entries.flow.async_configure(flujo["flow_id"], sin_contratada)
        comprobar(r["errors"] == {"contratada": "falta_pareja"}, "red y potencia contratada van juntas")
        sin_soc = {k: v for k, v in datos.items() if k != "soc"}
        r = await hass.config_entries.flow.async_configure(flujo["flow_id"], sin_soc)
        comprobar(r["errors"] == {"soc": "falta_soc"}, "con batería pide el sensor de carga")
        r = await hass.config_entries.flow.async_configure(flujo["flow_id"], datos)
        await hass.async_block_till_done()
        entrada = hass.config_entries.async_entries(DOMINIO)[0]
        comprobar(r["type"] == "create_entry" and entrada.state is ConfigEntryState.LOADED, "la entrada se crea y carga")
        r = await hass.config_entries.flow.async_init(DOMINIO, context={"source": "user"})
        comprobar(r["type"] == "abort", "no deja dar de alta una segunda")

        registro = er.async_get(hass)
        comprobar(all(estado(e) is not None for e in ENTIDADES), "están todas las entidades, con su entity_id fijo")
        comprobar(len(er.async_entries_for_config_entry(registro, entrada.entry_id)) == len(ENTIDADES),
                  "y ninguna más")
        dispositivos = dr.async_entries_for_config_entry(dr.async_get(hass), entrada.entry_id)
        comprobar(len(dispositivos) == 1 and dispositivos[0].name == "Termo Solar", "un solo dispositivo")
        comprobar(estado("switch.termo_solar_control").state == "off", "empieza en simulación (Control apagado)")
        # Ajustes de la prueba: termo de 2000 W, objetivo 50, mínima 40.
        for clave, valor in (("potencia", 2000), ("objetivo", 50), ("minima_ducha", 40)):
            await ajustar("number", clave, valor)
        comprobar(entrada.options["potencia"] == 2000.0 and entrada.state is ConfigEntryState.LOADED
                  and gestor().ajustes().potencia == 2000.0,
                  "los ajustes se cambian desde sus entidades, se guardan y no recargan")

        print("\n  · simulación: decide pero no toca el termo")
        await avanzar(1)
        comprobar(estado("sensor.termo_solar_estado").state == "esperando"
                  and estado("binary_sensor.termo_solar_orden").state == "off"
                  and "Esperando al sol" in estado("sensor.termo_solar_motivo").state,
                  "sin sol, espera y dice por qué")
        comprobar(casi(float(estado("sensor.termo_solar_energia_necesaria").state), 1.8)
                  and float(estado("sensor.termo_solar_temperatura_ducha").state) < 30
                  and casi(float(estado("sensor.termo_solar_sol_sobrante").state), 0.85 * 7 - 0.4 * 7 - 5 - 1.8, 0.02),
                  "los sensores dan la energía que falta, la temperatura a la ducha y el sol sobrante")
        fuente("fv", 2.6, "kW")
        await avanzar(2.5)
        comprobar(estado("sensor.termo_solar_estado").state == "sol"
                  and estado("binary_sensor.termo_solar_orden").state == "on"
                  and estado("sensor.termo_solar_estado").attributes["simulacion"] is True
                  and float(estado("sensor.termo_solar_excedente").state) == 2300,
                  "con 2,6 kW de placas (sensor en kW) ordenaría calentar con sol")
        comprobar(ordenes == [] and estado(FUENTES["interruptor"]).state == "off",
                  "pero en simulación no ha tocado el interruptor")

        print("\n  · con Control: manda sobre el termo")
        await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.termo_solar_control"}, blocking=True)
        await hass.async_block_till_done()
        await avanzar(1)
        comprobar(gestor().control and estado("switch.termo_solar_control").state == "on"
                  and estado(FUENTES["interruptor"]).state == "on" and ordenes == ["turn_on"],
                  "al encender Control, enciende el termo (una sola orden)")
        fuente("consumo", 2300, "W")
        await avanzar(30)
        comprobar(ordenes == ["turn_on"] and casi(float(estado("sensor.termo_solar_energia_hoy").state), 2.0 * 30.5 / 60, 0.02)
                  and casi(estado("sensor.termo_solar_energia_hoy").attributes["sol"], 2.0 * 30.5 / 60, 0.02),
                  "cuenta la energía del termo (2 kW × tiempo encendido) y la apunta al sol")
        fuente("temperatura", 50.0, "°C")
        await hass.async_block_till_done()
        await avanzar(0.5)
        comprobar(estado(FUENTES["interruptor"]).state == "off" and ordenes == ["turn_on", "turn_off"],
                  "al llegar al objetivo lo apaga (la sonda dispara la decisión)")
        comprobar(casi(gestor().kwh_por_grado, 0.09 + 0.2 * (2.0 * 32 / 60 / 20 - 0.09), 0.002) and gestor().ciclos == 1,
                  "aprende los kWh por grado del calentado (32 min a 2 kW para 20 °C)")

        print("\n  · interruptor no disponible, encendido a mano y vuelta a simulación")
        fuente("consumo", 300, "W")
        fuente("temperatura", 30.0, "°C")
        await avanzar(6)
        comprobar(estado(FUENTES["interruptor"]).state == "on", "vuelve a hacer falta y lo enciende")
        fuente("temperatura", "unavailable")
        await avanzar(4)
        comprobar(estado(FUENTES["interruptor"]).state == "on" and estado("sensor.termo_solar_estado").state == "sol",
                  "un corte de la sonda de 4 min no apaga el termo (sigue con el último valor)")
        await avanzar(2)
        comprobar(estado(FUENTES["interruptor"]).state == "off" and estado("sensor.termo_solar_estado").state == "sin_datos",
                  "pasados 5 min sin sonda, lo apaga")
        fuente("interruptor", "unavailable")
        fuente("temperatura", 51.0, "°C")
        await avanzar(1)
        n = len(ordenes)
        comprobar(estado("binary_sensor.termo_solar_orden").state == "off" and len(ordenes) == n,
                  "con el interruptor no disponible no manda órdenes al aire")
        fuente("interruptor", "on")
        await avanzar(1)
        comprobar(estado(FUENTES["interruptor"]).state == "off", "cuando vuelve encendido y no toca, lo apaga")
        fuente("fv", 0, "W")
        await avanzar(6)
        fuente("interruptor", "on")  # alguien lo enciende
        await hass.async_block_till_done()
        await avanzar(2)
        comprobar(estado("sensor.termo_solar_estado").state == "manual" and estado(FUENTES["interruptor"]).state == "on",
                  "un encendido a mano se respeta")
        fuente("temperatura", 60.0, "°C")
        await avanzar(1)
        comprobar(estado(FUENTES["interruptor"]).state == "off", "hasta la máxima con sol; ahí lo apaga")

        fuente("temperatura", 30.0, "°C")
        fuente("fv", 2600, "W")
        await avanzar(8)
        comprobar(estado(FUENTES["interruptor"]).state == "on" and gestor().ordenado, "lo enciende la integración")
        await gestor().async_cambiar_ajuste("control", False)
        await hass.async_block_till_done()
        comprobar(estado(FUENTES["interruptor"]).state == "off",
                  "al apagar Control, apaga lo que encendió ella")
        n = len(ordenes)
        await avanzar(5)
        comprobar(len(ordenes) == n and estado("binary_sensor.termo_solar_orden").state == "on",
                  "y vuelve a simular sin mandar nada")

        print("\n  · horas, Configurar y recarga")
        await ajustar("time", "hora_respaldo", "15:30:00")
        comprobar(entrada.options["hora_respaldo"] == "15:30:00" and gestor().ajustes().hora_respaldo.minute == 30,
                  "las horas se cambian desde sus entidades")
        aprendido = gestor().kwh_por_grado
        flujo = await hass.config_entries.options.async_init(entrada.entry_id)
        nuevas = {k: v for k, v in datos.items() if k != "red_conectada"}
        r = await hass.config_entries.options.async_configure(flujo["flow_id"], nuevas)
        await hass.async_block_till_done()
        entrada = hass.config_entries.async_entries(DOMINIO)[0]
        comprobar(r["type"] == "create_entry" and "red_conectada" not in entrada.options
                  and entrada.options["potencia"] == 2000.0 and entrada.options["hora_respaldo"] == "15:30:00",
                  "Configurar cambia las entidades y conserva los ajustes")
        comprobar(entrada.state is ConfigEntryState.LOADED and gestor().kwh_por_grado == aprendido
                  and gestor().ciclos == 1 and gestor().energia["total"] > 1,
                  "tras recargar sigue lo aprendido y la energía de hoy")

        print("\n  · día nuevo, perfil de consumo y diagnóstico")
        fuente("fv", 0, "W")
        reloj.t = _hora("23:59:30")
        gestor().async_actualizar()
        await avanzar(1)
        comprobar(float(estado("sensor.termo_solar_energia_hoy").state) == 0.0
                  and estado("sensor.termo_solar_energia_hoy").attributes["last_reset"].startswith("2026-11-19T00:00:00"),
                  "a medianoche la energía de hoy vuelve a 0")
        fuente("consumo", 700, "W")
        reloj.t = _hora("09:59:30", "2026-11-19")
        gestor().async_actualizar()
        await avanzar(61)
        comprobar(gestor().perfil["laborable"][10] == 700.0 and gestor().perfil["festivo"][10] is None,
                  "aprende lo que gasta la casa a cada hora (laborables aparte de festivos)")
        esperado = sum(400.0 if v is None else v for v in gestor().perfil["laborable"][9:17]) / 1000
        comprobar(casi(float(estado("sensor.termo_solar_consumo_casa").state), esperado, 0.01)
                  and estado("sensor.termo_solar_consumo_casa").attributes["laborable"][10] == 700.0,
                  "y lo enseña como consumo de 9 a 17 (400 W donde aún no ha aprendido)")

        from custom_components.termo_solar.diagnostics import async_get_config_entry_diagnostics

        diagnostico = await async_get_config_entry_diagnostics(hass, entrada)
        comprobar(json.dumps(diagnostico, default=str) and diagnostico["decision"]["accion"] in plan.ACCIONES
                  and diagnostico["fuentes"]["temperatura"] == "30.0",
                  "el diagnóstico se genera y es serializable")

        comprobar(await hass.config_entries.async_unload(entrada.entry_id), "la entrada se descarga")
        guardado = json.loads((directorio / ".storage" / DOMINIO).read_text("utf-8"))["data"]
        comprobar(guardado["ciclos"] == 1 and guardado["perfil"]["laborable"][10] == 700.0,
                  "al descargar deja lo aprendido en disco")
        propios = [m for m in registros.mensajes if DOMINIO in m and "not been tested" not in m]
        comprobar(not propios, f"sin avisos ni errores de la integración en el log {propios[:3]}")
    finally:
        await hass.async_stop(force=True)
        logging.getLogger().removeHandler(registros)


def test_home_assistant() -> None:
    try:
        import homeassistant  # noqa: F401
    except ImportError:
        print("\nHome Assistant no instalado: se saltan las pruebas de integración")
        return

    print("\nIntegración en un Home Assistant real")
    directorio = Path(tempfile.mkdtemp(prefix="termo_solar_"))
    try:
        (directorio / "custom_components").mkdir()
        (directorio / "custom_components" / DOMINIO).symlink_to(BASE)
        asyncio.run(_recorrido(directorio))
    finally:
        shutil.rmtree(directorio, ignore_errors=True)


if __name__ == "__main__":
    test_ficheros()
    test_plan()
    test_home_assistant()
    print()
    if fallos:
        print(f"{len(fallos)} FALLOS:")
        for f in fallos:
            print(f"  - {f}")
    else:
        print("Todo OK")
    # os._exit y no sys.exit: con el HA y el Python del venv, el intérprete
    # da un segfault al cerrarse si hay alguna entrada de configuración
    # cargada (lo mismo pasa en las demás integraciones).
    sys.stdout.flush()
    sys.stderr.flush()
    import os

    os._exit(1 if fallos else 0)
