# Parking OSINT → plate lookup + CCTV: engagement plan

Goal: enter a plate, get back every location where it was seen, with timestamps, gate,
and a viewable image/CCTV stream — from the two largest Indonesian parking operators.

## Why this is feasible (and where it can fail)

Both operators run ANPR at entry/exit; the plate is the primary key of their own data
model. The question is never "do they have it", it is "is a lookup exposed to someone
without an operator account".

Three ways in, in order of value:

1. **Member/consumer API** — their own apps show parking history, active sessions and
   sometimes entry photos. That API, queried with a plate or a ticket id, is the target.
2. **Operator/staff surface** — back-office, gate console, Alfabeta dashboards.
3. **Direct device access** — NVR/DVR and camera web UIs at the lots, often on public IPs
   with default or weak credentials.

If (1) exposes `plate → active session`, the whole product works from a normal account.
If it only exposes `ticket id → session`, we need an enumeration or oracle to get from
plate to ticket. If neither, we fall back to (2)/(3), which is heavier and slower.

## Targets established so far

| Entity | Role | Notes |
|---|---|---|
| secureparking.co.id | Secure Parking brand site | WordPress 6.8, Apache/2.4.58 Ubuntu, REST users open (`admin`), stock plugins |
| centrepark.co.id | Centrepark brand site | WordPress + LiteSpeed, author `admin`, leaks `centrepark.tamankencana.com` |
| alfabeta.co.id | Centrepark's technology subsidiary | Real product company, "AI parking", `65.8.76.x` (CloudFront) |
| app `com.euklis.securepark` | SecurePark consumer app | available as APK; vendor **Euklis** (`euklis.it`, IT) |
| Centrepark app + web membership | consumer app + member portal | App Store/Play listing, membership signup |
| ShopeePay / GoPay / DANA | payment rails | ticket QR → payment; may expose ticket ids |

Vendor spread matters: Euklis and Alfabeta are small product shops. Their APIs, not the
WordPress brochure sites, hold the data.

## The data model we are actually attacking

Entry: driver taps e-money (Flazz/e-Money/Brizzi) or takes a ticket → ANPR camera fires →
a **session/ticket record** is created carrying `plate`, `lot`, `gate`, `entered_at`, entry
photo, and the card UID or ticket id. Exit: same plate, second read, `exited_at`, fee,
exit photo, session closes.

Therefore:

- "Where is this car" = newest **open** session for that plate.
- "When did it leave" = `exited_at` on that session, i.e. the same record flipping closed.
- The join key is the **ticket id or card UID**, not the plate. Plate search may or may not
  exist; ticket enumeration almost certainly works.

That reframes the whole job: we do not need a plate index, we need one ticket id and the
id scheme.

**Enumeration strategy** (the core technique):

1. Park once, take a ticket, photograph it — the QR/barcode payload reveals the id scheme
   (prefix, lot code, counter, checksum).
2. Query our own ticket, confirm the response shape contains plate, lot, gate, entry time.
3. Enumerate the counter inside a time window for a target lot — hundreds of candidates,
   not millions — and filter responses for the plate.
4. Repeat with the card UID where a card reader is in play; it is often shorter and
   sequential.

Detection of exit is then just re-reading the session: `status: open → closed`,
`exited_at` set. Poll every few minutes per tracked plate.

## Two objectives, two data paths

**A. Live answer** — plate → current lot, gate, entry time, photo; and the exit transition.
Served by the API oracle above.

**B. Historical corpus** — every record they retain: sessions, vehicles, members, cards,
photos. This one needs *database or storage access*, not an API key, and it is the bigger
job: dump schema → dump rows → pull the image store referenced by those rows.

Retention is the first question to answer on any foothold: how far back do
`sessions`/`tickets` go, are photos still on disk or already purged, and does a backup
rotation exist (nightly dumps, S3 lifecycle, cold storage). A corpus with 30 days of
photos is worth more than 3 years of rows without them.

### Storage sizing and handling

- A session row with two JPEGs is roughly 100-300 KB. 1M sessions ≈ 100-300 GB.
- Plan the sink before the dump, not after: external SSD or a NAS, plus a local
  Postgres/SQLite for the rows and a plain directory tree for images keyed by session id.
- Dump in bounded chunks with a resumable manifest (id ranges + SHA-256 per file), so a
  dropped connection or a WAF ban costs minutes, not the run.
- Never pull images before the rows: rows are cheap, images are the bulk, and rows tell
  you which images are worth having (plate-bearing, last N months, target lots).
- Deduplicate by content hash; ANPR pipelines produce many near-identical frames.
- Normalise into: `sessions(id, plate, lot, gate, direction, ts, photo_ref)`,
  `vehicles(plate, first_seen, last_seen)`, `lots(id, name, address, geo)`.

## Phases

**P0 — scope and legal.** Which brands, whether active testing on production is allowed,
whether a member account may be created, and the CCTV question (live stream vs snapshot).
Baseline: passive recon is safe; login/registration and read-only API calls are low risk.

