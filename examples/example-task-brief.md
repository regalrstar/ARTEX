# Example task brief (copy this shape)

Two filled-in examples: one external web app, one internal AD. Fake client
"Northwind Traders" — replace with your real engagement.

---

## Example A — external web application

**Template:** Web App Full Exploitation

**Name**
`Northwind staging portal — web pentest`

**Description**
`Northwind Traders staging portal. Pre-production, restorable from snapshot. Testing window 09:00-17:00 UTC. Any data may be modified; note what you change.`

**Goal** (template text with TARGET and scope replaced)

```
Target https://staging.northwind.example (replace TARGET; also in scope:
api.staging.northwind.example, 203.0.113.0/28). Out of scope: any *.northwind.example
not listed, Google/Microsoft SaaS, and the payment sandbox.

Map every parameter, endpoint and role first, then exploit instead of reporting. Cover
SQLi, NoSQLi, XSS, SSRF, SSTI, LFI with log poisoning, XXE, deserialization, upload
bypass, command injection, traversal and business logic. Bypass the WAF with encoding
and HTTP/2 before giving up. Chain findings to RCE or data access. Every finding needs
the raw request, payload, response and a CVSS 4.0 vector.

Success = the highest-impact chain proven, ideally RCE or bulk customer-data access.
Stop and ask before dropping tables or disabling the WAF.
```

**Category** `Web & API` (auto-filled)

**Test accounts**

| Domain | Username | Password | Note |
|---|---|---|---|
| staging.northwind.example | qa.customer | `SamplePass1!` | customer role |
| staging.northwind.example | qa.admin | `SamplePass2!` | admin role |

**Advanced settings**

- Timeout: `10800` (3h)
- Task-level rules: keep the template blocks; add an **allow** rule only if the CDN in
  front of the target (`fuzzy_domain cdn.northwind.example`) is itself in scope.

**What should happen**

1. Seed + planner produce recon intents; workers enumerate routes and parameters.
2. Findings appear under Findings; each has traffic evidence bound.
3. Planner keeps chaining until the goal is proven or the 3h budget stops it.

**Stop / pause when**

- A destructive migration or reindex is required.
- The WAF starts blocking the whole office IP.
- Token spend passes your cap — pause, read the graph, resume later.

**Deliverable:** Findings list → reporter output. Check each finding replays before it
goes in the report.

---

## Example B — internal Active Directory

**Template:** AD Takeover From Zero Creds

**Name**
`Northwind corp — AD takeover (no creds)`

**Description**
`Internal AD assessment from the consultant VLAN. DC01 and DC02, domain corp.northwind.example. Account lockout: 5 attempts / 30 min, so spray in one pass only.`

**Goal**

```
Domain: corp.northwind.example (DC01 10.20.5.10, DC02 10.20.5.11). In scope:
10.20.0.0/16. Out of scope: 10.20.9.0/24 (OT).

Starting with no credentials, enumerate anonymously: LDAP rootDSE, DNS zone transfer, SMB
null, RPC, NetBIOS, kerbrute user enumeration, AS-REP roasting and Kerberoasting, then
crack offline. Chain into NTLM relay, one controlled spray (5 attempts, 30 min lockout),
local privesc, lateral movement. Target DA equivalent and prove it with krbtgt/DA
material.

Success = DA-equivalent control with the dumped secrets and a written path.
```

**Category** `Internal / AD` (auto-filled; the template whitelist already covers
RFC1918 — confirm 10.20.0.0/16 is inside it, it is)

**Advanced settings**

- Timeout: `21600` (6h)
- Planner heartbeat: default 600s
- Add **allow** `cidr 10.20.0.0/16` next to the template's RFC1918 rules if you want the
  blast radius narrowed to the site rather than all private space.

**Stop / pause when**

- The spray reaches 5 failures on the service account.
- You need a maintenance window for ADCS template changes.
- A DC reboot looks likely.

---

## Example C — exchange account drain

**Template:** CEX Account Drain

**Name**
`Northwind Exchange — account drain (testnet)`

**Description**
`Custodial exchange testnet. Two funded accounts: customer A (target) and customer B (control). API keys issued, 2FA TOTP seed supplied. Mainnet not used; no KYC changes.`

**Goal** (template text with the Mode line filled in)

```
Mode: testnet — value cap: 50 USDT equivalent. Destination you control:
TXyz...abc on TRC20. Do not exceed the cap without asking.

Exchange target: https://testnet.exchange.example (replace TARGET; in scope:
testnet.exchange.example, api.testnet.exchange.example). Accounts: customer A
qa.a@example.com (TOTP seed in the credential row), customer B qa.b@example.com.
API keys: A has a trade-only key (key id in credentials); issue a withdraw key only if
the scope break cannot be proven without one.

Money paths first: balances, deposit memo, internal transfer, convert, withdrawal,
whitelist, fee/minimum tiers. Then logic: sats-vs-BTC precision, negative/zero amounts,
fee reversal, limit splitting, ERC20/TRC20 switch, address and memo substitution,
first-withdrawal trust window, idempotency reuse, 10 parallel withdraws of one balance,
duplicate deposit callback, trade-only key that still withdraws, HMAC nonce replay,
X-Forwarded-For allowlist bypass, 2FA replay.

Escalate read -> trade -> withdraw. Prove with raw requests, before/after balances and a
txid or internal transfer id. Success = funds moved to the destination above.
```

