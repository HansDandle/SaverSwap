"""Paste-a-link box: setting it downloads that video as a new scene."""
from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SaverSwapConfigEntry
from .entity import SaverSwapEntity


async def async_setup_entry(hass: HomeAssistant, entry: SaverSwapConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([LinkText(entry.runtime_data)])


class LinkText(SaverSwapEntity, TextEntity):
    _attr_name = "Add video link"
    _attr_icon = "mdi:link-variant-plus"
    _attr_native_max = 255
    _attr_native_value = ""

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "link")

    async def async_set_value(self, value: str) -> None:
        # "Name https://..." names the scene; a bare link uses the video's title.
        if value.strip():
            await self.coordinator.command("/api/add", {"url": value.strip()})
        self._attr_native_value = ""
        self.async_write_ha_state()
