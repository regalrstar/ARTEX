#!/usr/bin/env python3
"""Scan the full retained window for a plate prefix, dump hits (ts, gate, photo).

Usage: ./scan_prefix.py B27 [--days 470] [--out hits.jsonl]
"""
import argparse
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

BASE = "https://district8.lpr-capture.alfabeta.co.id"


def day_rows(day):
    nxt = day + timedelta(days=1)
    url = f"{BASE}/history-gates?startDate={day}&endDate={nxt}"
    try:
        with urllib.request.urlopen(url, timeout=90, context=_ctx()) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return []


def _ctx():
    import ssl
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix")
    ap.add_argument("--days", type=int, default=470)
    ap.add_argument("--out", default="hits.jsonl")
    a = ap.parse_args()
    pre = "".join(a.prefix.upper().split())
    today = date.today()
    days = [today - timedelta(days=i) for i in range(a.days)]
    hits = 0
    with open(a.out, "w") as out, ThreadPoolExecutor(max_workers=4) as ex:
        for day, rows in zip(days, ex.map(day_rows, days)):
            for r in rows:
                for k, dk, gk, ik in (("plate_in", "date_in", "gate_in", "image_in"),
                                      ("plate_out", "date_out", "gate_out", "image_out")):
                    p = "".join((r.get(k) or "").upper().split())
                    if p.startswith(pre):
                        rec = {"plate": p, "gate": r.get(gk), "ts": r.get(dk),
                               "direction": "IN" if k.endswith("in") else "OUT",
                               "photo": (BASE + r[ik]) if r.get(ik) else None}
                        out.write(json.dumps(rec) + "\n")
                        hits += 1
            print(f"{day} rows={len(rows)} hits={hits}", flush=True)
    print(f"done: {hits} hits -> {a.out}")


if __name__ == "__main__":
    main()
