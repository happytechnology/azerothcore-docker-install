# AzerothCore WotLK Docker Install Guide (Arch Linux) — with Playerbots

Repeatable installation of AzerothCore WotLK using Docker with the official `mysql:8.4` image and the **Playerbot fork** (required for full playerbots support).

This guide consolidates the steps that successfully worked around MySQL source-build issues (OOM/LTO) by using the official AzerothCore Docker setup. It installs the Playerbot fork plus recommended modules: `mod-playerbots`, `mod-no-hearthstone-cooldown`, `mod-dungeon-clear`, and `mod-npc-enchanter`.

## One-command install

A single script is provided that automates the entire process (Playerbot fork + modules + override file).

### Usage

```bash
# Install git if needed
sudo pacman -S git --noconfirm

# Clone this repository first (or download the script)
git clone https://github.com/happytechnology/azerothcore-docker-install.git
cd azerothcore-docker-install
chmod +x install.sh

# Optional: pass the IP that clients will use to connect
./install.sh 10.0.0.18
```

The script installs packages, enables Docker + BuildKit, clones the Playerbot fork of AzerothCore, clones the four modules, creates `docker-compose.override.yml`, starts the stack, waits for the database to become healthy, and (if an IP was given) updates the realmlist.

### After it finishes, attach to the worldserver and create accounts as usual:

```bash
docker attach ac-worldserver
```

At the `AC>` prompt:

```
account create YOURUSERNAME yourpassword 3 -1
.server debug          # verify modules loaded
.npc add 601015        # optional: spawn the enchanter NPC
```

Detach with `Ctrl+P` then `Ctrl+Q` (**do not** use `Ctrl+C`).

## Prerequisites

- Arch Linux (updated)
- A normal user with `sudo` privileges
- Sufficient disk space (client data + database volumes) and RAM (the Docker build is memory-intensive; 8 GB+ recommended; more for high bot counts)
- Git

## Manual steps (if you prefer not to use the script)

### 1. Install Docker and required plugins

```bash
sudo pacman -Syu
sudo pacman -S --needed docker docker-compose docker-buildx git
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
newgrp docker          # or log out and back in so the group change takes effect
```

### 2. Enable BuildKit

```bash
sudo mkdir -p /etc/docker
echo '{"features":{"buildkit":true}}' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1
```

### 3. Clone the Playerbot fork

```bash
cd ~
git clone https://github.com/mod-playerbots/azerothcore-wotlk.git --branch Playerbot --depth 1 azerothcore-wotlk
cd azerothcore-wotlk
```

### 4. Clone modules and create override

```bash
mkdir -p modules
cd modules
git clone https://github.com/mod-playerbots/mod-playerbots.git
git clone https://github.com/BytesGalore/mod-no-hearthstone-cooldown.git
git clone https://github.com/jrad7/mod-dungeon-clear.git
git clone https://github.com/azerothcore/mod-npc-enchanter.git
cd ..

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
```

### 5. Start the stack

```bash
docker compose up -d --build
```

Monitor with `docker compose logs -f` and confirm `ac-database` is healthy.

### 6. Update realmlist and create account

See the one-command section above.

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
| Check loaded modules      | `.server debug` (inside worldserver)         |
| Spawn enchanter NPC       | `.npc add 601015`                            |

Default MySQL root password is `password`.

Data persists in Docker volumes and survives container restarts. To fully reset the database:

```bash
docker compose down
docker volume rm azerothcore-wotlk_ac-database
```

## Configuring Playerbots

After the first start, the configuration file appears at:

```
env/dist/etc/modules/playerbots.conf
```

You can edit it on the host and restart the worldserver (`docker compose restart ac-worldserver`).

### Key settings (recommended starting point)

Open `playerbots.conf` and look for these (names may be `AiPlayerbot.` or `Playerbots.` depending on version):

- `Playerbots.Enabled = 1` — must be on
- `Playerbots.RandomBotAutologin = 1` — bots log in automatically
- `Playerbots.MinRandomBots = 50` / `Playerbots.MaxRandomBots = 200` — adjust to your hardware (start low)
- `AiPlayerbot.BotActiveAlone = 10` — lower value = bots idle more when no real players nearby (better performance)
- `AiPlayerbot.DisabledWithoutRealPlayer = 1` — optional: bots only log in when a real player is online

Many options can also be set as environment variables in `docker-compose.override.yml` (uppercase, dots → underscores, prefix `AC_`):

```yaml
services:
  ac-worldserver:
    environment:
      AC_PLAYERBOTS_RANDOM_BOT_AUTOLOGIN: "1"
      AC_PLAYERBOTS_MIN_RANDOM_BOTS: "50"
      AC_PLAYERBOTS_MAX_RANDOM_BOTS: "200"
```

Full documentation: https://github.com/mod-playerbots/mod-playerbots/wiki/Playerbot-Configuration

### Performance tips

- Start with a low bot count and increase while watching `.server info` latency (keep under ~80 ms if possible).
- MySQL benefits from a larger `innodb_buffer_pool_size` (ideally ~50% of RAM). You can add a custom MySQL config via volume mount if needed.
- Restart the worldserver periodically if memory usage grows with high bot counts.

## Other helpful tips

- Prefer targeted restarts (`docker compose restart ac-authserver ac-worldserver`) after the initial import so the one-shot `ac-db-import` does not re-run.
- Ports: Auth `3724`, World `8085`, SOAP `7878`, MySQL `3306`.
- Client `realmlist.wtf`: `set realmlist YOUR_SERVER_IP`
- To update later: `git pull` inside the core and each module directory, then `docker compose up -d --build`.

## Notes

- Official AzerothCore Docker guide: https://www.azerothcore.org/wiki/install-with-docker
- Playerbot fork: https://github.com/mod-playerbots/azerothcore-wotlk (branch `Playerbot`)
- Source document referenced during setup: https://zread.ai/azerothcore/azerothcore-wotlk/3-docker-deployment
- The Docker setup uses the official `mysql:8.4` image, so you do not need to compile MySQL from source.
