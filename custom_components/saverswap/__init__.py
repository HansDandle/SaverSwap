"""SaverSwap: any video as your Roku's idle screen. Controls for Home Assistant."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CONF_ATTENTION_ONLY, CONF_LABELS, CONF_STATUS_ENTITIES, DOMAIN
from .coordinator import SaverSwapCoordinator
from .overlay import StatusPusher, register_services

PLATFORMS = [Platform.SELECT, Platform.SWITCH, Platform.TEXT, Platform.IMAGE, Platform.BUTTON, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type SaverSwapConfigEntry = ConfigEntry[SaverSwapCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    # saverswap.show_camera / show_message / clear
    register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SaverSwapConfigEntry) -> bool:
    coordinator = SaverSwapCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # status lines on the TV (chosen in the integration's options)
    pusher = StatusPusher(hass, coordinator, entry.options.get(CONF_STATUS_ENTITIES, []),
                          entry.options.get(CONF_ATTENTION_ONLY, False), entry.options.get(CONF_LABELS, ""))
    await pusher.start()
    entry.async_on_unload(pusher.stop)
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass: HomeAssistant, entry: SaverSwapConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SaverSwapConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
