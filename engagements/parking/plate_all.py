#!/usr/bin/env python3
"""plate_all — search every live per-site agent for one plate.

Usage: ./plate_all.py B66REG [--days 2] [--ports live.txt]
"""
import argparse, json, ssl, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
HOST = "http://52.74.58.117:{}"
REPORT = "/external/v1/report/summary-lpr"


def probe(port):
    body = json.dumps({"startDate": f"{date.today()}T00:00:00.000Z",
                       "endDate": f"{date.today()}T01:00:00.000Z"}).encode()
    try:
        r = urllib.request.Request(HOST.format(port) + REPORT, data=body,
                                   headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=5) as resp:
            return port if resp.status == 200 else None
    except Exception:
        return None


def live_ports():
    with ThreadPoolExecutor(max_workers=40) as ex:
        return [p for p in ex.map(probe, range(8600, 8801)) if p]


def day_hits(port, day, plate):
    body = json.dumps({"startDate": f"{day}T00:00:00.000Z",
                       "endDate": f"{day}T23:59:00.000Z"}).encode()
    try:
        r = urllib.request.Request(HOST.format(port) + REPORT, data=body,
                                   headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=45) as resp:
            d = json.loads(resp.read())
    except Exception:
        return []
    out = []
    for x in d.get("summaryLprs", []):
        if "".join((x.get("vehiclePlateNumber") or "").upper().split()) != plate:
            continue
        for t in (x.get("checkinTime"), x.get("checkoutTime")):
            if t:
                out.append({"port": port, "ts": t, "gate": x.get("entryGateName") or x.get("exitGateName"),
                            "slip": x.get("parkingSlipNumber")})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plate")
    ap.add_argument("--days", type=int, default=2)
    a = ap.parse_args()
    plate = "".join(a.plate.upper().split())
    ports = live_ports()
    print(f"{len(ports)} live agents", flush=True)
    days = [date.today() - timedelta(days=i) for i in range(a.days)]
    hits = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(day_hits, p, d, plate) for p in ports for d in days]
        for f in futs:
            hits.extend(f.result())
    seen=set(); uniq=[]
    for h in hits:
        k=(h["port"], h["ts"], h["slip"])
        if k in seen: continue
        seen.add(k); uniq.append(h)
    hits = uniq
    hits.sort(key=lambda h: h["ts"])
    for h in hits:
        print(f"{h['ts']}  port {h['port']}  gate {h['gate']}  slip {h['slip']}")
    print(f"{len(hits)} hits across {len({h['port'] for h in hits})} sites")


if __name__ == "__main__":
    main()
