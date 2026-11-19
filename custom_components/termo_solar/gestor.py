"""El estado vivo: lee las entradas, decide, manda y aprende.

Cada 30 s (y cuando cambian el interruptor o la sonda) hace una foto de las
entradas, llama a `plan.decidir` y, si «Control» está encendido, pone el
interruptor del termo como diga la decisión. Con «Control» apagado no toca
nada: solo enseña lo que haría (simulación).

De paso aprende dos cosas que la decisión necesita (DECISIONES §5): los
kWh por grado del termo, de cada calentado real, y lo que gasta la casa a
cada hora sin el termo.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
    EVENT_HOMEASSISTANT_STOP,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import plan
from .const import (
    AJUSTES_POR_DEFECTO,
    ALIAS_PERIODO,
    CONF_CAPACIDAD_BATERIA,
    CONF_CONSUMO,
    CONF_CONTRATADA,
    CONF_CONTROL,
    CONF_FIN_VALLE,
    CONF_FV,
    CONF_HORA_DUCHA,
    CONF_HORA_RESPALDO,
    CONF_INTERRUPTOR,
    CONF_LABORABLE,
    CONF_MARGEN_PREVISION,
    CONF_MAXIMA_SOLAR,
    CONF_MINIMA_DUCHA,
    CONF_OBJETIVO,
    CONF_PERIODO,
    CONF_POTENCIA,
    CONF_PREVISION,
    CONF_RED,
    CONF_RED_CONECTADA,
    CONF_SOC,
    CONF_TEMPERATURA,
    DOMAIN,
    INTERVALO,
    MAX_INTERVALO,
    RETRASO_GUARDADO,
    VERSION_ALMACEN,
)

_LOGGER = logging.getLogger(__name__)

type EntradaTermo = ConfigEntry[GestorTermo]

# Un calentado sirve para aprender si dura y sube al menos esto.
CICLO_MINIMO = timedelta(minutes=10)
CICLO_GRADOS = 5.0
# Peso de cada dato nuevo en lo aprendido.
PESO_NUEVO = 0.2
# Muestras (de 30 s) para dar por buena la media de una hora.
MUESTRAS_HORA = 40
# Tras una orden, margen para que el interruptor cambie antes de repetirla
# y para no tomar por manual un encendido que es nuestro.
MARGEN_ORDEN = timedelta(seconds=20)
# Si la sonda deja de dar dato un momento (una reconexión de Zigbee), se
# sigue con el último valor este tiempo antes de darla por perdida.
GRACIA_SONDA = timedelta(minutes=5)
FUENTES_ENERGIA = ("total", plan.SOL, plan.VALLE, plan.RESPALDO, plan.MANUAL, "otros")


def _ahora() -> datetime:
    """Hora actual (UTC). Aparte para que las pruebas puedan mover el reloj."""
    return dt_util.utcnow()


def senal_actualizado(entry_id: str) -> str:
    return f"{DOMAIN}_{entry_id}_actualizado"


def _hora(texto: Any, defecto: str) -> time:
    try:
        return time.fromisoformat(str(texto))
    except ValueError:
        return time.fromisoformat(defecto)


class GestorTermo:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.opciones = {**AJUSTES_POR_DEFECTO, **entry.options}
        self.almacen: Store[dict[str, Any]] = Store(hass, VERSION_ALMACEN, DOMAIN)
        self.memoria = plan.Memoria()
        self.decision = plan.Decision(plan.SIN_DATOS, False, "Arrancando.")
        self.prevision: dict[str, Any] = {}
        # Aprendido.
        self.kwh_por_grado = plan.KWH_POR_GRADO_INICIAL
        self.ciclos = 0
        self.perfil: dict[str, list[float | None]] = {"laborable": [None] * 24, "festivo": [None] * 24}
        # Energía que ha gastado hoy el termo, por fuente (kWh).
        self.energia = dict.fromkeys(FUENTES_ENERGIA, 0.0)
        self.dia: str | None = None
        # El último encendido lo pidió la integración / fue a mano.
        self.ordenado = False
        self.manual = False
        self._orden_en: datetime | None = None
        self._ultimo: datetime | None = None
        self._estaba_encendido = False
        self._fuente_anterior = "otros"
        self._temp: float | None = None
        self._temp_cambio: datetime | None = None
        self._temp_vista: datetime | None = None
        self._ciclo: tuple[datetime, float] | None = None
        self._hora: tuple[str, int] | None = None
        self._hora_suma = 0.0
        self._hora_muestras = 0
        self._quitar: list[Callable[[], None]] = []
        self._quitar_parada: Callable[[], None] | None = None

    # ── Arranque y parada ──────────────────────────────────────────────

    async def async_cargar(self) -> None:
        datos = await self.almacen.async_load() or {}
        limites = plan.KWH_POR_GRADO_LIMITES
        try:
            self.kwh_por_grado = min(max(float(datos.get("kwh_por_grado", self.kwh_por_grado)), limites[0]), limites[1])
        except (TypeError, ValueError):
            pass
        self.ciclos = int(datos.get("ciclos", 0))
        for tipo, valores in (datos.get("perfil") or {}).items():
            if tipo in self.perfil and isinstance(valores, list) and len(valores) == 24:
                self.perfil[tipo] = valores
        self.dia = datos.get("dia")
        for fuente, kwh in (datos.get("energia") or {}).items():
            if fuente in self.energia:
                self.energia[fuente] = float(kwh)
        self.memoria = plan.Memoria.desde_dict(datos.get("memoria"))
        self.ordenado = bool(datos.get("ordenado", False))
        self.manual = bool(datos.get("manual", False))

    @callback
    def async_arrancar(self) -> None:
        vigiladas = [eid for clave in (CONF_INTERRUPTOR, CONF_TEMPERATURA) if (eid := self.opciones.get(clave))]
        self._quitar = [
            async_track_state_change_event(self.hass, vigiladas, self._al_cambiar),
            async_track_time_interval(self.hass, self._al_tocar, INTERVALO, name=f"{DOMAIN} decisión"),
        ]
        self._quitar_parada = self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._al_parar)
        self.async_actualizar()

    async def async_parar(self) -> None:
        for quitar in self._quitar:
            quitar()
        self._quitar = []
        if self._quitar_parada is not None:
            self._quitar_parada()
            self._quitar_parada = None
        await self.almacen.async_save(self._datos())

    @callback
    def _al_parar(self, _event: Event) -> None:
        self._quitar_parada = None
        self.almacen.async_delay_save(self._datos, 0)

    def _datos(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry.entry_id,
            "kwh_por_grado": self.kwh_por_grado,
            "ciclos": self.ciclos,
            "perfil": self.perfil,
            "dia": self.dia,
            "energia": self.energia,
            "memoria": self.memoria.a_dict(),
            "ordenado": self.ordenado,
            "manual": self.manual,
        }

    # ── Ajustes ────────────────────────────────────────────────────────

    def opcion(self, clave: str) -> Any:
        return self.opciones.get(clave, AJUSTES_POR_DEFECTO.get(clave))

    @property
    def control(self) -> bool:
        return bool(self.opcion(CONF_CONTROL))

    async def async_cambiar_ajuste(self, clave: str, valor: Any) -> None:
        """Cambia un ajuste (desde su entidad) sin recargar."""
        self.opciones[clave] = valor
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, clave: valor}
        )
        if clave == CONF_CONTROL and not valor:
            # Al dejar de mandar no se deja encendido lo que encendió la
            # integración: nadie lo iba a apagar.
            if self.ordenado and self._encendido() is True:
                self._ordenar(False)
            self.ordenado = self.manual = False
        self.async_actualizar()

    def ajustes(self) -> plan.Ajustes:
        defecto = AJUSTES_POR_DEFECTO
        return plan.Ajustes(
            objetivo=float(self.opcion(CONF_OBJETIVO)),
            maxima_solar=float(self.opcion(CONF_MAXIMA_SOLAR)),
            minima_ducha=float(self.opcion(CONF_MINIMA_DUCHA)),
            potencia=float(self.opcion(CONF_POTENCIA)),
            margen_prevision=float(self.opcion(CONF_MARGEN_PREVISION)),
            hora_ducha=_hora(self.opcion(CONF_HORA_DUCHA), defecto[CONF_HORA_DUCHA]),
            hora_respaldo=_hora(self.opcion(CONF_HORA_RESPALDO), defecto[CONF_HORA_RESPALDO]),
            fin_valle=_hora(self.opcion(CONF_FIN_VALLE), defecto[CONF_FIN_VALLE]),
            capacidad_bateria=float(self.opciones.get(CONF_CAPACIDAD_BATERIA) or 0.0),
        )

    # ── Lectura de las entradas ────────────────────────────────────────

    def _estado(self, clave: str):
        entity_id = self.opciones.get(clave)
        estado = self.hass.states.get(entity_id) if entity_id else None
        if estado is None or estado.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, "", "none"):
            return None
        return estado

    def _numero(self, clave: str) -> float | None:
        estado = self._estado(clave)
        if estado is None:
            return None
        try:
            return float(estado.state)
        except ValueError:
            return None

    def _potencia(self, clave: str) -> float | None:
        """En W, venga el sensor en W o en kW."""
        valor = self._numero(clave)
        if valor is None:
            return None
        unidad = str(self._estado(clave).attributes.get(ATTR_UNIT_OF_MEASUREMENT, "")).lower()
        return valor * 1000 if unidad == "kw" else valor

    def _encendido(self) -> bool | None:
        estado = self._estado(CONF_INTERRUPTOR)
        if estado is None or estado.state not in (STATE_ON, STATE_OFF):
            return None
        return estado.state == STATE_ON

    def _binario(self, clave: str) -> bool | None:
        estado = self._estado(clave)
        return None if estado is None else estado.state == STATE_ON

    def _leer_prevision(self) -> tuple[list[tuple[datetime, float]] | None, float | None]:
        estado = self._estado(CONF_PREVISION)
        if estado is None:
            return None, None
        try:
            total: float | None = float(estado.state)
        except ValueError:
            total = None
        if total is not None and str(estado.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "")).lower() == "wh":
            total /= 1000
        tramos: list[tuple[datetime, float]] = []
        # Solcast: lista de {period_start, pv_estimate} en kW medios.
        for tramo in estado.attributes.get("detailedForecast") or []:
            try:
                inicio = tramo["period_start"]
                if not isinstance(inicio, datetime):
                    inicio = datetime.fromisoformat(str(inicio))
                tramos.append((dt_util.as_local(inicio), float(tramo["pv_estimate"])))
            except (KeyError, TypeError, ValueError):
                continue
        return tramos or None, total

    def _perfil_de(self, laborable: bool | None) -> list[float]:
        valores = self.perfil["festivo" if laborable is False else "laborable"]
        return [plan.CONSUMO_CASA_INICIAL if v is None else float(v) for v in valores]

    def _leer(self, ahora: datetime) -> plan.Lectura:
        temperatura = self._numero(CONF_TEMPERATURA)
        if temperatura is not None:
            self._temp_vista = ahora
        elif self._temp is not None and self._temp_vista is not None and ahora - self._temp_vista <= GRACIA_SONDA:
            temperatura = self._temp
        if temperatura != self._temp or self._temp_cambio is None:
            self._temp, self._temp_cambio = temperatura, ahora
        periodo = self._estado(CONF_PERIODO)
        laborable = self._binario(CONF_LABORABLE)
        red_conectada = self._binario(CONF_RED_CONECTADA)
        tramos, total = self._leer_prevision()
        return plan.Lectura(
            ahora=dt_util.as_local(ahora),
            temperatura=temperatura,
            temperatura_cambio=self._temp_cambio,
            encendido=self._encendido(),
            fv=self._potencia(CONF_FV),
            consumo=self._potencia(CONF_CONSUMO),
            red=self._potencia(CONF_RED),
            contratada=self._potencia(CONF_CONTRATADA),
            soc=self._numero(CONF_SOC),
            periodo=None if periodo is None else ALIAS_PERIODO.get(periodo.state.strip().lower()),
            # Sin sensor de laborables, todos los días lo son.
            laborable=True if not self.opciones.get(CONF_LABORABLE) else laborable,
            red_conectada=True if red_conectada is None else red_conectada,
            prevision=tramos,
            prevision_kwh=total,
            perfil_casa=self._perfil_de(laborable),
            kwh_por_grado=self.kwh_por_grado,
            control=self.control,
            manual=self.manual,
        )

    # ── Ciclo ──────────────────────────────────────────────────────────

    @callback
    def _al_tocar(self, _ahora: datetime) -> None:
        self.async_actualizar()

    @callback
    def _al_cambiar(self, event: Event[EventStateChangedData]) -> None:
        if event.data["entity_id"] == self.opciones.get(CONF_INTERRUPTOR):
            viejo, nuevo = event.data["old_state"], event.data["new_state"]
            if nuevo is not None and nuevo.state == STATE_ON:
                nuestro = self._orden_en is not None and _ahora() - self._orden_en <= MARGEN_ORDEN
                if self.control and not nuestro and viejo is not None and viejo.state == STATE_OFF:
                    self.manual = True
            elif nuevo is not None and nuevo.state == STATE_OFF:
                self.manual = False
        self.async_actualizar()

    @callback
    def async_actualizar(self) -> None:
        ahora = _ahora()
        lectura = self._leer(ahora)
        ajustes = self.ajustes()
        self._contar(ahora, lectura, ajustes)
        self._aprender_ciclo(ahora, lectura, ajustes)

        self.decision = plan.decidir(lectura, ajustes, self.memoria)
        if lectura.temperatura is not None and lectura.ahora.time() < ajustes.hora_respaldo:
            self.prevision = plan.prevision_del_dia(
                lectura, ajustes, plan.energia_necesaria(lectura.temperatura, ajustes.objetivo, self.kwh_por_grado)
            )

        if self.control:
            self._mandar(ahora, lectura)
        self._ultimo = ahora
        self._estaba_encendido = lectura.encendido is True
        self._fuente_anterior = (
            self.decision.accion
            if self.control and self.decision.calentar and self.decision.accion in self.energia
            else "otros"
        )
        self.almacen.async_delay_save(self._datos, RETRASO_GUARDADO)
        async_dispatcher_send(self.hass, senal_actualizado(self.entry.entry_id))

    def _mandar(self, ahora: datetime, lectura: plan.Lectura) -> None:
        if lectura.encendido is None:
            return  # interruptor no disponible: se reintenta cuando vuelva
        if self._orden_en is not None and ahora - self._orden_en < MARGEN_ORDEN:
            return
        if self.decision.calentar and not lectura.encendido:
            self._ordenar(True)
        elif not self.decision.calentar and lectura.encendido:
            self._ordenar(False)

    def _ordenar(self, encender: bool) -> None:
        self._orden_en = _ahora()
        self.ordenado = encender
        if not encender:
            self.manual = False
        _LOGGER.info("Termo %s: %s", "ON" if encender else "OFF", self.decision.motivo)
        self.hass.async_create_task(
            self.hass.services.async_call(
                "homeassistant",
                SERVICE_TURN_ON if encender else SERVICE_TURN_OFF,
                {ATTR_ENTITY_ID: self.opciones[CONF_INTERRUPTOR]},
            ),
            name=f"{DOMAIN} orden",
        )

    # ── Cuenta y aprendizaje ───────────────────────────────────────────

    def _contar(self, ahora: datetime, lectura: plan.Lectura, ajustes: plan.Ajustes) -> None:
        dia = lectura.ahora.date().isoformat()
        if dia != self.dia:
            self.dia = dia
            self.energia = dict.fromkeys(FUENTES_ENERGIA, 0.0)
        if self._ultimo is None:
            return
        paso = ahora - self._ultimo
        if not timedelta(0) < paso <= MAX_INTERVALO:
            return
        if self._estaba_encendido:
            kwh = ajustes.potencia / 1000 * paso.total_seconds() / 3600
            self.energia["total"] += kwh
            self.energia[self._fuente_anterior] += kwh

        # Consumo de la casa sin el termo, media de cada hora.
        if lectura.consumo is not None and lectura.encendido is not None:
            casa = max(lectura.consumo - (ajustes.potencia if lectura.encendido else 0.0), 0.0)
            hora = ("festivo" if lectura.laborable is False else "laborable", lectura.ahora.hour)
            if hora != self._hora:
                self._cerrar_hora()
                self._hora = hora
            self._hora_suma += casa
            self._hora_muestras += 1

    def _cerrar_hora(self) -> None:
        if self._hora is not None and self._hora_muestras >= MUESTRAS_HORA:
            tipo, hora = self._hora
            media = self._hora_suma / self._hora_muestras
            anterior = self.perfil[tipo][hora]
            self.perfil[tipo][hora] = round(
                media if anterior is None else anterior + PESO_NUEVO * (media - anterior), 1
            )
        self._hora_suma, self._hora_muestras = 0.0, 0

    def _aprender_ciclo(self, ahora: datetime, lectura: plan.Lectura, ajustes: plan.Ajustes) -> None:
        if lectura.encendido is None or lectura.temperatura is None:
            self._ciclo = None
            return
        if lectura.encendido and self._ciclo is None:
            self._ciclo = (ahora, lectura.temperatura)
        elif not lectura.encendido and self._ciclo is not None:
            inicio, temperatura_inicial = self._ciclo
            self._ciclo = None
            duracion = ahora - inicio
            grados = lectura.temperatura - temperatura_inicial
            if duracion >= CICLO_MINIMO and grados >= CICLO_GRADOS:
                valor = ajustes.potencia / 1000 * duracion.total_seconds() / 3600 / grados
                minimo, maximo = plan.KWH_POR_GRADO_LIMITES
                if minimo <= valor <= maximo:
                    self.kwh_por_grado = round(
                        self.kwh_por_grado + PESO_NUEVO * (valor - self.kwh_por_grado), 4
                    )
                    self.ciclos += 1

    # ── Para los sensores y el diagnóstico ─────────────────────────────

    def consumo_casa_de_dia(self) -> float | None:
        """kWh que gasta la casa de 9 a 17 según lo aprendido (None: aún nada)."""
        valores = self.perfil["laborable"][9:17]
        if all(v is None for v in valores):
            return None
        return round(sum(plan.CONSUMO_CASA_INICIAL if v is None else v for v in valores) / 1000, 2)

    def diagnostico(self) -> dict[str, Any]:
        return {
            "decision": {
                "accion": self.decision.accion,
                "calentar": self.decision.calentar,
                "motivo": self.decision.motivo,
                "consigna": self.decision.consigna,
                "datos": self.decision.datos,
            },
            "prevision": self.prevision,
            "memoria": self.memoria.a_dict(),
            "kwh_por_grado": self.kwh_por_grado,
            "ciclos": self.ciclos,
            "perfil": self.perfil,
            "energia": self.energia,
            "ordenado": self.ordenado,
            "manual": self.manual,
            "fuentes": {
                clave: (None if (estado := self._estado(clave)) is None else estado.state)
                for clave in (
                    CONF_INTERRUPTOR, CONF_TEMPERATURA, CONF_FV, CONF_CONSUMO, CONF_RED,
                    CONF_CONTRATADA, CONF_SOC, CONF_PERIODO, CONF_LABORABLE, CONF_PREVISION,
                    CONF_RED_CONECTADA,
                )
            },
        }
