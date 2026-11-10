#!/usr/bin/env python3
"""SaverSwap server: turns any video into a Roku's idle screen.

  * web page (/) to set everything up: find the Roku, open Developer Mode,
    install the app, pick scenes, add videos from links, sound, weather, clock
  * watches each Roku and launches the SaverSwap app the moment the Roku's own
    screensaver starts (Roku doesn't allow video inside real screensavers)
  * JSON API for the Roku app and Home Assistant; serves videos (with Range
    support) and thumbnails

Needs Python 3.9+, ffmpeg/ffprobe on PATH, and yt-dlp (pip install "yt-dlp[default]").
Everything is kept in the data folder.
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
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import rokus

VERSION = "1.5.0"
# Each scene is stored as one file of "clip_minutes" (setting, default 20): long videos are cut
# to that length, short ones are repeated up to it (the Roku blinks black ~1 s each time a file loops).
CLIP_MINUTES = (5, 10, 15, 20, 30, 45, 60)
SEAMLESS_UNDER = 120  # silent clips shorter than this get a crossfaded, seamless loop
HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = next((p for p in (os.path.join(HERE, "roku"), os.path.join(HERE, "..", "roku"))
                if os.path.isfile(os.path.join(p, "manifest"))), None)
_lock = threading.Lock()
jobs = {}  # id -> {"url", "name", "status", "error"}

# Free clips from Mixkit (mixkit.co, free license). Downloaded from Mixkit when the
# user asks for the starter pack; nothing is redistributed with SaverSwap.
STARTER = [
    ("Aquarium", "https://assets.mixkit.co/videos/14490/14490-720.mp4"),
    ("Fireplace", "https://assets.mixkit.co/videos/30252/30252-720.mp4"),
    ("Rain on the window", "https://assets.mixkit.co/videos/2846/2846-720.mp4"),
    ("Beach", "https://assets.mixkit.co/videos/1925/1925-720.mp4"),
    ("Snowfall", "https://assets.mixkit.co/videos/35040/35040-720.mp4"),
]

DEFAULTS = {
    "current": None, "scenes": [],
    "sound": False,        # play the video's sound on the TV
    "autostart": True,     # launch when the Roku's screensaver starts
    "rokus": [],           # [{"ip", "name", "model", "password"}]
    "place": None, "lat": None, "lon": None,  # weather location
    "units": "fahrenheit", "clock": True, "weather": True,
    "clip_minutes": 20,    # length of each stored scene file (see CLIP_MINUTES)
}


# ---------------------------------------------------------------- state

class Store:
    def __init__(self, data_dir, seed):
        self.dir = os.path.abspath(data_dir)
        self.videos = os.path.join(self.dir, "videos")
        self.thumbs = os.path.join(self.dir, "thumbs")
        self.tmp = os.path.join(self.dir, "tmp")
        for d in (self.videos, self.thumbs, self.tmp):
            os.makedirs(d, exist_ok=True)
        self.path = os.path.join(self.dir, "state.json")
        self.state = {}
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.state = json.load(f)
        for k, v in DEFAULTS.items():
            if k not in self.state:
                self.state[k] = seed.get(k, v) if seed.get(k) is not None else v
        # Rokus given on the command line / environment are added if new
        known = {r["ip"] for r in self.state["rokus"]}
        for ip in seed.get("roku_ips", []):
            if ip not in known:
                self.state["rokus"].append({"ip": ip, "name": ip, "model": "", "password": ""})
        self.scan()

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=1)
        os.replace(tmp, self.path)

    def scan(self):
        """Pick up .mp4 files dropped into videos/ by hand; forget deleted ones; make thumbnails."""
        with _lock:
            known = {s["slug"] for s in self.state["scenes"]}
            for fn in sorted(os.listdir(self.videos)):
                slug, ext = os.path.splitext(fn)
                if ext.lower() == ".mp4" and slug not in known and re.fullmatch(r"[a-z0-9_]+", slug):
                    self.state["scenes"].append({"slug": slug, "name": slug.replace("_", " ").capitalize()})
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

    def roku(self, ip):
        return next((r for r in self.state["rokus"] if r["ip"] == ip), None)


def slugify(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def unique_name(store, name):
    name = re.sub(r"\s+", " ", re.sub(r"[\[\(\{].*?[\]\)\}]", "", name)).strip(" -|*") or "Video"
    if len(name) > 40:
        name = name[:40].rsplit(" ", 1)[0]
    base, n = name, 2
    while store.find(name) or store.find(slugify(name)) or not slugify(name):
        name, n = f"{base} {n}", n + 1
    return name


# ---------------------------------------------------------------- video work

def run(args, timeout=3600):
    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    if p.returncode != 0:
        lines = (p.stderr or p.stdout).strip().splitlines() or ["failed"]
        raise RuntimeError(lines[-1][:300])
    return p.stdout


def _hms(text):
    h, m, s = text.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def run_progress(args, job, total=None, timeout=7200):
    """Run yt-dlp or ffmpeg and keep job["progress"] (0-100) up to date from its output:
    yt-dlp's "NN.N%" lines, or ffmpeg's "time=HH:MM:SS" / "out_time=" against total seconds."""
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    tail, buf, start = [], "", time.time()
    while True:
        ch = p.stdout.read(1)
        if not ch:
            break
        if ch not in "\r\n":
            buf += ch
            continue
        line, buf = buf.strip(), ""
        if not line:
            continue
        tail = (tail + [line])[-5:]
        m = re.search(r"(\d+(?:\.\d+)?)%", line)
        t = re.search(r"(?:out_time|time)=\s*(\d+:\d\d:\d\d(?:\.\d+)?)", line)
        if m and "download" in line.lower():
            # YouTube sends video then audio as two downloads; keep the bar moving forward
            job["progress"] = max(job.get("progress") or 0, min(100, int(float(m.group(1)))))
        elif t and total:
            job["progress"] = min(100, int(_hms(t.group(1)) * 100 / total))
        if time.time() - start > timeout:
            p.kill()
            raise RuntimeError("took too long")
    if p.wait() != 0:
        raise RuntimeError((tail or ["failed"])[-1][:300])


def probe(path):
    d = json.loads(run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name,width,height:stream_side_data=rotation"
                        ":format=duration", "-of", "json", path], 120))
    v = next(s for s in d["streams"] if s.get("codec_type") == "video")
    has_audio = any(s.get("codec_type") == "audio" for s in d["streams"])
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    if any(abs(int(sd.get("rotation") or 0)) in (90, 270) for sd in v.get("side_data_list", [])):
        w, h = h, w  # phone video stored sideways with a rotation flag
    return v["codec_name"], h, float(d["format"]["duration"]), has_audio, w


def make_thumb(video, out):
    try:
        dur = probe(video)[2]
        run(["ffmpeg", "-v", "error", "-y", "-ss", str(min(10, dur / 3)), "-i", video,
             "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", out], 120)
    except Exception as e:
        print(f"thumbnail failed for {video}: {e}", file=sys.stderr)


ENC = ["-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
       "-profile:v", "high", "-level", "4.1"]


def add_video(store, job_id, url, name):
    job = jobs[job_id]
    try:
        for f in os.listdir(store.tmp):
            os.remove(os.path.join(store.tmp, f))
        ytdlp = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--js-runtimes", "node,deno"]
        job["status"], job["progress"] = "Looking up the video", None
        info = run(ytdlp + ["--skip-download", "--print", "%(title)s\t%(duration)s", url], 300)
        title, _, length = (info.strip().splitlines() or ["Video\tNA"])[0].partition("\t")
        try:
            length = float(length)
        except ValueError:
            length = None
        if not name:
            name = title or "Video"
            if re.fullmatch(r"[\w-]*\d[\w-]*", name):  # bare file names like 30252-720
                name = "Video"
        with _lock:
            name = unique_name(store, name)
        job["name"] = name
        slug = slugify(name)
        clip = int(store.state.get("clip_minutes") or 20) * 60

        job["status"], job["progress"] = "Downloading", 0
        fmt = ["-f", "bv*[vcodec^=avc1][height<=1080]+ba[ext=m4a]/bv*[height<=1080]+ba"
                     "/b[height<=1080]/bv*[height<=1080]/b", "--merge-output-format", "mp4", "--newline"]
        if length is None or length > clip + 60:
            # only the first clip_minutes (yt-dlp hands this to ffmpeg, which reports time=)
            fmt += ["--download-sections", f"*0-{clip}"]
        run_progress(ytdlp + fmt + ["-o", os.path.join(store.tmp, "dl.%(ext)s"), url], job,
                     total=min(length or clip, clip))
        src = os.path.join(store.tmp, next(f for f in os.listdir(store.tmp)
                                           if f.startswith("dl.") and not f.endswith(".part")))

        job["status"], job["progress"] = "Converting for the Roku", 0
        codec, height, dur, has_audio, width = probe(src)
        if dur > clip + 5:  # short videos were downloaded whole; keep the first clip_minutes
            trimmed = os.path.join(store.tmp, "trim.mp4")
            run(["ffmpeg", "-v", "error", "-y", "-i", src, "-t", str(clip), "-c", "copy", trimmed])
            src, dur = trimmed, float(clip)
        prog = ["-progress", "pipe:1", "-nostats"]
        clean = os.path.join(store.tmp, "clean.mp4")
        audio = ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "160k"]  # sound kept; muted unless "Sound" is on
        # Portrait (phone) video: fill the 16:9 screen with a blurred, zoomed copy behind it
        # instead of big black bars.
        portrait = width and height and width < height
        scale = ("split[bg][fg];[bg]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,"
                 "gblur=sigma=40,eq=brightness=-0.08[bgb];[fg]scale=-2:1080[fgs];"
                 "[bgb][fgs]overlay=(W-w)/2:0" if portrait else "scale=-2:'min(1080,ih)'")
        if not has_audio and dur < SEAMLESS_UNDER:
            # short silent clip: crossfade its end into its start so the repeat is invisible
            fade = min(2.0, dur / 4)
            run_progress(["ffmpeg", "-v", "error", "-y", "-i", src, "-filter_complex",
                          f"[0:v]fps=30,{scale},format=yuv420p,split[s1][s2];"
                          f"[s1]trim={fade}:{dur},setpts=PTS-STARTPTS,settb=AVTB,fps=30[a];"
                          f"[s2]trim=0:{fade},setpts=PTS-STARTPTS,settb=AVTB,fps=30[b];"
                          f"[a][b]xfade=transition=fade:duration={fade}:offset={dur - 2 * fade:.3f}[v]",
                          "-map", "[v]", "-an"] + ENC + prog + [clean], job, total=dur - fade)
            dur -= fade
        elif codec == "h264" and height <= 1080 and not portrait:
            run_progress(["ffmpeg", "-v", "error", "-y", "-i", src, "-map", "0:v:0", "-c:v", "copy"]
                         + audio + prog + [clean], job, total=dur)
        else:
            run_progress(["ffmpeg", "-v", "error", "-y", "-i", src, "-filter_complex",
                          f"[0:v:0]{scale},fps=30,format=yuv420p[v]", "-map", "[v]"]
                         + ENC + audio + prog + [clean], job, total=dur)
        job["status"], job["progress"] = "Finishing", 100
        loops = max(0, math.ceil(clip / dur) - 1) if dur > 0 else 0
        dest = os.path.join(store.videos, slug + ".mp4")
        run(["ffmpeg", "-v", "error", "-y", "-stream_loop", str(loops), "-i", clean,
             "-c", "copy", "-movflags", "+faststart", dest])
        make_thumb(clean, os.path.join(store.thumbs, slug + ".jpg"))
        for f in os.listdir(store.tmp):
            os.remove(os.path.join(store.tmp, f))

        with _lock:
            store.state["scenes"].append({"slug": slug, "name": name})
            if not store.state["current"] or job.get("select", True):
                store.state["current"] = slug
            store.save()
        job["status"] = "done"
    except Exception as e:
        job["status"], job["error"] = "failed", str(e)


_queue = threading.Lock()  # one download at a time

# Things Home Assistant (or anything) puts on the screen; kept in memory only.
live = {"status": [], "popup": None, "popup_img": b"", "popup_ver": 0, "message": None}


def launch_if_idle(store):
    """Bring SaverSwap up on TVs sitting on the Roku home screen or its screensaver."""
    for r in store.state["rokus"]:
        try:
            active = rokus._get(f"http://{r['ip']}:{rokus.ECP}/query/active-app", 3)
            if "<screensaver" in active or 'type="home"' in active or "<app>Roku</app>" in active:
                rokus.launch(r["ip"])
        except Exception:
            pass


def queue_video(store, url, name, select=True):
    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = {"url": url, "name": name or "", "status": "Waiting", "error": None, "select": select,
                    "progress": None}

    def work():
        with _queue:
            add_video(store, job_id, url, name)
    threading.Thread(target=work, daemon=True).start()
    return job_id


# ---------------------------------------------------------------- Roku watcher

def watch_rokus(store):
    """When a Roku's own screensaver starts, launch SaverSwap over it."""
    last = {}
    while True:
        for r in list(store.state["rokus"]):
            ip = r["ip"]
            try:
                if (store.state["autostart"] and store.state["scenes"] and rokus.screensaver_running(ip)
                        and time.time() - last.get(ip, 0) > 30):
                    rokus.launch(ip)
                    last[ip] = time.time()
                    print(f"screensaver started on {r['name']}: launched SaverSwap", flush=True)
            except Exception as e:
                if time.time() - last.get("err" + ip, 0) > 600:
                    print(f"can't reach Roku {ip}: {e}", file=sys.stderr, flush=True)
                    last["err" + ip] = time.time()
        time.sleep(5)


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    store = None       # set in main()
    public_url = None  # optional override of the address the Roku should use
    # HTTP/1.1 keep-alive + ranges like a real web server (every reply sets Content-Length)
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

    def host(self):
        return self.headers.get("Host") or "localhost"

    def base_url(self):
        return f"http://{self.host()}"

    def host_ip(self):
        return self.host().rsplit(":", 1)[0].strip("[]")

    def server_url_for(self, roku_ip):
        """The address the Roku should use to reach this server."""
        if self.public_url:
            return self.public_url
        h = self.host_ip()
        if h not in ("localhost", "127.0.0.1", "::1"):
            return self.base_url()
        ip = rokus.lan_address_towards(roku_ip)
        if rokus.is_docker_address(ip):
            raise rokus.InstallError(
                "Open this page using the computer's network address (like http://192.168.1.10:8099) "
                "instead of localhost, so the TV knows where to find it.")
        return f"http://{ip}:{self.server.server_address[1]}"

    def payload(self):
        st = self.store.state
        cur = self.store.find(st["current"])
        b = self.base_url()
        du = shutil.disk_usage(self.store.dir)
        used = sum(os.path.getsize(os.path.join(self.store.videos, f)) for f in os.listdir(self.store.videos))
        return {
            "current": cur["name"] if cur else None,
            "video": f"{b}/videos/{cur['slug']}.mp4" if cur else None,
            "setup_url": b,
            "scenes": [{"name": x["name"], "slug": x["slug"], "thumb": f"{b}/thumbs/{x['slug']}.jpg"}
                       for x in st["scenes"]],
            "overlay": {"clock": st["clock"], "weather": bool(st["weather"] and st["lat"] is not None),
                        "lat": st["lat"], "lon": st["lon"], "units": st["units"], "sound": st["sound"],
                        "status": live["status"],
                        "popup": ({"url": f"{b}/popup.jpg?v={live['popup_ver']}", "title": live["popup"]["title"]}
                                  if live["popup"] and live["popup"]["until"] > time.time() else None),
                        "message": (live["message"]["text"]
                                    if live["message"] and live["message"]["until"] > time.time() else None)},
            "settings": {k: st[k] for k in ("sound", "autostart", "units", "clock", "weather", "place",
                                            "clip_minutes")},
            "rokus": [{"ip": r["ip"], "name": r["name"], "model": r.get("model", ""),
                       "saved_password": bool(r.get("password"))} for r in st["rokus"]],
            "storage": {"path": self.store.dir, "used_gb": round(used / 1e9, 1),
                        "free_gb": round(du.free / 1e9, 1)},
            "jobs": [dict(id=k, progress=v.get("progress"), **{x: v[x] for x in ("url", "name", "status", "error")})
                     for k, v in jobs.items() if v["status"] != "done"],
            "starter_left": [n for n, _ in STARTER if not self.store.find(n)],
            "version": VERSION,
        }

    # ---- GET

    def do_GET(self):
        u = urlparse(self.path)
        path, q = unquote(u.path), parse_qs(u.query)
        if path in ("/", "/index.html"):
            return self.send_file(os.path.join(HERE, "index.html"), "text/html; charset=utf-8")
        if path == "/api/scene":
            return self.send_json(self.payload())
        if path == "/api/rokus/scan":
            subnet = (q.get("subnet") or [""])[0]
            if not subnet:
                h = self.host_ip()
                if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", h) or h.startswith("127."):
                    return self.send_json({"error": "Open this page using the computer's network address "
                                                    "(not localhost) so I know which network to search."}, 400)
                subnet = h.rsplit(".", 1)[0] + ".0/24"
            known = {r["ip"] for r in self.store.state["rokus"]}
            found = [dict(f, added=f["ip"] in known) for f in rokus.scan(subnet)]
            return self.send_json({"subnet": subnet, "found": found})
        if path == "/api/rokus/status":
            ip = (q.get("ip") or [""])[0]
            try:
                return self.send_json(rokus.device_info(ip))
            except Exception:
                return self.send_json({"ip": ip, "error": "TV not reachable (is it on?)"}, 502)
        if path == "/api/geocode":
            name = (q.get("q") or [""])[0].strip()
            if not name:
                return self.send_json({"results": []})
            url = ("https://geocoding-api.open-meteo.com/v1/search?count=5&language=en&format=json&name="
                   + urllib.parse.quote(name))
            try:
                with urllib.request.urlopen(url, timeout=10) as r:
                    res = json.load(r).get("results") or []
            except Exception:
                return self.send_json({"error": "Couldn't look that up right now."}, 502)
            return self.send_json({"results": [
                {"place": ", ".join(x for x in (p.get("name"), p.get("admin1"), p.get("country_code")) if x),
                 "lat": round(p["latitude"], 3), "lon": round(p["longitude"], 3)} for p in res]})
        if path == "/popup.jpg":
            data = live["popup_img"]
            if not data:
                return self.send_json({"error": "no picture"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/qr.png":
            return self.send_qr((q.get("text") or [self.base_url()])[0])
        if path == "/api/log":  # diagnostics from the Roku app
            print(f"roku {self.client_address[0]}: {(q.get('msg') or [''])[0][:500]}", flush=True)
            return self.send_json({"ok": True})
        m = re.fullmatch(r"/(videos|thumbs)/([a-z0-9_]+)\.(mp4|jpg)", path)
        if m:
            folder = self.store.videos if m.group(1) == "videos" else self.store.thumbs
            return self.send_file(os.path.join(folder, f"{m.group(2)}.{m.group(3)}"))
        self.send_json({"error": "not found"}, 404)

    # ---- POST

    def do_POST(self):
        u = urlparse(self.path)
        path = u.path
        if path == "/api/overlay/popup":
            # body = a JPEG (e.g. a camera snapshot); ?title=...&seconds=30&launch=1
            q = parse_qs(u.query)
            n = int(self.headers.get("Content-Length") or 0)
            img = self.rfile.read(n) if n else b""
            if not img:
                return self.send_json({"error": "send a JPEG as the request body"}, 400)
            seconds = max(3, min(600, float((q.get("seconds") or ["30"])[0])))
            fresh = not (live["popup"] and live["popup"]["until"] > time.time())
            live["popup_img"], live["popup_ver"] = img, live["popup_ver"] + 1
            live["popup"] = {"title": (q.get("title") or [""])[0][:80], "until": time.time() + seconds}
            if fresh and (q.get("launch") or ["0"])[0] in ("1", "true"):
                threading.Thread(target=launch_if_idle, args=(self.store,), daemon=True).start()
            return self.send_json({"ok": True})
        body = self.read_json()
        st = self.store.state
        try:
            handler = self.POSTS.get(path)
            if not handler:
                return self.send_json({"error": "not found"}, 404)
            return handler(self, body, st)
        except rokus.InstallError as e:
            return self.send_json({"error": str(e)}, 400)
        except OSError:
            return self.send_json({"error": "Couldn't reach the TV. Is it on and on the same network?"}, 502)

    def p_select(self, body, st):
        s = self.store.find(body.get("scene"))
        if not s:
            return self.send_json({"error": "no such scene"}, 404)
        with _lock:
            st["current"] = s["slug"]
            self.store.save()
        return self.send_json(self.payload())

    def p_add(self, body, st):
        text = (body.get("url") or "").strip()
        m = re.search(r"https?://\S+", text)
        if not m:
            return self.send_json({"error": "That doesn't look like a link."}, 400)
        name = (body.get("name") or (text[:m.start()] + " " + text[m.end():])).strip(" -:|")
        return self.send_json({"job": queue_video(self.store, m.group(0), name)}, 202)

    def p_starter(self, body, st):
        first = not st["scenes"]
        for i, (name, url) in enumerate(STARTER):
            if not self.store.find(name) and not any(j["name"] == name for j in jobs.values()
                                                     if j["status"] not in ("done", "failed")):
                queue_video(self.store, url, name, select=first and i == 0)
        return self.send_json(self.payload(), 202)

    def p_delete(self, body, st):
        s = self.store.find(body.get("scene"))
        if not s:
            return self.send_json({"error": "no such scene"}, 404)
        for p in (os.path.join(self.store.videos, s["slug"] + ".mp4"),
                  os.path.join(self.store.thumbs, s["slug"] + ".jpg")):
            if os.path.exists(p):
                os.remove(p)
        self.store.scan()
        return self.send_json(self.payload())

    def p_rename(self, body, st):
        s = self.store.find(body.get("scene"))
        if not s:
            return self.send_json({"error": "no such scene"}, 404)
        with _lock:
            new = unique_name(self.store, (body.get("name") or "").strip()) if body.get("name") else None
            if not new:
                return self.send_json({"error": "Give it a name."}, 400)
            old, slug = s["slug"], slugify(new)
            for folder, ext in ((self.store.videos, ".mp4"), (self.store.thumbs, ".jpg")):
                if os.path.exists(os.path.join(folder, old + ext)):
                    os.replace(os.path.join(folder, old + ext), os.path.join(folder, slug + ext))
            s["name"], s["slug"] = new, slug
            if st["current"] == old:
                st["current"] = slug
            self.store.save()
        return self.send_json(self.payload())

    def p_settings(self, body, st):
        with _lock:
            for k in ("sound", "autostart", "clock", "weather"):
                if isinstance(body.get(k), bool):
                    st[k] = body[k]
            if body.get("units") in ("fahrenheit", "celsius"):
                st["units"] = body["units"]
            if body.get("clip_minutes") in CLIP_MINUTES:
                st["clip_minutes"] = body["clip_minutes"]
            if "lat" in body and "lon" in body:
                try:
                    st["lat"], st["lon"] = float(body["lat"]), float(body["lon"])
                    st["place"] = (body.get("place") or "").strip() or f"{st['lat']}, {st['lon']}"
                except (TypeError, ValueError):
                    return self.send_json({"error": "That location didn't work."}, 400)
            self.store.save()
        return self.send_json(self.payload())

    def p_roku_add(self, body, st):
        info = rokus.device_info(body.get("ip", "").strip())
        with _lock:
            r = self.store.roku(info["ip"])
            if r:
                r.update(name=info["name"], model=info["model"])
            else:
                st["rokus"].append({"ip": info["ip"], "name": info["name"], "model": info["model"],
                                    "password": ""})
            self.store.save()
        return self.send_json(self.payload())

    def p_roku_remove(self, body, st):
        with _lock:
            st["rokus"] = [r for r in st["rokus"] if r["ip"] != body.get("ip")]
            self.store.save()
        return self.send_json(self.payload())

    def p_roku_install(self, body, st):
        if not APP_DIR:
            raise rokus.InstallError("The Roku app files are missing from this install.")
        ip = body.get("ip", "")
        r = self.store.roku(ip)
        if not r:
            return self.send_json({"error": "Add that TV first."}, 400)
        password = (body.get("password") or "").strip() or r.get("password", "")
        if not password:
            return self.send_json({"error": "Enter the Developer Mode password you set on the TV."}, 400)
        rokus.install(ip, password, APP_DIR, self.server_url_for(ip))
        with _lock:
            r["password"] = password
            self.store.save()
        return self.send_json(self.payload())

    def p_roku_launch(self, body, st):
        rokus.launch(body.get("ip", ""))
        return self.send_json({"ok": True})

    def p_rescan(self, body, st):
        self.store.scan()
        return self.send_json(self.payload())

    def p_overlay_status(self, body, st):
        items = body.get("items") or []
        live["status"] = [{"text": str(i.get("text", ""))[:60], "alert": bool(i.get("alert"))}
                          for i in items if isinstance(i, dict) and i.get("text")][:6]
        return self.send_json({"ok": True})

    def p_overlay_message(self, body, st):
        text = str(body.get("text") or "").strip()[:120]
        seconds = max(3, min(3600, float(body.get("seconds") or 30)))
        live["message"] = {"text": text, "until": time.time() + seconds} if text else None
        if text and body.get("launch"):
            threading.Thread(target=launch_if_idle, args=(self.store,), daemon=True).start()
        return self.send_json({"ok": True})

    def p_overlay_clear(self, body, st):
        what = body.get("what", "all")
        if what in ("popup", "all"):
            live["popup"] = None
        if what in ("message", "all"):
            live["message"] = None
        return self.send_json({"ok": True})

    POSTS = {
        "/api/overlay/status": p_overlay_status, "/api/overlay/message": p_overlay_message,
        "/api/overlay/clear": p_overlay_clear,
        "/api/select": p_select, "/api/add": p_add, "/api/starter": p_starter,
        "/api/delete": p_delete, "/api/rename": p_rename, "/api/settings": p_settings,
        "/api/rescan": p_rescan, "/api/rokus/add": p_roku_add, "/api/rokus/remove": p_roku_remove,
        "/api/rokus/install": p_roku_install,
        "/api/rokus/launch": p_roku_launch,
    }

    # ---- files

    def send_qr(self, text):
        try:
            import qrcode
            import qrcode.image.pure
            buf = __import__("io").BytesIO()
            qrcode.make(text, image_factory=qrcode.image.pure.PyPNGImage, box_size=10, border=2).save(buf)
            data = buf.getvalue()
        except Exception:
            return self.send_json({"error": "QR codes need: pip install qrcode pypng"}, 501)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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


def main():
    env = os.environ.get
    ap = argparse.ArgumentParser(description="SaverSwap server. Everything else is set up on its web page.")
    ap.add_argument("--data", default=env("SAVERSWAP_DATA", os.path.join(HERE, "data")),
                    help="folder for videos, thumbnails and settings (default: ./data)")
    ap.add_argument("--port", type=int, default=int(env("SAVERSWAP_PORT", "8099")))
    ap.add_argument("--url", default=env("SAVERSWAP_URL"),
                    help="address the TV should use to reach this server, if the automatic one is wrong")
    # Optional first-run defaults (the web page can change all of these later)
    ap.add_argument("--roku", default=env("SAVERSWAP_ROKU", ""), help="Roku IP address(es), comma-separated")
    ap.add_argument("--lat", type=float, default=float(env("SAVERSWAP_LAT")) if env("SAVERSWAP_LAT") else None)
    ap.add_argument("--lon", type=float, default=float(env("SAVERSWAP_LON")) if env("SAVERSWAP_LON") else None)
    ap.add_argument("--units", choices=["fahrenheit", "celsius"], default=env("SAVERSWAP_UNITS"))
    a = ap.parse_args()
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print(f"warning: {tool} not found on PATH; adding videos won't work", file=sys.stderr)
    seed = {"roku_ips": [r.strip() for r in a.roku.split(",") if r.strip()], "units": a.units,
            "lat": a.lat, "lon": a.lon}
    if a.lat is not None and a.lon is not None:
        seed["place"] = f"{a.lat}, {a.lon}"
    Handler.store = Store(a.data, seed)
    Handler.public_url = a.url.rstrip("/") if a.url else None
    threading.Thread(target=watch_rokus, args=(Handler.store,), daemon=True).start()
    print(f"SaverSwap {VERSION} on http://0.0.0.0:{a.port}  (data: {Handler.store.dir})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
