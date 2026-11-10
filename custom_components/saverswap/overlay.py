"""Home Assistant things shown on the TV: status lines, camera pictures, messages."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.camera import async_get_image
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, ServiceCall, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval

from .const import CONF_ATTENTION_ONLY, CONF_LABELS, CONF_STATUS_ENTITIES, DOMAIN

_LOGGER = logging.getLogger(__name__)

# device classes / domains where "on"/"open" means someone should look
ALERT_BINARY = {"door", "garage_door", "window", "opening", "lock", "moisture", "smoke", "gas", "problem",
                "safety", "carbon_monoxide", "battery", "tamper", "heat", "cold", "vibration"}


def parse_labels(text: str) -> dict[str, str]:
    """'lock.front = Front door' lines -> {entity_id: label}."""
    out = {}
    for line in (text or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if k.strip() and v.strip():
                out[k.strip()] = v.strip()
    return out


def tidy_name(name: str) -> str:
    """'Garage Door Garage Door' -> 'Garage Door' (device name + same entity name)."""
    w = name.split()
    if len(w) % 2 == 0 and w[: len(w) // 2] == w[len(w) // 2:]:
        return " ".join(w[: len(w) // 2])
    return name


def describe(state: State, label: str | None = None) -> tuple[str, bool | None]:
    """Turn a state into (text, needs_attention). needs_attention None = no opinion (always shown)."""
    name = label or tidy_name(state.name)
    domain, s, a = state.domain, state.state, state.attributes
    if s in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return f"{name}: unavailable", None
    if domain == "lock":
        words = {"locked": "Locked", "unlocked": "Unlocked", "open": "Open", "jammed": "Jammed",
                 "locking": "Locking", "unlocking": "Unlocking", "opening": "Opening"}
        return f"{name}: {words.get(s, s)}", s != "locked"
    if domain == "cover":
        return f"{name}: {s.capitalize()}", s not in ("closed",)
    if domain == "binary_sensor":
        dc = a.get("device_class")
        on_off = {"door": ("Open", "Closed"), "garage_door": ("Open", "Closed"), "window": ("Open", "Closed"),
                  "opening": ("Open", "Closed"), "lock": ("Unlocked", "Locked"), "motion": ("Motion", "Clear"),
                  "occupancy": ("Occupied", "Clear"), "presence": ("Home", "Away"), "moisture": ("Wet", "Dry"),
                  "battery": ("Low", "OK"), "problem": ("Problem", "OK"), "smoke": ("Smoke!", "Clear")}
        on, off = on_off.get(dc, ("On", "Off"))
        return f"{name}: {on if s == 'on' else off}", (s == "on") if dc in ALERT_BINARY else None
    if domain == "climate":
        cur, tgt = a.get("current_temperature"), a.get("temperature")
        text = f"{name}: {round(cur) if isinstance(cur, (int, float)) else cur}°"
        if isinstance(tgt, (int, float)):
            text += f" → {round(tgt)}°"
        return text, None
    if domain == "calendar":
        if a.get("message"):
            start = (a.get("start_time") or "")[11:16]
            return f"{a['message']}" + (f" at {start}" if start and start != "00:00" else ""), None
        return "", None
    if domain == "media_player":
        if s == "playing" and a.get("media_title"):
            artist = a.get("media_artist")
            return f"♪ {a['media_title']}" + (f" – {artist}" if artist else ""), None
        return "", None
    if domain == "timer":
        if s == "active":
            return f"{name}: {a.get('remaining', '')}", None
        return "", None
    if domain in ("person", "device_tracker"):
        return f"{name}: {'Home' if s == 'home' else s.replace('_', ' ').capitalize()}", None
    unit = a.get("unit_of_measurement") or ""
    return f"{name}: {s}{(' ' + unit) if unit and unit != '%' else unit}", None


class StatusPusher:
    """Sends the chosen entities' states to the server whenever they change."""

    def __init__(self, hass: HomeAssistant, coordinator, entities: list[str], attention_only: bool,
                 labels: str = "") -> None:
        self.hass, self.coordinator = hass, coordinator
        self.entities, self.attention_only = entities, attention_only
        self.labels = parse_labels(labels)
        self._unsubs: list = []

    async def start(self) -> None:
        if self.entities:
            self._unsubs.append(async_track_state_change_event(self.hass, self.entities, self._changed))
        # calendars and timers change without state events worth tracking; refresh every minute
        from datetime import timedelta
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, timedelta(minutes=1)))
        await self.push()

    def stop(self) -> None:
        for u in self._unsubs:
            u()
        self._unsubs.clear()

    @callback
    def _changed(self, event: Event) -> None:
        self.hass.async_create_task(self.push())

    async def _tick(self, _now) -> None:
        await self.push()

    async def push(self) -> None:
        items = []
        for eid in self.entities:
            st = self.hass.states.get(eid)
            if st is None:
                continue
            text, alert = describe(st, self.labels.get(eid))
            if not text:
                continue
            if self.attention_only and alert is False:
                continue
            items.append({"text": text, "alert": bool(alert)})
        try:
            await self.coordinator.client.post("/api/overlay/status", {"items": items})
        except Exception as err:  # server down: try again on the next change/minute
            _LOGGER.debug("SaverSwap status push failed: %s", err)


