"""«Orden de calentar»: lo que la integración manda (o mandaría) al termo.

En simulación sirve para compararlo, en el historial, con lo que hace de
verdad el interruptor del termo.
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import EntidadTermo
from .gestor import EntradaTermo


async def async_setup_entry(
    hass: HomeAssistant, entry: EntradaTermo, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([OrdenCalentar(entry)])


class OrdenCalentar(EntidadTermo, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, entry: EntradaTermo) -> None:
        super().__init__(entry, "binary_sensor", "orden")

    @property
    def is_on(self) -> bool:
        return self._gestor.decision.calentar

    @property
    def extra_state_attributes(self) -> dict:
        return {"modo": self._gestor.decision.accion, "simulacion": not self._gestor.control}
