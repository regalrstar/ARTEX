#!/usr/bin/env python3
"""Host-side WiFi agent for the ARTEX wifi workspace (macOS only).

Runs on the Mac, not in Docker, because macOS only lets root scan and sniff.
Start it manually:

    sudo python3 artex/wifi/agent.py

Endpoints (all require the X-Agent-Token header):
    GET  /status                 -> readiness, uid, active capture
    GET  /scan                   -> nearby networks
    POST /capture {channel,seconds} -> sniff, pcap lands in artex/data/wifi
    POST /stop                   -> stop the active capture early

The token is generated on first run into data/wifi/agent.token and read from
there by the workspace container.
"""
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEST = Path(os.environ.get("WIFI_DATA", HERE.parent / "data" / "wifi"))
TOKEN_FILE = DEST / "agent.token"
PORT = int(os.environ.get("AGENT_PORT", "8791"))
MAC = re.compile(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", re.I)
STATE = {"proc": None, "channel": None, "until": 0, "file": None}
LOCK = threading.Lock()


def token():
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    DEST.mkdir(parents=True, exist_ok=True)
    t = secrets.token_urlsafe(24)
    TOKEN_FILE.write_text(t + "\n")
    TOKEN_FILE.chmod(0o600)
    return t


def parse_scan(text):
    nets = []
    for line in text.splitlines():
        line = line.strip()
        m = MAC.search(line)
        if not m:
            continue
        toks = line.split()
        i = next((k for k, t in enumerate(toks) if MAC.fullmatch(t)), None)
        if i is None:
            continue
        ssid = " ".join(toks[:i]).strip()
        rest = toks[i + 1:]
        rssi = next((int(t) for t in rest if re.fullmatch(r"-\d{1,3}", t)), None)
        chan = next((t for t in rest if re.fullmatch(r"\d{1,3}(,\d+)?", t)), "")
        sec = ["WPA3"] if any("WPA3" in t for t in rest) else []
        sec += ["WPA2"] if any("WPA2" in t for t in rest) else []
        sec += ["WPS"] if any("WPS" in t for t in rest.upper()) else []
        if not sec and any(t.upper() in ("NONE", "OPEN") for t in rest):
            sec = ["open"]
        nets.append({"ssid": ssid, "bssid": m.group(0).lower(), "rssi": rssi,
                     "channel": chan.split(",")[0], "security": sec or ["unknown"]})
    nets.sort(key=lambda n: n["rssi"] or -127, reverse=True)
    return nets


def do_scan():
    p = subprocess.run(["wdutil", "scan"], capture_output=True, text=True, timeout=90)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "wdutil failed").strip()[:300])
    return parse_scan(p.stdout)


def start_capture(channel, seconds):
    if STATE["proc"] and STATE["proc"].poll() is None:
        raise RuntimeError("a capture is already running")
    DEST.mkdir(parents=True, exist_ok=True)
    before = set(Path("/tmp").glob("airportSniff*.pcap"))
    p = subprocess.Popen(["/usr/libexec/airportd", "sniff", str(channel), str(seconds)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    STATE.update(proc=p, channel=str(channel), until=time.time() + seconds, file=None)

    def collect():
        p.wait()
        new = list(set(Path("/tmp").glob("airportSniff*.pcap")) - before)
        if new:
            src = max(new, key=lambda f: f.stat().st_mtime)
            dst = DEST / f"sniff-{time.strftime('%Y%m%d-%H%M%S')}-ch{channel}.pcap"
            try:
                src.replace(dst)
                STATE["file"] = str(dst)
            except OSError:
                pass
        STATE["proc"] = None

    threading.Thread(target=collect, daemon=True).start()
    return {"channel": channel, "seconds": seconds}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _authed(self):
        return self.headers.get("X-Agent-Token") == token()

    def do_GET(self):
        if not self._authed():
            return self._send(401, {"error": "bad token"})
        if self.path.startswith("/status"):
            running = bool(STATE["proc"] and STATE["proc"].poll() is None)
            return self._send(200, {"ok": True, "uid": os.geteuid(), "running": running,
                                    "channel": STATE["channel"] if running else None,
                                    "remaining": max(0, int(STATE["until"] - time.time())) if running else 0,
                                    "file": STATE["file"]})
        if self.path.startswith("/scan"):
            try:
                return self._send(200, {"networks": do_scan()})
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": str(e)})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._authed():
            return self._send(401, {"error": "bad token"})
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path.startswith("/capture"):
            try:
                return self._send(200, start_capture(body.get("channel", "6"),
                                                     int(body.get("seconds", 90))))
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": str(e)})
        if self.path.startswith("/stop"):
            p = STATE.get("proc")
            if p and p.poll() is None:
                p.send_signal(signal.SIGTERM)
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("warning: not root, wdutil/airportd will fail. Re-run with sudo.", file=sys.stderr)
    print(f"wifi agent on 0.0.0.0:{PORT} dest={DEST} token={TOKEN_FILE}", flush=True)
    print("stop with Ctrl-C", flush=True)
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
    except KeyboardInterrupt:
        pass
