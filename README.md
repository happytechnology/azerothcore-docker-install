# AzerothCore WotLK Docker Install Guide (Arch Linux)

Repeatable installation of AzerothCore WotLK using Docker with MySQL 8.4, including restoration of existing character/auth/world databases.

This guide consolidates the steps that successfully worked around MySQL source-build OOM/LTO issues by using the official AzerothCore Docker setup.

## Prerequisites

- Arch Linux
- Git
- Sufficient disk space and RAM (Docker build is memory-intensive)

## 1. Install Docker and required plugins

```bash
sudo pacman -Syu docker docker-compose docker-buildx
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
newgrp docker          # or log out and back in
```

Verify:

```bash
docker --version
docker compose version
docker buildx version
```

## 2. Enable BuildKit

BuildKit is required by the AzerothCore Dockerfile (`RUN --mount=...`).

**Temporary (current shell):**

```bash
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1
```

**Permanent:**

```bash
sudo mkdir -p /etc/docker
echo '{"features":{"buildkit":true}}' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
```

## 3. Clone AzerothCore

```bash
cd ~
git clone https://github.com/azerothcore/azerothcore-wotlk.git --depth 1
cd azerothcore-wotlk
```

> If you need a specific fork (e.g. Playerbot), clone that repository and check out the correct branch instead.

## 4. Start the stack

```bash
docker compose up -d --build
```

First run takes a while (image build + client data download + initial database setup). Monitor progress:

```bash
docker compose logs -f
```

Confirm the database is healthy:

```bash
docker compose ps
# ac-database should show (healthy)
```

## 5. Restore existing databases

Copy your SQL dump files into `~/db-saves` on the new machine.

Create the databases:

```bash
docker exec -i ac-database mysql -uroot -ppassword -e "CREATE DATABASE IF NOT EXISTS acore_auth; CREATE DATABASE IF NOT EXISTS acore_characters; CREATE DATABASE IF NOT EXISTS acore_world; CREATE DATABASE IF NOT EXISTS acore_playerbots;"
```

### Fix MySQL 8.4 TEXT/BLOB DEFAULT restriction

MySQL 8.4 rejects `DEFAULT` values on TEXT/BLOB columns. Strip them with `sed`:

```bash
sed -E "s/(longtext|text|mediumtext|tinytext)[[:space:]]+DEFAULT[[:space:]]+('[^']*'|NULL)/\\1/gI" \
  ~/db-saves/acore_auth_backup.sql > /tmp/acore_auth_fixed.sql

sed -E "s/(longtext|text|mediumtext|tinytext)[[:space:]]+DEFAULT[[:space:]]+('[^']*'|NULL)/\\1/gI" \
  ~/db-saves/acore_characters_backup.sql > /tmp/acore_characters_fixed.sql

sed -E "s/(longtext|text|mediumtext|tinytext)[[:space:]]+DEFAULT[[:space:]]+('[^']*'|NULL)/\\1/gI" \
  ~/db-saves/acore_world_backup.sql > /tmp/acore_world_fixed.sql

sed -E "s/(longtext|text|mediumtext|tinytext)[[:space:]]+DEFAULT[[:space:]]+('[^']*'|NULL)/\\1/gI" \
  ~/db-saves/acore_playerbots.sql > /tmp/acore_playerbots_fixed.sql
```

Import the fixed dumps:

```bash
docker exec -i ac-database mysql -uroot -ppassword acore_auth < /tmp/acore_auth_fixed.sql
docker exec -i ac-database mysql -uroot -ppassword acore_characters < /tmp/acore_characters_fixed.sql
docker exec -i ac-database mysql -uroot -ppassword acore_world < /tmp/acore_world_fixed.sql
docker exec -i ac-database mysql -uroot -ppassword acore_playerbots < /tmp/acore_playerbots_fixed.sql
```

> The "Using a password on the command line interface can be insecure" warning is normal and can be ignored.

## 6. Restart the game servers

```bash
docker compose restart ac-authserver ac-worldserver
```

## 7. Update realmlist (if the new server IP differs)

```bash
docker exec -i ac-database mysql -uroot -ppassword acore_auth -e "UPDATE realmlist SET address='YOUR_NEW_IP';"
```

## 8. Attach to the worldserver console

```bash
docker attach ac-worldserver
```

Create accounts at the `AC>` prompt.  
Detach with `Ctrl+P` then `Ctrl+Q` (**do not** use `Ctrl+C`).

## Useful commands

| Action                    | Command                                      |
|---------------------------|----------------------------------------------|
| Stop everything           | `docker compose down`                        |
| Start again               | `docker compose up -d`                       |
| View logs                 | `docker compose logs -f`                     |
| Rebuild after updates     | `docker compose up -d --build`               |
| Shell into MySQL          | `docker exec -it ac-database mysql -uroot -ppassword` |

Default MySQL root password is `password`.  
Data persists in Docker volumes (`ac-database`, `ac-client-data`) and survives container restarts.

## Notes

- Official AzerothCore Docker guide: https://www.azerothcore.org/wiki/install-with-docker
- The Docker setup uses the official `mysql:8.4` image, avoiding the need to compile MySQL from source.
- After restoring databases, run any pending AzerothCore database updates if required by your core version.
