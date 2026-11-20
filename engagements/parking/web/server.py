#!/usr/bin/env python3
"""Parking console — local dashboard over the ANPR estate.

Reads cached inventory (data/*.json), queries live per-site agents and the
Grand Indonesia engine, caches thumbnails, keeps a watchlist.

    python3 server.py            # http://127.0.0.1:8792
"""
import csv, hashlib, io, json, os, re, ssl, threading, time, urllib.parse, urllib.request
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE.parent / "data"
THUMBS = HERE.parent / "thumbs"
CACHE = HERE.parent / "cache"
WATCH = HERE.parent / "watchlist.json"
EVENTS = HERE.parent / "watch_events.jsonl"
POLL = {"interval": 300, "last": 0, "busy": False}
AGENTS = "http://52.74.58.117:{}"
REPORT = "/external/v1/report/summary-lpr"
ENGINE = "https://district8.lpr-capture.alfabeta.co.id"
EUKLIS = "https://pqrcode.euklis.com/api"
PORT = 8792
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
AUTH = {"viewer": "ViewPass9341", "alfabeta": "Alfabeta43B!"}
LOCS = json.loads((DATA / "locations.json").read_text())
GATES = json.loads((DATA / "gates.json").read_text())
PORT2SITE = {}
for _l in LOCS:
    m = re.search(r":(\d+)$", _l.get("url") or "")
    if m:
        PORT2SITE[m.group(1)] = _l
AGENT_CACHE = {"ts": 0, "ports": []}
LAST = {"rows": []}


def live_agents():
    if time.time() - AGENT_CACHE["ts"] < 120:
        return AGENT_CACHE["ports"]
    body = json.dumps({"startDate": f"{date.today()}T00:00:00.000Z",
                       "endDate": f"{date.today()}T01:00:00.000Z"}).encode()

    def probe(p):
        try:
            r = urllib.request.Request(AGENTS.format(p) + REPORT, data=body,
                                       headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(r, timeout=4) as resp:
                return p if resp.status == 200 else None
        except Exception:
            return None

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=32) as ex:
        ports = [p for p in ex.map(probe, range(8600, 8801)) if p]
    AGENT_CACHE.update(ts=time.time(), ports=ports)
    return ports


def norm(p):
    return "".join((p or "").upper().split())


def car_from(path):
    m = re.search(r"/snapshot/[A-Z0-9-]+_[A-Z0-9]+_([^_]+)_([^_]+)_([^_]+)_", path or "")
    if not m:
        return ("", "", "")
    a, b, c = m.groups()
    if a == "brand" or b == "model":
        return ("", "", "")
    return (a, b, c)


def day_rows_agent(port, day):
    body = json.dumps({"startDate": f"{day}T00:00:00.000Z",
                       "endDate": f"{day}T23:59:00.000Z"}).encode()
    try:
        r = urllib.request.Request(AGENTS.format(port) + REPORT, data=body,
                                   headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=40) as resp:
            return json.loads(resp.read())
    except Exception:
        return {}


def day_rows_engine(day):
    import gzip
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"{day}.json.gz"
    if f.exists():
        try:
            return json.loads(gzip.decompress(f.read_bytes()))
        except Exception:
            pass
    nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    u = f"{ENGINE}/history-gates?startDate={day}&endDate={nxt}"
    try:
        with urllib.request.urlopen(u, timeout=150, context=CTX) as resp:
            raw = resp.read()
        f.write_bytes(gzip.compress(raw))
        return json.loads(raw)
    except Exception:
        return []


