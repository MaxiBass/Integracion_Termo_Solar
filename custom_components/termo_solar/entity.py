"""Base de las entidades: un solo dispositivo de tipo servicio."""
from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .gestor import EntradaTermo, senal_actualizado


class EntidadTermo(Entity):
    """Se refresca cada vez que el gestor decide. `entity_id` fijo."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: EntradaTermo, dominio: str, clave: str) -> None:
        self._gestor = entry.runtime_data
        self._attr_translation_key = clave
        self._attr_unique_id = f"{DOMAIN}_{clave}"
        self.entity_id = f"{dominio}.{DOMAIN}_{clave}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Termo Solar",
            manufacturer="MaxiBass",
            model="Control del termo",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, senal_actualizado(self._gestor.entry.entry_id), self._al_actualizar
            )
        )

    @callback
    def _al_actualizar(self) -> None:
        self.async_write_ha_state()
