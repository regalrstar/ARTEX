#!/bin/bash
# Docker watchdog. Bounded probes only — a hung `docker info` must never stall the check.
LOG="$HOME/Library/Logs/docker-watch.log"
SOCK="$HOME/.docker/run/docker.sock"
DOCKER="$(command -v docker || echo /usr/local/bin/docker)"

bounded() { perl -e 'alarm 8; exec @ARGV' -- "$@" >/dev/null 2>&1; }

# healthy?
if [ -S "$SOCK" ] && bounded "$DOCKER" info; then
  exit 0
fi

# a relaunch already in progress?
if pgrep -f "open -a Docker.app" >/dev/null 2>&1 || [ $(( $(date +%s) - $(stat -f %m "$LOG" 2>/dev/null || echo 0) )) -lt 120 ]; then
  exit 0
fi

echo "$(date -u +%FT%TZ) probe failed (socket=$([ -S "$SOCK" ] && echo yes || echo no)), relaunching" >> "$LOG"
killall -9 com.docker.backend com.docker.build com.docker.virtualization 2>/dev/null
pkill -9 -f "Docker Desktop" 2>/dev/null
sleep 3
rm -f "$SOCK" "$HOME/.docker/run/docker.pid"
open -a Docker.app
for i in $(seq 1 40); do
  sleep 5
  [ -S "$SOCK" ] && bounded "$DOCKER" info && break
done
cd "$HOME/Developer/artex" && bounded "$DOCKER" compose -p artex-main up -d
echo "$(date -u +%FT%TZ) relaunch attempt finished" >> "$LOG"
