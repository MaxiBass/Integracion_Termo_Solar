"""Alta y Configurar: las entidades de las que sale la decisión.

Los ajustes del día a día (temperaturas y horas) no están aquí: son
entidades del dispositivo y se cambian desde un panel sin recargar.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_CAPACIDAD_BATERIA,
    CONF_CONSUMO,
    CONF_CONTRATADA,
    CONF_FV,
    CONF_INTERRUPTOR,
    CONF_LABORABLE,
    CONF_OBJETIVO_ENTIDAD,
    CONF_PERIODO,
    CONF_PREVISION,
    CONF_RED,
    CONF_RED_CONECTADA,
    CONF_SOC,
    CONF_TEMPERATURA,
    DOMAIN,
    FUENTES,
    SUGERIDAS,
)

_POTENCIA = EntitySelector(EntitySelectorConfig(domain="sensor"))
_VALOR = EntitySelector(EntitySelectorConfig(domain=["sensor", "input_number", "number"]))
_BINARIO = EntitySelector(EntitySelectorConfig(domain=["binary_sensor", "input_boolean"]))

ESQUEMA = vol.Schema(
    {
        vol.Required(CONF_INTERRUPTOR): EntitySelector(
            EntitySelectorConfig(domain=["switch", "input_boolean"])
        ),
        vol.Required(CONF_TEMPERATURA): _POTENCIA,
        vol.Optional(CONF_OBJETIVO_ENTIDAD): EntitySelector(
            EntitySelectorConfig(domain=["input_number", "number"])
        ),
        vol.Required(CONF_FV): _POTENCIA,
        vol.Required(CONF_CONSUMO): _POTENCIA,
        vol.Required(CONF_PERIODO): EntitySelector(
            EntitySelectorConfig(domain=["sensor", "input_select", "select"])
        ),
        vol.Optional(CONF_LABORABLE): _BINARIO,
        vol.Optional(CONF_PREVISION): _POTENCIA,
        vol.Optional(CONF_SOC): _POTENCIA,
        vol.Required(CONF_CAPACIDAD_BATERIA, default=0.0): NumberSelector(
            NumberSelectorConfig(min=0, max=200, step=0.1, mode=NumberSelectorMode.BOX, unit_of_measurement="kWh")
        ),
        vol.Optional(CONF_RED): _POTENCIA,
        vol.Optional(CONF_CONTRATADA): _VALOR,
        vol.Optional(CONF_RED_CONECTADA): _BINARIO,
    }
)


def _sugeridas(hass: HomeAssistant) -> dict[str, Any]:
    return {clave: eid for clave, eid in SUGERIDAS.items() if hass.states.get(eid) is not None}


def _validar(datos: dict[str, Any]) -> dict[str, str]:
    usadas = [datos[clave] for clave in FUENTES if datos.get(clave)]
    if len(usadas) != len(set(usadas)):
        return {"base": "misma_entidad"}
    if bool(datos.get(CONF_RED)) != bool(datos.get(CONF_CONTRATADA)):
        return {CONF_CONTRATADA: "falta_pareja"}
    if datos.get(CONF_CAPACIDAD_BATERIA) and not datos.get(CONF_SOC):
        return {CONF_SOC: "falta_soc"}
    return {}


class TermoSolarConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OpcionesTermoSolar:
        return OpcionesTermoSolar()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errores: dict[str, str] = {}
        if user_input is not None:
            errores = _validar(user_input)
            if not errores:
                return self.async_create_entry(title="Termo Solar", data={}, options=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(ESQUEMA, user_input or _sugeridas(self.hass)),
            errors=errores,
        )


class OpcionesTermoSolar(OptionsFlowWithReload):
    """Configurar: cambiar las entidades. Los ajustes y lo aprendido siguen."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errores: dict[str, str] = {}
        if user_input is not None:
            errores = _validar(user_input)
            if not errores:
                # Un campo opcional vaciado desaparece; los ajustes (que no
                # salen en el formulario) se conservan.
                ajustes = {k: v for k, v in self.config_entry.options.items() if k not in ESQUEMA.schema}
                return self.async_create_entry(data={**ajustes, **user_input})
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                ESQUEMA, user_input or dict(self.config_entry.options)
            ),
            errors=errores,
        )
