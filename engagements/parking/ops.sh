#!/usr/bin/env bash
# One command for everything. up | down | status | tunnel
set -uo pipefail
ROOT="$HOME/Developer/artex"
cd "$ROOT/engagements/parking/web" 2>/dev/null || exit 1

case "${1:-}" in
  up)
    open -a Docker.app 2>/dev/null
    for i in $(seq 1 40); do docker info >/dev/null 2>&1 && break; sleep 5; done
    ( cd "$ROOT" && docker compose up -d >/dev/null 2>&1 )
    pgrep -f "python3 server.py" >/dev/null || ( nohup python3 server.py >/tmp/pc.log 2>&1 & )
    pgrep -f dashproxy.py     >/dev/null || ( nohup python3 dashproxy.py >/tmp/dp.log 2>&1 & )
    pgrep -f "http.server 8794" >/dev/null || ( cd "$ROOT/engagements/atcs" && nohup python3 -m http.server 8794 --bind 127.0.0.1 >/tmp/atcs.log 2>&1 & )
    sleep 4
    echo "ARTEX        http://localhost:8787   ARTEX / Artex-Local-7Qm4Xz!9"
    echo "Parking      http://localhost:8792   viewer / ViewPass9341 (local: no login)"
    echo "Dashboard    http://localhost:8793   alfabeta / Alfabeta43B!  then  dash9viewer@alfabeta.co.id / Dash9Pass11"
    echo "ATCS feeds   http://localhost:8794/feeds.html"
    echo
    echo "remote: ./ops.sh tunnel" ;;
  down)
    pkill -f "python3 server.py"; pkill -f dashproxy.py; pkill -f "http.server 8794"
    pkill -f "cloudflared tunnel --url"
    ( cd "$ROOT" && docker compose stop >/dev/null 2>&1 )
    echo stopped ;;
  status)
    for u in 8787 8792 8793 8794; do printf "%s -> " $u; curl -s -o /dev/null -w "%{http_code}\n" -m 4 "http://127.0.0.1:$u/"; done ;;
  tunnel)
    pgrep -f "cloudflared tunnel --url http://127.0.0.1:8792" >/dev/null || nohup cloudflared tunnel --url http://127.0.0.1:8792 >/tmp/t1.log 2>&1 &
    pgrep -f "cloudflared tunnel --url http://127.0.0.1:8793" >/dev/null || nohup cloudflared tunnel --url http://127.0.0.1:8793 >/tmp/t2.log 2>&1 &
    sleep 20
    echo "console:   $(grep -hoE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/t1.log | head -1)"
    echo "dashboard: $(grep -hoE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/t2.log | head -1)" ;;
  *) echo "usage: $0 {up|down|status|tunnel}"; exit 1 ;;
esac
