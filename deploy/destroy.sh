#!/usr/bin/env bash
# Destroy a scan box and its IP. Data goes with it — that is the point.
set -euo pipefail
HOST="${1:?usage: destroy.sh root@IP}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"

# optional: export the last results before the box dies
mkdir -p ./exports
if ssh -i "$SSH_KEY" -o ConnectTimeout=10 "$HOST" 'test -d /opt/artex' 2>/dev/null; then
  docker_out=$(mktemp -d)
  echo "[*] pulling findings DB dump"
  ssh -i "$SSH_KEY" "$HOST" \
      'cd /opt/artex && docker compose -f compose.prod.yml exec -T postgres pg_dump -U artex artex' \
      | gzip > "exports/artex-$(date +%Y%m%d-%H%M%S).sql.gz" || echo "[!] dump failed"
  rmdir "$docker_out" 2>/dev/null || true
fi

PROVIDER="${PROVIDER:-vultr}"
if [ "$PROVIDER" = "vultr" ] && [ -n "${VULTR_API_KEY:-}" ]; then
  ID="${VULTR_INSTANCE_ID:-$(cat /tmp/artex-instance-id 2>/dev/null || true)}"
  if [ -n "$ID" ]; then
    echo "[*] deleting vultr instance $ID"
    curl -fsS -X DELETE "${VULTR_API:-https://api.vultr.com/v2}/instances/$ID" \
        -H "Authorization: Bearer $VULTR_API_KEY" >/dev/null \
        && echo "[+] deleted" || echo "[!] API delete failed — remove it in the panel"
  else
    echo "[!] no instance id (pass VULTR_INSTANCE_ID=...)"; exit 1
  fi
elif [ -n "${BUYVM_INSTANCE_ID:-}" ] && [ -n "${BUYVM_KEY:-}" ]; then
  echo "[*] deleting instance $BUYVM_INSTANCE_ID"
  curl -fsS -X DELETE "${BUYVM_API:-https://my.frantech.ca/api/v1}/instances/$BUYVM_INSTANCE_ID" \
      -H "X-API-Key: $BUYVM_KEY" -H "X-API-Secret: $BUYVM_SECRET" >/dev/null \
      || echo "[!] API delete failed — remove it in the panel"
else
  echo "[i] no API credentials: delete the box in the panel, then confirm"
  echo "    the IP is gone: curl -s https://ipinfo.io/\$(echo $HOST | cut -d@ -f2)/json"
fi