SHOW_CAMERA_SCHEMA = vol.Schema({
    vol.Required(ATTR_ENTITY_ID): cv.entity_id,
    vol.Optional("title"): cv.string,
    vol.Optional("seconds", default=30): vol.All(vol.Coerce(int), vol.Range(min=5, max=600)),
    vol.Optional("refresh", default=5): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
    vol.Optional("turn_on_tv", default=True): cv.boolean,
    # True: if this camera is already on the TV, hide it instead (one dashboard button shows and hides)
    vol.Optional("toggle", default=False): cv.boolean,
})
SHOW_MESSAGE_SCHEMA = vol.Schema({
    vol.Required("message"): cv.string,
    vol.Optional("seconds", default=30): vol.All(vol.Coerce(int), vol.Range(min=3, max=3600)),
    vol.Optional("turn_on_tv", default=False): cv.boolean,
})
CLEAR_SCHEMA = vol.Schema({vol.Optional("what", default="all"): vol.In(["all", "camera", "message"])})


def _clients(hass: HomeAssistant):
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise HomeAssistantError("SaverSwap isn't set up")
    return [e.runtime_data.client for e in entries]


def register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, "show_camera"):
        return
    camera_tasks: dict[str, asyncio.Task] = {}
    showing: dict[str, Any] = {}  # {"entity": camera on the TV now, "end": loop time it goes away}

    async def hide_camera() -> None:
        task = camera_tasks.pop("popup", None)
        if task:
            task.cancel()
        showing.clear()
        for client in _clients(hass):
            await client.post("/api/overlay/clear", {"what": "popup"})

    async def show_camera(call: ServiceCall) -> None:
        eid = call.data[ATTR_ENTITY_ID]
        state = hass.states.get(eid)
        title = call.data.get("title") or (state.name if state else eid)
        seconds, refresh = call.data["seconds"], call.data["refresh"]
        launch = call.data["turn_on_tv"]

        loop_ = asyncio.get_running_loop()
        if (call.data["toggle"] and showing.get("entity") == eid
                and showing.get("end", 0) > loop_.time()):
            await hide_camera()
            return
        end = loop_.time() + seconds

        async def send(first: bool) -> None:
            img = await async_get_image(hass, eid, timeout=20)
            left = max(3, int(end - loop_.time()))
            for client in _clients(hass):
                await client.post_raw("/api/overlay/popup", img.content,
                                      {"title": title, "seconds": left, "launch": "1" if (first and launch) else "0"})

        async def refresh_loop() -> None:
            # keep the picture fresh until time's up (each camera grab can take a few seconds)
            while True:
                await asyncio.sleep(refresh)
                if loop_.time() >= end - 2:
                    return
                try:
                    await send(False)
                except Exception as err:
                    _LOGGER.debug("camera refresh failed: %s", err)

        old = camera_tasks.pop("popup", None)
        if old:
            old.cancel()
        # send the first picture right away (errors reach the caller), then keep refreshing in the background
        try:
            await send(True)
        except Exception as err:
            raise HomeAssistantError(f"Couldn't get a picture from {eid}: {err}") from err
        task = hass.async_create_background_task(refresh_loop(), "saverswap camera refresh")
        camera_tasks["popup"] = task
        showing.update(entity=eid, end=end)

    async def show_message(call: ServiceCall) -> None:
        for client in _clients(hass):
            await client.post("/api/overlay/message", {"text": call.data["message"], "seconds": call.data["seconds"],
                                                       "launch": call.data["turn_on_tv"]})

    async def clear(call: ServiceCall) -> None:
        what = call.data["what"]
        if what == "camera":
            return await hide_camera()
        if what == "all":
            task = camera_tasks.pop("popup", None)
            if task:
                task.cancel()
            showing.clear()
        for client in _clients(hass):
            await client.post("/api/overlay/clear", {"what": what})

    hass.services.async_register(DOMAIN, "show_camera", show_camera, SHOW_CAMERA_SCHEMA)
    hass.services.async_register(DOMAIN, "show_message", show_message, SHOW_MESSAGE_SCHEMA)
    hass.services.async_register(DOMAIN, "clear", clear, CLEAR_SCHEMA)
