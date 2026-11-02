#!/usr/bin/env bash
# AzerothCore WotLK Docker install script for Arch Linux
# Runs the clean install process documented in README.md
# Usage: ./install.sh [SERVER_IP]
# If SERVER_IP is provided it will be set in realmlist after the stack is healthy.

set -euo pipefail

SERVER_IP="${1:-}"
ACORE_DIR="${HOME}/azerothcore-wotlk"

# Helper to run a command with the docker group active
# (needed because usermod does not affect the current shell)
run_docker() {
  sg docker -c "$1"
}

echo "=== AzerothCore WotLK Docker Install (Arch Linux) ==="

# 1. Update system and install packages
echo "[1/6] Installing packages..."
sudo pacman -Syu --noconfirm
sudo pacman -S --needed --noconfirm docker docker-compose docker-buildx git

# 2. Enable and start Docker
echo "[2/6] Enabling Docker service..."
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER" || true
# Note: group change requires new login for future shells; this script uses sg docker below

# 3. Enable BuildKit permanently
echo "[3/6] Configuring BuildKit..."
sudo mkdir -p /etc/docker
if [ ! -f /etc/docker/daemon.json ] || ! grep -q buildkit /etc/docker/daemon.json 2>/dev/null; then
  echo '{"features":{"buildkit":true}}' | sudo tee /etc/docker/daemon.json >/dev/null
  sudo systemctl restart docker
fi
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

# 4. Clone repository if it does not exist
echo "[4/6] Cloning AzerothCore..."
if [ ! -d "$ACORE_DIR" ]; then
  git clone https://github.com/azerothcore/azerothcore-wotlk.git --depth 1 "$ACORE_DIR"
else
  echo "Directory $ACORE_DIR already exists, skipping clone."
fi
cd "$ACORE_DIR"

# 5. Build and start the stack (via sg docker so group membership is active)
echo "[5/6] Building and starting containers (this may take a long time on first run)..."
run_docker "docker compose up -d --build"

# Wait for database to become healthy
echo "Waiting for ac-database to become healthy..."
for i in {1..60}; do
  if run_docker "docker inspect --format '{{.State.Health.Status}}' ac-database 2>/dev/null" | grep -q healthy; then
    echo "Database is healthy."
    break
  fi
  sleep 10
  if [ "$i" -eq 60 ]; then
    echo "Timed out waiting for database. Check logs with: docker compose logs -f"
    exit 1
  fi
done

# 6. Update realmlist if an IP was provided
if [ -n "$SERVER_IP" ]; then
  echo "[6/6] Updating realmlist address to $SERVER_IP..."
  run_docker "docker exec -i ac-database mysql -uroot -ppassword acore_auth -e \"UPDATE realmlist SET address='${SERVER_IP}', flag=0 WHERE id=1;\""
else
  echo "[6/6] No SERVER_IP provided. Realmlist left at default (127.0.0.1)."
  echo "Update later with:"
  echo "  docker exec -i ac-database mysql -uroot -ppassword acore_auth -e \"UPDATE realmlist SET address='YOUR_IP', flag=0 WHERE id=1;\""
fi

echo ""
echo "=== Install complete ==="
echo "Database is healthy and servers should be starting."
echo ""
echo "Next steps:"
echo "  1. Attach to the worldserver:  docker attach ac-worldserver"
echo "  2. Create an account:         account create USERNAME password 3 -1"
echo "  3. Detach:                    Ctrl+P then Ctrl+Q"
echo ""
echo "Useful commands:"
echo "  docker compose ps"
echo "  docker compose logs -f"
echo "  docker compose restart ac-authserver ac-worldserver"
echo ""
echo "Default MySQL root password: password"
echo "Ports: Auth 3724, World 8085, SOAP 7878, MySQL 3306"
echo ""
echo "Note: You may need to log out and back in (or run 'newgrp docker')"
echo "so that future shells can run docker without 'sg docker'."
