# AzerothCore WotLK Docker Install Guide (Arch Linux)

Repeatable installation of AzerothCore WotLK using Docker with the official `mysql:8.4` image.

This guide consolidates the steps that successfully worked around MySQL source-build issues (OOM/LTO) by using the official AzerothCore Docker setup. It covers a clean install from scratch.

## Prerequisites

- Arch Linux (updated)
- A normal user with `sudo` privileges
- Sufficient disk space (client data + database volumes) and RAM (the Docker build is memory-intensive; 8 GB+ recommended)
- Git

## 1. Install Docker and required plugins

```bash
sudo pacman -Syu
sudo pacman -S --needed docker docker-compose docker-buildx git
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
newgrp docker          # or log out and back in so the group change takes effect
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

If you see a warning about the buildx plugin, the classic builder still works for this setup once BuildKit is enabled.

## 3. Clone AzerothCore

```bash
cd ~
git clone https://github.com/azerothcore/azerothcore-wotlk.git --depth 1
cd azerothcore-wotlk
```

All subsequent commands must be run from inside this directory.

> If you need a specific fork (e.g. Playerbot), clone that repository and check out the correct branch instead.

## 4. Start the stack

```bash
docker compose up -d --build
```

The first run takes a while (image build + client data download + initial database setup via `ac-db-import`). Monitor progress:

```bash
docker compose logs -f
```

Confirm the database is healthy before proceeding:

```bash
docker compose ps
# ac-database should show (healthy)
```

The `ac-db-import` service is a one-shot container that runs only on first start (or after the database volume is removed). Once it completes successfully, the auth and world servers start.

## 5. Update realmlist (recommended)

By default the realm address is `127.0.0.1`. Update it to the IP clients will use:

```bash
docker exec -i ac-database mysql -uroot -ppassword acore_auth -e "UPDATE realmlist SET address='YOUR_SERVER_IP', flag=0 WHERE id=1;"
```

Replace `YOUR_SERVER_IP` with the address clients can reach (e.g. `10.0.0.18` or a public IP). Flag `0` marks the realm as online/normal.

## 6. Create an account

Attach to the worldserver console:

```bash
docker attach ac-worldserver
```

At the `AC>` prompt:

```
account create YOURUSERNAME yourpassword 3 -1
```

Detach with `Ctrl+P` then `Ctrl+Q` (**do not** use `Ctrl+C`).

## Useful commands

| Action                    | Command                                      |
|---------------------------|----------------------------------------------|
| Stop everything           | `docker compose down`                        |
| Start again               | `docker compose up -d`                       |
| Restart game servers only | `docker compose restart ac-authserver ac-worldserver` |
| View logs                 | `docker compose logs -f`                     |
| Rebuild after updates     | `docker compose up -d --build`               |
| Shell into MySQL          | `docker exec -it ac-database mysql -uroot -ppassword` |
| Attach to worldserver     | `docker attach ac-worldserver`               |

Default MySQL root password is `password`.

Data persists in Docker volumes (`ac-database`, client data volumes) and survives container restarts. To fully reset the database, stop the stack and remove the volume:

```bash
docker compose down
docker volume rm azerothcore-wotlk_ac-database
```

## Notes

- Official AzerothCore Docker guide: https://www.azerothcore.org/wiki/install-with-docker
- Source document referenced during setup: https://zread.ai/azerothcore/azerothcore-wotlk/3-docker-deployment
- The Docker setup uses the official `mysql:8.4` image, so you do not need to compile MySQL from source.
- After the initial `ac-db-import` finishes, prefer targeted restarts (`docker compose restart ac-authserver ac-worldserver`) rather than a full `docker compose up` if you want to avoid re-triggering the one-shot import service.
- Ports exposed by default: Auth `3724`, World `8085` / SOAP `7878`, MySQL `3306`.
