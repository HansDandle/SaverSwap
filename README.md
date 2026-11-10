# SaverSwap

**Turn any video into your Roku's idle screen.** An aquarium, a crackling fireplace for the holidays, a thunderstorm, a beach: paste a link, tap a picture, and that's what your TV shows when nobody's using it. There's a clock and the local weather in the corner, and sound if you want it.

Made when Roku announced it was retiring the Aquatic Life screensaver (December 1, 2026). SaverSwap can't bring back those exact fish, but it can bring back the idea, with any video you like.

## Setup (about 5 minutes)

You need a Roku (stick, box or Roku TV) and a computer at home that stays on: a PC, Mac, Raspberry Pi or NAS that can run Docker.

**1. Start SaverSwap** on that computer:

```sh
docker run -d --name saverswap --restart unless-stopped -p 8099:8099 \
  -v ./saverswap-data:/data ghcr.io/hansdandle/saverswap:latest
```

Or download [`docker-compose.yml`](docker-compose.yml) and run `docker compose up -d`. On a Synology, Unraid or similar NAS, add the image `ghcr.io/hansdandle/saverswap` in its Docker/Container app with port 8099 and a folder mapped to `/data`.

**2. Open `http://<that computer's address>:8099` on your phone or computer.** Use the computer's network address, like `http://192.168.1.10:8099`, not `localhost`. Then follow the page:

1. **Find my Roku.** The page searches your network and lists your Rokus.
2. **Turn on Developer Mode.** The page shows how. It's Roku's official, free way to add your own app and takes a minute with the remote.
3. **Install.** Type the password you set on the TV. SaverSwap appears on the TV.
4. **Add scenes.** Tap **Starter pack** (aquarium, fireplace, rain, beach, snow) or paste any YouTube or `.mp4` link.
5. **Set your location** for the weather, and choose sound, clock and °F/°C.

That's it. Keep any normal screensaver selected on the Roku (Settings → Theme → Screensavers) and set its wait time. When it kicks in, SaverSwap takes over about a second later. Any button on the remote closes it.

## How it works

Roku doesn't allow video or sound in real screensavers. A screensaver that tries to play video gets shut down instantly. So SaverSwap does it differently:

```
 phone / browser / Home Assistant ──► SaverSwap server ──► downloads + converts videos
                                         │
                                         │ watches the Roku; when its normal screensaver
                                         │ starts, launches the SaverSwap app over it
                                         ▼
                              Roku: plays the scene full screen.
                              Any remote button closes it, like a screensaver.
```

It uses Roku's built-in local control API (ECP) and Developer Mode installer. There are no accounts, no cloud, and nothing leaves your home except downloading the videos you ask for and the weather.

## Good to know

* **Each video is saved as about 20 minutes** (changeable in Settings, 5–60). When a Roku video loops it blinks black for about a second, so SaverSwap saves the first 20 minutes and repeats short clips seamlessly until they're that long. The blink then happens once every 20 minutes. A 10-hour YouTube video only downloads its first 20 minutes.
* **Portrait (phone) videos** are fitted to the TV with a blurred copy of themselves filling the sides, instead of black bars.
* **Disk space:** roughly 0.5–2 GB per scene. The page shows usage, and scenes can be deleted there.
* **Where videos are kept:** the folder you map to `/data` (Docker), or `--data <folder>` without Docker.
* **Your own files:** drop `.mp4` files (H.264, named like `snowy_cabin.mp4`) into `data/videos/`, then reload the page.
* **If the computer is off,** SaverSwap won't start, and if you open it the TV shows a message.
* **Roku updates** occasionally remove sideloaded apps. Tap **Reinstall** on the page; the password is remembered.
* **Use videos you're allowed to use.** The starter pack is downloaded straight from [Mixkit](https://mixkit.co/free-stock-video/) (free license). [Pexels](https://www.pexels.com/videos/) and [Pixabay](https://pixabay.com/videos/) are other good free sources.
* Only one homemade app can be installed on a Roku at a time. That's a Roku rule.

## Without Docker

