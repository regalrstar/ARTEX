#!/usr/bin/env python3
"""Quiet, resumable corpus puller for the parking estate.

Rows first, images second, both throttled and hashed. Skips anything already on
disk, so interruption costs minutes, not the run.

  ./pull.py rows   --days 3  --out /Volumes/SSD/parking
  ./pull.py images --days 3  --out /Volumes/SSD/parking --rps 2

Defaults to the Grand Indonesia engine + every live agent for rows; images come
from the engine only (it is the sole image source).
"""
import argparse, gzip, hashlib, json, random, ssl, time, urllib.request
from datetime import date, timedelta
from pathlib import Path

AGENTS = "http://52.74.58.117:{}/external/v1/report/summary-lpr"
ENGINE = "https://district8.lpr-capture.alfabeta.co.id"
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def get(url, data=None, timeout=120):
    req = urllib.request.Request(url, data=data,
                                 headers={"User-Agent": UA,
                                          **({"Content-Type": "application/json"} if data else {})})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read()


def sha(b):
    return hashlib.sha256(b).hexdigest()


def log(path, rec):
    with path.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def live_agents():
    body = json.dumps({"startDate": f"{date.today()}T00:00:00.000Z",
                       "endDate": f"{date.today()}T01:00:00.000Z"}).encode()
    from concurrent.futures import ThreadPoolExecutor
    def probe(p):
        try:
            get(AGENTS.format(p), body, timeout=5)
            return p
        except Exception:
            return None
    with ThreadPoolExecutor(max_workers=32) as ex:
        return [p for p in ex.map(probe, range(8600, 8801)) if p]


def do_rows(out, days, rps):
    man = out / "manifest-rows.jsonl"
    ports = live_agents()
    print(f"{len(ports)} live agents", flush=True)
    for i in range(days):
        day = (date.today() - timedelta(days=i)).isoformat()
        d = out / "rows" / day
        d.mkdir(parents=True, exist_ok=True)
        nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        jobs = [("engine", None, f"https://district8.lpr-capture.alfabeta.co.id/history-gates?startDate={day}&endDate={nxt}", None)]
        for p in ports:
            body = json.dumps({"startDate": f"{day}T00:00:00.000Z", "endDate": f"{day}T23:59:00.000Z"}).encode()
            jobs.append(("agent", p, AGENTS.format(p), body))
        def one(job):
            kind, p, url, body = job
            f = d / f"{kind}-{p or 'gi'}.json.gz"
            if f.exists():
                continue
            try:
                raw = get(url, body, timeout=180)
                f.write_bytes(gzip.compress(raw))
                log(man, {"file": str(f), "sha256": sha(raw), "bytes": len(raw), "kind": kind, "port": p, "day": day})
            except Exception as e:
                log(man, {"file": str(f), "error": str(e)[:80], "kind": kind, "port": p, "day": day})
            time.sleep(random.uniform(0.2, 1.0 / rps if rps else 0.6))

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(one, jobs))
        print(day, "rows done", flush=True)


def do_images(out, days, rps):
    man = out / "manifest-images.jsonl"
    n = 0
    for i in range(days):
        day = (date.today() - timedelta(days=i)).isoformat()
        d = out / "img" / day
        d.mkdir(parents=True, exist_ok=True)
        nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        try:
            rows = json.loads(get(f"{ENGINE}/history-gates?startDate={day}&endDate={nxt}"))
        except Exception as e:
            print(day, "history fail", e, flush=True)
            continue
        for r in rows:
            for k in ("image_in", "image_out"):
                rel = r.get(k)
                if not rel:
                    continue
                name = rel.rsplit("/", 1)[-1]
                f = d / name
                if f.exists():
                    continue
                try:
                    raw = get(ENGINE + rel, timeout=60)
                    f.write_bytes(raw)
                    log(man, {"file": str(f), "sha256": sha(raw), "bytes": len(raw)})
                    n += 1
                except Exception:
                    log(man, {"file": str(f), "missing": True})
                time.sleep(random.uniform(0.3, 1.0 / rps if rps else 0.5))
        print(day, "images done", n, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["rows", "images"])
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rps", type=float, default=2.0)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (do_rows if a.what == "rows" else do_images)(out, a.days, a.rps)


if __name__ == "__main__":
    main()
