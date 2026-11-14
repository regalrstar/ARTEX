#!/usr/bin/env bash
# One-shot box bootstrap. Pasted as cloud-init user-data (or run by hand on a
# fresh Debian/Ubuntu box). Ends with the VPN up and ARTEX on loopback only.
#
# Expects these to be substituted before use: __MULLVAD_ACCOUNT__, __ENV__.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg jq ufw fail2ban wireguard-tools

# --- SSH hardening + firewall (no scan ports are opened; all is loopback) ---
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw --force enable

# --- Docker ---
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${ID} ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin

# --- Mullvad, kill switch on before anything else can egress ---
curl -fsSL https://repository.mullvad.net/deb/mullvad-keyring.asc | \
  gpg --dearmor -o /usr/share/keyrings/mullvad-keyring.asc
echo "deb [signed-by=/usr/share/keyrings/mullvad-keyring.asc arch=$(dpkg --print-architecture)] https://repository.mullvad.net/deb/stable $(lsb_release -cs) main" \
  > /etc/apt/sources.list.d/mullvad.list
apt-get update -qq
apt-get install -y -qq mullvad-vpn
mullvad account login __MULLVAD_ACCOUNT__
mullvad lockdown-mode set on
mullvad relay set location __MULLVAD_LOCATION__
mullvad connect
for i in $(seq 1 30); do
  [ "$(mullvad status | head -1)" = "Connected" ] && break
  sleep 2
done
mullvad status | head -1

# --- ARTEX ---
mkdir -p /opt/artex
cat > /opt/artex/.env <<'ENVEOF'
__ENV__
ENVEOF
chmod 600 /opt/artex/.env
# image and compose are scp'd in by deploy.sh before this step
cd /opt/artex
docker load -i /opt/artex/artex.tar
docker compose -f compose.prod.yml --env-file .env up -d

sysctl -w net.netfilter.nf_conntrack_max=262144 || true
echo "ready" > /opt/artex/.ready
