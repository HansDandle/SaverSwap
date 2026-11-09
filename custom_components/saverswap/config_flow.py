"""Set up SaverSwap: just the server's address."""
from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_URL, DEFAULT_PORT, DOMAIN
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
