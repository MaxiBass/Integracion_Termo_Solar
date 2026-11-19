"""«Control»: encendido, la integración manda sobre el termo; apagado, solo
calcula y enseña lo que haría (simulación)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_CONTROL
from .entity import EntidadTermo
from .gestor import EntradaTermo


async def async_setup_entry(
    hass: HomeAssistant, entry: EntradaTermo, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([Control(entry)])


class Control(EntidadTermo, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: EntradaTermo) -> None:
        super().__init__(entry, "switch", CONF_CONTROL)

    @property
    def is_on(self) -> bool:
        return self._gestor.control

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._gestor.async_cambiar_ajuste(CONF_CONTROL, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._gestor.async_cambiar_ajuste(CONF_CONTROL, False)
