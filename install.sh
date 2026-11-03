#!/usr/bin/env bash
# AzerothCore WotLK Docker install script for Arch Linux
# Uses the Playerbot fork + recommended modules (playerbots, no-hearthstone-cooldown, dungeon-clear, npc-enchanter)
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

echo "=== AzerothCore WotLK Docker Install with Playerbots (Arch Linux) ==="

# 1. Update system and install packages
echo "[1/7] Installing packages..."
sudo pacman -Syu --noconfirm
sudo pacman -S --needed --noconfirm docker docker-compose docker-buildx git

# 2. Enable and start Docker
echo "[2/7] Enabling Docker service..."
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER" || true
# Note: group change requires new login for future shells; this script uses sg docker below

# 3. Enable BuildKit permanently
echo "[3/7] Configuring BuildKit..."
sudo mkdir -p /etc/docker
if [ ! -f /etc/docker/daemon.json ] || ! grep -q buildkit /etc/docker/daemon.json 2>/dev/null; then
  echo '{"features":{"buildkit":true}}' | sudo tee /etc/docker/daemon.json >/dev/null
  sudo systemctl restart docker
fi
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

# 4. Clone Playerbot fork if it does not exist
echo "[4/7] Cloning AzerothCore Playerbot fork..."
if [ ! -d "$ACORE_DIR" ]; then
  git clone https://github.com/mod-playerbots/azerothcore-wotlk.git --branch Playerbot --depth 1 "$ACORE_DIR"
else
  echo "Directory $ACORE_DIR already exists, skipping clone."
fi
cd "$ACORE_DIR"

# 5. Clone recommended modules
echo "[5/7] Cloning modules..."
mkdir -p modules
cd modules
[ ! -d mod-playerbots ] && git clone https://github.com/mod-playerbots/mod-playerbots.git || echo "mod-playerbots already present"
[ ! -d mod-no-hearthstone-cooldown ] && git clone https://github.com/BytesGalore/mod-no-hearthstone-cooldown.git || echo "mod-no-hearthstone-cooldown already present"
[ ! -d mod-dungeon-clear ] && git clone https://github.com/jrad7/mod-dungeon-clear.git || echo "mod-dungeon-clear already present"
[ ! -d mod-npc-enchanter ] && git clone https://github.com/azerothcore/mod-npc-enchanter.git || echo "mod-npc-enchanter already present"
cd ..

# Create docker-compose.override.yml so containers see the modules
if [ ! -f docker-compose.override.yml ]; then
  cat > docker-compose.override.yml << 'EOF'
services:
  ac-worldserver:
    volumes:
      - ./modules:/azerothcore/modules:ro
  ac-authserver:
    volumes:
      - ./modules:/azerothcore/modules:ro
  ac-db-import:
    volumes:
      - ./modules:/azerothcore/modules:ro
EOF
  echo "Created docker-compose.override.yml"
fi

# Copy module .conf.dist files so the server does not warn about missing configs
echo "Copying module configuration templates..."
mkdir -p env/dist/etc/modules
[ -f modules/mod-no-hearthstone-cooldown/conf/mod_no_hearthstone_cooldown.conf.dist ] && \
  cp -n modules/mod-no-hearthstone-cooldown/conf/mod_no_hearthstone_cooldown.conf.dist \
         env/dist/etc/modules/mod_no_hearthstone_cooldown.conf || true
[ -f modules/mod-dungeon-clear/conf/mod_dungeon_clear.conf.dist ] && \
  cp -n modules/mod-dungeon-clear/conf/mod_dungeon_clear.conf.dist \
         env/dist/etc/modules/mod_dungeon_clear.conf || true
[ -f modules/mod-npc-enchanter/conf/npc_enchanter.conf.dist ] && \
  cp -n modules/mod-npc-enchanter/conf/npc_enchanter.conf.dist \
         env/dist/etc/modules/npc_enchanter.conf || true
