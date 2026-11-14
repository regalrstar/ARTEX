#!/usr/bin/env bash
# Deploy a disposable scan box.
#
#   ./deploy.sh --host root@1.2.3.4        # box already created in a panel
#   ./deploy.sh --create                  # Vultr (default) or BuyVM via PROVIDER
#
# Requires in the environment:
#   MULLVAD_ACCOUNT  16-digit account number (VPS logs in and locks down before egress)
#   OPENAI_API_KEY   LLM key
#   SSH_KEY          path to the private key matching the one on the box
set -euo pipefail
cd "$(dirname "$0")/.."

SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
KEY_OPTS=(-i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
PROVIDER="${PROVIDER:-vultr}"
VULTR_API="${VULTR_API:-https://api.vultr.com/v2}"
BUYVM_API="${BUYVM_API:-https://my.frantech.ca/api/v1}"

usage() { sed -n '2,12p' "$0"; exit 1; }
MODE="${1:-}"; HOST="${2:-}"
[ -z "$MODE" ] && usage

if [ "$MODE" = "--create" ] && [ "$PROVIDER" = "vultr" ]; then
  : "${VULTR_API_KEY:?set VULTR_API_KEY (my.vultr.com -> Settings -> API)}"
  REGION="${VULTR_REGION:-sgp}"
  PLAN="${VULTR_PLAN:-vhf-2c-4gb}"
  OS_ID="${VULTR_OS_ID:-2136}"          # Debian 12
  echo "[*] uploading ssh key"
  KEY_ID=$(curl -fsS -X POST "$VULTR_API/ssh-keys" -H "Authorization: Bearer $VULTR_API_KEY" \
      -H 'Content-Type: application/json' \
      -d "$(jq -nc --arg k "$(cat "$SSH_KEY.pub")" '{name:"artex-deploy",ssh_key:$k}')" | jq -r '.ssh_key.id')
  echo "[*] creating $PLAN in $REGION"
  resp=$(curl -fsS -X POST "$VULTR_API/instances" -H "Authorization: Bearer $VULTR_API_KEY" \
      -H 'Content-Type: application/json' \
      -d "$(jq -nc --arg r "$REGION" --arg p "$PLAN" --argjson o "$OS_ID" --arg k "$KEY_ID" \
            '{region:$r,plan:$p,os_id:$o,sshkey_ids:[$k],label:"artex-scan",hostname:"scan01"}')") || {
        echo "[!] API call failed — create the box in the panel and re-run with --host root@IP"; exit 1; }
  ID=$(printf '%s' "$resp" | jq -r '.instance.id'); echo "$ID" > /tmp/artex-instance-id
  echo "[*] instance $ID, waiting for an IP"
  for i in $(seq 1 40); do
    HOST="root@$(curl -fsS "$VULTR_API/instances/$ID" -H "Authorization: Bearer $VULTR_API_KEY" | jq -r '.instance.main_ip // empty')"
    [ "$HOST" != "root@" ] && break; sleep 6
  done
  [ "$HOST" = "root@" ] && { echo "[!] no IP assigned"; exit 1; }
  echo "[*] instance: $HOST"
elif [ "$MODE" = "--create" ] && [ "$PROVIDER" = "buyvm" ]; then
  : "${BUYVM_KEY:?set BUYVM_KEY and BUYVM_SECRET}"
  : "${BUYVM_SECRET:?}"
  : "${BUYVM_PLAN:?set BUYVM_PLAN}"
  : "${BUYVM_LOCATION:?set BUYVM_LOCATION}"
  echo "[*] creating instance via $BUYVM_API"
  resp=$(curl -fsS -X POST "$BUYVM_API/instances" \
      -H "X-API-Key: $BUYVM_KEY" -H "X-API-Secret: $BUYVM_SECRET" \
      -H 'Content-Type: application/json' \
      -d "{\"plan\":\"$BUYVM_PLAN\",\"location\":\"$BUYVM_LOCATION\",\"template\":\"debian-12\"}") || {
        echo "[!] API call failed — create the box in the panel and re-run with --host root@IP"; exit 1; }
  HOST="root@$(printf '%s' "$resp" | jq -r '.ip // .main_ip // empty')"
  echo "[*] instance: $HOST"
elif [ "$MODE" = "--host" ]; then
  HOST="${2:-}"; [ -z "$HOST" ] && usage
else usage; fi

: "${MULLVAD_ACCOUNT:?}"
: "${OPENAI_API_KEY:?}"

echo "[*] waiting for ssh on $HOST"
for i in $(seq 1 60); do ssh "${KEY_OPTS[@]}" "$HOST" true 2>/dev/null && break; sleep 5; done
ssh "${KEY_OPTS[@]}" "$HOST" true || { echo "[!] ssh unreachable"; exit 1; }

echo "[*] building amd64 image"
docker buildx build --platform linux/amd64 -t artex:local --load . >/dev/null
docker save artex:local | gzip -1 > /tmp/artex.tar.gz

PG_PW=$(openssl rand -hex 16)
ADMIN_PW=$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-18)
ENV_BLOCK="POSTGRES_PASSWORD=$PG_PW
ARTEX_ADMIN_PASSWORD=$ADMIN_PW
OPENAI_API_KEY=$OPENAI_API_KEY
ARTEX_LLM_PROVIDER=openai
ARTEX_LLM_MODEL=deepseek-v4.1-flash-uncensored
ARTEX_LLM_BASE_URL=https://api.experientiallabs.ai/v1"
[ -n "${ARTEX_CPUSET:-}" ] && ENV_BLOCK="$ENV_BLOCK
ARTEX_CPUSET=$ARTEX_CPUSET"
[ -n "${WIFI_CPUSET:-}" ] && ENV_BLOCK="$ENV_BLOCK
WIFI_CPUSET=$WIFI_CPUSET"