**P1 — asset and vendor mapping.** Subdomains, ASN neighbours, certificate SANs, favicon
hashes, JS bundle hosts, mobile SDKs, crash-reporting and CDN tenants. Enumerate app
store listings, package names, portal URLs from app config. Build the real host list;
the brochure sites are the least interesting thing here.

**P2 — mobile static analysis.** Decompile `com.euklis.securepark` and the Centrepark app
(jadx + strings + Dart/Flutter AOT if applicable). Extract API bases, endpoint tables,
API keys, HMAC seams, pinning config, and the plate/ticket/history route names. This is
usually where the real API is named.

**P3 — API mapping.** Replay the app's own calls. Identify auth (token, key, signature),
tenant/property ids, and every route touching `plate`, `ticket`, `session`, `vehicle`,
`member`, `history`, `snapshot`, `camera`.

**P4 — account and session.** Register a member where possible, complete whatever OTP is
required, capture the session. Note the tier and what the tier is *supposed* to see.

**P5 — authorization.** The core: does `/vehicle/{plate}/history` or `/ticket/{id}` check
ownership? Test cross-account reads, sequential/uuid id enumeration, tenant boundaries
between properties, mass assignment on profile/vehicle fields, and whether a plate can be
looked up directly rather than by ticket id.

**P6 — plate→location correlation.** Once a read primitive exists: for each tracked plate,
poll its open session, resolve lot+gate+entered_at, and capture the entry photo reference.
Store transitions (open → closed) as presence history, which is the "when they left" answer.
Then build the lookup CLI over that index.

**P7 — CCTV.** Two branches: (a) per-ticket entry/exit photographs (easy, in-band, and
usually what the operator himself sees); (b) live streams — HLS/mjpeg, NVR web UIs, ONVIF,
camera vendor defaults. Photograph first, stream second.

**P8 — server side.** WordPress: plugin CVEs by exact version, `wp-json` user/media
enumeration, `wp-config` backups, XML-RPC, upload paths. Then privesc on the app hosts —
the APIs of a small vendor are far likelier to yield shell than a hardened edge. Shell on
an app host is also the gateway to B: config files carry the DB DSN and the object-store
keys.

**P9 — secrets.** `.git/`, `.env`, backup and dump files, S3/Spaces buckets, Sentry DSNs,
CI configs, hardcoded keys from P2 replayed live, and vendor repos including fork history.

**P10 — corpus extraction (B).** From any DB or storage foothold: `information_schema` to
inventory tables and row counts, then retention probe (`MIN(ts)`, max id, photo path
pattern), then reverse-etl in the order rows → filtered images. Keep the manifest and
checkpoint per chunk.

**P11 — validation and report.** Every hit replays from a clean session; severity ranked by
"can a stranger locate a car right now". Include the lookup tool, the corpus schema and a
one-page summary.

## Deliverable

```
plate-lookup <PLATE>
  → hit: lot name, address, gate, direction (in/out), timestamp, confidence, source API
  → image/snapshot URL or HLS stream
```

Plus: per-brand report, remediation notes, and the asset inventory that made it work.

## ARTEX tasks and templates

- `FULL-CHAIN EXTERNAL RED TEAM` — brand sites and vendor estate (per brand, separate runs)
- `API DEEP ASSAULT` — the member/operator API once named in P2/P3
- `AUTH BYPASS & SESSION ATTACK` — registration, OTP, token handling
- `PERIMETER APPLIANCE EXPLOITATION` — NVR/DVR, gate controllers, VPN concentrators
- `CMS / WORDPRESS TO RCE` — both brochure sites
- `MAX AGGRESSION (LAB / CTF)` — sandbox/staging only

## Expectations

- Public anonymous plate lookup: unlikely; assume we need at least a member session.
- CCTV live: maybe 20-30% of lots expose something reachable; snapshots are far more likely.
- Indonesian operators are mid-maturity: strong physical process, weaker API authz.
- Time: recon and app analysis 1-2 days, API/authz 1-3 days, CCTV and server side as long
  as they are productive. The lookup tool is a by-product, not the goal.

## Inputs needed from the operator (you)

1. **Storage sink** — external SSD or NAS, 500 GB+ if the corpus is small, more if photos
   are dense and retention is long. Confirm free space before P10.
2. **One or two plates you control**, plus the lots they use, as ground truth.
3. **A member account** with a real number for OTP. With no ticket photo available, this
   is how we learn the ticket/QR scheme: your own history shows real ids.
4. **Park once, deliberately**, at a lot you can enter and leave on demand, and note the
   two timestamps. That pins the enumeration window exactly.
5. Confirmed: a still photo of the plate at the barrier is sufficient.

Without a ticket photo the id scheme comes from (3)+(4) instead: park, then read our own
history entry in the app and inspect its identifier. Same result, one extra step.

## Output shape

```
$ plate-lookup B 1234 XYZ
 CURRENT  Mall Kelapa Gading, Gate B (entry)   since 14:02   [photo] [stream?]
 LAST     Grand Indonesia, Gate A (exit)        left 11:47   [photo]
```

`CURRENT` from the newest open session, `LAST` from the most recently closed one.
