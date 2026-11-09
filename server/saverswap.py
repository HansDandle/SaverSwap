#!/usr/bin/env python3
"""SaverSwap server: hosts screensaver videos for the SaverSwap Roku app.

  * web page (/) to pick the scene, add a video from a link (YouTube or any
    page/file yt-dlp understands, or a plain .mp4), and delete scenes
  * JSON API for the Roku app and for Home Assistant
  * serves the videos (with HTTP Range support) and thumbnails

Needs Python 3.9+, ffmpeg/ffprobe on PATH, and yt-dlp (pip install "yt-dlp[default]")
for adding videos from links. Everything is kept in the data folder.
"""
import argparse
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

LOOP_SECONDS = 1200  # files are repeated to ~20 min: the Roku blinks black for ~1 s on each loop
HERE = os.path.dirname(os.path.abspath(__file__))
_lock = threading.Lock()
jobs = {}  # id -> {"url", "name", "status", "error"}


# ---------------------------------------------------------------- state

class Store:
    def __init__(self, data_dir, settings):
        self.dir = os.path.abspath(data_dir)
        self.videos = os.path.join(self.dir, "videos")
        self.thumbs = os.path.join(self.dir, "thumbs")
        self.tmp = os.path.join(self.dir, "tmp")
        for d in (self.videos, self.thumbs, self.tmp):
            os.makedirs(d, exist_ok=True)
        self.path = os.path.join(self.dir, "state.json")
        self.settings = settings
        self.state = {"current": None, "scenes": []}
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.state = json.load(f)
        self.state.setdefault("sound", False)      # play the video's sound on the TV
        self.state.setdefault("autostart", True)   # launch when the Roku's screensaver starts
        self.scan()

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=1)
        os.replace(tmp, self.path)

    def scan(self):
        """Pick up .mp4 files dropped into videos/ by hand; forget deleted ones."""
        with _lock:
            known = {s["slug"] for s in self.state["scenes"]}
            for fn in sorted(os.listdir(self.videos)):
                slug, ext = os.path.splitext(fn)
                if ext.lower() == ".mp4" and slug not in known and re.fullmatch(r"[a-z0-9_]+", slug):
                    self.state["scenes"].append({"slug": slug, "name": slug.replace("_", " ").title()})
                    make_thumb(os.path.join(self.videos, fn), os.path.join(self.thumbs, slug + ".jpg"))
            self.state["scenes"] = [s for s in self.state["scenes"]
                                    if os.path.exists(os.path.join(self.videos, s["slug"] + ".mp4"))]
            for s in self.state["scenes"]:
                thumb = os.path.join(self.thumbs, s["slug"] + ".jpg")
                if not os.path.exists(thumb):
                    make_thumb(os.path.join(self.videos, s["slug"] + ".mp4"), thumb)
            slugs = [s["slug"] for s in self.state["scenes"]]
            if self.state["current"] not in slugs:
                self.state["current"] = slugs[0] if slugs else None
            self.save()

    def find(self, key):
        key = (key or "").strip().lower()
        for s in self.state["scenes"]:
            if key in (s["slug"], s["name"].lower()):
                return s
        return None


