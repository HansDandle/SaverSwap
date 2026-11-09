"""Polls the SaverSwap server and sends commands to it."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_URL, DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class SaverSwapClient:
    """Tiny client for the SaverSwap JSON API."""

    def __init__(self, hass: HomeAssistant, url: str) -> None:
        self.url = url.rstrip("/")
        self._session = async_get_clientsession(hass)

    async def get_scene(self) -> dict[str, Any]:
        async with self._session.get(f"{self.url}/api/scene", timeout=aiohttp.ClientTimeout(total=10)) as r:
            r.raise_for_status()
            return await r.json()

    async def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        async with self._session.post(f"{self.url}{path}", json=body or {},
                                      timeout=aiohttp.ClientTimeout(total=120)) as r:
            data = await r.json(content_type=None)
            if r.status >= 400:
                raise HomeAssistantError(data.get("error") or f"SaverSwap answered {r.status}")
            return data


class SaverSwapCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Keeps the server's state (scenes, settings, TVs, downloads) fresh."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.client = SaverSwapClient(hass, entry.data[CONF_URL])

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.get_scene()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Can't reach SaverSwap at {self.client.url}: {err}") from err

    async def command(self, path: str, body: dict[str, Any] | None = None) -> None:
        """Send a command, then use the fresh state the server returns."""
        try:
            data = await self.client.post(path, body)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError(f"Can't reach SaverSwap: {err}") from err
        if "scenes" in data:
            self.async_set_updated_data(data)
        else:
            await self.async_request_refresh()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.config_entry.entry_id)},
            name="SaverSwap",
            manufacturer="SaverSwap",
            model="Roku idle-screen server",
            sw_version=(self.data or {}).get("version"),
            configuration_url=self.client.url,
        )
