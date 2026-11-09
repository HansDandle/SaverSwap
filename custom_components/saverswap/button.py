"""Buttons: show SaverSwap on each TV now, and add the starter pack."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SaverSwapConfigEntry
from .entity import SaverSwapEntity


async def async_setup_entry(hass: HomeAssistant, entry: SaverSwapConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    c = entry.runtime_data
    entities: list[ButtonEntity] = [StarterButton(c)]
    entities += [ShowButton(c, r) for r in (c.data or {}).get("rokus", [])]
    async_add_entities(entities)


class ShowButton(SaverSwapEntity, ButtonEntity):
    _attr_icon = "mdi:television-play"

    def __init__(self, coordinator, roku: dict) -> None:
        super().__init__(coordinator, f"show_{roku['ip']}")
        self._ip = roku["ip"]
        self._attr_name = f"Show on {roku['name']}"

    async def async_press(self) -> None:
        await self.coordinator.command("/api/rokus/launch", {"ip": self._ip})


class StarterButton(SaverSwapEntity, ButtonEntity):
    _attr_name = "Add starter pack"
    _attr_icon = "mdi:package-variant-plus"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "starter")

    async def async_press(self) -> None:
        await self.coordinator.command("/api/starter")
