"""Ajustes numéricos, para cambiarlos desde un panel sin recargar."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import NUMEROS
from .entity import EntidadTermo
from .gestor import EntradaTermo


async def async_setup_entry(
    hass: HomeAssistant, entry: EntradaTermo, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(Ajuste(entry, clave) for clave in NUMEROS)


class Ajuste(EntidadTermo, NumberEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(self, entry: EntradaTermo, clave: str) -> None:
        super().__init__(entry, "number", clave)
        self._clave = clave
        minimo, maximo, paso, unidad = NUMEROS[clave]
        self._attr_native_min_value = minimo
        self._attr_native_max_value = maximo
        self._attr_native_step = paso
        self._attr_native_unit_of_measurement = unidad

    @property
    def native_value(self) -> float:
        return float(self._gestor.opcion(self._clave))

    async def async_set_native_value(self, value: float) -> None:
        await self._gestor.async_cambiar_ajuste(self._clave, float(value))
