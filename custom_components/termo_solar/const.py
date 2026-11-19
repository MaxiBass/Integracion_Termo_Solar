"""Constantes de Termo Solar."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "termo_solar"

# ── Entidades de origen (opciones de la entrada; se cambian en Configurar) ──
CONF_INTERRUPTOR = "interruptor"
CONF_TEMPERATURA = "temperatura"
CONF_FV = "fv"
CONF_CONSUMO = "consumo"
CONF_RED = "red"
CONF_CONTRATADA = "contratada"
CONF_SOC = "soc"
CONF_PERIODO = "periodo"
CONF_LABORABLE = "laborable"
CONF_PREVISION = "prevision"
CONF_RED_CONECTADA = "red_conectada"
# Capacidad útil de la batería en kWh (0 = sin batería).
CONF_CAPACIDAD_BATERIA = "capacidad_bateria"

FUENTES = (
    CONF_INTERRUPTOR,
    CONF_TEMPERATURA,
    CONF_FV,
    CONF_CONSUMO,
    CONF_RED,
    CONF_CONTRATADA,
    CONF_SOC,
    CONF_PERIODO,
    CONF_LABORABLE,
    CONF_PREVISION,
    CONF_RED_CONECTADA,
)

# Si existen, el formulario de alta sale relleno con estas entidades (un
# inversor Deye, Solcast y las plantillas de la casa del autor).
SUGERIDAS = {
    CONF_INTERRUPTOR: "switch.termo_boiler",
    CONF_TEMPERATURA: "sensor.termo_boiler_temperature",
    CONF_FV: "sensor.deye_pv_total_power",
    CONF_CONSUMO: "sensor.deye_load_power",
    CONF_RED: "sensor.deye_grid_ct_power",
    CONF_CONTRATADA: "sensor.potencia_contratada_actual",
    CONF_SOC: "sensor.deye_battery_soc",
    CONF_PERIODO: "sensor.periodo_tarifario",
    CONF_LABORABLE: "binary_sensor.dia_laborable",
    CONF_PREVISION: "sensor.solcast_pv_forecast_pronostico_hoy",
    CONF_RED_CONECTADA: "binary_sensor.deye_grid_connected",
}

# ── Ajustes (también en las opciones; se cambian desde sus entidades sin
# recargar) ──
CONF_CONTROL = "control"
CONF_OBJETIVO = "objetivo"
CONF_MAXIMA_SOLAR = "maxima_solar"
CONF_MINIMA_DUCHA = "minima_ducha"
CONF_POTENCIA = "potencia"
CONF_MARGEN_PREVISION = "margen_prevision"
CONF_HORA_DUCHA = "hora_ducha"
CONF_HORA_RESPALDO = "hora_respaldo"
CONF_FIN_VALLE = "fin_valle"

AJUSTES_POR_DEFECTO = {
    # Apagado: solo calcula y enseña lo que haría (simulación).
    CONF_CONTROL: False,
    CONF_OBJETIVO: 51.0,
    CONF_MAXIMA_SOLAR: 60.0,
    CONF_MINIMA_DUCHA: 42.0,
    CONF_POTENCIA: 1700.0,
    CONF_MARGEN_PREVISION: 15.0,
    CONF_HORA_DUCHA: "19:00:00",
    CONF_HORA_RESPALDO: "16:00:00",
    CONF_FIN_VALLE: "08:00:00",
}

# (mínimo, máximo, paso, unidad) de los ajustes numéricos.
NUMEROS = {
    CONF_OBJETIVO: (30.0, 75.0, 1.0, "°C"),
    CONF_MAXIMA_SOLAR: (30.0, 80.0, 1.0, "°C"),
    CONF_MINIMA_DUCHA: (25.0, 70.0, 1.0, "°C"),
    CONF_POTENCIA: (300.0, 4000.0, 50.0, "W"),
    CONF_MARGEN_PREVISION: (0.0, 60.0, 5.0, "%"),
}
HORAS = (CONF_HORA_DUCHA, CONF_HORA_RESPALDO, CONF_FIN_VALLE)

# Estado del sensor de periodo (en minúsculas) → periodo.
ALIAS_PERIODO = {
    "punta": "punta",
    "p1": "punta",
    "llano": "llano",
    "p2": "llano",
    "valle": "valle",
    "p3": "valle",
}

# Cada cuánto se vuelve a decidir.
INTERVALO = timedelta(seconds=30)
# Un hueco mayor entre dos decisiones no se cuenta como tiempo encendido
# (HA colgado o equipo suspendido).
MAX_INTERVALO = timedelta(minutes=5)
RETRASO_GUARDADO = 60
VERSION_ALMACEN = 1
