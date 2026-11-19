"""La decisión: cuándo calentar el termo y con qué. Sin Home Assistant.

Tres fuentes, por orden de preferencia (docs/DECISIONES.md §2):

1. **Sol**: cuando sobra potencia solar para el termo entero.
2. **Valle**: los laborables, justo antes de que acabe el Valle, si la
   previsión dice que hoy el sol no va a sobrar.
3. **Respaldo**: por la tarde, si a la hora de la ducha el agua no va a
   llegar al mínimo, con la red (o lo que haya), pero nunca en Punta.

`decidir` se llama cada pocos segundos con una foto de las entradas
(`Lectura`) y una memoria que guarda lo que dura más que una llamada
(`Memoria`). No hay «una vez al día»: cada llamada mira cómo está el agua.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
import math
from typing import Any

# ── Acciones (estado del sensor «Estado») ──
ESPERANDO = "esperando"
SOL = "sol"
VALLE = "valle"
RESPALDO = "respaldo"
MANUAL = "manual"
PAUSA_ICP = "pausa_icp"
SIN_DATOS = "sin_datos"
SONDA = "sonda"
ACCIONES = (ESPERANDO, SOL, VALLE, RESPALDO, MANUAL, PAUSA_ICP, SIN_DATOS, SONDA)

# ── Constantes de la decisión (DECISIONES §3) ──
# El excedente tiene que aguantar este tiempo para encender con sol…
SOSTENIDO_ENCENDER = timedelta(minutes=2)
# …y faltar este otro para apagar (las nubes pasan).
SOSTENIDO_APAGAR = timedelta(minutes=3)
# Con sol, el termo se enciende y se apaga como mucho cada 5 min.
MINIMO_ENCENDIDO = timedelta(minutes=5)
MINIMO_APAGADO = timedelta(minutes=5)
# Con sol se admite que hasta 300 W del termo salgan de la batería o la red.
TOLERANCIA_SOL = 300.0
# No se vuelve a calentar hasta que el agua baja esto de la consigna.
HISTERESIS = 3.0
# Batería «llena»: lo que sobre a partir de aquí se iba a exportar.
SOC_LLENO = 97.0
# ICP: como la automatización a la que sustituye. Más de 1,1 veces la
# potencia contratada durante 10 min, o más de 1,5 veces en cualquier
# momento, apaga; vuelve cuando el termo cabe durante 2 min.
ICP_MODERADA = 1.1
ICP_EXTREMA = 1.5
ICP_AGUANTE = timedelta(minutes=10)
ICP_VUELTA = timedelta(minutes=2)
# Sonda atascada: una hora calentando sin que cambie la temperatura.
SONDA_ATASCADA = timedelta(hours=1)
# El Valle se decide en las horas previas a su fin, no antes.
VENTANA_VALLE = timedelta(hours=4)
# Colchón al calcular cuándo empezar en Valle: 10 % más 10 min.
COLCHON_VALLE = timedelta(minutes=10)
# Pérdidas del termo parado: fracción de (T − ambiente) que pierde por hora
# (medido: 0,5 °C/h a 50 °C con 22 °C alrededor).
PERDIDA_POR_HORA = 0.018
AMBIENTE = 22.0
# Media hora de previsión cuenta como «de día» a partir de esta potencia.
FV_MINIMA_KW = 0.05

KWH_POR_GRADO_INICIAL = 0.09
KWH_POR_GRADO_LIMITES = (0.03, 0.30)
CONSUMO_CASA_INICIAL = 400.0


@dataclass
class Ajustes:
    objetivo: float = 51.0
    maxima_solar: float = 60.0
    minima_ducha: float = 42.0
    potencia: float = 1700.0
    margen_prevision: float = 15.0
    hora_ducha: time = time(19, 0)
    hora_respaldo: time = time(16, 0)
    fin_valle: time = time(8, 0)
    capacidad_bateria: float = 0.0


@dataclass
class Lectura:
    """Las entradas en un momento. `ahora` es hora local con zona."""

    ahora: datetime
    temperatura: float | None = None
    # Cuándo cambió por última vez la sonda.
    temperatura_cambio: datetime | None = None
    # Estado real del interruptor (None: no disponible).
    encendido: bool | None = None
    fv: float | None = None
    consumo: float | None = None
    # Potencia de la red, positiva al importar.
    red: float | None = None
    contratada: float | None = None
    soc: float | None = None
    # "valle" / "llano" / "punta" o None si no se sabe.
    periodo: str | None = None
    laborable: bool | None = None
    red_conectada: bool = True
    # Previsión de hoy por tramos: (inicio, kW medios). None: sin tramos.
    prevision: list[tuple[datetime, float]] | None = None
    # Previsión total de hoy en kWh (por si no hay tramos).
    prevision_kwh: float | None = None
    # Consumo de la casa sin el termo, W por hora del día (24 valores).
    perfil_casa: list[float] = field(default_factory=lambda: [CONSUMO_CASA_INICIAL] * 24)
    kwh_por_grado: float = KWH_POR_GRADO_INICIAL
    # La integración manda sobre el interruptor (si no, simula).
    control: bool = False
    # Alguien encendió el termo a mano (solo con control).
    manual: bool = False


@dataclass
class Memoria:
    """Lo que dura más que una llamada. Se guarda en disco."""

    # Modo que está calentando (SOL / VALLE / RESPALDO) o None.
    modo: str | None = None
    # Lo que la decisión quiere ahora (en simulación, lo que haría).
    calentando: bool = False
    encendido_en: datetime | None = None
    apagado_en: datetime | None = None
    sobra_desde: datetime | None = None
    falta_desde: datetime | None = None
    sobrecarga_desde: datetime | None = None
    hueco_desde: datetime | None = None
    pausa_icp: bool = False
    # Hora del último cambio de la sonda cuando se dio por atascada.
    sonda_atascada: datetime | None = None

    def a_dict(self) -> dict[str, Any]:
        return {
            clave: valor.isoformat() if isinstance(valor, datetime) else valor
            for clave, valor in self.__dict__.items()
        }

    @classmethod
    def desde_dict(cls, datos: dict[str, Any] | None) -> Memoria:
        memoria = cls()
        for clave, valor in (datos or {}).items():
            if clave not in memoria.__dict__:
                continue
            if isinstance(valor, str) and clave != "modo":
                try:
                    valor = datetime.fromisoformat(valor)
                except ValueError:
                    continue
            setattr(memoria, clave, valor)
        return memoria


@dataclass
class Decision:
    accion: str
    calentar: bool
    motivo: str
    # Hasta dónde calienta el modo en curso.
    consigna: float | None = None
    datos: dict[str, Any] = field(default_factory=dict)


# ── Cuentas sueltas ──────────────────────────────────────────────────


def temperatura_prevista(temperatura: float, horas: float) -> float:
    """Temperatura del agua dentro de `horas` si no se toca el termo."""
    if horas <= 0 or temperatura <= AMBIENTE:
        return temperatura
    return AMBIENTE + (temperatura - AMBIENTE) * math.exp(-PERDIDA_POR_HORA * horas)


def energia_necesaria(temperatura: float, consigna: float, kwh_por_grado: float) -> float:
    return max(0.0, consigna - temperatura) * kwh_por_grado


def _horas_hasta(ahora: datetime, hora: time) -> float:
    destino = ahora.replace(hour=hora.hour, minute=hora.minute, second=0, microsecond=0)
    return (destino - ahora).total_seconds() / 3600


def excedente(lectura: Lectura, ajustes: Ajustes) -> float | None:
    """Lo que sobra de las placas sin contar lo que gasta el termo (W)."""
    if lectura.fv is None or lectura.consumo is None:
        return None
    casa = lectura.consumo - (ajustes.potencia if lectura.encendido else 0.0)
    return lectura.fv - max(casa, 0.0)


def prevision_del_dia(lectura: Lectura, ajustes: Ajustes, necesaria: float) -> dict[str, Any]:
    """¿Va a sobrar sol hoy para el termo? (DECISIONES §4)

    Hace falta que sobre **energía** (previsión prudente − lo que gasta la
    casa de día − lo que le cabe a la batería ≥ lo que pide el termo) y que
    haya **potencia** (tramos en los que el sol previsto cubre el termo
    entero) antes de la hora del respaldo. Si falta una de las dos, el sol
    que se lleve el termo se lo quita a la batería y sale más barato el
    Valle. Sin previsión, Valle.
    """
    factor = 1 - ajustes.margen_prevision / 100
    potencia_kw = ajustes.potencia / 1000
    ahora = lectura.ahora
    hueco = 0.0
    if ajustes.capacidad_bateria > 0 and lectura.soc is not None:
        hueco = max(0.0, 1 - lectura.soc / 100) * ajustes.capacidad_bateria

    if lectura.prevision:
        limite = ahora.replace(
            hour=ajustes.hora_respaldo.hour, minute=ajustes.hora_respaldo.minute, second=0, microsecond=0
        )
        sol = casa = horas_con_sol = 0.0
        tramos = sorted(lectura.prevision)
        for indice, (inicio, kw) in enumerate(tramos):
            if inicio.date() != ahora.date():
                continue
            if indice + 1 < len(tramos):
                duracion = (tramos[indice + 1][0] - inicio).total_seconds() / 3600
            else:
                duracion = 0.5
            if not 0 < duracion <= 1:
                duracion = 0.5
            fin = inicio + timedelta(hours=duracion)
            if fin <= ahora or kw < FV_MINIMA_KW:
                continue
            casa_kw = lectura.perfil_casa[inicio.hour] / 1000
            sol += kw * factor * duracion
            casa += casa_kw * duracion
            if fin <= limite and kw * factor - casa_kw >= potencia_kw:
                horas_con_sol += duracion
        horas_necesarias = necesaria / potencia_kw if potencia_kw > 0 else 0.0
        hay_potencia = horas_con_sol >= horas_necesarias
    elif lectura.prevision_kwh is not None:
        # Solo el total del día: se supone que hay sol de 9 a 17 y no se
        # puede saber si habrá potencia.
        sol = lectura.prevision_kwh * factor
        casa = sum(lectura.perfil_casa[9:17]) / 1000
        horas_con_sol = horas_necesarias = None
        hay_potencia = True
    else:
        return {"decision": VALLE, "motivo": "no hay previsión solar", "sobra_kwh": None}

    sobra = sol - casa - hueco - necesaria
    if sobra < 0:
        decision, motivo = VALLE, (
            f"hoy no sobra sol: {sol:.1f} kWh previstos para {casa:.1f} de la casa, "
            f"{hueco:.1f} de la batería y {necesaria:.1f} del termo"
        )
    elif not hay_potencia:
        decision, motivo = VALLE, (
            f"el sol previsto no llega a cubrir el termo entero el tiempo necesario "
            f"({horas_con_sol:.1f} h de {horas_necesarias:.1f} h)"
        )
    else:
        decision, motivo = SOL, f"hoy sobran {sobra:.1f} kWh de sol después de casa, batería y termo"
    return {
        "decision": decision,
        "motivo": motivo,
        "sobra_kwh": round(sobra, 2),
        "sol_kwh": round(sol, 2),
        "casa_kwh": round(casa, 2),
        "hueco_bateria_kwh": round(hueco, 2),
        "horas_con_sol": horas_con_sol,
        "horas_necesarias": None if horas_necesarias is None else round(horas_necesarias, 2),
    }


# ── La decisión ──────────────────────────────────────────────────────


def decidir(lectura: Lectura, ajustes: Ajustes, memoria: Memoria) -> Decision:
    ahora = lectura.ahora
    objetivo = ajustes.objetivo
    maxima = max(ajustes.maxima_solar, objetivo)
    datos: dict[str, Any] = {}

    def resultado(accion: str, calentar: bool, motivo: str, consigna: float | None = None) -> Decision:
        if calentar and not memoria.calentando:
            memoria.encendido_en = ahora
        elif not calentar and memoria.calentando:
            memoria.apagado_en = ahora
        memoria.calentando = calentar
        if not calentar and accion != PAUSA_ICP:
            memoria.modo = None
        return Decision(accion, calentar, motivo, consigna, datos)

    def soltar_icp() -> None:
        memoria.pausa_icp = False
        memoria.sobrecarga_desde = memoria.hueco_desde = None

    # ── Sin lo imprescindible no se calienta ──
    if lectura.temperatura is None:
        soltar_icp()
        return resultado(SIN_DATOS, False, "La sonda del termo no da dato: no se calienta.")
    temperatura = lectura.temperatura
    datos["necesaria_kwh"] = round(energia_necesaria(temperatura, objetivo, lectura.kwh_por_grado), 2)
    horas_ducha = _horas_hasta(ahora, ajustes.hora_ducha)
    prevista_ducha = temperatura_prevista(temperatura, horas_ducha)
    datos["prevista_ducha"] = round(prevista_ducha, 1)

    sobra = excedente(lectura, ajustes)
    datos["excedente"] = None if sobra is None else round(sobra)
    if sobra is not None and sobra >= ajustes.potencia:
        memoria.sobra_desde = memoria.sobra_desde or ahora
    else:
        memoria.sobra_desde = None
    if sobra is None or sobra < ajustes.potencia - TOLERANCIA_SOL:
        memoria.falta_desde = memoria.falta_desde or ahora
    else:
        memoria.falta_desde = None
    hay_sol = memoria.sobra_desde is not None and ahora - memoria.sobra_desde >= SOSTENIDO_ENCENDER
    sin_sol = memoria.falta_desde is not None and ahora - memoria.falta_desde >= SOSTENIDO_APAGAR

    if not lectura.red_conectada:
        soltar_icp()
        return resultado(ESPERANDO, False, "No hay red eléctrica: el termo no se enciende.")

    # ── Sonda atascada ──
    if memoria.sonda_atascada is not None and lectura.temperatura_cambio != memoria.sonda_atascada:
        memoria.sonda_atascada = None
    if (
        memoria.sonda_atascada is None
        and lectura.encendido
        and memoria.calentando
        and memoria.encendido_en is not None
        and ahora - memoria.encendido_en >= SONDA_ATASCADA
        and lectura.temperatura_cambio is not None
        and ahora - lectura.temperatura_cambio >= SONDA_ATASCADA
    ):
        memoria.sonda_atascada = lectura.temperatura_cambio
    if memoria.sonda_atascada is not None:
        soltar_icp()
        return resultado(
            SONDA, False,
            f"La sonda lleva más de una hora en {temperatura:.1f} °C con el termo encendido: "
            "se da por atascada y no se calienta hasta que cambie.",
        )

    # ── Encendido a mano (solo cuando la integración manda) ──
    if lectura.control and lectura.manual and lectura.encendido and memoria.modo is None:
        if temperatura < maxima:
            soltar_icp()
            return resultado(
                MANUAL, True,
                f"Encendido a mano: se deja hasta {maxima:.0f} °C o hasta que lo apagues.", maxima,
            )

    bateria_llena = ajustes.capacidad_bateria <= 0 or (lectura.soc is not None and lectura.soc >= SOC_LLENO)
    consigna_sol = maxima if bateria_llena else objetivo
    es_valle = lectura.periodo == VALLE
    es_punta = lectura.periodo == "punta"
    hora = ahora.time()

    # ── ¿Sigue valiendo el modo en curso? ──
    if memoria.modo == VALLE and not (
        es_valle and lectura.laborable and hora < ajustes.fin_valle and temperatura < objetivo
    ):
        memoria.modo = None
    elif memoria.modo == RESPALDO and (es_punta or temperatura >= objetivo):
        memoria.modo = None
    elif memoria.modo == SOL:
        aguanta = memoria.encendido_en is not None and ahora - memoria.encendido_en < MINIMO_ENCENDIDO
        if temperatura >= consigna_sol or (sin_sol and not aguanta):
            memoria.modo = None

    # ── ¿Empieza alguno? ──
    motivo_espera = ""
    if memoria.modo is None:
        # 1. Sol.
        if hay_sol and temperatura < objetivo - HISTERESIS:
            memoria.modo = SOL
        elif hay_sol and bateria_llena and temperatura < maxima - HISTERESIS:
            memoria.modo = SOL

    if memoria.modo is None and lectura.laborable and es_valle and hora < ajustes.fin_valle:
        # 2. Valle, lo más tarde posible.
        fin = ahora.replace(hour=ajustes.fin_valle.hour, minute=ajustes.fin_valle.minute, second=0, microsecond=0)
        if fin - ahora <= VENTANA_VALLE and temperatura < objetivo - HISTERESIS:
            prevision = prevision_del_dia(lectura, ajustes, datos["necesaria_kwh"])
            datos["prevision"] = prevision
            if prevision["decision"] == VALLE:
                duracion = timedelta(hours=datos["necesaria_kwh"] / (ajustes.potencia / 1000) * 1.1)
                inicio = fin - duracion - COLCHON_VALLE
                datos["inicio_valle"] = inicio.isoformat()
                if ahora >= inicio:
                    memoria.modo = VALLE
                else:
                    motivo_espera = (
                        f"Se calentará en Valle a las {inicio:%H:%M} porque {prevision['motivo']}."
                    )
            else:
                motivo_espera = f"No se calienta en Valle: {prevision['motivo']}."

    if (
        memoria.modo is None
        and ajustes.hora_respaldo <= hora < ajustes.hora_ducha
        and prevista_ducha < ajustes.minima_ducha
    ):
        # 3. Respaldo de la tarde.
        if es_punta:
            motivo_espera = (
                f"A la hora de la ducha habrá {prevista_ducha:.0f} °C (mínimo {ajustes.minima_ducha:.0f}), "
                "pero es periodo Punta: no se calienta con la red."
            )
        else:
            memoria.modo = RESPALDO

    if memoria.modo is None:
        soltar_icp()
        if not motivo_espera:
            if temperatura >= objetivo - HISTERESIS:
                motivo_espera = f"El agua está a {temperatura:.1f} °C: no hace falta calentar."
            elif sobra is None:
                motivo_espera = "Faltan datos de las placas o del consumo: se espera."
            elif memoria.sobra_desde is not None:
                motivo_espera = f"Sobra sol ({sobra:.0f} W): se encenderá si aguanta dos minutos."
            elif sobra <= 0:
                motivo_espera = f"Esperando al sol: ahora no sobra nada y el termo necesita {ajustes.potencia:.0f} W."
            else:
                motivo_espera = (
                    f"Esperando al sol: sobran {sobra:.0f} W y el termo necesita {ajustes.potencia:.0f} W."
                )
        return resultado(ESPERANDO, False, motivo_espera)

    consigna = consigna_sol if memoria.modo == SOL else objetivo
    motivo = {
        SOL: f"Calentando con el sol que sobra ({(sobra or 0):.0f} W) hasta {consigna:.0f} °C.",
        VALLE: f"Calentando en Valle hasta {consigna:.0f} °C: hoy el sol no va a sobrar.",
        RESPALDO: (
            f"Respaldo: a la hora de la ducha habría {prevista_ducha:.0f} °C "
            f"(mínimo {ajustes.minima_ducha:.0f}); se calienta hasta {consigna:.0f} °C."
        ),
    }[memoria.modo]

    # ── ICP: que el termo no haga saltar el limitador ──
    if lectura.red is not None and lectura.contratada:
        # Lo que se importaría con el termo encendido.
        con_termo = lectura.red + (0.0 if lectura.encendido else ajustes.potencia)
        if lectura.encendido and lectura.red / lectura.contratada > ICP_EXTREMA:
            memoria.pausa_icp = True
        elif lectura.encendido and lectura.red / lectura.contratada > ICP_MODERADA:
            memoria.sobrecarga_desde = memoria.sobrecarga_desde or ahora
            if ahora - memoria.sobrecarga_desde >= ICP_AGUANTE:
                memoria.pausa_icp = True
        else:
            memoria.sobrecarga_desde = None
        cabe = con_termo / lectura.contratada <= ICP_MODERADA
        if not memoria.calentando and not memoria.pausa_icp and not cabe:
            # No se arranca sabiendo que no cabe.
            memoria.pausa_icp = True
        if memoria.pausa_icp:
            if cabe and not lectura.encendido:
                memoria.hueco_desde = memoria.hueco_desde or ahora
                if ahora - memoria.hueco_desde >= ICP_VUELTA:
                    soltar_icp()
            else:
                memoria.hueco_desde = None
        if memoria.pausa_icp:
            return resultado(
                PAUSA_ICP, False,
                f"En pausa para no pasar de la potencia contratada ({lectura.red:.0f} W de "
                f"{lectura.contratada:.0f} W); seguirá en modo {memoria.modo} cuando quepa.",
                consigna,
            )

    # Con sol, entre apagar y volver a encender pasan al menos 5 min.
    if (
        memoria.modo == SOL
        and not memoria.calentando
        and memoria.apagado_en is not None
        and ahora - memoria.apagado_en < MINIMO_APAGADO
    ):
        memoria.modo = None
        return resultado(ESPERANDO, False, "Hay sol de sobra; espera unos minutos antes de volver a encender.")

    return resultado(memoria.modo, True, motivo, consigna)
