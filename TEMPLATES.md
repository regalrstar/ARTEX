# Which ARTEX template to use, and when

Pick a template from **Tasks → New task → Task template**. Applying one copies its
description, goal, category and scope rules into the form; replace `TARGET` and the
placeholders, then create.

If you are unsure: **Web App Full Exploitation** for a normal web target,
**Full-Chain External Red Team** for a whole external estate, **CEX Account Drain** when
the objective is moving funds, **Max Aggression** only on a lab box.

## External Surface

| Template | What it does | Use when | You must supply | Typical run | Blast radius |
|---|---|---|---|---|---|
| Full-Chain External Red Team | Recon → exploit → privesc → lateral → domain/tenant proof, in one continuous chain | Real external engagement with a written scope; you want an end-to-end story | Entry URL, full in-scope domain/CIDR list | Hours, millions of tokens | High: exploits, may change data |
| Perimeter Appliance Exploitation | Exact-build fingerprint of VPN/edge gear, then auth bypass → RCE or config grab | Client exposes Citrix/Fortinet/Pulse/GlobalProtect/Exchange/MOVEit | Appliance host list | 1-3h | Medium-high |
| Bug Bounty Max-Impact Sprint | Low-duplicate classes, strict scope, submission-ready reports | You are hunting a program for payout | Program scope + payout rules + disclosed-report list | 1-4h | Medium |

## Web & API

| Template | What it does | Use when | You must supply | Typical run | Blast radius |
|---|---|---|---|---|---|
| Web App Full Exploitation | Every injection class with WAF bypass, chained to RCE/data access | Standard web app pentest, staging or prod | URL, hosts, test accounts | 1-4h | High: uploads, injection, writes |
| API Deep Assault | BOLA/BFLA, mass assignment, JWT/OAuth abuse, tenant isolation | REST API with at least two roles | Base URL, two role tokens, OpenAPI doc | 1-3h | Medium-high |
| GraphQL Deep Enumeration | Schema rebuild without introspection, then field authz/BOLA/injection | GraphQL endpoint, introspection off | Endpoint, per-role tokens | 1-3h | Medium |
| Auth Bypass & Session Attack | Reset flaws, MFA bypass, JWT/OAuth/SAML breaks, fixation | Login/SSO is the interesting surface | Login URL, SSO config, test accounts | 1-2h | Medium: lockouts possible |
| CMS / WordPress to RCE | Version-matched core/plugin exploits → admin → RCE → config secrets | WordPress/Joomla/Drupal site | URL, and a backup if production | 1-2h | High: plugin edits, files written |

## Internal / AD

| Template | What it does | Use when | You must supply | Typical run | Blast radius |
|---|---|---|---|---|---|
| AD Takeover From Zero Creds | Unauth AD enum, roast, relay, spray, privesc, DA proof | Internal test starting with no account | Domain, DC IP, reachable subnet | 2-6h | High: account lockouts, relay |
| AD Assumed Breach | ACL abuse, delegation, ADCS ESC1-8, shortest path to DCSync | You were handed a low-priv domain user | Domain, DC, that user's creds | 1-3h | High |

## Identity & Cloud

| Template | What it does | Use when | You must supply | Typical run | Blast radius |
|---|---|---|---|---|---|
| Cloud IAM Privesc | Enumerate identity, walk privesc paths, admin-equivalent + live data access | Cloud review with a starting key/role | Account/tenant id, region scope, start creds | 1-3h | High: may create resources |
| Entra ID / M365 | Enum, tuned spray, device-code, illicit consent, Graph/Teams/SharePoint abuse | Microsoft 365 tenant review | Tenant domain, 1-2 known accounts | 2-4h | Medium: spray lockouts |
| Kubernetes / Container Takeover | Anonymous API, kubelet, SA tokens, RBAC to cluster-admin, node escape | Exposed cluster or a pod shell | API server/kubelet or pod access | 1-3h | High |

## Post-Exploitation

| Template | What it does | Use when | You must supply | Typical run | Blast radius |
|---|---|---|---|---|---|
| Internal Pivot & Spread | Tunnel, harvest creds, spray once, move, hit crown jewels | You already own one internal host | Foothold host + access method | 2-5h | High |
| Data Exfiltration & Impact Proof | Locate crown-jewel data, exfil a verified sample, quantify | You need the "so what" for the report | Foothold host + creds | 1-2h | Medium: read-only mostly |

## Crypto / Fintech

| Template | What it does | Use when | You must supply | Typical run | Blast radius |
|---|---|---|---|---|---|
| CEX Account Drain | Money-path logic, precision/race/idempotency, 2FA and API-key bypass, ends in a real withdrawal or internal transfer | Exchange or custodial wallet where the point is moving funds | Funded test account, 2FA seed, API key pair, your withdrawal address, value cap | 2-5h | High: real funds leave |

Notes for this one:

- Say whether you are on **testnet or mainnet**; on mainnet add "cap = X, ask before
  exceeding it" or the agent may broadcast more than you expect.
- A trade-only API key is worth supplying even when you also have a session — proving a
  scope break is half the finding.
- Withdrawal and internal transfer are different proofs. Internal transfer is acceptable
  only when external withdrawal is blocked by whitelist or KYC.
- Race/duplicate-spend work needs **parallel** intents; do not lower worker count.

## Wireless

| Template | What it does | Use when | You must supply | Typical run | Blast radius |
|---|---|---|---|---|---|
| WIFI WPA/WPA2/PMKID CRACK | Validates a capture, then cracks WPA-specific lists → rockyou → rules → targeted masks, verifies the PSK; optional WPS Pixie-Dust | You already hold a handshake/PMKID file | The capture file (and SSID/BSSID) | Minutes to hours, depends on password | Read-only, no deauth unless you say so |

Important: **the container has no radio.** Capture on the host with a monitor-mode
adapter (or a Kali VM), then upload the `.cap`/`.pcapng`/`.22000`. Only run live capture
inside ARTEX when it is deployed on a Linux host with the adapter passed through —
macOS Docker Desktop cannot pass USB through.

## Supply Chain

| Template | What it does | Use when | You must supply | Typical run | Blast radius |
|---|---|---|---|---|---|
| CI/CD & Supply Chain | Token over-permission, PR-target, runner takeover, artifact poisoning | SCM org, Jenkins/GitLab, registry in scope | Org/repo URL, CI host | 2-4h | High: commits, builds |

## Lab / CTF

| Template | What it does | Use when | You must supply | Typical run | Blast radius |
|---|---|---|---|---|---|
| Max Aggression | No rate limits, all scanners at once, destructive allowed | Disposable lab, HTB/CTF, snapshot taken | Target URL | 30-90 min | Destructive |

## Rules of thumb

- **Snapshot first** before anything destructive (Max Aggression, CMS, Cloud IAM).
- **Never run Auth Bypass or AD Zero-Creds against prod** without knowing the lockout
  policy; lower the spray or hand over a user.
- Internal templates **whitelist RFC1918 only**; add the target's host/CIDR or the first
  intent is refused.
- External templates **block analytics/CDN noise** so budget is not wasted. Remove a
  block if the CDN host is genuinely in scope.
- One template per task. If a job spans external + internal, run two tasks and link the
  second as a source task so it inherits facts.
- Multilingual or low-cost recon: swap the LLM in Advanced settings; the template text
  is model-agnostic.