echo "[*] uploading image and compose"
scp "${KEY_OPTS[@]}" /tmp/artex.tar.gz "$HOST:/opt/artex.tar.gz" 2>/dev/null || {
  ssh "${KEY_OPTS[@]}" "$HOST" mkdir -p /opt; scp "${KEY_OPTS[@]}" /tmp/artex.tar.gz "$HOST:/opt/artex.tar.gz"; }
scp "${KEY_OPTS[@]}" deploy/compose.prod.yml "$HOST:/opt/artex/compose.prod.yml"
scp "${KEY_OPTS[@]}" -r wifi "$HOST:/opt/artex/wifi"

sed -e "s|__MULLVAD_ACCOUNT__|$MULLVAD_ACCOUNT|" \
    -e "s|__MULLVAD_LOCATION__|${MULLVAD_LOCATION:-any}|" \
    -e "s|__ENV__|$ENV_BLOCK|" deploy/cloud-init.sh > /tmp/bootstrap.sh
scp "${KEY_OPTS[@]}" /tmp/bootstrap.sh "$HOST:/root/bootstrap.sh"

echo "[*] bootstrapping (docker install + VPN lockdown + start), ~4-6 min"
ssh "${KEY_OPTS[@]}" "$HOST" 'bash /root/bootstrap.sh' || { echo "[!] bootstrap failed, inspect: ssh $HOST journalctl -xe"; exit 1; }

echo "[*] verifying egress is the VPN"
ssh "${KEY_OPTS[@]}" "$HOST" 'curl -4 -s -m 15 https://ipinfo.io/json | jq -r ".ip + \" \" + (.org // \"\")"'

cat <<EOF

ready.
  tunnel:  ssh -i $SSH_KEY -N -L 8787:127.0.0.1:8787 -L 8790:127.0.0.1:8790 $HOST
  panel:   http://127.0.0.1:8787   admin: ARTEX / $ADMIN_PW
  wifi:    http://127.0.0.1:8790  (file-based only, no USB)
  destroy: ./deploy/destroy.sh $HOST     (or delete it in the panel)

postgres password is in /opt/artex/.env on the box; nothing is exposed publicly.
EOF
rm -f /tmp/artex.tar.gz /tmp/bootstrap.sh