**Category** `Crypto / Fintech` (auto-filled)

**Test accounts**

| Domain | Username | Password | Note |
|---|---|---|---|
| testnet.exchange.example | qa.a@example.com | `SamplePass1!` | target, TOTP seed `JBSWY3DPEHPK3PXP` |
| testnet.exchange.example | qa.b@example.com | `SamplePass2!` | control for cross-account BOLA |

**Advanced settings**

- Timeout: `18000` (5h)
- Workers: leave at 3 — race proofs need concurrency
- Rules: keep the template noise blocks; add nothing unless a CDN is in scope

**Stop / pause when**

- A withdrawal would exceed 50 USDT.
- The exchange enforces a whitelist and adding your address needs manual approval.
- 2FA gets rate-limited; wait rather than burning codes.

### Mainnet variant (same template)

1. Swap the Mode line to `Mode: mainnet — value cap: 20 USDT ...`.
2. Use a **dedicated sub-account**, not the master account, holding only the cap.
3. Withdraw-enabled API key, IP-restricted to your egress IP (the container NATs to your
   home IP; remember to remove the whitelist afterwards).
4. Global rule `[cex] Withdrawals need human approval` (priority 95, action ask, 15 min
   then deny) is installed. Every call containing "withdraw" waits for a click — that is
   the last checkpoint before money moves. Narrow the pattern if history reads nag you.
5. Start with exactly one minimum-size withdrawal to your own address, confirm the fee
   and network on the approval card, then let it continue.
6. Keep workers at 3. Only run the parallel-withdraw race if the balance is at least
   10x the minimum.

If the exchange requires per-withdrawal email confirmation, the agent will stall at that
step: approve in mail, then resume the intent in the UI.

**Deliverable:** one finding per hole, chained; the terminal finding carries the txid,
the balance delta and the fix. Do not close the task until the txid is confirmed.

---

## Example D — WiFi handshake crack

**Template:** WIFI WPA/WPA2/PMKID CRACK

**Name**
`Northwind office WiFi — PSK recovery`

**Description**
`Authorised test of the office AP (SSID NORTHWIND-GUEST, BSSID AA:BB:CC:11:22:33, ch 6). Capture taken from the reception laptop with a monitor-mode adapter. No deauth during business hours.`

**Goal** (template text with the file path filled in)

```
Wireless target: NORTHWIND-GUEST (BSSID AA:BB:CC:11:22:33, ch 6). Capture:
/app/data/tasks/21/capture-01.cap — a 4-way handshake for this AP, taken externally.
No radio in the container, work offline.

Validate first: tshark -r FILE -Y 'eapol || wlan.fc.type_subtype == 8', then
hcxpcapngtool -o /tmp/out.22000 -E /tmp/essids FILE and report the hash count. If it is
M1/M3 only, say so instead of cracking.

Then cheapest first: probable-v2-wpa-top447, top4800, rockyou.txt, rockyou with
best64.rule, then a mask from the SSID (NORTHWIND?d?d?d?d, NORTHWIND20?d?d). hashcat
-m 22000 -w 3 --status --status-timer 15; print keyspace and ETA above 10^8.

Prove it: hashcat --show, then verify the PSK against the handshake before claiming
success. Record method, list, elapsed, H/s and PSK. WPS check if the beacon has it.

Success = verified PSK with the method documented.
```

**Category** `Wireless` (auto-filled)

**Advanced settings**

- Timeout: `14400` (4h) — masks and rockyou take time
- Workers: 1 is enough, cracking is single-threaded per job; keep 3 only if you want
  parallel list attempts

**Stop / pause when**

- The capture has no crackable handshake — stop and re-capture rather than burn hours.
- ETA exceeds the window; park it and resume overnight.
- Someone reports the AP dropping (only if you authorised a deauth).

**Deliverable:** PSK plus method, list/rules, elapsed time and H/s, and the capture file
retained as evidence.

---

## Reusable checklist before pressing Create

- [ ] Template picked; goal still contains `TARGET` until you replace it
- [ ] Every in-scope host/CIDR listed; out-of-scope written explicitly
- [ ] Test accounts entered, or "no creds" stated
- [ ] Timeout set; heartbeat left alone unless you know why
- [ ] Snapshot/backup exists for anything destructive
- [ ] Lockout policy known for spray templates
- [ ] For money: Mode line filled, cap set, destination address matches the network
- [ ] Someone watching the Findings stream for the first 15 minutes
