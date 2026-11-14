#!/usr/bin/env python3
"""plate — look up an Indonesian plate in the exposed ANPR feeds.

Usage:
    ./plate.py B2643BBO            # last 7 days
    ./plate.py B2643BBO --days 30
    ./plate.py B2643BBO --json

Sources (both anonymous, no auth):
  alfabeta district8 LPR engine  /history-gates  (plate_in/out, gate, ts, snapshot path)
  parkee agent report            /external/v1/report/summary-lpr  (sessions)
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta

SRC_HIST = "https://district8.lpr-capture.alfabeta.co.id/history-gates"
SRC_SNAP = "https://district8.lpr-capture.alfabeta.co.id"
SRC_REPORT = "http://52.74.58.117:8602/external/v1/report/summary-lpr"


def norm(p):
    return "".join((p or "").upper().split())


def get(url, timeout=120, data=None):
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _day_rows(day):
    """The engine ignores plate filters and caps payloads, so query one day at a time."""
    # endDate is exclusive: a single-day window returns nothing
    url = f"{SRC_HIST}?startDate={day}&endDate={day + timedelta(days=1)}"
    try:
        rows = get(url, timeout=90)
    except Exception:  # noqa: BLE001
        return []
    return rows if isinstance(rows, list) else []


def hits_history(plate, days):
    out = []
    today = date.today()
    for offset in range(days):
        for r in _day_rows(today - timedelta(days=offset)):
            if norm(r.get("plate_in")) == plate:
                out.append({"source": "lpr-engine", "plate": plate, "gate": r.get("gate_in"),
                            "direction": "IN", "ts": r.get("date_in"),
                            "photo": SRC_SNAP + r["image_in"] if r.get("image_in") else None,
                            "open": not r.get("date_out"), "raw_id": r.get("id")})
            if norm(r.get("plate_out")) == plate:
                out.append({"source": "lpr-engine", "plate": plate, "gate": r.get("gate_out"),
                            "direction": "OUT", "ts": r.get("date_out"),
                            "photo": SRC_SNAP + r["image_out"] if r.get("image_out") else None,
                            "open": False, "raw_id": r.get("id")})
    return out


def hits_report(plate, days):
    out = []
    today = date.today()
    for offset in range(days):
        day = today - timedelta(days=offset)
        body = json.dumps({"startDate": f"{day}T00:00:00.000Z",
                           "endDate": f"{day}T23:59:00.000Z"}).encode()
        try:
            d = get(SRC_REPORT, data=body, timeout=90)
        except Exception:  # noqa: BLE001
            continue
        for r in d.get("summaryLprs", []):
            if norm(r.get("vehiclePlateNumber")) != plate:
                continue
            if r.get("checkinTime"):
                out.append({"source": "parkee-report", "plate": plate,
                            "gate": r.get("branchMatch") or r.get("branchCode"),
                            "direction": "IN", "ts": r.get("checkinTime"),
                            "photo": None, "open": not r.get("checkoutTime"),
                            "slip": r.get("parkingSlipNumber")})
            if r.get("checkoutTime"):
                out.append({"source": "parkee-report", "plate": plate,
                            "gate": r.get("branchMatch") or r.get("branchCode"),
                            "direction": "OUT", "ts": r.get("checkoutTime"),
                            "photo": None, "open": False,
                            "slip": r.get("parkingSlipNumber")})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plate")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    plate = norm(a.plate)
    rows = hits_history(plate, a.days) + hits_report(plate, a.days)
    rows.sort(key=lambda r: r.get("ts") or "")
    if a.json:
        print(json.dumps(rows, indent=1))
        return
    if not rows:
        print(f"{plate}: no records in the last {a.days} days")
        return
    open_now = [r for r in rows if r.get("open")]
    print(f"{plate}: {len(rows)} records, {len(open_now)} open\n")
    for r in rows:
        flag = "STILL IN" if r.get("open") else "left"
        print(f"{r['ts']}  {r['direction']:<3} {r.get('gate') or '?':<14} {flag:<9} {r['source']}")
        if r.get("photo"):
            print(f"    {r['photo']}")


if __name__ == "__main__":
    main()