[ -f modules/mod-playerbots/conf/playerbots.conf.dist ] && \
  cp -n modules/mod-playerbots/conf/playerbots.conf.dist \
         env/dist/etc/modules/playerbots.conf || true

# Optional: copy playerbots SQL into custom import path for more reliable first import
mkdir -p data/sql/custom/db_characters data/sql/custom/db_world data/sql/custom/db_auth
if [ -d modules/mod-playerbots/sql/characters/base ]; then
  cp -n modules/mod-playerbots/sql/characters/base/*.sql data/sql/custom/db_characters/ 2>/dev/null || true
fi
if [ -d modules/mod-playerbots/sql/world/base ]; then
  cp -n modules/mod-playerbots/sql/world/base/*.sql data/sql/custom/db_world/ 2>/dev/null || true
fi

# 6. Build and start the stack (via sg docker so group membership is active)
echo "[6/7] Building and starting containers (this may take a long time on first run)..."
run_docker "docker compose up -d --build"

# Wait for database to become healthy
echo "Waiting for ac-database to become healthy..."
for i in {1..90}; do
  if run_docker "docker inspect --format '{{.State.Health.Status}}' ac-database 2>/dev/null" | grep -q healthy; then
    echo "Database is healthy."
    break
  fi
  sleep 10
  if [ "$i" -eq 90 ]; then
    echo "Timed out waiting for database. Check logs with: docker compose logs -f"
    exit 1
  fi
done

# 7. Ensure a valid default realm exists, then set the server IP if provided
echo "[7/7] Ensuring a valid realm exists in realmlist..."
run_docker "docker exec -i ac-database mysql -uroot -ppassword acore_auth -e \"
INSERT INTO realmlist (id, name, address, localAddress, localSubnetMask, port, icon, flag, timezone, allowedSecurityLevel, population, gamebuild)
VALUES (1, 'AzerothCore', '127.0.0.1', '127.0.0.1', '255.255.255.0', 8085, 0, 0, 1, 0, 0, 12340)
ON DUPLICATE KEY UPDATE
  address = IF(address = '' OR address IS NULL, '127.0.0.1', address),
  flag = 0,
  port = 8085;
\""

if [ -n "$SERVER_IP" ]; then
  echo "Updating realmlist address to $SERVER_IP..."
  run_docker "docker exec -i ac-database mysql -uroot -ppassword acore_auth -e \"UPDATE realmlist SET address='${SERVER_IP}', flag=0 WHERE id=1;\""
else
  echo "No SERVER_IP provided. Realmlist left at 127.0.0.1 (flag=0)."
  echo "Update later with:"
  echo "  docker exec -i ac-database mysql -uroot -ppassword acore_auth -e \"UPDATE realmlist SET address='YOUR_IP', flag=0 WHERE id=1;\""
fi

# Restart authserver so it picks up the realmlist change
run_docker "docker compose restart ac-authserver" || true

echo ""
echo "=== Install complete ==="
echo "Database is healthy and servers should be starting."
echo ""
echo "Next steps:"
echo "  1. Attach to the worldserver:  docker attach ac-worldserver"
echo "  2. Create an account:         account create USERNAME password 3 -1"
echo "  3. Detach:                    Ctrl+P then Ctrl+Q"
echo "  4. Verify modules:            .server debug"
echo "  5. Spawn enchanter (optional): .npc add 601015"
echo ""
echo "Useful commands:"
echo "  docker compose ps"
echo "  docker compose logs -f"
echo "  docker compose restart ac-authserver ac-worldserver"
echo ""
echo "Default MySQL root password: password"
echo "Ports: Auth 3724, World 8085, SOAP 7878, MySQL 3306"
echo ""
echo "Module configs have been copied to env/dist/etc/modules/"
echo "Edit them and restart the worldserver if you want to change defaults."
echo "See README for recommended playerbots settings."
echo ""
echo "Note: You may need to log out and back in (or run 'newgrp docker')"
echo "so that future shells can run docker without 'sg docker'."
