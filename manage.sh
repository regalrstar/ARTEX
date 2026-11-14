#!/usr/bin/env bash
# Local control helper for this ARTEX checkout (Docker Compose based).
set -euo pipefail
cd "$(cd "$(dirname "$0")" && pwd)"

case "${1:-}" in
  up)     docker compose up -d --build ;;
  start)  docker compose up -d ;;
  stop)   docker compose stop ;;
  down)   docker compose down ;;
  restart) docker compose restart artex ;;
  status) docker compose ps ;;
  logs)   docker compose logs -f --tail=200 artex ;;
  token)  docker compose logs artex | grep -i "setup token" | tail -1 ;;
  url)    echo "ARTEX http://localhost:8787   |   wifi workspace http://localhost:8790" ;;
  wifi)   echo "http://localhost:8790  (drop captures in data/wifi/)";;
  agent)  sudo python3 "$(dirname "$0")/wifi/agent.py";;
  psql)   docker compose exec postgres psql -U "${POSTGRES_USER:-artex}" -d "${POSTGRES_DB:-artex}" ;;
  backup)
    mkdir -p backups
    f="backups/artex-db-$(date +%Y%m%d-%H%M%S).sql.gz"
    docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-artex}" "${POSTGRES_DB:-artex}" | gzip > "$f"
    echo "wrote $f" ;;
  *) echo "usage: $0 {up|start|stop|down|restart|status|logs|token|url|psql|backup}"; exit 1 ;;
esac
