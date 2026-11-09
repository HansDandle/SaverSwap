"""Download status and storage sensors."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SaverSwapConfigEntry
from .entity import SaverSwapEntity


async def async_setup_entry(hass: HomeAssistant, entry: SaverSwapConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    c = entry.runtime_data
    async_add_entities([DownloadSensor(c), FreeSpaceSensor(c)])


class DownloadSensor(SaverSwapEntity, SensorEntity):
    """'Idle', or what's being added (e.g. 'Beach: Downloading')."""

    _attr_name = "Downloads"
    _attr_icon = "mdi:download"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "downloads")

    @property
    def native_value(self) -> str:
        busy = [j for j in self.data.get("jobs", []) if j["status"] != "failed"]
        if not busy:
            return "Idle"
        return f"{busy[0]['name'] or 'Video'}: {busy[0]['status']}" + (f" (+{len(busy) - 1})" if len(busy) > 1 else "")

    @property
    def extra_state_attributes(self) -> dict:
        return {"failed": [f"{j['name'] or j['url']}: {j['error']}"
                           for j in self.data.get("jobs", []) if j["status"] == "failed"]}


class FreeSpaceSensor(SaverSwapEntity, SensorEntity):
    _attr_name = "Free space"
    _attr_icon = "mdi:harddisk"
    _attr_native_unit_of_measurement = UnitOfInformation.GIGABYTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "free_space")

    @property
    def native_value(self) -> float | None:
        return self.data.get("storage", {}).get("free_gb")
