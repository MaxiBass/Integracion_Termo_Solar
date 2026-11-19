"""Diagnóstico descargable: entidades de origen, lo que valen, la última
decisión y lo aprendido. No hay credenciales que ocultar."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .gestor import EntradaTermo


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: EntradaTermo) -> dict[str, Any]:
    return {"opciones": dict(entry.options), **entry.runtime_data.diagnostico()}
