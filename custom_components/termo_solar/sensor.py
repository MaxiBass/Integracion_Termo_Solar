"""Sensores: qué hace (o haría) la integración y por qué."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import plan
from .entity import EntidadTermo
from .gestor import EntradaTermo, GestorTermo


@dataclass(frozen=True, kw_only=True)
class DescripcionTermo(SensorEntityDescription):
    valor: Callable[[GestorTermo], Any]
    atributos: Callable[[GestorTermo], dict[str, Any]] | None = None
    # Se pone a 0 cada medianoche.
    diario: bool = False


def _dato(clave: str) -> Callable[[GestorTermo], Any]:
    return lambda g: g.decision.datos.get(clave)


SENSORES: tuple[DescripcionTermo, ...] = (
    DescripcionTermo(
        key="estado",
        device_class=SensorDeviceClass.ENUM,
        options=list(plan.ACCIONES),
        valor=lambda g: g.decision.accion,
        atributos=lambda g: {
            "motivo": g.decision.motivo,
            "consigna": g.decision.consigna,
            "simulacion": not g.control,
            "objetivo": g.ajustes().objetivo,
            "maxima_con_sol": g.ajustes().maxima_solar,
            "minima_ducha": g.ajustes().minima_ducha,
        },
    ),
    # El motivo, como texto, para ponerlo tal cual en un panel.
    DescripcionTermo(key="motivo", valor=lambda g: g.decision.motivo[:255]),
    DescripcionTermo(
        key="energia_necesaria",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        valor=_dato("necesaria_kwh"),
    ),
    DescripcionTermo(
        key="temperatura_ducha",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        valor=_dato("prevista_ducha"),
    ),
    DescripcionTermo(
        key="excedente",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        valor=_dato("excedente"),
    ),
    DescripcionTermo(
        key="sol_sobrante",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        valor=lambda g: g.prevision.get("sobra_kwh"),
        atributos=lambda g: {k: v for k, v in g.prevision.items() if k != "sobra_kwh"},
    ),
    DescripcionTermo(
        key="energia_hoy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        diario=True,
        valor=lambda g: round(g.energia["total"], 3),
        atributos=lambda g: {k: round(v, 3) for k, v in g.energia.items() if k != "total"},
    ),
    DescripcionTermo(
        key="kwh_por_grado",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="kWh/°C",
        suggested_display_precision=3,
        valor=lambda g: g.kwh_por_grado,
        atributos=lambda g: {"calentados_medidos": g.ciclos},
    ),
    DescripcionTermo(
        key="consumo_casa",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        valor=lambda g: g.consumo_casa_de_dia(),
        atributos=lambda g: dict(g.perfil),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: EntradaTermo, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(SensorTermo(entry, descripcion) for descripcion in SENSORES)


class SensorTermo(EntidadTermo, SensorEntity):
    entity_description: DescripcionTermo

    def __init__(self, entry: EntradaTermo, descripcion: DescripcionTermo) -> None:
        super().__init__(entry, "sensor", descripcion.key)
        self.entity_description = descripcion

    @property
    def native_value(self) -> Any:
        return self.entity_description.valor(self._gestor)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        atributos = self.entity_description.atributos
        return atributos(self._gestor) if atributos else None

    @property
    def last_reset(self) -> datetime | None:
        if not self.entity_description.diario or self._gestor.dia is None:
            return None
        return dt_util.start_of_local_day(datetime.fromisoformat(self._gestor.dia))
