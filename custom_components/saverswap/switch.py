"""Sound, auto-start, clock and weather switches."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SaverSwapConfigEntry
from .entity import SaverSwapEntity

SWITCHES = [
    # key, name, icon, config (shown under Configuration on the device page)
    ("sound", "Sound", "mdi:volume-high", False),
    ("autostart", "Autostart", "mdi:television-play", False),
    ("clock", "Clock", "mdi:clock-outline", True),
    ("weather", "Weather", "mdi:weather-partly-cloudy", True),
]


async def async_setup_entry(hass: HomeAssistant, entry: SaverSwapConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(SettingSwitch(entry.runtime_data, *s) for s in SWITCHES)


class SettingSwitch(SaverSwapEntity, SwitchEntity):
    def __init__(self, coordinator, key: str, name: str, icon: str, config: bool) -> None:
        super().__init__(coordinator, key)
        self._key = key
        self._attr_name = name
        self._attr_icon = icon
        if config:
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool | None:
        return self.data.get("settings", {}).get(self._key)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.command("/api/settings", {self._key: True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.command("/api/settings", {self._key: False})
