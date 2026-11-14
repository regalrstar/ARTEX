# Anonymous egress before scanning

Threat model chosen: **target-side only.** Scans must not be traceable to the home IP;
LLM calls stay direct (the provider sees prompts, not targets).

A proxy alone is not enough — `nmap` uses raw sockets and ignores `HTTP_PROXY`. The
tunnel must be at the network layer. ARTEX's `global_proxy` is only a second belt.

## One-time setup

1. **Account, no identity** — https://mullvad.net/en/account/create
   Generates a 16-digit account number. No email. Pay with cash or crypto; EUR 5/month.
   Save the number; it is the only credential.

2. **Install**

   ```bash
   brew install --cask mullvad-vpn
   ```

3. **Log in and lock down**

   ```bash
   mullvad account login <16-digit-number>
   mullvad lockdown-mode set on      # kill switch: no tunnel, no traffic
   mullvad relay set location id     # any relay; note it per engagement
   mullvad connect
   mullvad status
   ```

4. **Verify from inside the container** (this is the part that matters):

   ```bash
   docker compose exec -T artex bash /app/data/anonymity-check.sh
   ```

   Expect every line `PASS`. The baseline is the home IP, recorded already; if the
   egress still equals it, Docker Desktop is not following the host tunnel and you
   must not scan yet.

```bash
# re-record the baseline after changing ISP/network
docker compose exec -T artex bash /app/data/anonymity-check.sh --baseline
```

## If the container leaks despite a connected tunnel

Docker Desktop's VM may not follow the host route. Fallbacks, in order:

1. **SOCKS relay to the VPN** — Mullvad exposes SOCKS5 at `10.64.0.1:1080` while
   connected. Relay it into Docker and set it as the global proxy:

   ```bash
   brew install socat
   socat TCP-LISTEN:1080,bind=0.0.0.0,reuseaddr,fork TCP:10.64.0.1:1080
   ```

   Then System Settings → `global_proxy` = `socks5://host.docker.internal:1080`.
   Note: this fixes HTTP tools only. `nmap` still needs the network path.

2. **Linux VM** — run ARTEX in a VM whose uplink is the VPN. This is the reliable
   answer when Docker Desktop will not cooperate, and it is also the path to the
   live WiFi source (USB passthrough).

## Per-engagement hygiene

- New relay per engagement; the IP changes with it.
- Lockdown mode stays on. If the tunnel drops, traffic dies rather than falling back.
- Exit IP is shared with other Mullvad users — good for blending, bad for targets that
  ban VPN ranges (Cloudflare captchas, aggressive WAFs).
- The VPN provider sees destinations; the target sees a VPN IP; the LLM provider sees
  prompts. Nothing here protects against a global passive adversary correlating both.
- Do not log into personal accounts (Google, GitHub) from the scanning browser tab if
  you want the run kept separate.
