# Disposable scan boxes

Every engagement gets a fresh box, a fresh IP, and a fresh VPN exit. Nothing is
reused and nothing is kept unless exported.

## Sizing

4 vCPU / 8 GB / 80 GB is right for 1-2 tasks. 8 / 16 / 160 for 3-4 tasks. Only go
16 / 32 if you genuinely run 5+ tasks at once; RAM caps you near 20-24 workers
regardless of cores. On 16 vCPU only, export `ARTEX_CPUSET=0-11 WIFI_CPUSET=12-15`
so cracking on the box (if you insist) cannot starve workers; on 4-8 vCPU leave them
empty. Cracking does not belong here — see below.

## Providers

**Vultr is the default** — real stock, `sgp` region for Asian latency, crypto accepted,
API deploy works. BuyVM is supported but sells out for days at a time.

Vultr: create the account, add crypto credit, then my.vultr.com → Settings → API.
Plan `vhf-2c-4gb` ($24/mo, 2 vCPU high-frequency) is the sane pick; `vc2-2c-4gb`
($20/mo) is the cheap equivalent. `sgp` unless the targets are elsewhere.

## Flow

1. Provision, either by API:

   ```bash
   VULTR_API_KEY=... ./deploy/deploy.sh --create
   ```

   or by hand in the panel (Debian 12, your SSH key), then `--host root@IP`.
2. `MULLVAD_ACCOUNT=... MULLVAD_LOCATION="sg sin" OPENAI_API_KEY=... ./deploy/deploy.sh --create`
3. Open the tunnel it prints. The panel is loopback-only.
4. Work. Export findings when done.
5. `PROVIDER=vultr VULTR_API_KEY=... ./deploy/destroy.sh root@IP` — dumps the DB to
   `exports/`, then the box dies.

Time: ~5-7 minutes cold. The image is built once and pushed over scp; no registry
account needed.

## What the bootstrap enforces

- SSH key-only, password auth off, ufw deny-incoming except 22.
- Mullvad installed, logged in, **lockdown mode on before any traffic**, then connect.
- ARTEX, Postgres and the WiFi workspace bind `127.0.0.1` only — reachable through the
  tunnel, never from the internet.
- `nofile` 65535 and raised conntrack, because parallel scans hit those before CPU.

## Cracking

Not on the box. 16 vCPU of pocl is ~40-60 kH/s; the M4 Metal GPU measures **108.7 kH/s**
and a rented 4090 is ~1-2 MH/s.

- Local: `hashcat -m 22000 -d 1 hash.22000 rockyou.txt` on the Mac (GPU, ~12x the box).
- Rented GPU when the job is big: Vast.ai 4090, upload the `.22000`, run, destroy. Pay
  per hour, nothing persists.

Cracking never needs the VPN or the scan box: the hash files are inert.

## Anonymity notes specific to this shape

- Pay the hoster in crypto; a card purchase names you.
- SSH through Mullvad, otherwise the hoster records your home IP against the instance.
- The VPS IP is fresh per engagement — better than a shared VPN pool for Cloudflare, and
  the reason a VPN inside the VPS is optional rather than mandatory.
- Destroy, do not reuse. A box alive for weeks accumulates a history.
