"""Scene picker."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SaverSwapConfigEntry
from .entity import SaverSwapEntity


async def async_setup_entry(hass: HomeAssistant, entry: SaverSwapConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([SceneSelect(entry.runtime_data)])


class SceneSelect(SaverSwapEntity, SelectEntity):
    _attr_name = "Scene"
    _attr_icon = "mdi:television-ambient-light"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "scene")

    @property
    def options(self) -> list[str]:
        return [s["name"] for s in self.data.get("scenes", [])]

    @property
    def current_option(self) -> str | None:
        return self.data.get("current")

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.command("/api/select", {"scene": option})
