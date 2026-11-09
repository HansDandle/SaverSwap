"""Picture of the scene that's on the TV."""
from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import SaverSwapConfigEntry
from .entity import SaverSwapEntity


async def async_setup_entry(hass: HomeAssistant, entry: SaverSwapConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([NowShowingImage(hass, entry.runtime_data)])


class NowShowingImage(SaverSwapEntity, ImageEntity):
    _attr_name = "Now showing"
    _attr_content_type = "image/jpeg"

    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        SaverSwapEntity.__init__(self, coordinator, "now_showing")
        ImageEntity.__init__(self, hass)
        self._update_url()

    def _update_url(self) -> None:
        cur = self.data.get("current")
        scene = next((s for s in self.data.get("scenes", []) if s["name"] == cur), None)
        url = scene["thumb"] if scene else None
        if url != self._attr_image_url:
            self._attr_image_url = url
            self._cached_image = None
            self._attr_image_last_updated = dt_util.utcnow()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_url()
        super()._handle_coordinator_update()
