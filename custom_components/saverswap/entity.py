"""Base entity for SaverSwap."""
from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SaverSwapCoordinator


class SaverSwapEntity(CoordinatorEntity[SaverSwapCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: SaverSwapCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"
        self._attr_device_info = coordinator.device_info

    @property
    def data(self) -> dict:
        return self.coordinator.data or {}
