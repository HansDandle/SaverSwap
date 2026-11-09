#!/usr/bin/env python3
"""Package the SaverSwap Roku app and install it on a Roku in Developer Mode.

    python tools/install_roku.py --roku 192.168.1.50 --password YOURDEVPASSWORD
    python tools/install_roku.py --roku 192.168.1.50 --password ... --server http://192.168.1.10:8099

--server defaults to this computer's LAN address on port 8099 (where saverswap.py runs).
Turn on Developer Mode first: on the Roku remote press Home x3, Up x2, Right, Left,
Right, Left, Right, then follow the prompts and set a password.
Only standard-library Python is needed.
"""
import argparse
import io
import json
import os
import socket
import sys
import urllib.error
import urllib.request
import uuid
import zipfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "roku")


def lan_ip(target):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target, 80))  # no packets sent; just picks the outgoing interface
        return s.getsockname()[0]
    finally:
        s.close()


def build_zip(server):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, _, files in os.walk(ROOT):
            for f in files:
                full = os.path.join(folder, f)
                z.write(full, os.path.relpath(full, ROOT).replace(os.sep, "/"))
        z.writestr("config.json", json.dumps({"server": server.rstrip("/")}))
    return buf.getvalue()


def install(roku, password, data):
    boundary = uuid.uuid4().hex
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"mysubmit\"\r\n\r\nInstall\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"archive\"; filename=\"saverswap.zip\"\r\n"
        f"Content-Type: application/zip\r\n\r\n".encode(), data, f"\r\n--{boundary}--\r\n".encode()])
    url = f"http://{roku}/plugin_install"
    pw = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    pw.add_password(None, url, "rokudev", password)
    opener = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(pw))
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        html = opener.open(req, timeout=120).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            sys.exit("The Roku rejected the password (user is always 'rokudev').")
        raise
    except urllib.error.URLError as e:
        sys.exit(f"Couldn't reach {roku}. Is Developer Mode on? ({e.reason})")
    if "Install Success" in html or "Identical to previous version" in html:
        return True
    sys.exit("Install failed. The Roku said:\n" + html[-800:])


def main():
    ap = argparse.ArgumentParser(description="Install SaverSwap on a Roku (Developer Mode)")
    ap.add_argument("--roku", required=True, help="the Roku's IP address")
    ap.add_argument("--password", required=True, help="the Developer Mode password you set")
    ap.add_argument("--server", help="SaverSwap server URL (default: this computer, port 8099)")
    a = ap.parse_args()
    server = a.server or f"http://{lan_ip(a.roku)}:8099"
    print(f"Installing SaverSwap on {a.roku}, using server {server} ...")
    install(a.roku, a.password, build_zip(server))
    print("Installed, and it's playing on the TV now (any remote button closes it).\n"
          "To have it start by itself when the TV goes idle, run the server with\n"
          f"--roku {a.roku} and keep any normal screensaver selected on the Roku.")


if __name__ == "__main__":
    main()