def slugify(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


# ---------------------------------------------------------------- video work

def run(args, timeout=3600):
    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    if p.returncode != 0:
        lines = (p.stderr or p.stdout).strip().splitlines() or ["failed"]
        raise RuntimeError(lines[-1][:300])
    return p.stdout


def probe(path):
    d = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=codec_name,height:format=duration", "-of", "json", path], 120))
    s = d["streams"][0]
    return s["codec_name"], int(s.get("height") or 0), float(d["format"]["duration"])


def make_thumb(video, out):
    try:
        _, _, dur = probe(video)
        run(["ffmpeg", "-v", "error", "-y", "-ss", str(min(10, dur / 3)), "-i", video,
             "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", out], 120)
    except Exception as e:
        print(f"thumbnail failed for {video}: {e}", file=sys.stderr)


def add_video(store, job_id, url, name):
    job = jobs[job_id]
    try:
        for f in os.listdir(store.tmp):
            os.remove(os.path.join(store.tmp, f))
        ytdlp = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--js-runtimes", "node,deno"]
        job["status"] = "Looking up the video"
        if not name:
            title = run(ytdlp + ["--skip-download", "--print", "title", url], 300).strip().splitlines()
            name = title[0] if title else "Video"
            if re.fullmatch(r"[\w-]*\d[\w-]*", name):  # bare file names like 30252-720
                name = "Video"
        name = re.sub(r"\s+", " ", re.sub(r"[\[\(].*?[\]\)]", "", name)).strip(" -|") or "Video"
        if len(name) > 40:
            name = name[:40].rsplit(" ", 1)[0]
        with _lock:
            base, n = name, 2
            while store.find(name) or store.find(slugify(name)) or not slugify(name):
                name, n = f"{base} {n}", n + 1
        job["name"] = name
        slug = slugify(name)

        job["status"] = "Downloading"
        run(ytdlp + ["-f", "bv*[vcodec^=avc1][height<=1080]+ba[ext=m4a]/bv*[height<=1080]+ba"
                           "/b[height<=1080]/bv*[height<=1080]/b",
                     "--merge-output-format", "mp4", "--download-sections", f"*0-{LOOP_SECONDS}",
                     "-o", os.path.join(store.tmp, "dl.%(ext)s"), url])
        src = os.path.join(store.tmp, next(f for f in os.listdir(store.tmp) if f.startswith("dl.")))

        job["status"] = "Converting for the Roku"
        codec, height, dur = probe(src)
        clean = os.path.join(store.tmp, "clean.mp4")
        # keep the sound (AAC) so it can be turned on; it's muted unless "Sound" is on
        audio = ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "160k"]
        if codec == "h264" and height <= 1080:
            run(["ffmpeg", "-v", "error", "-y", "-i", src, "-map", "0:v:0", "-c:v", "copy"] + audio + [clean])
        else:
            run(["ffmpeg", "-v", "error", "-y", "-i", src, "-map", "0:v:0",
                 "-vf", "scale=-2:'min(1080,ih)',fps=30,format=yuv420p", "-c:v", "libx264",
                 "-preset", "veryfast", "-crf", "22", "-profile:v", "high", "-level", "4.1"] + audio + [clean])
        loops = max(0, math.ceil(LOOP_SECONDS / dur) - 1) if dur > 0 else 0
        dest = os.path.join(store.videos, slug + ".mp4")
        run(["ffmpeg", "-v", "error", "-y", "-stream_loop", str(loops), "-i", clean,
             "-c", "copy", "-movflags", "+faststart", dest])
        make_thumb(clean, os.path.join(store.thumbs, slug + ".jpg"))
        for f in os.listdir(store.tmp):
            os.remove(os.path.join(store.tmp, f))

        with _lock:
            store.state["scenes"].append({"slug": slug, "name": name})
            store.state["current"] = slug
            store.save()
        job["status"] = "done"
    except Exception as e:
        job["status"], job["error"] = "failed", str(e)


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    store = None  # set in main()
    # HTTP/1.1 keep-alive + ranges like a real web server (every reply sets Content-Length);
    # the Roku video player is happier with it than with HTTP/1.0.
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def send_json(self, body, code=200):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def base_url(self):
        return f"http://{self.headers.get('Host') or 'localhost'}"

    def scene_payload(self):
        st, s = self.store.state, self.store.settings
        cur = self.store.find(st["current"])
        return {
            "current": cur["name"] if cur else None,
            "video": f"{self.base_url()}/videos/{cur['slug']}.mp4" if cur else None,
            "scenes": [{"name": x["name"], "slug": x["slug"],
                        "thumb": f"{self.base_url()}/thumbs/{x['slug']}.jpg"} for x in st["scenes"]],
            "overlay": {"clock": s["clock"], "weather": s["lat"] is not None,
                        "lat": s["lat"], "lon": s["lon"], "units": s["units"], "sound": st["sound"]},
            "settings": {"sound": st["sound"], "autostart": st["autostart"], "rokus": s["rokus"]},
            "jobs": [dict(id=k, **v) for k, v in jobs.items() if v["status"] != "done"],
        }

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            return self.send_file(os.path.join(HERE, "index.html"), "text/html; charset=utf-8")
        if path == "/api/scene":
            return self.send_json(self.scene_payload())
        if path == "/api/log":  # diagnostics from the Roku app
            from urllib.parse import parse_qs
            msg = parse_qs(urlparse(self.path).query).get("msg", [""])[0][:500]
            print(f"roku {self.client_address[0]}: {msg}", flush=True)
            return self.send_json({"ok": True})
        m = re.fullmatch(r"/(videos|thumbs)/([a-z0-9_]+)\.(mp4|jpg)", path)
        if m:
            folder = self.store.videos if m.group(1) == "videos" else self.store.thumbs
            return self.send_file(os.path.join(folder, f"{m.group(2)}.{m.group(3)}"))
        self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self.read_json()
        if path == "/api/select":
            s = self.store.find(body.get("scene"))
            if not s:
                return self.send_json({"error": "no such scene"}, 404)
            with _lock:
                self.store.state["current"] = s["slug"]
                self.store.save()
            return self.send_json(self.scene_payload())
        if path == "/api/add":
            text = (body.get("url") or "").strip()
            m = re.search(r"https?://\S+", text)
            if not m:
                return self.send_json({"error": "that doesn't look like a link"}, 400)
            name = (body.get("name") or (text[:m.start()] + " " + text[m.end():])).strip(" -:|")
            job_id = uuid.uuid4().hex[:8]
            jobs[job_id] = {"url": m.group(0), "name": name or "", "status": "Queued", "error": None}
            threading.Thread(target=self.worker, args=(job_id, m.group(0), name), daemon=True).start()
            return self.send_json({"job": job_id}, 202)
        if path == "/api/delete":
            s = self.store.find(body.get("scene"))
            if not s:
                return self.send_json({"error": "no such scene"}, 404)
            for p in (os.path.join(self.store.videos, s["slug"] + ".mp4"),
                      os.path.join(self.store.thumbs, s["slug"] + ".jpg")):
                if os.path.exists(p):
                    os.remove(p)
            self.store.scan()
            return self.send_json(self.scene_payload())
        if path == "/api/settings":
            with _lock:
                for k in ("sound", "autostart"):
                    if isinstance(body.get(k), bool):
                        self.store.state[k] = body[k]
                self.store.save()
            return self.send_json(self.scene_payload())
        if path == "/api/rescan":
            self.store.scan()
            return self.send_json(self.scene_payload())
        self.send_json({"error": "not found"}, 404)

    _queue = threading.Lock()  # one download at a time

    def worker(self, job_id, url, name):
        with Handler._queue:
            add_video(self.store, job_id, url, name)

    def send_file(self, path, ctype=None):
        if not os.path.isfile(path):
            return self.send_json({"error": "not found"}, 404)
        size = os.path.getsize(path)
        ctype = ctype or mimetypes.guess_type(path)[0] or "application/octet-stream"
        start, end = 0, size - 1
        rng = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        if rng and (rng.group(1) or rng.group(2)):
            if rng.group(1):
                start = int(rng.group(1))
                end = min(int(rng.group(2)), size - 1) if rng.group(2) else size - 1
            else:
                start = max(0, size - int(rng.group(2)))
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_HEAD(self):
        self.do_GET()