def search(plate, days, ports, prefix=False, agents=True):
    plate = norm(plate)
    rows, seen = [], set()
    today = date.today()

    def match(p):
        p = norm(p)
        return p.startswith(plate) if prefix else p == plate

    def engine_task(iso):
        out = []
        for r in day_rows_engine(iso):
            for k, dk, gk, ik in (("plate_in", "date_in", "gate_in", "image_in"),
                                  ("plate_out", "date_out", "gate_out", "image_out")):
                if not match(r.get(k)):
                    continue
                brand, model, col = car_from(r.get(ik))
                out.append({"src": "engine", "site": "Grand Indonesia", "port": None,
                            "plate": norm(r.get(k)), "ts": r.get(dk),
                            "dir": "IN" if k.endswith("in") else "OUT", "gate": r.get(gk),
                            "photo": ENGINE + r[ik] if r.get(ik) else None,
                            "brand": brand, "model": model, "color": col})
        return out

    def agent_task(port, start, end):
        out = []
        body = json.dumps({"startDate": f"{start}T00:00:00.000Z",
                           "endDate": f"{end}T23:59:00.000Z"}).encode()
        try:
            r = urllib.request.Request(AGENTS.format(port) + REPORT, data=body,
                                       headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(r, timeout=120) as resp:
                d = json.loads(resp.read())
        except Exception:
            d = {}
        for x in d.get("summaryLprs", []):
            if not match(x.get("vehiclePlateNumber")):
                continue
            site = (PORT2SITE.get(port) or {}).get("title") or f"site {port}"
            for t, dirn, gate in ((x.get("checkinTime"), "IN", x.get("entryGateName")),
                                  (x.get("checkoutTime"), "OUT", x.get("exitGateName"))):
                if t:
                    out.append({"src": "agent", "site": site, "port": port,
                                "plate": norm(x.get("vehiclePlateNumber")), "ts": t, "dir": dirn,
                                "gate": gate, "photo": None, "brand": x.get("entryVehicleBrand") or "",
                                "model": x.get("entryVehicleModel") or "", "color": x.get("entryVehicleColor") or "",
                                "slip": x.get("parkingSlipNumber")})
        return out

    from concurrent.futures import ThreadPoolExecutor
    isos = [(today - timedelta(days=i)).isoformat() for i in range(days)]
    jobs = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        # always query the engine: it is the only photo source
        for iso in isos:
            jobs.append(ex.submit(engine_task, iso))
        if ports and agents:  # chunked ranges: long windows in 7-day slices per agent
            from datetime import date as _d
            lo = _d.fromisoformat(min(isos)); hi = _d.fromisoformat(max(isos))
            while lo <= hi:
                chunk_end = min(lo + timedelta(days=6), hi)
                for p in ports:
                    jobs.append(ex.submit(agent_task, p, lo.isoformat(), chunk_end.isoformat()))
                lo = chunk_end + timedelta(days=1)
        for f in jobs:
            try:
                for r in f.result():
                    key = (r["site"], r["ts"], r["dir"])
                    if key in seen:
                        continue
                    seen.add(key); rows.append(r)
            except Exception:
                continue
    rows.sort(key=lambda r: r["ts"] or "")
    brands = {r["brand"].lower() for r in rows if r.get("brand")}
    for r in rows:
        r["collision"] = len(brands) > 1
    return rows


def thumb(url):
    h = hashlib.sha1(url.encode()).hexdigest()[:20]
    f = THUMBS / (h + ".jpg")
    if f.exists():
        return f
    try:
        with urllib.request.urlopen(url, timeout=25, context=CTX) as r:
            THUMBS.mkdir(exist_ok=True)
            f.write_bytes(r.read())
            return f
    except Exception:
        return None




def _wload():
    return json.loads(WATCH.read_text()) if WATCH.exists() else []


def _wsave(items):
    WATCH.write_text(json.dumps(items, indent=1))


def _event(kind, plate, row, note=""):
    rec = {"kind": kind, "plate": plate, "ts": row.get("ts"), "site": row.get("site"),
           "gate": row.get("gate"), "dir": row.get("dir"), "photo": row.get("photo"),
           "note": note, "seen": datetime.now().isoformat(timespec="seconds")}
    with EVENTS.open("a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    return rec


def track_once():
    """Poll watched plates over the last day and emit change events."""
    if POLL["busy"]:
        return 0
    POLL["busy"] = True
    n = 0
    try:
        items = _wload()
        if not items:
            return 0
        ports = live_agents()
        for w in items:
            plate = w["plate"]
            rows = search(plate, 1, ports)
            last_ts = w.get("last_ts") or ""
            new = [r for r in rows if (r.get("ts") or "") > last_ts]
            new.sort(key=lambda r: r["ts"] or "")
            for r in new:
                kind = "IN" if r["dir"] == "IN" else "OUT"
                if w.get("last_site") and r.get("site") != w.get("last_site"):
                    kind = "MOVED"
                _event(kind, plate, r)
                n += 1
                w["last_ts"] = r["ts"]
                w["last_site"] = r.get("site")
                w["last_dir"] = r["dir"]
            # open too long
            if w.get("last_dir") == "IN" and w.get("last_ts"):
                try:
                    age = (datetime.utcnow() - datetime.fromisoformat(
                        w["last_ts"].replace("Z", "+00:00")).replace(tzinfo=None)).total_seconds()
                except Exception:
                    age = 0
                if age > 5 * 3600 and w.get("dwell_alert_ts") != w.get("last_ts"):
                    _event("DWELL5H", plate, {"ts": w["last_ts"], "site": w.get("last_site"),
                                              "gate": "", "dir": "IN"},
                           "open longer than 5h")
                    w["dwell_alert_ts"] = w["last_ts"]
                    n += 1
        _wsave(items)
        POLL["last"] = time.time()
        return n
    finally:
        POLL["busy"] = False


def poller():
    while True:
        time.sleep(15)
        if time.time() - POLL["last"] >= POLL["interval"] and _wload():
            try:
                track_once()
            except Exception:
                pass

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _authed(self):
        import base64
        h = self.headers.get("Authorization") or ""
        if not h.startswith("Basic "):
            return False
        try:
            u, _, p = base64.b64decode(h[6:]).decode().partition(":")
        except Exception:
            return False
        return AUTH.get(u) == p

    def _gate(self):
        # local browser: no auth needed; tunnel requests arrive with X-Forwarded-For
        if self.client_address[0] in ("127.0.0.1", "::1") and not self.headers.get("X-Forwarded-For"):
            return True
        if self._authed():
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="parking"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _send(self, code, obj=None, raw=None, ctype="application/json"):
        b = raw if raw is not None else json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if not self._gate():
            return
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if u.path == "/":
            return self._send(200, raw=(HERE / "index.html").read_bytes(), ctype="text/html; charset=utf-8")
        if u.path == "/api/locations":
            q = (qs.get("q", [""])[0] or "").lower()
            out = [{"title": l["title"], "port": (re.search(r":(\d+)$", l["url"] or "") or [None, None])[1],
                    "addr": l.get("addr"), "deleted": l.get("deleted")}
                   for l in LOCS if q in (l.get("title") or "").lower() or q in (l.get("addr") or "").lower()]
            return self._send(200, {"items": out[:60], "total": len(out)})
        if u.path == "/api/agents":
            return self._send(200, {"ports": live_agents()})
        if u.path == "/api/thumb":
            f = thumb(qs.get("u", [""])[0])
            if not f:
                return self._send(404, {"error": "gone"})
            return self._send(200, raw=f.read_bytes(), ctype="image/jpeg")
        if u.path == "/api/watch":
            return self._send(200, {"items": _wload(), "poll": POLL})
        if u.path == "/api/alerts":
            rows = []
            if EVENTS.exists():
                rows = [json.loads(l) for l in EVENTS.read_text().splitlines()[-200:]]
            rows.reverse()
            return self._send(200, {"items": rows})
        if u.path.startswith("/api/timeline/"):
            p = norm(urllib.parse.unquote(u.path.rsplit("/", 1)[-1]))
            rows = []
            if EVENTS.exists():
                rows = [json.loads(l) for l in EVENTS.read_text().splitlines() if json.loads(l)["plate"] == p]
            return self._send(200, {"items": rows})
        if u.path == "/api/feed":
            ports = live_agents()[:12]
            rows = []
            for p in ports:
                d = day_rows_agent(p, date.today().isoformat())
                for x in d.get("summaryLprs", [])[:20]:
                    rows.append({"site": (PORT2SITE.get(p) or {}).get("title") or p, "port": p,
                                 "plate": x.get("vehiclePlateNumber"), "ts": x.get("checkinTime"),
                                 "gate": x.get("entryGateName")})
            rows = [r for r in rows if r["ts"]]
            rows.sort(key=lambda r: r["ts"], reverse=True)
            return self._send(200, {"items": rows[:60]})
        if u.path == "/api/export":
            buf = io.StringIO(); w = csv.writer(buf)
            w.writerow(["ts", "dir", "plate", "site", "gate", "brand", "model", "color", "photo"])
            for r in LAST["rows"]:
                w.writerow([r.get("ts"), r.get("dir"), r.get("plate"), r.get("site"), r.get("gate"),
                            r.get("brand"), r.get("model"), r.get("color"), r.get("photo")])
            return self._send(200, raw=buf.getvalue().encode(), ctype="text/csv")
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._gate():
            return
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/search":
            ports = [str(p) for p in body.get("ports") or live_agents()]
            rows = search(body.get("plate", ""), int(body.get("days", 3)), ports,
                          bool(body.get("prefix")), bool(body.get("agents", True)))
            LAST["rows"] = rows
            return self._send(200, {"items": rows, "count": len(rows),
                                    "sites": len({r["site"] for r in rows})})
        if u.path == "/api/person":
            q = (body.get("q") or "").lower()
            try:
                r = urllib.request.Request(EUKLIS + "/GetMobilePinsRequest", data=b'{"Filter":{}}',
                                           headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(r, timeout=25, context=CTX) as resp:
                    d = json.loads(resp.read())
            except Exception as e:
                return self._send(502, {"error": str(e)[:120]})
            out = []
            for m in d.get("MobilePins", []):
                i = m.get("Identity") or {}
                blob = " ".join(str(i.get(k) or "") for k in ("Name", "Surname", "Email", "PhoneNumber", "TaxCode")).lower()
                if q and q not in blob:
                    continue
                out.append({"id": i.get("IdentityID"), "name": f"{i.get('Name') or ''} {i.get('Surname') or ''}".strip(),
                            "email": i.get("Email"), "phone": i.get("PhoneNumber"), "tax": i.get("TaxCode"),
                            "pin": m.get("Pin"), "code": m.get("Code")})
            return self._send(200, {"items": out})
        if u.path == "/api/identity":
            iid = int(body.get("id"))
            try:
                r = urllib.request.Request(EUKLIS + "/GetIdentityCredentialRequest",
                                           data=json.dumps({"IdentityId": iid}).encode(),
                                           headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(r, timeout=25, context=CTX) as resp:
                    d = json.loads(resp.read())
            except Exception as e:
                return self._send(502, {"error": str(e)[:120]})
            return self._send(200, {"items": [{"plate": c.get("Plate"), "code": c.get("Code"),
                                               "type": c.get("CodeType")} for c in d.get("CredentialModels", [])]})
        if u.path == "/api/watch":
            items = _wload()
            p = norm(body.get("plate"))
            if p and not any(x["plate"] == p for x in items):
                rows = search(p, 2, live_agents())
                rows.sort(key=lambda r: r["ts"] or "")
                base = rows[-1] if rows else {}
                items.append({"plate": p, "label": body.get("label") or "",
                              "added": datetime.now().isoformat(timespec="seconds"),
                              "last_ts": base.get("ts"), "last_site": base.get("site"),
                              "last_dir": base.get("dir")})
                _wsave(items)
            return self._send(200, {"items": items})
        if u.path == "/api/poll":
            return self._send(200, {"events": track_once(), "poll": POLL})
        return self._send(404, {"error": "not found"})

    def do_DELETE(self):
        if not self._gate():
            return
        u = urllib.parse.urlparse(self.path)
        if u.path.startswith("/api/watch/"):
            p = norm(urllib.parse.unquote(u.path.rsplit("/", 1)[-1]))
            items = [x for x in _wload() if x["plate"] != p]
            _wsave(items)
            return self._send(200, {"items": items})
        return self._send(404, {"error": "not found"})


if __name__ == "__main__":
    THUMBS.mkdir(exist_ok=True)
    print(f"parking console on :{PORT}  sites={len(LOCS)} gates={len(GATES)}", flush=True)
    threading.Thread(target=live_agents, daemon=True).start()
    threading.Thread(target=poller, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
