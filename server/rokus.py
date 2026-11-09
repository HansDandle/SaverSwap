"""Talking to Rokus on the home network: find them, read their status, open the
Developer Mode screen, install the SaverSwap app, and launch it.

Uses Roku's local control API (ECP, port 8060) and the Developer Mode installer
(port 80). Nothing here needs an account or the internet.
"""
import concurrent.futures
import io
import ipaddress
import json
import os
import re
import socket
import urllib.error
import urllib.request
import uuid
import zipfile

ECP = 8060


def _get(url, timeout=3):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _post(url, timeout=5):
    urllib.request.urlopen(urllib.request.Request(url, data=b"", method="POST"), timeout=timeout).close()


def _tag(xml, name):
    m = re.search(rf"<{name}>(.*?)</{name}>", xml, re.S)
    return m.group(1).strip() if m else ""


def device_info(ip, timeout=3):
    """Name, model and Developer Mode state of the Roku at ip (raises if it isn't one)."""
    x = _get(f"http://{ip}:{ECP}/query/device-info", timeout)
    model = _tag(x, "friendly-model-name") or _tag(x, "model-name") or "Roku"
    name = _tag(x, "user-device-name") or _tag(x, "friendly-device-name") or model
    return {"ip": ip, "name": name, "model": model,
            "dev": _tag(x, "developer-enabled") == "true",
            "installed": installed(ip)}


def installed(ip):
    try:
        return bool(re.search(r'<app id="dev"[^>]*>SaverSwap<', _get(f"http://{ip}:{ECP}/query/apps")))
    except Exception:
        return False


def scan(subnet):
    """Find Rokus on a /24 like 192.168.1.0/24 (about 2 seconds)."""
    net = ipaddress.ip_network(subnet, strict=False)
    hosts = [str(h) for h in net.hosts()][:1024]

    def probe(ip):
        try:
            with socket.create_connection((ip, ECP), timeout=0.6):
                pass
            return device_info(ip)
        except Exception:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=96) as pool:
        return [r for r in pool.map(probe, hosts) if r]


# Note: Roku ignores the Developer Mode button sequence when it's sent over the
# network (tested), so the web page explains how to do it with the remote instead.


def launch(ip):
    _post(f"http://{ip}:{ECP}/launch/dev")


def screensaver_running(ip):
    return "<screensaver" in _get(f"http://{ip}:{ECP}/query/active-app", 5)


def build_zip(app_dir, server_url):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, _, files in os.walk(app_dir):
            for f in files:
                full = os.path.join(folder, f)
                z.write(full, os.path.relpath(full, app_dir).replace(os.sep, "/"))
        z.writestr("config.json", json.dumps({"server": server_url.rstrip("/")}))
    return buf.getvalue()


class InstallError(Exception):
    pass


def install(ip, password, app_dir, server_url):
    """Sideload the app through the Developer Mode installer (user is always rokudev)."""
    data = build_zip(app_dir, server_url)
    boundary = uuid.uuid4().hex
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"mysubmit\"\r\n\r\nInstall\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"archive\"; filename=\"saverswap.zip\"\r\n"
        f"Content-Type: application/zip\r\n\r\n".encode(), data, f"\r\n--{boundary}--\r\n".encode()])
    url = f"http://{ip}/plugin_install"
    pw = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    pw.add_password(None, url, "rokudev", password)
    opener = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(pw))
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        html = opener.open(req, timeout=120).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise InstallError("The TV didn't accept that password.")
        raise InstallError(f"The TV answered with an error ({e.code}).")
    except urllib.error.URLError:
        raise InstallError("Couldn't reach the TV's installer. Is Developer Mode turned on?")
    if "Install Success" in html or "Identical to previous version" in html:
        return
    m = re.search(r"Install Failure[^<\"]*", html)
    raise InstallError(m.group(0) if m else "The TV refused the app.")


def is_docker_address(ip):
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network("172.16.0.0/12")
    except ValueError:
        return False


def lan_address_towards(ip):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((ip, 80))  # no packets are sent; this just picks the outgoing interface
        return s.getsockname()[0]
    finally:
        s.close()