You need Python 3.9+ and [ffmpeg](https://ffmpeg.org/download.html). For YouTube links, also [Node.js](https://nodejs.org) or [Deno](https://deno.com).

```sh
pip install -r server/requirements.txt
python server/saverswap.py            # then open http://<this computer's address>:8099
```

Options: `--data` (video folder), `--port` (default 8099), `--url` (the address the TV should use, if the automatic one is wrong). If you prefer the command line, `tools/install_roku.py` installs the app without the web page.

## Home Assistant (optional)

SaverSwap has a Home Assistant integration: no YAML, everything set up from the UI.

**Install it**, any one of these ways:

* **From HACS, or the built-in Marketplace that replaces it in Home Assistant 2026.11:** add `https://github.com/HansDandle/SaverSwap` as a custom repository (type: Integration), then install **SaverSwap**.
* **By hand:** copy `custom_components/saverswap` into your Home Assistant `config/custom_components/` folder.

Restart Home Assistant, then go to **Settings → Devices & services → Add integration → SaverSwap** and enter the server's address (like `192.168.1.10`).

You get a **SaverSwap** device with:

| Entity | What it does |
|---|---|
| `select.saverswap_scene` | pick the scene |
| `image.saverswap_now_showing` | picture of the current scene |
| `text.saverswap_add_video_link` | paste a link to add a video (`Name https://…` names it) |
| `switch.saverswap_sound`, `switch.saverswap_autostart` | sound, start when the TV goes idle |
| `switch.saverswap_clock`, `switch.saverswap_weather` | overlay on/off |
| `button.saverswap_show_on_<tv>` | show SaverSwap on that TV now |
| `button.saverswap_add_starter_pack` | add the starter scenes |
| `sensor.saverswap_downloads`, `sensor.saverswap_free_space` | what's being added, disk space |
| actions `saverswap.show_camera`, `saverswap.show_message`, `saverswap.clear` | put a camera picture or a message on the TV |

### On the TV: status lines, cameras and messages

* **Status lines.** In **Settings → Devices & services → SaverSwap → Configure**, pick entities to show under the clock: locks, doors, garage, thermostat, calendar, what's playing, timers, people. Locks and doors that need attention (unlocked, open) show in amber. Turn on **only when they need attention** to keep the screen clean, and rename lines for the TV (`lock.front_door = Front door`).
* **Camera in the corner:** the action `saverswap.show_camera` shows a camera's picture, refreshed every few seconds, for as long as you say. With **Bring up SaverSwap** on, it also opens SaverSwap on TVs that are idle (home screen or screensaver); it never interrupts something you're watching. A Roku can only play one video at a time, so cameras are refreshed still pictures, not live video.
* **Messages:** the action `saverswap.show_message` shows a line of text at the bottom ("Laundry's done").

Doorbell example:

```yaml
- alias: Doorbell on the TV
  triggers:
    - trigger: state
      entity_id: event.front_doorbell_ring   # your doorbell's event or binary_sensor
  actions:
    - action: saverswap.show_camera
      data:
        entity_id: camera.front_door
        title: Someone's at the door
        seconds: 45
```

Example dashboard card:

```yaml
type: vertical-stack
cards:
  - type: tile
    entity: select.saverswap_scene
    name: Screensaver
    features:
      - type: select-options
  - type: picture-entity
    entity: image.saverswap_now_showing
    show_name: false
    show_state: false
  - type: entities
    entities:
      - switch.saverswap_sound
      - switch.saverswap_autostart
      - text.saverswap_add_video_link
```

Example automation:

```yaml
- alias: Fireplace for the holidays
  triggers:
    - trigger: template
      value_template: "{{ now().month == 12 }}"
  actions:
    - action: select.select_option
      target: { entity_id: select.saverswap_scene }
      data: { option: Fireplace }
```

## API

| Method | Path | Body | |
|---|---|---|---|
| GET | `/api/scene` | | current scene, scenes, settings, TVs, storage, download jobs |
| POST | `/api/select` | `{"scene": "Fireplace"}` | switch scene (name or slug) |
| POST | `/api/settings` | `{"sound": true}` | also `autostart`, `clock`, `weather`, `units`, `lat`+`lon`+`place` |
| POST | `/api/add` | `{"url": "https://…", "name": "optional"}` | download a video in the background |
| POST | `/api/starter` | | add the starter pack |
| POST | `/api/rename` | `{"scene": "…", "name": "…"}` | rename a scene |
| POST | `/api/delete` | `{"scene": "Fireplace"}` | remove a scene and its files |
| GET | `/api/rokus/scan` | | find Rokus on the network |
| POST | `/api/rokus/add`, `/api/rokus/remove` | `{"ip": "…"}` | add or remove a TV |
| POST | `/api/rokus/install` | `{"ip": "…", "password": "…"}` | install the app on a TV |
| POST | `/api/rokus/launch` | `{"ip": "…"}` | show SaverSwap on a TV now |
| POST | `/api/overlay/status` | `{"items": [{"text": "Front door: Unlocked", "alert": true}]}` | status lines under the clock |
| POST | `/api/overlay/popup?title=…&seconds=30&launch=1` | a JPEG | picture in the corner |
| POST | `/api/overlay/message` | `{"text": "…", "seconds": 30}` | message banner |
| POST | `/api/overlay/clear` | `{"what": "all"}` | remove picture/message |

## License

MIT
