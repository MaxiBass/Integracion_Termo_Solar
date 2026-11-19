"""Las horas: la de la ducha, la del respaldo y el fin del Valle."""
from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import AJUSTES_POR_DEFECTO, HORAS
from .entity import EntidadTermo
from .gestor import EntradaTermo, _hora


async def async_setup_entry(
    hass: HomeAssistant, entry: EntradaTermo, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(Hora(entry, clave) for clave in HORAS)


class Hora(EntidadTermo, TimeEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: EntradaTermo, clave: str) -> None:
        super().__init__(entry, "time", clave)
        self._clave = clave

    @property
    def native_value(self) -> time:
        return _hora(self._gestor.opcion(self._clave), AJUSTES_POR_DEFECTO[self._clave])

    async def async_set_value(self, value: time) -> None:
        await self._gestor.async_cambiar_ajuste(self._clave, value.replace(microsecond=0).isoformat())
