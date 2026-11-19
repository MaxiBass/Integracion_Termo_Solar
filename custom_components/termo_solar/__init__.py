"""Termo Solar: calienta el termo eléctrico con el sol que sobra y, si no va
a sobrar, en Valle; con una red de seguridad por la tarde para que a la hora
de la ducha haya agua caliente. Ver README y docs/DECISIONES.md.
"""
from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .gestor import EntradaTermo, GestorTermo

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH, Platform.NUMBER, Platform.TIME]


async def async_setup_entry(hass: HomeAssistant, entry: EntradaTermo) -> bool:
    gestor = GestorTermo(hass, entry)
    await gestor.async_cargar()
    entry.runtime_data = gestor
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    gestor.async_arrancar()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EntradaTermo) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_parar()
    return unload_ok