def watch_rokus(store, rokus):
    """Roku forbids video in real screensavers, so SaverSwap is an app: when a Roku's
    own screensaver starts (it shows up in ECP /query/active-app), launch SaverSwap
    over it. Any remote button closes SaverSwap again."""
    last = {}
    while True:
        for ip in rokus:
            try:
                with urllib.request.urlopen(f"http://{ip}:8060/query/active-app", timeout=5) as r:
                    active = r.read().decode("utf-8", "replace")
                if ("<screensaver" in active and store.state["autostart"] and store.state["scenes"]
                        and time.time() - last.get(ip, 0) > 30):
                    urllib.request.urlopen(urllib.request.Request(
                        f"http://{ip}:8060/launch/dev", data=b"", method="POST"), timeout=5).close()
                    last[ip] = time.time()
                    print(f"screensaver started on {ip}: launched SaverSwap", flush=True)
            except Exception as e:
                if time.time() - last.get(f"err{ip}", 0) > 600:
                    print(f"can't reach Roku {ip}: {e}", file=sys.stderr, flush=True)
                    last[f"err{ip}"] = time.time()
        time.sleep(10)


def main():
    env = os.environ.get
    ap = argparse.ArgumentParser(description="SaverSwap server")
    ap.add_argument("--data", default=env("SAVERSWAP_DATA", os.path.join(HERE, "data")),
                    help="folder for videos, thumbnails and state (default: ./data)")
    ap.add_argument("--port", type=int, default=int(env("SAVERSWAP_PORT", "8099")))
    ap.add_argument("--lat", type=float, default=float(env("SAVERSWAP_LAT")) if env("SAVERSWAP_LAT") else None,
                    help="latitude for the weather overlay (leave out to hide weather)")
    ap.add_argument("--lon", type=float, default=float(env("SAVERSWAP_LON")) if env("SAVERSWAP_LON") else None)
    ap.add_argument("--units", choices=["fahrenheit", "celsius"], default=env("SAVERSWAP_UNITS", "fahrenheit"))
    ap.add_argument("--no-clock", action="store_true", default=env("SAVERSWAP_CLOCK", "1") == "0")
    ap.add_argument("--roku", default=env("SAVERSWAP_ROKU", ""),
                    help="Roku IP address(es), comma-separated: launch SaverSwap when its screensaver starts")
    a = ap.parse_args()
    if (a.lat is None) != (a.lon is None):
        ap.error("--lat and --lon go together")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print(f"warning: {tool} not found on PATH; adding videos from links won't work", file=sys.stderr)
    rokus = [r.strip() for r in a.roku.split(",") if r.strip()]
    Handler.store = Store(a.data, {"lat": a.lat, "lon": a.lon, "units": a.units,
                                   "clock": not a.no_clock, "rokus": rokus})
    if rokus:
        threading.Thread(target=watch_rokus, args=(Handler.store, rokus), daemon=True).start()
    else:
        print("no --roku given: SaverSwap won't start by itself when the TV goes idle", file=sys.stderr)
    print(f"SaverSwap on http://0.0.0.0:{a.port}  (data: {Handler.store.dir})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
