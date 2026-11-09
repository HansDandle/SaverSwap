# SaverSwap

**Turn any video into your Roku's idle screen.** An aquarium, a crackling fireplace for the holidays, a thunderstorm, a beach: paste a link, tap a picture, and that's what your TV shows when nobody's using it. There's a clock and the local weather in the corner, and sound if you want it.

Made when Roku announced it was retiring the Aquatic Life screensaver (December 1, 2026). SaverSwap can't bring back those exact fish, but it can bring back the idea, with any video you like.

## How it works

Roku doesn't allow video or sound in real screensavers. A screensaver that tries to play video gets shut down instantly. So SaverSwap does it differently:

```
 your phone / browser / Home Assistant
              │  pick a scene, paste a link, sound on/off
              ▼
   SaverSwap server (saverswap.py)  ──►  downloads + converts videos (yt-dlp, ffmpeg)
              │
              │  watches the Roku; the moment its normal screensaver
              │  kicks in, launches the SaverSwap app over it
              ▼
   Roku TV: SaverSwap app plays the scene full screen.
            Any button on the remote closes it, just like a screensaver.
```

* **Roku app.** Plays the current scene looped, draws the time and weather, and plays sound if you turned it on. Any remote button closes it and returns you to the Roku. You can also open it from the home screen yourself.
* **Server.** One small Python program on any always-on computer at home (PC, Mac, Raspberry Pi, NAS with Docker). It stores the videos, serves a web page for picking scenes and adding new ones, and watches the Roku for its screensaver so it can take over. It uses Roku's built-in local control API, so no account or cloud is involved.
* **Home Assistant (optional).** A scene dropdown, sound and auto-start switches, a preview, and a paste-a-link box, so automations can switch scenes too (fireplace from December 1, say).

Because it rides on the Roku's own idle timer, it starts exactly when your normal screensaver would.

## Setup

### 1. Run the server

**With Docker:**

```sh
cd server
# edit docker-compose.yml: your Roku's IP, and your latitude/longitude for the weather
docker compose up -d
```

**Or with Python 3.9+** (and [ffmpeg](https://ffmpeg.org/download.html) installed):

```sh
pip install -r server/requirements.txt
python server/saverswap.py --roku 192.168.1.50 --lat 40.71 --lon -74.01
```

Open `http://<that-computer's-IP>:8099` and add your first video. Paste a YouTube link or a direct `.mp4` link, and give it a name if you like.

Options:

* `--roku`: the Roku's IP address, or several separated by commas. Without it SaverSwap only runs when you open it yourself.
* `--lat` / `--lon`: your location for the weather overlay. Leave them out to hide the weather.
* `--units celsius`, `--no-clock`.
* `--port`: default 8099.
* `--data`: where videos are kept, default `server/data`.

Every option also has an environment variable (`SAVERSWAP_ROKU`, `SAVERSWAP_LAT`, …). To find the Roku's IP, go to Settings → Network → About.

> For YouTube links yt-dlp needs a JavaScript runtime; install [Node.js](https://nodejs.org) or [Deno](https://deno.com). The Docker image already includes Node.

### 2. Put your Roku in Developer Mode

On the Roku remote press **Home ×3, Up ×2, Right, Left, Right, Left, Right**. Accept the agreement and set a password. The Roku restarts.

This is Roku's official way to install your own apps, and it's harmless. It allows one homemade app at a time.

### 3. Install the app

From this repo, on any computer on the same network:

```sh
python tools/install_roku.py --roku <ROKU-IP> --password <DEV-PASSWORD>
```

It points the app at the computer you run it from (port 8099). If the server runs somewhere else, add `--server http://<server-IP>:8099`. Once installed, the app starts playing so you can see it.

### 4. Keep a normal screensaver on

In **Settings → Theme → Screensavers**, pick any screensaver (not "None"). Set **Wait time** to however long the TV should sit idle first. When that screensaver starts, SaverSwap takes over about a second later.

## Home Assistant (optional)

1. Copy `homeassistant/saverswap.yaml` to `/config/packages/`, set the server address (replace `SAVERSWAP_HOST`), and make sure packages are enabled (see the comment at the top of the file). Then restart.
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

## Good to know

* **Each video is saved as about 20 minutes.** When a Roku video loops it blinks black for about a second, so SaverSwap saves the first 20 minutes and repeats short clips until they're that long. The blink then happens once every 20 minutes.
* **Sound is saved but off by default.** Turn on **Sound** on the web page or in Home Assistant.
* **Disk space:** a 20-minute 1080p video is roughly 0.5–2 GB. Delete scenes from the web page.
* **Your own files:** drop `.mp4` files (H.264, named like `snowy_cabin.mp4`) into `data/videos/`, then reload the page (or `POST /api/rescan`).
* **If the server is off,** the app shows the clock and keeps retrying, and it won't start by itself.
* **Firmware updates** occasionally remove sideloaded apps. Run the installer again if SaverSwap disappears.
* **Use videos you're allowed to use.** Free sources: [Mixkit](https://mixkit.co/free-stock-video/), [Pexels](https://www.pexels.com/videos/), [Pixabay](https://pixabay.com/videos/).

## API

| Method | Path | Body | |
|---|---|---|---|
| GET | `/api/scene` | | current scene, video URL, all scenes, settings, download jobs |
| POST | `/api/select` | `{"scene": "Fireplace"}` | switch scene (name or slug) |
| POST | `/api/settings` | `{"sound": true, "autostart": true}` | change settings |
| POST | `/api/add` | `{"url": "https://…", "name": "optional"}` | download a video in the background |
| POST | `/api/delete` | `{"scene": "Fireplace"}` | remove a scene and its files |
| POST | `/api/rescan` | | pick up files added to `data/videos/` by hand |

## License

MIT
