# MariaDB 10.11 → MySQL 8.4 migration

Streaming converter and notes for moving an existing AzerothCore database from MariaDB 10.11 (Debian 12) onto the MySQL 8.4 Docker stack this repository installs.

The converter reads a `mariadb-dump` file and writes data-only SQL whose `INSERT` column lists match the new schema. It does not talk to either database. You export on the old host, run the script, then import with `docker exec` into `ac-database`.

## Validation status

The converter was run in Python against the real MariaDB dumps from 2026-11-02. No MySQL server was involved in that check. Per-table row counts matched, nothing failed to parse, and no row had the wrong number of values:

| dump | rows in | rows out | what the run showed |
|---|---:|---:|---|
| `acore_auth` (9 tables with data) | 517 | 517 | every `account.locale` index `0` became `'enUS'` (202 accounts) |
| `acore_characters` (44 tables with data) | 508,887 | 496,952 in the main file, plus 11,935 from the three playerbot name tables | `character_homebind.posO` dropped; name tables emitted by a second pass |
| `acore_playerbots` (16 tables with data) | 1,440,986 | 1,440,986 | column lists passed through; the new playerbots schema was still empty |

**That converted SQL has not yet been imported into a live MySQL 8.4 server.** The live import is being tested now. Keep both the MariaDB dumps and the pre-import MySQL backup until you have logged in and checked characters in game. The synthetic tests in `tests/` cover the column mapping only; they are not a substitute for that import.

The mechanical diff behind the table above is [DIFF_REPORT.md](DIFF_REPORT.md). Raw `schema_diff.py` output is in `source_schema/diff_*.txt`.

## Background

The old server was AzerothCore on MariaDB 10.11 (the host is Debian 12; it had been assumed to be 10.6). `mariadb --version` on that host reports the 10.11 line, and the dump header is `MariaDB dump 10.19 Distrib 10.11.18-MariaDB`. The new server is the Docker stack from this repository: official AzerothCore images plus `mysql:8.4` (the compared schema dump was 8.4.13). See the [main install guide](../../README.md).

A direct load of the old dumps into MySQL 8.4 failed. The dump is still the right backup. It is the wrong thing to execute as-is, because the new core's table layouts changed and because the dump was being executed line by line.

