"""Set up SaverSwap: just the server's address."""
from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import CONF_ATTENTION_ONLY, CONF_LABELS, CONF_STATUS_ENTITIES, CONF_URL, DEFAULT_PORT, DOMAIN
from .coordinator import SaverSwapClient


def normalize(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    host = url.split("://", 1)[1]
    if ":" not in host.split("/")[0]:
        url = f"{url}:{DEFAULT_PORT}"
    return url


class SaverSwapConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SaverSwapOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = normalize(user_input[CONF_URL])
            try:
                await SaverSwapClient(self.hass, url).get_scene()
            except (aiohttp.ClientError, TimeoutError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="SaverSwap", data={CONF_URL: url})
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_URL, default=(user_input or {}).get(CONF_URL, "")): str}),
            errors=errors,
        )


class SaverSwapOptionsFlow(OptionsFlow):
    """Pick what Home Assistant shows on the TV under the clock and weather."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_STATUS_ENTITIES, default=opts.get(CONF_STATUS_ENTITIES, [])):
                    selector.EntitySelector(selector.EntitySelectorConfig(
                        multiple=True,
                        domain=["lock", "cover", "binary_sensor", "climate", "sensor", "calendar",
                                "media_player", "timer", "person", "device_tracker", "input_boolean",
                                "switch", "alarm_control_panel"])),
                vol.Optional(CONF_ATTENTION_ONLY, default=opts.get(CONF_ATTENTION_ONLY, False)): bool,
                vol.Optional(CONF_LABELS, default=opts.get(CONF_LABELS, "")):
                    selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
            }),
        )
