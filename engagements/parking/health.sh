#!/usr/bin/env bash
# Access health check: does every door still open? Run before a session and on a timer.
set -uo pipefail
OK=0; BAD=0
say(){ printf '%-28s %s\n' "$1" "$2"; }
pass(){ say "$1" "PASS"; OK=$((OK+1)); }
fail(){ say "$1" "FAIL  $2"; BAD=$((BAD+1)); }

# 1. engine + snapshot
code=$(curl -sk -o /tmp/h.json -w '%{http_code}' -m 40 \
  "https://district8.lpr-capture.alfabeta.co.id/history-gates?startDate=$(date -v-1d +%F)&endDate=$(date +%F)")
[ "$code" = 200 ] && pass "engine history" || fail "engine history" "http $code"
img=$(python3 -c "
import json;d=json.load(open('/tmp/h.json'))
print(next((r['image_in'] for r in d if r.get('image_in')),''))" 2>/dev/null)
if [ -n "$img" ]; then
  c=$(curl -sk -o /dev/null -w '%{http_code}' -m 20 "https://district8.lpr-capture.alfabeta.co.id$img")
  [ "$c" = 200 ] && pass "snapshot" || fail "snapshot" "http $c"
else fail "snapshot" "no image path"; fi

# 2. agents
n=0; for p in 8602 8606 8609 8612; do
  [ "$(curl -s -o /dev/null -w '%{http_code}' -m 6 -X POST "http://52.74.58.117:$p/external/v1/report/summary-lpr" \
     -H 'Content-Type: application/json' -d '{"startDate":"'"$(date +%F)"'T00:00:00.000Z","endDate":"'"$(date +%F)"'T01:00:00.000Z"}')" = 200 ] && n=$((n+1))
done
[ "$n" -ge 2 ] && pass "site agents ($n/4)" || fail "site agents" "$n/4"

# 3. register key still mints an account
rk=$(curl -s -o /tmp/r.json -w '%{http_code}' -m 20 -X POST "http://52.74.58.117:9110/api/v1/auth/register_v2" \
  -H 'Content-Type: application/json' \
  -d '{"username":"health'$(date +%s)'","password":"Health1pass","role":"superadmin","permissions":["all"],"register_key":"d3f3c35c7fe7069267cdb146897968c960fec131"}')
grep -q access_token /tmp/r.json && pass "register_key" || fail "register_key" "http $rk"

# 4. Basic pair on the internal dashboard
c=$(curl -s -o /dev/null -w '%{http_code}' -m 20 -u 'alfabeta:Alfabeta43B!' "https://internal.lpr.alfabeta.co.id/")
[ "$c" = 200 ] && pass "dashboard basic auth" || fail "dashboard basic auth" "http $c"

# 5. Mongo
docker exec artex-artex-1 python3 -c "
import pymongo,sys
pymongo.MongoClient('mongodb://alfabeta:Alfabeta43B!@52.74.58.117:47251/?authSource=admin',serverSelectionTimeoutMS=6000).list_database_names()
" >/dev/null 2>&1 && pass "mongo" || fail "mongo" "connect failed"

# 6. Euklis read
grep -q CredentialModels <(curl -s -m 20 -X POST https://pqrcode.euklis.com/api/GetIdentityCredentialRequest \
  -H 'Content-Type: application/json' -d '{"IdentityId":33957}') && pass "euklis read" || fail "euklis read" "no data"

echo "--- $OK pass / $BAD fail ---"
exit "$BAD"
