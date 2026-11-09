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

* **Each video is saved as about 20 minutes.** When a Roku video loops it blinks black for about a second, so SaverSwap saves the first 20 minutes and repeats short clips seamlessly until they're that long. The blink then happens once every 20 minutes.
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

1. Copy `homeassistant/saverswap.yaml` to `/config/packages/`, replace `SAVERSWAP_HOST` with the server's address, and make sure packages are enabled (see the comment at the top of the file). Then restart.
2. Add the cards from `homeassistant/dashboard-card.yaml` to a dashboard.

You get:

* `select.saverswap_scene`
* `switch.saverswap_sound`
* `switch.saverswap_autostart`
* `input_text.saverswap_link` for pasting links

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

## License

MIT