`install.sh` clones upstream `azerothcore/azerothcore-wotlk`, which does not include [mod-playerbots](https://github.com/mod-playerbots/mod-playerbots). Playerbot data needs the Playerbots fork (`https://github.com/mod-playerbots/azerothcore-wotlk`, branch `Playerbot`) and the module checked out under `modules/mod-playerbots`. The module's own Docker notes are in its [installation guide](https://github.com/mod-playerbots/mod-playerbots/wiki/Installation-Guide). Docker support there is limited; the commands below use the container and service names this repository already documents (`ac-database`, `ac-authserver`, `ac-worldserver`, `ac-db-import`).

## Why a raw import fails

`mariadb-dump` writes `INSERT INTO \`table\` VALUES (...);` with **no column list**, and it wraps long statements across many lines. Three MySQL errors follow from that.

### ERROR 1064 — syntax error, `INSERT` split from its rows

Something walked the dump line by line and executed a line that was only `INSERT INTO \`some_table\` VALUES`, leaving the `(...)` tuples on the following lines. MySQL then reports a syntax error near the end of that fragment. The same class of failure shows up as an empty statement, `INSERT INTO \`t\` VALUES ;`, which is illegal SQL.

MariaDB also writes a leading conditional comment, `/*M!999999\- enable the sandbox mode */`. A line-oriented tool that strips comments badly can turn that into SQL the server tries to run.

The converter is a statement parser, not a line parser. It understands quotes, backslash escapes, and `--` comments, drops the sandbox comment with the rest of the DDL, and drops empty `INSERT` stubs. Feed it the dump file itself. Do not `sed`, `split`, `head`, or otherwise cut the file first.

### ERROR 1136 — column count doesn't match

Because the `INSERT` has no column list, MySQL binds values by position against the **current** table. Eight tables changed width between MariaDB 10.11 and this MySQL 8.4 schema. On the dumped server only three of them actually contained rows (`account`, `uptime`, `character_homebind`); those are the 1136s a raw import hits first. The others fail the same way as soon as they have data.

| database.table | change | rows on the dumped server | what the converter does |
|---|---|---|---|
| `acore_auth.account` | adds `Flags` `int unsigned NOT NULL DEFAULT 0` after `expansion` | 202 | omits `Flags` so MySQL stores `0` |
| `acore_auth.uptime` | adds `EndTime` after `uptime`, and `ShutdownType`, `ExitCode`, `ShutdownReason` after `revision` | yes | omits the new columns; defaults are `NULL`, `0`, `NULL`, `''` |
| `acore_characters.character_homebind` | removes `posO` | yes | drops `posO` |
| `acore_characters.bugreport` | adds `State` `DEFAULT 1`, `Assignee`, `Comment` | 0 | omits them; defaults apply |
| `acore_characters.mail_server_template` | removes `reqLevel`, `reqPlayTime`, `itemA`, `itemCountA`, `itemH`, `itemCountH`; adds `senderEntry` `DEFAULT 0` | 0 | writes items and level/playtime conditions into the new child tables |
| `acore_characters.petition` | adds `petition_id` after `petitionguid` | 0 | fills `petition_id` with the core's formula |
| `acore_characters.petition_sign` | adds `petition_id`; primary key becomes `(petition_id, playerguid)` | 0 | same formula |
| `acore_characters.recovery_item` | adds `DeleteDate` `NULL` | 0 | omits it; stays `NULL` |

There is a second 1136 that is not a width change. `account.locale` changed from `tinyint unsigned DEFAULT 0` to `varchar(4) DEFAULT 'enUS'`. A raw integer would be stored as the string `'0'`, which is not a locale the client understands. The converter maps the old index. On this dump every account was `0`, so every locale became `'enUS'`.

### ERROR 1062 — duplicate key

`addons` and world tables such as `achievement_criteria_data` already contain rows after `ac-db-import` (and after a module's base SQL). Loading the old dump on top of that collides on primary keys. A second import of the same file does the same thing.

The converter's default is `INSERT IGNORE` (`--dup ignore`): the row already in MySQL wins, and the old row is skipped with no error. That is the wrong outcome when the old row is the one you want. `--dup replace` emits `REPLACE`, so the old row overwrites. `--truncate` emits `TRUNCATE TABLE` before the first insert of each table, which is the mode to use for this migration: seed rows are cleared, then the old data is the only data. `INSERT IGNORE` still guards the new unique key on `quest_tracker` if two old rows collapse to the same key.

Do not use a raw import plus `--force` to "skip" 1062. `--force` commits the rows that happened to be new and leaves the rest as a mix of old and new.

## Per-table schema differences

Column order below is the new MySQL 8.4 order. "Omitted" means the `INSERT` does not name the column, so the table default applies. Full text of every difference, including charset-only noise, is in [DIFF_REPORT.md](DIFF_REPORT.md).

### `acore_auth`

Compared column lists: `source_schema/acore_auth.cols` (old) and `target_schema/acore_auth.cols` (new).

**`account`**

* New column `Flags int unsigned NOT NULL DEFAULT 0`, placed after `expansion`. Omitted on insert.
* `locale` changes from `tinyint unsigned NOT NULL DEFAULT 0` to `varchar(4) NOT NULL DEFAULT 'enUS'`. Mapping follows AzerothCore's `LocaleConstant` order:

  | old index | new value |
  |---:|---|
  | 0 | `enUS` |
  | 1 | `koKR` |
  | 2 | `frFR` |
  | 3 | `deDE` |
  | 4 | `zhCN` |
  | 5 | `zhTW` |
  | 6 | `esES` |
  | 7 | `esMX` |
  | 8 | `ruRU` |

  Any other index is written as `'enUS'`.

**`uptime`**

* `EndTime int unsigned DEFAULT NULL` after `uptime`.
* `ShutdownType tinyint unsigned NOT NULL DEFAULT 0` after `revision` (`0` unknown, `1` shutdown, `2` restart, `3` error).
* `ExitCode tinyint unsigned DEFAULT NULL` after `ShutdownType`.
* `ShutdownReason varchar(255) NOT NULL DEFAULT ''` after `ExitCode`.

All four are omitted.

**`motd`**

* `text` lost `DEFAULT 'TESTING123'`. A `TEXT` column with a string literal default is MariaDB syntax; MySQL 8.4 rejects it. Data rows are copied unchanged. This was not a 1136.

**`updates` / `updates_include`**

* `state` gained the enum value `'PENDING'`. These tables are skipped on import (see below). Do not load the old rows just because the enum is a superset.

**Keys and new tables**

* `realmlist`'s `CHECK (population >= 0)` is reprinted by MySQL with an extra pair of parentheses. Same constraint.
* Tables that exist only on the new server, and therefore have nothing to import: `autobroadcast_locale`, `motd_localized`, `rbac_account_permissions`, `rbac_default_permissions`, `rbac_linked_permissions`, `rbac_permissions`.
* No auth table exists only on the old server.

No auth column was renamed or reordered, apart from the additions above.

### `acore_characters`

Compared column lists: `source_schema/acore_characters.cols` and `target_schema/acore_characters.cols`.

**`character_homebind`** — `posO` is removed. The value is dropped. Remaining columns stay in order: `guid`, `mapId`, `zoneId`, `posX`, `posY`, `posZ`.

**`bugreport`** — adds `State tinyint NOT NULL DEFAULT 1`, `Assignee varchar(255) NULL`, `Comment longtext`. All omitted.

**`mail_server_template`** — this is the [AzerothCore PR #21590](https://github.com/azerothcore/azerothcore-wotlk/pull/21590) split.

Removed from the parent: `reqLevel`, `reqPlayTime`, `itemA`, `itemCountA`, `itemH`, `itemCountH`. Added on the parent: `senderEntry int unsigned NOT NULL DEFAULT 0` (creature entry; `0` means the default "Customer Support" sender). Omitted, so it stays `0`.

When a removed column is greater than zero, the converter appends rows:

* `itemA` / `itemCountA` → `mail_server_template_items` with `faction = 'Alliance'`
* `itemH` / `itemCountH` → `mail_server_template_items` with `faction = 'Horde'`
* `reqLevel` → `mail_server_template_conditions` with `conditionType = 'Level'`
* `reqPlayTime` → `mail_server_template_conditions` with `conditionType = 'PlayTime'`

The parent `INSERT` is emitted before those child inserts. `id` on the child tables is auto-increment and is left out. The dumped server had zero rows here; the mapping is still applied so a later dump with templates does not need a separate script.

**`petition` / `petition_sign`** — `petition_id int unsigned NOT NULL DEFAULT 0` is added after `petitionguid`. `petition_sign`'s primary key changes from `(petitionguid, playerguid)` to `(petition_id, playerguid)`. `petition` gains `KEY idx_petition_id (petition_id)`.

The value is the one from AzerothCore `rev_1756841669142726711.sql` ([PR #22774](https://github.com/azerothcore/azerothcore-wotlk/pull/22774)):

```text
petition_id = petitionguid                      if petitionguid <= 2147483647
petition_id = petitionguid - 2147483648         otherwise
```

`2147483648` is 2^31. A charter item's first enchantment slot has to carry the same id; that update is `post_import_characters.sql`, run after the load, because it joins `item_instance` to `petition`.

**`recovery_item`** — adds nullable `DeleteDate`. Omitted.

**`quest_tracker`**

* `id` changes from nullable (`DEFAULT 0` in the diff's type line; the old dump also contains explicit `NULL`) to `int unsigned NOT NULL DEFAULT 0`.
* New unique key `(id, character_guid, quest_accept_time DESC)`.

The converter rewrites a SQL `NULL` id to `0`. Two rows that both had `NULL` and share the same character and accept time then collide; `INSERT IGNORE` keeps one of them. Check the converter's stderr for `rows with wrong value count` (that counter is a different problem) and, after import, compare `COUNT(*)` with the old dump.

**`mail_server_character`** — no column change. MySQL adds `FOREIGN KEY (mailId) REFERENCES mail_server_template (id) ON DELETE CASCADE`. The converter sets `FOREIGN_KEY_CHECKS=0` for the session, and it writes the template before the character rows only when both appear in the same converted file. Import `chars.sql` as one file.

**`updates` / `updates_include`** — `state` gained `'PENDING'`. Skip these tables.

**Tables only on one side**

New server only (left untouched): `active_arena_season`, `character_achievement_offline_updates`, `chat_filter`, `mail_server_template_conditions`, `mail_server_template_items`, `spam_reports`, `world_state`.

Old server only, all from mod-playerbots:

| table | rows on the dumped server |
|---|---:|
| `playerbots_arena_team_names` | 615 |
| `playerbots_guild_names` | 641 |
| `playerbots_names` | 10,679 |

The new `acore_characters` dump did not contain them, because worldserver had not been started with the module yet. They are skipped by the main characters conversion (they are absent from `target_schema/acore_characters.cols`) and written by a second pass. See the convert step.

**Other character changes that do not affect the load**

* Several `TEXT` columns are printed by MySQL with an explicit charset and without MariaDB's `DEFAULT NULL`. Same column.
* `character_stats`'s `CHECK` is reprinted with extra parentheses.
* `world_state` (new) uses `utf8mb4_0900_ai_ci`. Every migrated table stays `utf8mb4_unicode_ci`.
* No character column was renamed. The only removal is `character_homebind.posO`.

`target_schema/notnull_nodefault.txt` lists a few `NOT NULL` columns with no default (`characters.innTriggerId`, `character_arena_stats.maxMMR`, `gm_survey.maxMMR`, `character_instance.extended`). The fill (`0`) is applied only when the old row does not already contain that column. Current MariaDB 10.11 dumps already have these columns, so the file is a safety net for a slightly older dump.

### `acore_playerbots`

The new server's dump of this database was a header only: the module had not created the database yet. The old server has 25 tables (the column list is `source_schema/acore_playerbots.cols`), 16 of them with data, 1,440,986 rows.

There is no `target_schema/acore_playerbots.cols`. The converter therefore copies column lists through unchanged and says so on stderr (`no target schema ... columns pass through unmapped`). That matched the 2026-11-02 module schema. If a newer module revision adds or removes columns, this pass-through will produce 1136s. Generate a column map from the new server and pass `--target-schema` (see Troubleshooting) before loading.

Old dumps of these tables also carry MariaDB-only syntax the converter never emits, because it emits `INSERT`s only:

* `ENGINE=MyISAM` and `ROW_FORMAT=FIXED` (InnoDB in strict mode rejects `ROW_FORMAT=FIXED`)
* `utf8mb3_general_ci`, and `latin1` on `playerbots_enchants`
* `current_timestamp()`, integer display widths such as `int(11)`, and the sandbox comment

`playerbots_schema_mysql84.sql` is that old `--no-data` dump rewritten to `InnoDB` and `utf8mb4_unicode_ci`, with display widths and `ROW_FORMAT=FIXED` removed. Prefer the tables the module creates itself; use this file only when the module cannot create them. Moving `utf8mb3_general_ci` unique `name` keys to `utf8mb4_unicode_ci` can treat near-identical names as duplicates. `INSERT IGNORE` skips the loser. The names that were skipped are the gap between the old row count and the new one.

`playerbots_characters_tables_mysql84.sql` is the same kind of rewrite for the three name tables that live in `acore_characters`.

### `acore_world` — leave the old dump unused

Do not convert or import the old world database. `ac-db-import` loads the world the new core was built with. The 2026-11-02 diff (`source_schema/diff_world.txt`) found **72 tables** that differ, plus tables that exist on only one side.

Structural changes (columns added or removed, which a positional `INSERT` will mis-bind):

| table | change |
|---|---|
| `creature` | `id1` / `id2` / `id3` removed, single `id` added |
| `creature_template` | `modelid1`–`modelid4`, `scale`, `trainer_type`, `trainer_spell`, `trainer_class`, `trainer_race`, `mechanic_immune_mask`, `spell_school_immune_mask` removed; `CreatureImmunitiesId` added |
| `creature_classlevelstats` | `Strength`, `Agility`, `Stamina`, `Intellect`, `Spirit` added |
| `creature_model_info` | `VerifiedBuild` added |
| `gameobject_addon` | `parent_rotation0`–`parent_rotation3` added |
| `item_template` | `StatsCount` removed |
| `charsections_dbc` | columns renamed (`Id`→`ID`, `Race`→`RaceID`, `Gender`→`SexID`, texture paths, …). The converter matches by name and would not follow these renames |
| `acore_string` | per-locale `locale_*` columns removed (the new schema has `acore_string_locale`) |
| `quest_template_addon` | `BreadcrumbForQuestId` added; `SpecialFlags` widened |
| `spell_group` | `special_flag` removed |
| `spell_proc` | `DisableEffectsMask` added |
| `waypoint_data` | `velocity`, `smoothTransition` added |
| `player_factionchange_achievement`, `player_factionchange_reputations` | comment columns added |

Tables present only in the old world dump include `playerbots_rpg_races`, `spell_proc_event`, `player_classlevelstats`, and `emotetextsound_dbc` (the new name is `emotestextsound_dbc`). Tables present only in the new world include `trainer`, `trainer_spell`, `spawn_group`, `creature_template_model`, and `acore_string_locale`. The rest of the 72 are mostly MySQL reprinting `TEXT` columns with an explicit charset. The raw list is `source_schema/diff_world.txt`.

Custom world edits made on the old server are not migrated by this toolkit. Module world rows (dungeon suggestions, RPG tables, and anything under the module's `sql/world` base files) come from the module's own SQL on first start, not from the old `acore_world` dump.

## What the converter does

`convert_mariadb_to_mysql.py` streams the dump in 1 MiB chunks and splits it into statements. For each `CREATE TABLE` it records the column order. For each `INSERT` it:

1. Skips the table if you named it in `--skip-tables`, if `--only-tables` is set and this table is not in it, or if a target column map is loaded and the table is not in it.
2. Parses the value tuples (quotes and escaped quotes included).
3. Zips values with the old column names from the `CREATE TABLE`, or with the column list if the dump used `--complete-insert`.
4. Applies the transform for that table, if any.
5. Writes `INSERT IGNORE` / `REPLACE` / `INSERT` with an explicit column list in **new-schema order**. Columns the new table does not have are dropped and listed on stderr. Columns only the new table has are omitted so MySQL applies the default, except the `NOT NULL` fills in `notnull_nodefault.txt`.

The database name is the first `Database: <name>` comment in the first 10 lines of the file, which is where `mariadb-dump --databases` puts it. That name selects `target_schema/<db>.cols`. One database per dump file. A combined dump would lock the column map to whichever database was named first.

Output starts with `SET NAMES utf8mb4`, `FOREIGN_KEY_CHECKS=0`, `UNIQUE_CHECKS=0`, `sql_mode='NO_AUTO_VALUE_ON_ZERO'` (so an explicit `0` id is stored as `0`), and `time_zone='+00:00'`. DDL, view definitions, routines, and MariaDB session settings from the source are dropped. The new core's schema is the one that already exists in MySQL.

```text
python3 convert_mariadb_to_mysql.py IN.sql OUT.sql
    [--dup ignore|replace|error] [--truncate]
    [--skip-tables a,b] [--only-tables a,b]
    [--db acore_characters] [--target-schema new_nodata.sql] [--no-embedded]
```

`--target-schema` is a `mysqldump --no-data` of the new database and replaces the bundled `*.cols` file. `--no-embedded` forces the pass-through behavior used for the playerbot name tables.

## Prerequisites

* Python 3. The script uses the standard library only. `python3 tests/test_changed_tables.py` is the check that the checkout is intact.
* The old MariaDB still has the data, or you already have per-database `mariadb-dump` files that include `CREATE TABLE` (not `--no-create-info`) and were not cut apart by line.
* `mariadb-dump` on the Debian host (`mariadb-client`; `mysqldump` is usually the same binary).
* This repository's Docker stack, built from `~/azerothcore-wotlk` as [the install guide](../../README.md) describes. Container `ac-database`, MySQL user `root`, password `password` (the default `install.sh` and the guide use).
* Enough disk for the dumps. The playerbots dump alone is on the order of the 1.4 million rows above; auth and characters are smaller but characters is still hundreds of thousands of rows.
* For playerbots, the Playerbots fork and `modules/mod-playerbots`, built into the worldserver image. Upstream AzerothCore will not create `acore_playerbots`.

Stop the old `authserver` and `worldserver` before dumping. Stop the new `ac-authserver` and `ac-worldserver` before importing. Leave `ac-database` running.

## Step by step

Paths below assume:

```bash
GUIDE=~/azerothcore-docker-install   # this repository
ACORE=~/azerothcore-wotlk            # where install.sh clones AzerothCore; compose project name matters
```

`install.sh` names the compose project from that directory, so the data volume is `azerothcore-wotlk_ac-database`. Run every `docker compose` command in `$ACORE`. Run `docker exec` against the container name `ac-database` from anywhere.

If `docker` says permission denied because the install script just added your user to the `docker` group, wrap the command the same way `install.sh` does: `sg docker -c 'docker exec ...'`.

### 1. Export the old MariaDB databases

This export is the backup of the old server. Keep the files. Do not import them directly.

On the Debian 12 host, with the old authserver and worldserver stopped:

```bash
mkdir -p ~/ac-migration && cd ~/ac-migration

dump_one() {
  mariadb-dump \
    --user=root --password \
    --single-transaction \
    --quick \
    --hex-blob \
    --routines --triggers --events \
    --default-character-set=utf8mb4 \
    --databases "$1" > "$2"
}

dump_one acore_auth        old_auth.sql
dump_one acore_characters  old_characters.sql
dump_one acore_playerbots  old_playerbots.sql
```

`mysqldump` with the same flags is fine when it is the MariaDB client symlink. Use the old server's real user if it is not `root`.

Why these flags:

| flag | why |
|---|---|
| `--single-transaction` | consistent snapshot of InnoDB (`acore_auth`, `acore_characters`) without a long global lock |
| `--quick` | streams rows instead of buffering a whole table; matters for playerbots |
| `--hex-blob` | writes `account.salt`, `verifier`, `session_key`, and `totp_secret` as `0x...`. Without it, the client charset can mangle those bytes and every login fails after a "successful" import |
| `--routines --triggers --events` | kept in the backup. The converter drops DDL; the new schema already has the routines it needs |
| `--default-character-set=utf8mb4` | matches the new tables |
| `--databases` | writes the `Database: acore_auth` header the converter reads, and keeps one database per file |

Do not pass `--no-create-info`. The converter learns column order from `CREATE TABLE`. Do not pass `--skip-comments` unless you also pass `--db` to the converter; the database name lives in a comment. `--complete-insert` is optional (it adds column lists, which the converter accepts). `--skip-extended-insert` only makes the file larger.

`--single-transaction` does not snapshot MyISAM. The old playerbots tables are MyISAM, which is why the game servers must be stopped first.

Do not dump `acore_world`. Do not pipe the files through `sed` or split them by line. Copy them off the host before you shut the old machine down.

### 2. Start the new stack once, including mod-playerbots

The new schemas have to exist before the converted `INSERT`s run. `ac-db-import` creates `acore_auth`, `acore_characters`, and `acore_world` on first start. mod-playerbots creates `acore_playerbots` and the three name tables in `acore_characters` when worldserver actually runs with the module.

`install.sh` clones upstream AzerothCore, which will not do the playerbots half. For a server that had playerbots, clone the fork into `$ACORE` **before** the first `docker compose up`. If `install.sh` already cloned upstream and you have not stored data you need in the volume, remove that tree and clone the fork; if the volume already ran an upstream import, leave the volume (it holds the fresh auth/characters/world) and rebuild worldserver from the fork.

```bash
git clone https://github.com/mod-playerbots/azerothcore-wotlk.git --branch=Playerbot "$ACORE"
git clone https://github.com/mod-playerbots/mod-playerbots.git --branch=master "$ACORE/modules/mod-playerbots"
```

The module's Docker guide mounts the module into the worldserver service. In `$ACORE/docker-compose.override.yml`:

```yaml
services:
  ac-worldserver:
    volumes:
      - ./modules:/azerothcore/modules:ro
```

Then, from `$ACORE`, the same first start as the install guide:

```bash
cd "$ACORE"
docker compose up -d --build
docker compose ps          # ac-database should become (healthy)
docker compose logs ac-db-import
```

`ac-db-import` is one-shot. When it exits successfully, auth and world start. Let worldserver finish its first startup so the module can create its tables (the console shows the usual AzerothCore "ready" line; bot login lines on a fresh database are normal). Then stop the game servers and leave the database up:

```bash
docker compose stop ac-authserver ac-worldserver
```

Confirm the module's tables exist:

```bash
docker exec -i ac-database mysql -uroot -ppassword -e "SHOW DATABASES LIKE 'acore_%';"
docker exec -i ac-database mysql -uroot -ppassword acore_characters -e "SHOW TABLES LIKE 'playerbots_%';"
docker exec -i ac-database mysql -uroot -ppassword acore_playerbots -e "SHOW TABLES;"
```

If `acore_playerbots` is missing, the module did not start. Create the empty database and fall back to the rewritten schema in this directory (same column layout as the MariaDB 10.11 dump, InnoDB, `utf8mb4_unicode_ci`):

```bash
docker exec -i ac-database mysql -uroot -ppassword -e \
  "CREATE DATABASE IF NOT EXISTS acore_playerbots CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

docker exec -i ac-database mysql -uroot -ppassword acore_playerbots \
  < "$GUIDE/tools/mariadb-to-mysql/playerbots_schema_mysql84.sql"

docker exec -i ac-database mysql -uroot -ppassword acore_characters \
  < "$GUIDE/tools/mariadb-to-mysql/playerbots_characters_tables_mysql84.sql"
```

Those files are `CREATE TABLE IF NOT EXISTS`, so they are safe to run when the module created some of the tables and not others. They are a fallback, not a newer module revision. If you can get worldserver to create the tables, do that and skip these two files.

### 3. Back up the new MySQL databases

Do this after the first start and before `--truncate` overwrites seed rows. This is the rollback if the import is wrong.

```bash
cd ~/ac-migration
docker exec ac-database mysqldump -uroot -ppassword \
  --single-transaction --quick --hex-blob --routines --triggers --events \
  --default-character-set=utf8mb4 \
  --databases acore_auth acore_characters acore_world acore_playerbots \
  > new_mysql84_backup.sql
```

Omit `acore_playerbots` from that list if the database does not exist yet. `acore_world` belongs in this backup. You will not replace it, and you want a copy in case a later command targets the wrong database.

### 4. Convert

From any working directory. The script finds `target_schema/` next to itself.

```bash
cd "$GUIDE/tools/mariadb-to-mysql"

python3 convert_mariadb_to_mysql.py ~/ac-migration/old_auth.sql ~/ac-migration/auth.sql \
  --truncate --skip-tables updates,updates_include,build_info

python3 convert_mariadb_to_mysql.py ~/ac-migration/old_characters.sql ~/ac-migration/chars.sql \
  --truncate --skip-tables updates,updates_include

python3 convert_mariadb_to_mysql.py ~/ac-migration/old_characters.sql ~/ac-migration/chars_bots.sql \
  --no-embedded --truncate \
  --only-tables playerbots_arena_team_names,playerbots_guild_names,playerbots_names

python3 convert_mariadb_to_mysql.py ~/ac-migration/old_playerbots.sql ~/ac-migration/bots.sql \
  --truncate --skip-tables updates,updates_include,version_db_playerbots
```

Stderr should include `using bundled target schema for acore_auth` and the same for `acore_characters`, then a line like `N INSERT stmts, N rows, 0 empty stubs removed, 0 rows with wrong value count SKIPPED`. The playerbots run reports that there is no bundled target schema. The characters run reports the three `playerbots_*` name tables as skipped; the `chars_bots.sql` run is what writes them.

Compare counts before importing:

```bash
python3 tests/count_rows.py ~/ac-migration/old_auth.sql ~/ac-migration/auth.sql
python3 tests/count_rows.py ~/ac-migration/old_characters.sql ~/ac-migration/chars.sql
python3 tests/count_rows.py ~/ac-migration/old_playerbots.sql ~/ac-migration/bots.sql
```

Skipped tables show up as mismatches `(old_count, 0)`. That is expected for `updates`, `updates_include`, `build_info`, and `version_db_playerbots`, and for the three name tables in the main characters file. Any other mismatch is a row the converter dropped; read stderr before importing.

The output files are the data. They are gitignored under this directory when written here. Do not commit them. They contain accounts, SRP verifier blobs, and emails.

### 5. Import, in this order

`ac-authserver` and `ac-worldserver` stay stopped. `--force` keeps going after an error so the log is complete; a non-empty error log still means the import did not fully succeed. `--max-allowed-packet=1G` is there because one extended `INSERT` from `mariadb-dump` can be larger than the server default.

```bash
cd ~/ac-migration

docker exec -i ac-database mysql -uroot -ppassword \
  --force --max-allowed-packet=1G acore_auth < auth.sql 2> auth_err.log

docker exec -i ac-database mysql -uroot -ppassword \
  --force --max-allowed-packet=1G acore_characters < chars.sql 2> chars_err.log

docker exec -i ac-database mysql -uroot -ppassword \
  --force --max-allowed-packet=1G acore_characters < chars_bots.sql 2> chars_bots_err.log

docker exec -i ac-database mysql -uroot -ppassword \
  --force --max-allowed-packet=1G acore_playerbots < bots.sql 2> bots_err.log
```

If MySQL itself rejects the packet (`ERROR 1153`), raise the server limit and rerun that file:

```bash
docker exec -i ac-database mysql -uroot -ppassword -e \
  "SET GLOBAL max_allowed_packet=1073741824;"
```

### 6. Tables to skip

Already applied via `--skip-tables` above. They must stay as the new server wrote them.

| table | database | why it stays |
|---|---|---|
| `build_info` | `acore_auth` | client build seeds and checksums for **this** core. Old seeds make the authserver reject the client |
| `updates` | auth, characters, playerbots | rows here mark a SQL update as already applied. Old rows can make the new core skip migrations it still needs |
| `updates_include` | auth, characters, playerbots | same tracking, for directories of update files |
| `version_db_playerbots` | `acore_playerbots` | the module's revision pointer. An old `sql_rev` hides updates the new module still has to run |

`--truncate` is per converted file and only runs for tables that file actually writes, so these skipped tables are not emptied.

### 7. `post_import_characters.sql`

After the characters load, charter items need `petition_id` in the first enchantment slot. The converter already filled `petition.petition_id` and `petition_sign.petition_id`. This statement copies that id onto the matching `item_instance` rows. It updates only items that join to `petition`, and it is a no-op when no petition guid differs from its `petition_id` (every charter on the dumped server was in that situation: zero petition rows).

```bash
docker exec -i ac-database mysql -uroot -ppassword acore_characters \
  < "$GUIDE/tools/mariadb-to-mysql/post_import_characters.sql"
```

### 8. Realmlist, then start the servers

The auth import replaces `realmlist` with the old row, including the old address. Set it back to the IP clients use, the same statement as the install guide:

```bash
docker exec -i ac-database mysql -uroot -ppassword acore_auth -e \
  "UPDATE realmlist SET address='YOUR_SERVER_IP', flag=0 WHERE id=1;"
```

Start auth first, then world:

```bash
cd "$ACORE"
docker compose start ac-authserver ac-worldserver
docker compose logs -f ac-authserver ac-worldserver
```

Log in with an existing account and open a character. That is the check the Python row counts could not do.

## Verification queries

Run these in the new database and compare them with `tests/count_rows.py` on the dump (or with `SELECT COUNT(*)` against the old MariaDB, if it is still up).

```bash
docker exec -i ac-database mysql -uroot -ppassword -e "
SELECT 'account' AS t, COUNT(*) AS n FROM acore_auth.account
UNION ALL SELECT 'account_access', COUNT(*) FROM acore_auth.account_access
UNION ALL SELECT 'realmcharacters', COUNT(*) FROM acore_auth.realmcharacters
UNION ALL SELECT 'characters', COUNT(*) FROM acore_characters.characters
UNION ALL SELECT 'character_inventory', COUNT(*) FROM acore_characters.character_inventory
UNION ALL SELECT 'item_instance', COUNT(*) FROM acore_characters.item_instance
UNION ALL SELECT 'character_homebind', COUNT(*) FROM acore_characters.character_homebind
UNION ALL SELECT 'playerbots_names', COUNT(*) FROM acore_characters.playerbots_names
UNION ALL SELECT 'playerbots_random_bots', COUNT(*) FROM acore_playerbots.playerbots_random_bots;
"
```

Locale values after the mapping (the dumped server was entirely `enUS`):

```bash
docker exec -i ac-database mysql -uroot -ppassword acore_auth -e \
  "SELECT locale, COUNT(*) FROM account GROUP BY locale;"
```

Inventory rows must point at an item. The count of orphans should be `0`:

```bash
docker exec -i ac-database mysql -uroot -ppassword acore_characters -e "
SELECT COUNT(*) AS orphan_inventory
FROM character_inventory ci
LEFT JOIN item_instance ii ON ii.guid = ci.item
WHERE ii.guid IS NULL;"
```

Homebind should have no `posO` column, and petition ids should be filled when petitions exist:

```bash
docker exec -i ac-database mysql -uroot -ppassword acore_characters -e "
SHOW COLUMNS FROM character_homebind LIKE 'posO';
SELECT COUNT(*) AS petitions,
       SUM(petition_id = 0 AND petitionguid <> 0) AS petition_id_still_zero
FROM petition;"
```

`SHOW COLUMNS ... LIKE 'posO'` returns an empty set. `petition_id_still_zero` is `0` (or `NULL` when there are no petitions).

On the 2026-11-02 dumps the Python converter preserved 517 auth rows, 508,887 character rows (split across `chars.sql` and `chars_bots.sql` as 496,952 + 11,935), and 1,440,986 playerbots rows. Those numbers are that server's counts, not a target for a different database. Use your own `count_rows.py` output.

## Troubleshooting

**`using bundled target schema` did not appear, or stderr says `no target schema`.** The dump has no `Database:` line in the first 10 lines (`--skip-comments`, or a file that is not `--databases`). Pass `--db acore_auth` (or `acore_characters`). For playerbots, "no target schema" is expected.

**`rows with wrong value count SKIPPED` is not zero.** The `CREATE TABLE` in the dump does not match the `INSERT` tuples, usually because the file was edited or truncated. Re-export. Do not import a file whose stderr reports skipped rows.

**ERROR 1064 on import.** The file being imported is still the raw dump, or a line-split piece of it. Import `auth.sql` / `chars.sql` / `bots.sql`, the converter output. A leftover `/*M!999999` in the converted file means an old converter; current output drops that comment.

**ERROR 1136 on import.** The converter was pointed at the wrong database, or playerbots tables on the new server no longer match the old column list. For auth and characters, rerun with `--db` set explicitly. For playerbots, dump the new schema and rebuild the column map:

```bash
docker exec ac-database mysqldump -uroot -ppassword --no-data acore_playerbots \
  > ~/ac-migration/new_playerbots_nodata.sql
python3 schema_diff.py ~/ac-migration/old_playerbots.sql ~/ac-migration/new_playerbots_nodata.sql
python3 convert_mariadb_to_mysql.py ~/ac-migration/old_playerbots.sql ~/ac-migration/bots.sql \
  --target-schema ~/ac-migration/new_playerbots_nodata.sql \
  --truncate --skip-tables updates,updates_include,version_db_playerbots
```

`schema_diff.py` must be run from this directory (`import convert_mariadb_to_mysql`). Read the diff before trusting the load: the converter has explicit transforms for auth and characters only. A playerbots column **rename** would need an entry in `RENAMES` inside `convert_mariadb_to_mysql.py`; a dropped or added column is handled by the target map.

**ERROR 1062 on import.** The table was not truncated. Confirm the converted file starts that table with `TRUNCATE TABLE`, and that you did not import the raw dump. Importing the converted file a second time is safe only because of `TRUNCATE` plus `INSERT IGNORE`. `INSERT IGNORE` alone, without `--truncate`, keeps whatever seed row was already there and drops the old row on conflict.

**ERROR 1146 (table missing) or ERROR 1049 (`acore_playerbots`).** Worldserver has not created the module tables. Go back to step 2, including the fallback `CREATE TABLE` files. Then rerun the import for that database.

**ERROR 1153, packet bigger than `max_allowed_packet`.** Use the `SET GLOBAL` statement in the import section and rerun that one file.

**ERROR 1267, illegal mix of collations, or unique-name errors on bot names.** The old name keys were `utf8mb3_general_ci`. The new tables are `utf8mb4_unicode_ci`. `INSERT IGNORE` skips the duplicate. `SELECT name, COUNT(*) FROM playerbots_names` is the wrong check (the unique key already forbids duplicates); compare the table count to the old dump instead. A shortfall is skipped near-identical names.

**Logins fail and the account count is right.** The dump was taken without `--hex-blob`, so `salt` and `verifier` were corrupted in transit. Re-export `acore_auth` with `--hex-blob`, reconvert, and reimport. Creating a new account with `account create` on the worldserver console still works, which is a hint that only the old verifier bytes are wrong.

**Characters exist, items do not.** Run the orphan-inventory query. A non-zero count means `character_inventory` and `item_instance` did not come from the same dump, or one of the two imports failed part way. Restore `acore_characters` from `new_mysql84_backup.sql` and import `chars.sql` again. Look at `chars_err.log` first.

**World creatures, quests, or spawns look wrong.** The old world dump was imported. `new_mysql84_backup.sql` is a `--databases` file, so replaying it restores every database in it, including auth and characters, to the pre-import snapshot. If the migrated auth and characters are worth keeping, dump those two (and playerbots) first, replay the backup, then import the migrated files again:

```bash
docker exec ac-database mysqldump -uroot -ppassword \
  --single-transaction --quick --hex-blob --default-character-set=utf8mb4 \
  --databases acore_auth acore_characters acore_playerbots \
  > ~/ac-migration/migrated_keep.sql

docker exec -i ac-database mysql -uroot -ppassword --max-allowed-packet=1G \
  < ~/ac-migration/new_mysql84_backup.sql

docker exec -i ac-database mysql -uroot -ppassword --max-allowed-packet=1G \
  < ~/ac-migration/migrated_keep.sql
```

Do not try to repair world from the MariaDB world dump. If `new_mysql84_backup.sql` was never taken, the recovery is to move auth, characters, and playerbots aside the same way and let `ac-db-import` load a fresh world (remove the world volume contents only by restoring a backup or by recreating the database from the core's base SQL). That is the situation the step-3 backup is there to avoid.

**New core SQL never runs, or the client is rejected at login with a world-version style error.** `updates`, `updates_include`, `build_info`, or `version_db_playerbots` were loaded from the old dump. Restore those tables from `new_mysql84_backup.sql`.

**`docker compose` cannot see `ac-database`.** The command was not run from `$ACORE` (`~/azerothcore-wotlk`), or the stack was started under a different project name. `docker ps` shows the container names; `docker exec` uses `ac-database` directly and does not care about the current directory.

## Tests

From this directory:

```bash
python3 tests/test_changed_tables.py
```

Seventeen checks, one per changed table plus the stub-line, playerbot-skip, and `--only-tables` cases. Fixtures are `tests/old_auth.sql` and `tests/old_chars.sql`. They are synthetic (short tokens, `0x01`-style blobs, placeholder mail). They are the only data rows in this tree.

`tests/count_rows.py` is the before/after counter used in step 4. It is not part of the seventeen checks. Run it from this directory so `import convert_mariadb_to_mysql` resolves:

```bash
python3 tests/count_rows.py tests/old_auth.sql /tmp/auth_converted.sql
```

## Files

| path | role |
|---|---|
| `convert_mariadb_to_mysql.py` | streaming converter |
| `schema_diff.py` | column-level diff of two `--no-data` dumps |
| `DIFF_REPORT.md` | the 2026-11-02 diff, written up |
| `source_schema/` | old column lists and raw diff output |
| `target_schema/` | new auth and characters column lists, plus NOT NULL fills |
| `playerbots_schema_mysql84.sql` | fallback `CREATE TABLE` for `acore_playerbots` |
| `playerbots_characters_tables_mysql84.sql` | fallback `CREATE TABLE` for the three name tables |
| `post_import_characters.sql` | charter enchantment update |
| `tests/` | synthetic checks and the row-count helper |

Regenerate a diff after a newer core build with:

```bash
python3 schema_diff.py old_nodata.sql new_nodata.sql
```
