#!/usr/bin/env bash
# Leak check for the ARTEX container. Run inside the container:
#   docker compose exec -T artex bash /app/../../scripts/anonymity-check.sh
# or from the host:  ./scripts/anonymity-check.sh
#
# Compares the container's egress against a recorded baseline and probes DNS and
# IPv6. Anything marked FAIL means traffic is reaching the internet without the
# tunnel and must be fixed before scanning.
set -uo pipefail

BASE_FILE="/app/data/.baseline-ip"
fail=0
say() { printf '%-28s %s\n' "$1" "$2"; }

real_ip() { curl -4 -s -m 12 https://ifconfig.me 2>/dev/null | tr -d '\n'; }

ip=$(real_ip)
if [ "${1:-}" = "--baseline" ] && [ -n "$ip" ]; then
  mkdir -p "$(dirname "$BASE_FILE")"
  printf '%s\n' "$ip" > "$BASE_FILE"
  echo "baseline recorded: $ip"
  exit 0
fi
if [ -z "$ip" ]; then
  say "egress ip" "FAIL (no answer — tunnel up but broken?)"
  exit 1
fi
say "egress ip" "$ip"

if [ -f "$BASE_FILE" ]; then
  base=$(cat "$BASE_FILE")
  if [ "$ip" = "$base" ]; then
    say "vs baseline" "FAIL (still $base — not tunnelled)"
    fail=1
  else
    say "vs baseline" "PASS (baseline $base)"
  fi
else
  say "vs baseline" "no baseline recorded (run with --baseline)"
fi

geo=$(curl -4 -s -m 12 https://ipinfo.io/"$ip"/json 2>/dev/null)
org=$(printf '%s' "$geo" | sed -n 's/.*"org": *"\([^"]*\)".*/\1/p')
city=$(printf '%s' "$geo" | sed -n 's/.*"city": *"\([^"]*\)".*/\1/p')
if printf '%s' "$org" | grep -qiE "mullvad|31173|datacamp|zenlayer|amazon|digitalocean|ovh|hetzner|leaseweb|m247"; then
  say "asn / org" "PASS ($org${city:+, $city})"
else
  say "asn / org" "WARN ($org — check it is the VPN, not your ISP)"
fi

# Resolver identity is hard to read behind Docker; the meaningful test is that
# resolution works at all and that the answer comes from the VPN's resolver path.
res=$(curl -4 -s -m 12 https://edns.ip-api.com/json 2>/dev/null | sed -n 's/.*"ip": *"\([^"]*\)".*/\1/p' | head -1)
if [ -n "$res" ]; then
  rorg=$(curl -4 -s -m 10 https://ipinfo.io/"$res"/json 2>/dev/null | sed -n 's/.*"org": *"\([^"]*\)".*/\1/p')
  if printf '%s %s' "$res" "$rorg" | grep -qiE "mullvad|31173|datacamp|zenlayer"; then
    say "dns resolver" "PASS ($res)"
  else
    say "dns resolver" "WARN ($res ${rorg:+- $rorg})"
  fi
elif getent hosts example.com >/dev/null 2>&1; then
  say "dns resolver" "PASS (resolves; direct 53 blocked by the VPN, expected)"
else
  say "dns resolver" "FAIL (no resolution)"
  fail=1
fi

v6=$(curl -6 -s -m 8 https://ifconfig.co 2>/dev/null | tr -d '\n')
if [ -z "$v6" ]; then
  say "ipv6" "PASS (no v6 egress, nothing to leak)"
else
  v6org=$(curl -4 -s -m 10 https://ipinfo.io/"$v6"/json 2>/dev/null | sed -n 's/.*"org": *"\([^"]*\)".*/\1/p')
  if printf '%s %s' "$v6" "$v6org" | grep -qiE "mullvad|31173|datacamp"; then
    say "ipv6" "PASS ($v6 tunnelled)"
  else
    say "ipv6" "FAIL ($v6 ${v6org:+- $v6org}) — v6 bypasses the tunnel"
    fail=1
  fi
fi

exit "$fail"
