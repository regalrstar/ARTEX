#!/usr/bin/env python3
"""WiFi workspace — offline capture triage for ARTEX.

Drop .pcap/.pcapng/.22000 files into /data, open http://127.0.0.1:8790, pick a
network, convert and crack. Capture itself happens outside (PortaPack, dongle,
phone hotspot); this box only ever touches files, which is also why it works
with no USB in Docker.

Sources are pluggable: `PcapSource` today, `LiveSource` (iw/airodump) later.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DATA = Path(os.environ.get("WIFI_DATA", "/data"))
WORDLISTS = Path(os.environ.get("WIFI_WORDLISTS", "/wordlists"))
ARTEX = os.environ.get("ARTEX_URL", "http://artex:8787")
ARTEX_USER = os.environ.get("ARTEX_USER", "")
ARTEX_PASS = os.environ.get("ARTEX_PASS", "")
PORT = int(os.environ.get("WIFI_PORT", "8790"))
AGENT = os.environ.get("AGENT_URL", "http://host.docker.internal:8791")
TOKEN_FILE = Path(os.environ.get("AGENT_TOKEN_FILE", "/data/agent.token"))
CAP_EXT = {".cap", ".pcap", ".pcapng"}
HASH_EXT = {".22000", ".hc22000"}
WORDLIST_PLAN = [
    ("probable-v2-wpa-top447.txt", None),
    ("probable-v2-wpa-top4800.txt", None),
    ("rockyou.txt", None),
    ("rockyou.txt", "best64.rule"),
]
JOBS = {}
LOCK = threading.Lock()


# ---------------------------------------------------------------- sources ---
def _maybe_hex(v):
    """tshark prints byte-typed fields as hex; decode when it looks like one."""
    if not v:
        return ""
    if len(v) % 2 == 0 and re.fullmatch(r"[0-9a-fA-F]+", v):
        try:
            return bytes.fromhex(v).decode("utf-8", "replace")
        except ValueError:
            return v
    return v


class PcapSource:
    """Every capture file under DATA, decoded with tshark."""

    name = "pcap"

    def files(self):
        for p in sorted(DATA.rglob("*")):
            if p.suffix.lower() in CAP_EXT:
                yield p

    def scan(self):
        nets = {}
        for f in self.files():
            for row in _decode(f):
                key = row["bssid"]
                n = nets.setdefault(key, {
                    "bssid": key, "ssid": "", "channel": "", "rssi": None,
                    "security": set(), "eapol": 0, "pmkid": False,
                    "sources": [], "last": 0,
                })
                if row.get("ssid"):
                    n["ssid"] = row["ssid"]
                if row.get("channel"):
                    n["channel"] = row["channel"]
                if row.get("rssi") is not None:
                    n["rssi"] = max(n["rssi"] or -127, row["rssi"])
                n["security"].update(row.get("security") or [])
                n["eapol"] += row.get("eapol", 0)
                n["pmkid"] = n["pmkid"] or row.get("pmkid", False)
                n["last"] = max(n["last"], row.get("ts", 0))
                if str(f) not in n["sources"]:
                    n["sources"].append(str(f))
        for p in DATA.rglob("*"):
            if p.suffix.lower() in HASH_EXT:
                for row in _decode_22000(p):
                    n = nets.setdefault(row["bssid"], {
                        "bssid": row["bssid"], "ssid": "", "channel": "", "rssi": None,
                        "security": set(), "eapol": 0, "pmkid": False,
                        "sources": [], "last": 0,
                    })
                    n["ssid"] = n["ssid"] or row["ssid"]
                    n["eapol"] = max(n["eapol"], row["count"])
                    n["pmkid"] = n["pmkid"] or row["pmkid"]
                    if str(p) not in n["sources"]:
                        n["sources"].append(str(p))
        out = []
        for n in nets.values():
            n["security"] = sorted(n["security"]) or ["unknown"]
            n["handshake"] = n["eapol"] >= 2 or n["pmkid"]
            n["health"] = _health(n)
            n["psk"] = _known_psk(n["bssid"])
            out.append(n)
        out.sort(key=lambda x: (not x["handshake"], -(x["rssi"] or -127)))
        return out


def _decode_22000(path):
    for line in path.read_text(errors="ignore").splitlines():
        parts = line.split("*")
        if len(parts) < 6 or parts[0] != "WPA":
            continue
        kind = parts[1]
        bssid = parts[3].lower()
        bssid = ":".join(bssid[i:i + 2] for i in range(0, 12, 2))
        try:
            ssid = bytes.fromhex(parts[5]).decode()
        except ValueError:
            ssid = ""
        yield {"bssid": bssid, "ssid": ssid, "count": 2, "pmkid": kind == "01"}


def _decode(path):
    """One tshark pass; missing optional fields fall back to a minimal set."""
    rich = ["-e", "frame.time_epoch", "-e", "wlan.bssid", "-e", "wlan.ssid",
            "-e", "wlan_radio.channel", "-e", "wlan_radio.signal_dbm",
            "-e", "wlan.rsn.version", "-e", "wlan.rsn.akms", "-e", "wlan.wfa.ie.wpa.version",
            "-e", "wlan.tag", "-e", "wlan_rsna_eapol.keydes.msgnr",
            "-e", "wlan.rsn.ie.pmkid", "-e", "wlan.fixed.capabilities.privacy"]
    rows = _tshark(path, rich)
    if rows is None:
        rows = _tshark(path, ["-e", "frame.time_epoch", "-e", "wlan.bssid",
                              "-e", "wlan.ssid", "-e", "wlan_radio.channel",
                              "-e", "wlan_radio.signal_dbm"])
    if not rows:
        return []
    for r in rows:
        if not r["bssid"]:
            continue
        yield r


def _tshark(path, fields):
    cmd = ["tshark", "-r", str(path), "-Y",
           "wlan.fc.type_subtype==8 || wlan.fc.type_subtype==5 || eapol",
           "-T", "fields", "-E", "separator=\t", "-E", "occurrence=a"] + fields
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if p.returncode != 0 and re.search(r"aren't valid|isn't a valid|not valid",
                                       p.stderr or ""):
        return None
    out = []
    idx = {}
    for i in range(0, len(fields), 2):
        idx[fields[i + 1]] = i // 2
    for line in p.stdout.splitlines():
        c = line.split("\t")
        if len(c) < 2:
            continue
        get = lambda k: c[idx[k]] if k in idx and idx[k] < len(c) else ""  # noqa: E731
        bssid = get("wlan.bssid").split(",")[0]
        if not bssid or bssid == "ff:ff:ff:ff:ff:ff":
            continue
        sec = []
        if get("wlan.rsn.version"):
            sec.append("WPA3" if "8" in get("wlan.rsn.akms").split(",") else "WPA2")
        if get("wlan.wfa.ie.wpa.version"):
            sec.append("WPA")
        if get("wlan.rsn.ie.pmkid"):
            sec.append("PMKID")
        if "0050f204" in get("wlan.tag").lower():
            sec.append("WPS")
        if not sec and get("wlan.fixed.capabilities.privacy") in ("1", "0x0001"):
            sec.append("WEP/open")
        try:
            ts = float(get("frame.time_epoch") or 0)
        except ValueError:
            ts = 0
        try:
            rssi = int(get("wlan_radio.signal_dbm").split(",")[0])
        except ValueError:
            rssi = None
        yield_obj = {
            "bssid": bssid.lower(),
            "ssid": _maybe_hex(get("wlan.ssid").split(",")[0]),
            "channel": get("wlan_radio.channel").split(",")[0],
            "rssi": rssi,
            "security": sec,
            "eapol": 2 if get("wlan_rsna_eapol.keydes.msgnr") else 0,
            "pmkid": bool(get("wlan.rsn.ie.pmkid")),
            "ts": ts,
        }
        out.append(yield_obj)
    return out


SOURCES = {"pcap": PcapSource()}


# ---------------------------------------------------------------- live agent --
def _token():
    try:
        return TOKEN_FILE.read_text().strip()
    except OSError:
        return ""


def _agent(path, method="GET", body=None):
    import urllib.error
    import urllib.request
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(AGENT + path, data=data, method=method)
    r.add_header("X-Agent-Token", _token())
    r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, timeout=120) as resp:
        return json.loads(resp.read() or b"{}")


def agent_status():
    if not _token():
        return {"up": False, "reason": "agent not started (sudo python3 wifi/agent.py)"}
    try:
        st = _agent("/status")
        st["up"] = True
        return st
    except Exception as e:  # noqa: BLE001
        return {"up": False, "reason": str(e)}


_SCAN = {"ts": 0, "nets": []}


def _live_scan(max_age=20):
    if time.time() - _SCAN["ts"] < max_age:
        return _SCAN["nets"]
    try:
        _SCAN["nets"] = _agent("/scan").get("networks", [])
        _SCAN["ts"] = time.time()
    except Exception:  # noqa: BLE001
        pass
    return _SCAN["nets"]


def merged_networks():
    files = {n["bssid"]: n for n in SOURCES["pcap"].scan()}
    out = []
    live = _live_scan()
    for l in live:
        n = files.get(l["bssid"])
        if n:
            n["rssi"] = l.get("rssi") or n["rssi"]
            if n["security"] in ([], ["unknown"]):
                n["security"] = l.get("security") or ["unknown"]
            n["live"] = True
        else:
            out.append({
                "bssid": l["bssid"], "ssid": l.get("ssid", ""), "channel": l.get("channel", ""),
                "rssi": l.get("rssi"), "security": l.get("security") or ["unknown"],
                "eapol": 0, "pmkid": False, "sources": [], "last": 0,
                "handshake": False, "health": "not-captured", "psk": None, "live": True,
            })
    out += [n for n in files.values()]
    out.sort(key=lambda x: (not x["handshake"], -(x["rssi"] or -127)))
    return out


def _health(n):
    if n.get("psk"):
        return "cracked"
    if n["pmkid"]:
        return "pmkid"
    if n["eapol"] >= 2:
        return "handshake"
    if n["eapol"]:
        return "partial"
    return "beacon-only"


# ---------------------------------------------------------------- cracking ---
def _hash_file(bssid):
    return DATA / "hashes" / (bssid.replace(":", "") + ".22000")


def _convert(bssid):
    """Run hcxpcapngtool over every source of this BSSID into one .22000."""
    srcs = [Path(s) for s in _sources_for(bssid)]
    if not srcs:
        raise RuntimeError("no capture file for this BSSID")
    out = _hash_file(bssid)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    essids = DATA / "hashes" / (out.stem + ".essid")
    for s in srcs:
        if s.suffix.lower() in HASH_EXT:
            with out.open("a") as dst:
                for line in s.read_text(errors="ignore").splitlines():
                    if line.startswith("WPA*") and bssid.replace(":", "") in line.replace(":", ""):
                        dst.write(line + "\n")
            continue
        subprocess.run(["hcxpcapngtool", "-o", str(out), "-E", str(essids), str(s)],
                       capture_output=True, timeout=600)
    if not out.exists():
        raise RuntimeError("conversion produced no hash")
    lines = [x for x in out.read_text(errors="ignore").splitlines() if x.startswith("WPA*")]
    if not lines:
        raise RuntimeError("no usable handshake/PMKID for this BSSID (M1/M3 only?)")
    return out, len(lines)


def _sources_for(bssid):
    for n in SOURCES["pcap"].scan():
        if n["bssid"] == bssid:
            return n["sources"]
    return []


def _known_psk(bssid):
    p = DATA / "hashes" / (bssid.replace(":", "") + ".psk")
    return p.read_text().strip() if p.exists() else None


def _start_crack(bssid):
    job = {"id": uuid.uuid4().hex[:12], "bssid": bssid, "state": "running",
           "step": "", "speed": 0.0, "pct": 0.0, "eta": "", "result": None,
           "started": time.time()}
    with LOCK:
        JOBS[job["id"]] = job
    threading.Thread(target=_crack_worker, args=(job,), daemon=True).start()
    return job


def _crack_worker(job):
    bssid = job["bssid"]
    try:
        hf, count = _convert(bssid)
    except Exception as e:  # noqa: BLE001
        job.update(state="error", step=str(e))
        return
    job["hashes"] = count
    for wl, rule in WORDLIST_PLAN:
        wpath = WORDLISTS / wl
        if not wpath.exists():
            continue
        job["step"] = f"dictionary {wl}" + (f" + {rule}" if rule else "")
        _run_hashcat(job, hf, ["-a", "0", str(wpath)] + (["-r", str(Path("/usr/share/hashcat/rules") / rule)] if rule else []))
        if job["state"] != "running":
            return
        if _finish(job, hf):
            return
    ssid = _ssid_for(bssid)
    if ssid:
        for mask in (f"{ssid}?d?d?d?d", f"{ssid}?d?d?d?d?d?d", f"{ssid}20?d?d",
                     f"{ssid}?d?d?d?d!"):
            job["step"] = f"mask {mask}"
            _run_hashcat(job, hf, ["-a", "3", mask])
            if job["state"] != "running":
                return
            if _finish(job, hf):
                return
    job["state"] = "exhausted"
    job["step"] = "lists and masks exhausted"


def _run_hashcat(job, hf, args):
    cmd = ["hashcat", "-m", "22000", "-w", "3", "--status", "--status-timer", "3",
           "--potfile-path", "/data/hashes/hashcat.potfile", "-o", str(hf) + ".out",
           "--outfile-format", "2", "-d", "1", str(hf)] + args
    env = dict(os.environ, OMP_NUM_THREADS="2")
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    job["pid"] = p.pid
    for line in p.stdout:
        if job["state"] != "running":
            p.terminate()
            return False
        m = re.search(r"Speed\.#\S*:\s*([\d.]+)\s*([kMG]?)H/s", line)
        if m:
            mult = {"": 1, "k": 1e3, "M": 1e6, "G": 1e9}[m.group(2)]
            job["speed"] = float(m.group(1)) * mult
        m = re.search(r"Progress\.+:\s*(\d+)/(\d+)", line)
        if m:
            done, total = int(m.group(1)), int(m.group(2)) or 1
            job["pct"] = round(done / total * 100, 1)
            if job["speed"]:
                left = (total - done) / job["speed"]
                job["eta"] = f"{int(left // 60)}m{int(left % 60)}s"
        if "Status.......: Cracked" in line:
            job["_cracked"] = True
        if re.search(r"No hashes loaded|Token encoding|Exhausted", line):
            job["step"] += " (done)"
    rc = p.wait()
    # hashcat: 0 ok, 1 exhausted (normal end of a list), >=2 real failure
    if rc >= 2 and job["state"] == "running":
        job["state"] = "error"
        job["step"] = f"hashcat exited {rc}"
        return False
    return True


def _show(hf):
    p = subprocess.run(["hashcat", "-m", "22000", "--show", "--potfile-path",
                        "/data/hashes/hashcat.potfile", str(hf)],
                       capture_output=True, text=True)
    for line in p.stdout.splitlines():
        if ":" in line and line.count(":") >= 6:
            return line.rsplit(":", 1)[-1].strip()
    return None


def _finish(job, hf):
    psk = _show(hf) or (_psk_from_out(hf))
    if not psk:
        return False
    job.update(state="cracked", result=psk, pct=100.0, eta="")
    (DATA / "hashes" / (job["bssid"].replace(":", "") + ".psk")).write_text(psk + "\n")
    return True


def _psk_from_out(hf):
    out = Path(str(hf) + ".out")
    if not out.exists():
        return None
    lines = [x for x in out.read_text().strip().splitlines() if x]
    return lines[-1].strip() if lines else None


def _ssid_for(bssid):
    for n in SOURCES["pcap"].scan():
        if n["bssid"] == bssid:
            return n["ssid"]
    return ""


# ---------------------------------------------------------------- handoff ---
def _artex_token():
    body = json.dumps({"username": "ARTEX", "password": ARTEX_PASS}).encode()
    req = __import__("urllib.request", fromlist=["request"]).Request(
        ARTEX + "/api/auth/login", data=body, method="POST",
        headers={"Content-Type": "application/json"})
    with __import__("urllib.request", fromlist=["request"]).urlopen(req, timeout=20) as r:
        return json.loads(r.read())["token"]


def _handoff(bssid):
    tpl = json.loads(__import__("urllib.request", fromlist=["request"]).urlopen(
        __import__("urllib.request", fromlist=["request"]).Request(
            ARTEX + "/api/task-templates", headers={"Authorization": "Bearer " + _artex_token()}),
        timeout=20).read())
    template = next(t for t in tpl["templates"] if t["id"] == 19)
    hf = _hash_file(bssid)
    ssid = _ssid_for(bssid) or bssid
    goal = template["goal"]
    goal = goal.replace("Wireless target: SSID TARGET (replace; add the BSSID and channel if known). ", "")
    goal = goal.replace("Capture source: upload the .cap / .pcapng / .22000 into the task files and put its path in this goal. ", "")
    goal = (f"Wireless target: {ssid} (BSSID {bssid}). Capture: {hf} — already converted to "
            f".22000 and validated, no upload needed. ") + goal
    payload = {"name": f"WiFi {ssid}", "description": template["description"],
               "goal": goal, "category_id": template["category_id"],
               "intercept_rules": template["intercept_rules"]}
    body = json.dumps(payload).encode()
    r = __import__("urllib.request", fromlist=["request"]).Request(
        ARTEX + "/api/tasks", data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + _artex_token()})
    with __import__("urllib.request", fromlist=["request"]).urlopen(r, timeout=20) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------- HTTP ------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj=None, ctype="application/json", raw=None):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/":
            return self._send(200, raw=INDEX, ctype="text/html; charset=utf-8")
        if p == "/api/networks":
            return self._send(200, {"source": "live+pcap", "agent": agent_status(),
                                    "networks": merged_networks()})
        if p == "/api/jobs":
            return self._send(200, {"jobs": list(JOBS.values())})
        if p.startswith("/api/result/"):
            return self._send(200, {"psk": _known_psk(p.rsplit("/", 1)[-1])})
        if p == "/api/health":
            return self._send(200, {"ok": True, "tools": _tools()})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        p = self.path.split("?")[0]
        try:
            if p == "/api/analyze":
                bssid = self._body()["bssid"]
                hf, n = _convert(bssid)
                return self._send(200, {"hash_file": str(hf), "hashes": n})
            if p == "/api/crack":
                bssid = self._body()["bssid"]
                for j in JOBS.values():
                    if j["bssid"] == bssid and j["state"] == "running":
                        return self._send(200, j)
                return self._send(202, _start_crack(bssid))
            if p == "/api/stop":
                jid = self._body()["id"]
                j = JOBS.get(jid)
                if j:
                    j["state"] = "stopped"
                return self._send(200, {"ok": True})
            if p == "/api/scan":
                _SCAN["ts"] = 0
                return self._send(200, {"networks": merged_networks(), "agent": agent_status()})
            if p == "/api/capture":
                b = self._body()
                return self._send(202, _agent("/capture", "POST",
                                              {"channel": b.get("channel", "6"),
                                               "seconds": int(b.get("seconds", 90))}))
            if p == "/api/stopcapture":
                return self._send(200, _agent("/stop", "POST", {}))
            if p == "/api/handoff":
                return self._send(200, _handoff(self._body()["bssid"]))
            if p == "/api/refresh":
                _SCAN["ts"] = 0
                return self._send(200, {"networks": merged_networks()})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": str(e)})
        return self._send(404, {"error": "not found"})

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")


def _tools():
    out = {}
    for t in ("tshark", "hcxpcapngtool", "hashcat", "aircrack-ng", "iw"):
        out[t] = shutil.which(t) is not None
    out["wordlists"] = sorted(x.name for x in WORDLISTS.glob("*.txt"))
    return out


INDEX = (Path(__file__).parent / "index.html").read_bytes()

if __name__ == "__main__":
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "hashes").mkdir(exist_ok=True)
    print(f"wifi workspace on :{PORT} data={DATA} tools={_tools()}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
