"""SaverSwap: any video as your Roku's idle screen. Controls for Home Assistant."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import SaverSwapCoordinator

PLATFORMS = [Platform.SELECT, Platform.SWITCH, Platform.TEXT, Platform.IMAGE, Platform.BUTTON, Platform.SENSOR]

type SaverSwapConfigEntry = ConfigEntry[SaverSwapCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: SaverSwapConfigEntry) -> bool:
    coordinator = SaverSwapCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SaverSwapConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
