# ARTEX — local install notes

Upstream `Autumn-27/ARTEX` was taken down / closed-sourced in Oct 2026. This install
uses the actively maintained English fork **`BaaRai/ARTEX`** (AGPL-3.0), cloned at
`artex/`. Upgrade path: `git pull` in this directory, then `./manage.sh up`.

## Run

```bash
./manage.sh up        # build (first run ~10-20 min) + start
./manage.sh logs      # follow backend logs
./manage.sh stop      # stop
```

- UI: http://localhost:8787 (loopback only). Traffic-recording proxy: 127.0.0.1:8788.
- `manage.sh backup` dumps Postgres to `backups/`.

## Login (already initialized)

- URL: http://localhost:8787  (setup page is used up; `/api/auth/status` → `initialized:true`)
- Username: `ARTEX` (fixed, read-only in the form)
- Password: `Artex-Local-7Qm4Xz!9`  ← change it in the UI, or `./reset-password.sh`
- The one-time setup token was consumed during install and is no longer valid.

## Build note (Apple Silicon)

bbot's own Chrome download is x86-64 and dies under Rosetta
(`rosetta error: failed to open elf at /lib64/ld-linux-x86-64.so.2`). The Dockerfile
installs Debian's arm64 `chromium` and links it as bbot's chrome path. If you `git pull`
an upstream Dockerfile over this, re-apply that hunk or the bbot layer breaks again.

## Instance conflict

A second install (`jiwoochris/artex-global`, prebuilt image) used to hold ports
8787/8788 from `~/Documents/Default Project/artex-engagement/artex-global`. It is
stopped; its volumes are intact. Restart it only after stopping this one.

## LLM wiring (already in `.env`)

OpenAI-compatible endpoint, so no code changes are needed:

```
ARTEX_LLM_PROVIDER=openai
ARTEX_LLM_MODEL=deepseek-v4.1-flash-uncensored
ARTEX_LLM_BASE_URL=https://api.experientiallabs.ai/v1
OPENAI_API_KEY=xpl_...
```

Change model/provider in the UI *LLM* page (`/system/llm`) or edit `.env` and
`./manage.sh up`. Supported formats: `anthropic`, `openai`, `openai-responses`, `ollama`.
Model profiles can be chained per task for failover.

The active config is also persisted in Postgres with `context_window_k=1000` (1M tokens,
matching the model) so compaction sizes correctly; without it ARTEX assumes 200K.
`POST /api/llm/test` round-trips the endpoint and returns `{"ok":true}`.

## Credentials

- Postgres password: in `.env` (`POSTGRES_PASSWORD`).
- Admin password: set on first visit to `/setup`; reset later with `./reset-password.sh`.

## Verified end-to-end (2026-11-08)

Task #1 "self-test" ran a full loop against a dummy local portal and finished `done`:
goals/seed → planner → 3 workers → tools → write-back → goals proven, 375K input tokens,
1 finding, 4 endpoint assets + service/ip/root_domain, coverage 83%.
Traffic capture was then switched on (Settings → `traffic_capture=true`) and a proxied
request landed in `/api/traffic`, so proxy evidence works too.

## Task templates (17, installed)

Tasks → **New task** → *Task template* picker. Applying copies description, goal,
category and task-level scope rules into the form; nothing is linked afterwards, so
edit the goal and replace `TARGET` before creating.

| Category | Templates |
|---|---|
| External Surface | Full-chain external red team · Perimeter appliance exploitation · Bug bounty max-impact · |
| Web & API | Web app full exploitation · API deep assault · GraphQL deep enumeration · Auth bypass & session attack · CMS/WordPress to RCE |
| Internal / AD | AD takeover from zero creds · AD assumed breach |
| Identity & Cloud | Cloud IAM privesc · Entra ID/M365 · Kubernetes/container takeover |
| Post-Exploitation | Internal pivot & spread · Data exfiltration & impact |
| Supply Chain | CI/CD & supply chain |
| Lab / CTF | Max aggression (disposable labs) |

Scope rules baked in: external templates block 13 third-party noise domains
(analytics/CDN/SaaS) so workers do not burn intents on them; internal and
post-exploitation templates whitelist RFC1918 + IPv6 ULA and nothing else. The
whitelist is strict — an internal template blocks an external target until you add it.

## WiFi workspace (port 8790)

Offline capture triage. Drop `.cap/.pcap/.pcapng/.22000` into `data/wifi/`, open
http://127.0.0.1:8790, pick a network, press *crack*. It runs hcxpcapngtool →
hashcat (WPA-specific lists → rockyou → rules → SSID mask), streams H/s and ETA,
and shows the PSK. `→ task` creates an ARTEX task from template #19 pre-wired to the
converted hash.

No radio: capture outside (PortaPack IQ → pcap via `gr-ieee802-11`, or a
monitor-mode dongle on a Linux host). The service is source-pluggable — a live
`iw`/`airodump` source drops in without touching the API or UI.

`data/wifi/test-wpa.cap` ships as a sample: aircrack-ng test vector, SSID `test`,
4-way handshake, PSK `biscotte` (cracks in ~8s at 8.6 kH/s on CPU OpenCL). Use it to
sanity-check the pipeline, then delete it.

## Live scan (optional, macOS host agent)

Scanning and capturing need root, so they run in a host process, not the container:

```bash
./manage.sh agent          # = sudo python3 wifi/agent.py, Ctrl-C to stop
```

With it running, the Wireless page gains **scan around** and a per-row **capture 90s**.
The token is generated at `data/wifi/agent.token` (0600) and the agent binds 8791 so
the container can reach it via `host.docker.internal`; it exposes only scan/capture/stop.

Capture forces the card into monitor mode: **internet drops for the duration**, the
dashboard keeps working over loopback. macOS cannot deauth, so a handshake still needs
a client to reconnect — toggle a phone on the target network while it records.

## Scope / safety defaults

The guard blocks `.gov`, `.gov.cn`, `.edu`, `.edu.cn` and destructive HTTP verbs by
default, then runs an LLM judge, then asks a human. Per-task allow/deny rules and
`System Settings` → worker concurrency (default 3) are where you tighten a test.
Everything a worker sends goes through the recording proxy on 8788 as evidence.

## Persistence

`./data` (files, SQLite, task state) and `./keys` (JWT signing key) are host bind
mounts and survive rebuilds. `pgdata` is a Docker volume — do not `docker compose down -v`.
