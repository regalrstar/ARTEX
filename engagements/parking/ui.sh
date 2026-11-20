#!/usr/bin/env bash
# Start/stop the two UI helpers (parking console + dashboard proxy).
# ARTEX itself is managed by docker compose.
set -uo pipefail
cd "$(dirname "$0")/web"

case "${1:-}" in
  start)
    pgrep -f "python3 server.py" >/dev/null || { nohup python3 server.py > /tmp/pc.log 2>&1 & echo "console :8792"; }
    pgrep -f "python3 dashproxy.py"   >/dev/null || { nohup python3 dashproxy.py > /tmp/dp.log 2>&1 & echo "dashboard :8793"; }
    sleep 2
    for p in 8792 8793; do printf "%s -> " $p; curl -s -o /dev/null -w "%{http_code}\n" -m 4 "http://127.0.0.1:$p/"; done ;;
  tunnel)
    pgrep -f "cloudflared tunnel --url http://127.0.0.1:8792" >/dev/null || nohup cloudflared tunnel --url http://127.0.0.1:8792 > /tmp/t1.log 2>&1 &
    pgrep -f "cloudflared tunnel --url http://127.0.0.1:8793" >/dev/null || nohup cloudflared tunnel --url http://127.0.0.1:8793 > /tmp/t2.log 2>&1 &
    sleep 20
    echo "console:   $(grep -hoE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/t1.log | head -1)"
    echo "dashboard: $(grep -hoE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/t2.log | head -1)" ;;
  stop)
    pkill -f "python3 server.py"; pkill -f dashproxy.py; pkill -f "cloudflared tunnel --url"; echo "stopped" ;;
  status)
    for u in http://127.0.0.1:8787/login http://127.0.0.1:8792/ http://127.0.0.1:8793/; do printf "%-30s " "$u"; curl -s -o /dev/null -w "%{http_code}\n" -m 4 "$u"; done ;;
  *) echo "usage: $0 {start|stop|status}"; exit 1 ;;
esac
