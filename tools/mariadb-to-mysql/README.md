# Move one character from MariaDB 10.11 to MySQL 8.4

`extract_character.py` reads a `mariadb-dump` of `acore_characters` and writes one SQL file for a single character, selected by `--guid` or `--name`. The file inserts that character's rows into the MySQL 8.4 `acore_characters` schema this repository's Docker stack already has. It does not connect to either database.

Auth, world, playerbots, and every other character stay where they are. The whole-database converter is still in this directory; it is not the path below. See [Whole-database converter](#whole-database-converter).

**Nothing here has been run against a live MySQL 8.4 server.** `python3 tests/test_extract_character.py` uses synthetic fixtures only (placeholder names, no hashes or emails). A real import is still a manual check: log the character in.

Column mapping reuses `convert_mariadb_to_mysql.py` (parser, per-table transforms, bundled `target_schema/`). The mechanical old-vs-new diff is [DIFF_REPORT.md](DIFF_REPORT.md).

## Workflow

1. Dump the old databases and keep those files.
2. Run `extract_character.py` on the characters dump.
3. Back up the new MySQL databases.
4. Import the generated file into `acore_characters`.
5. Start the servers and log in as the destination account.

The new stack has to exist first (schemas created, destination account created). [The install guide](../../README.md) is that setup. Stop `ac-authserver` and `ac-worldserver` before the backup and the import. Leave `ac-database` running. Worldserver keeps the next character and item guids in memory; importing while it is up can collide with a guid it is about to allocate.

```bash
GUIDE=~/azerothcore-docker-install
ACORE=~/azerothcore-wotlk          # compose project; run docker compose from here
```

`install.sh` names the compose project from `$ACORE`, so the data volume is `azerothcore-wotlk_ac-database`. `docker exec` uses the container name `ac-database` from any directory. If `docker` says permission denied because the install script just added your user to the `docker` group, wrap the command the way `install.sh` does: `sg docker -c 'docker exec ...'`.

Default MySQL root password in this stack is `password`.

### 1. Dump the old MariaDB databases

This dump is the backup of the old server. Keep the files. Do not import them directly, and do not commit them.

On the old host, with the old authserver and worldserver stopped:

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

| flag | why |
|---|---|
| `--single-transaction` | consistent snapshot of InnoDB (`acore_auth`, `acore_characters`) without a long global lock |
| `--quick` | streams rows instead of buffering a whole table |
| `--hex-blob` | writes `account.salt`, `verifier`, `session_key`, and `totp_secret` as `0x...` in the auth backup. Without it, the client charset can mangle those bytes |
| `--routines --triggers --events` | kept in the backup. The extractor writes `INSERT`s only |
| `--default-character-set=utf8mb4` | matches the new tables |
| `--databases` | writes the `Database: acore_characters` header the extractor reads |

Do not pass `--no-create-info`. The extractor learns column order from `CREATE TABLE`. Do not pass `--skip-comments` unless the header still contains `Database: acore_characters`. `--complete-insert` is optional. Do not pipe the files through `sed` or split them by line. `--single-transaction` does not snapshot MyISAM; stop the game servers first so the playerbots backup is consistent.

The extractor reads `old_characters.sql` only. `old_auth.sql`, `old_playerbots.sql`, and a copy of the characters dump are the backups you keep. Do not dump `acore_world` to import it. Copy the files off the host before you shut the old machine down.

A raw `INSERT INTO \`table\` VALUES` load of that dump into MySQL 8.4 fails: the statement has no column list, long inserts are split across lines, and a few character tables changed width (`character_homebind` lost `posO`). The extractor parses statements, maps columns by name, and writes a column list in the new order.

### 2. Extract one character

The destination account must already exist in the new `acore_auth` (`account create` on the worldserver console, before you stop the servers for the import). `--account` is that account's numeric id.

From this directory:

```bash
cd "$GUIDE/tools/mariadb-to-mysql"

python3 extract_character.py \
  --dump ~/ac-migration/old_characters.sql \
  --account 42 \
  --guid 123 \
  --out ~/ac-migration/character_123.sql

# same character, looked up by name (case-insensitive)
python3 extract_character.py \
  --dump ~/ac-migration/old_characters.sql \
  --account 42 \
  --name Foo \
  --out ~/ac-migration/character_Foo.sql
```

`--guid` and `--name` are mutually exclusive. If the name matches more than one row, the script exits and prints the guids; pass `--guid`. A name that exists only in `deleteInfos_Name` (a soft-deleted character) is reported the same way.

`--out` defaults to `./character_<guid>_<name>.sql`. The file is character data. Do not commit it. This directory gitignores `character_*.sql`.

`--new-guid 5000` pins the character guid. Omit it and the file sets `@ac_new_guid` to one past the highest character guid already stored on the target. Details are in [Guids, items, and the account](#guids-items-and-the-account).

Stderr lists the row count and any column the new schema dropped (on a current dump that is `character_homebind.posO`). A non-zero exit means the file was not written: unknown guid or name, ambiguous name, empty name with nothing to restore, or a dump that is not `acore_characters`.

### 3. Back up the new MySQL databases

Do this after the new stack has completed its first start and before you import. This is the rollback if the import is wrong.

```bash
cd ~/ac-migration
docker exec ac-database mysqldump -uroot -ppassword \
  --single-transaction --quick --hex-blob --routines --triggers --events \
  --default-character-set=utf8mb4 \
  --databases acore_auth acore_characters acore_world acore_playerbots \
  > new_mysql84_backup.sql
```

Omit `acore_playerbots` from that list if the database does not exist yet. `acore_world` belongs in this backup. The one-character import does not replace it, and you want a copy in case a later command targets the wrong database.

Keep `new_mysql84_backup.sql` next to the MariaDB dumps until you have logged the character in. Do not commit either.

### 4. Import

`ac-authserver` and `ac-worldserver` stay stopped. Run the mysql client **without** `--force`. The script is one transaction. On the first error the client exits, the session disconnects, and MySQL rolls the open transaction back. `--force` would keep going and the final `COMMIT` would keep a partial character.

```bash
docker exec -i ac-database mysql -uroot -ppassword \
  --max-allowed-packet=1G acore_characters < ~/ac-migration/character_123.sql
```

What a failed precondition looks like:

| situation | mysql error |
|---|---|
| `--account` is not an `acore_auth.account.id` | `PROCEDURE acore_characters.import_aborted_account_not_found does not exist` |
| the name is already taken, case-insensitively | `PROCEDURE ...import_aborted_character_name_already_exists does not exist` |
| the chosen guid is already used | `PROCEDURE ...import_aborted_character_guid_already_exists does not exist` |

Those procedures are not created. The `CALL` is how the script aborts with a readable name. A duplicate key on a later `INSERT` aborts the same way (the client stops, the transaction rolls back). Fix the cause and import the file again. Importing it twice without a new guid fails the guid check on the second run, so the first import is left as it was.

The script does not `DELETE`, `UPDATE`, `REPLACE`, or `TRUNCATE` anything.

`post_import_characters.sql` is for a full characters load that includes `petition`. This file does not. Leave that script unused here.

### 5. Log in

Start auth, then world, from `$ACORE`:

```bash
docker compose start ac-authserver ac-worldserver
```

Log in with the destination account. The character should be on the list under the extracted name. That login is the check the synthetic tests cannot do.

After you are in, this is a reasonable spot check (replace the name):

```bash
docker exec -i ac-database mysql -uroot -ppassword acore_characters -e "
SELECT guid, account, name, online FROM characters WHERE name = 'Foo';
SELECT COUNT(*) AS orphan_inventory
FROM character_inventory ci
LEFT JOIN item_instance ii ON ii.guid = ci.item
WHERE ci.guid = (SELECT guid FROM characters WHERE name = 'Foo')
  AND ii.guid IS NULL;"
```

`online` should be `0` until you log in. `orphan_inventory` should be `0`. `SHOW COLUMNS FROM character_homebind LIKE 'posO'` returns an empty set; that column is gone on MySQL 8.4.

If the character was standing in an instance when the dump was taken, `instance_id` was written as `0` (see below). They may need a GM teleport out of the dungeon map. Position coordinates are the ones from the dump.

## Tables included

A row is included when it belongs to the selected character. The list follows AzerothCore `Player::DeleteFromDB` (`CHAR_DEL_*` in `CharacterDatabase.cpp` on current `azerothcore-wotlk`) plus the other per-character tables in `source_schema/acore_characters.cols` and `target_schema/acore_characters.cols`. Every table in those two files is either in this list or in [Tables left out](#tables-left-out).

| rows | how they are chosen |
|---|---|
| `characters` | the selected guid. `account` becomes `--account`, `online` is `0`, `instance_id` and `instance_mode_mask` are `0`. A soft-deleted row (empty `name`, name kept in `deleteInfos_Name`) is restored: the name is put back and `deleteDate` / `deleteInfos_Account` / `deleteInfos_Name` are cleared so the character can log in |
| `character_inventory`, `character_gifts` | this character. Item guids point at the new `item_instance` guids |
| `item_instance` | items this character has in inventory, mail, gifts, equipment sets, or refund data, plus other `item_instance` rows they own. Auctioned items and guild-bank items are the exception in the next section |
| `item_loot_storage` | loot saved inside one of those items (`containerGUID`) |
| `item_refund_instance` | refund data for one of those items |
| `mail`, `mail_items` | mail whose `receiver` is this character, and the items attached to it |
| `character_spell`, `character_spell_cooldown`, `character_skills`, `character_talent`, `character_action`, `character_glyphs` | this character. `character_spell_cooldown.item` is an item entry, so it is copied as-is |
| `character_queststatus`, `character_queststatus_daily`, `character_queststatus_weekly`, `character_queststatus_monthly`, `character_queststatus_seasonal`, `character_queststatus_rewarded` | this character |
| `quest_tracker` | this character. A SQL `NULL` id is written as `0` (the new column is `NOT NULL`) |
| `character_reputation` | this character |
| `character_achievement`, `character_achievement_progress`, `character_achievement_offline_updates` | this character. The offline-updates table exists only on the new schema; an old dump simply has no rows |
| `character_aura` | this character. A caster guid that is this player is rewritten. An item guid that is one of their items is rewritten, including the full `HighGuid::Item` form (`counter + (0x4000 << 48)`). Other caster guids are copied unchanged |
| `character_homebind`, `character_stats`, `character_arena_stats` | this character. Personal arena MMR lives in `character_arena_stats`. Arena teams do not |
| `character_pet`, `character_pet_declinedname`, `pet_spell`, `pet_aura`, `pet_spell_cooldown` | pets whose `owner` is this character, and the spell/aura rows for those pet ids |
| `character_equipmentsets` | this character. `setguid` and the item slots are remapped. An empty slot stays `0` |
| `character_social` | rows this character owns (`guid` = this character). `friend` stays the old guid. See the note under guids |
| `character_account_data`, `character_settings`, `character_declinedname`, `character_entry_point`, `character_banned`, `character_battleground_random`, `character_brew_of_the_month` | this character. A ban moves with them |
| `corpse` | this character. `guildId` and `instanceId` are written as `0` |
| `lfg_data`, `battleground_deserters` | this character |
| `recovery_item` | this character. `Id` is omitted so MySQL assigns a new auto-increment value. `DeleteDate` is omitted and stays `NULL` |

## Tables left out

These rows are shared, account-wide, global, or logs. Copying them would attach this character to somebody else's guild, instance, auction, or match, or it would write a guid that means a different player on the new server.

**Shared with other players.** Left untouched on both servers.

`guild`, `guild_rank`, `guild_member`, `guild_member_withdraw`, `guild_bank_tab`, `guild_bank_item`, `guild_bank_right`, `guild_bank_eventlog`, `guild_eventlog`, `arena_team`, `arena_team_member`, `groups`, `group_member`, `auctionhouse`, `petition`, `petition_sign`, `calendar_events`, `calendar_invites`, `channels`, `channels_bans`, `channels_rights`, `instance`, `instance_reset`, `instance_saved_go_state_data`, `character_instance`, `item_soulbound_trade_data`, `pvpstats_battlegrounds`, `pvpstats_players`.

What that means in play:

* The character is not in their old guild, arena team, or group. Personal arena numbers in `character_arena_stats` still come across. A guild they led is unchanged, because this file never writes `guild`.
* An item listed in `auctionhouse` is left on the old server. Collect auctions before you dump if those items should move. The extractor prints the item guids it left behind.
* `guild_bank_item` stays with the guild. Current cores clear `item_instance.owner_guid` on deposit. If an older row still names the depositor, that item is still left behind, and the extractor prints its guid.
* `item_soulbound_trade_data.allowedPlayers` is a list of other character guids. Those numbers would allow a trade to whoever has that guid now, so the row is omitted. The item itself still moves, without the trade window.
* `character_instance` and the `instance*` tables are server instance ids. `characters.instance_id` is cleared for the same reason.
* `pvpstats_players` is a score line on a shared `pvpstats_battlegrounds` row. The battleground id may already be a different match here. Personal combat numbers are `character_stats` and `character_arena_stats`.
* `petition` / `petition_sign` are a guild or arena charter plus other players' signatures. The charter item in the inventory still moves as an ordinary item.

**Account-wide.** Left on the old account. The destination account keeps its own.

`account_data`, `account_instance_times`, `account_tutorial`.

**Server-global.** The new core and its modules already own these.

`addons`, `banned_addons`, `bugreport`, `chat_filter`, `active_arena_season`, `game_event_save`, `game_event_condition_save`, `creature_respawn`, `gameobject_respawn`, `pool_quest_save`, `profanity_name`, `reserved_name`, `updates`, `updates_include`, `warden_action`, `worldstates`, `world_state`, `mail_server_template`, `mail_server_template_conditions`, `mail_server_template_items`, `mail_server_character`, `playerbots_names`, `playerbots_guild_names`, `playerbots_arena_team_names`.

`mail_server_character` ties a character to a server-mail template id. Those ids are content on the new core, so the link is not copied. `updates` and `updates_include` are how the new core knows which SQL updates it has already applied.

**Logs and staff rows.** Several of these also store another player's IP.

`log_arena_fights`, `log_arena_memberstats`, `log_encounter`, `log_money`, `lag_reports`, `gm_ticket`, `gm_survey`, `gm_subsurvey`, `spam_reports`.

Mail this character sent to someone else stays out. That row is the recipient's inbox. Mail they received is included.

`character_social` rows owned by other people (they had this character as a friend) stay out. Inserting those would edit another character's friend list.

## Guids, items, and the account

The target server already has characters and items. The file only inserts, and it allocates new ids at import time so the old numbers are not reused.

| id | what the file does |
|---|---|
| character guid | `@ac_new_guid` is `1 +` the maximum of every column this import writes a character guid into (`characters.guid`, inventory `guid`, `item_instance.owner_guid`, `character_social.friend`, and the rest). `--new-guid N` stores `N` instead. Either way the script counts existing rows for that number and aborts if any are found |
| item guid | `@ac_item_<old>` is `MAX(item_instance.guid, character_inventory.item, mail_items.item_guid, ...)+n`. Inventory, gifts, mail items, equipment-set slots, refunds, saved container loot, and aura item guids use that variable |
| pet id | `@ac_pet_<old>` from `MAX` of `character_pet.id` and the pet spell/aura tables |
| mail id | `@ac_mail_<old>` from `MAX` of `mail.id` and `mail_items.mail_id` |
| equipment `setguid` | `@ac_set_<old>` from `MAX(character_equipmentsets.setguid)` |
| `recovery_item.Id` | column omitted; MySQL assigns the next auto-increment value |
| account | `--account` replaces `characters.account`. The import checks `acore_auth.account.id` and aborts when that row is missing |

`creatorGuid` / `giftCreatorGuid` stay `@ac_new_guid` when the old value is this character. Any other player guid in those columns is written as `0`, so the item is not credited to whoever now has the old number.

Player mail (`messageType = 0`) whose sender is this character uses `@ac_new_guid` (returned mail). Player mail from someone else is stored with sender `0`, so it does not show as coming from a different character who happens to have that guid. Creature, gameobject, and item mail keep the sender entry.

`character_social.friend` is the one guid that is deliberately left as the old number. The other characters are not in the file, so there is nothing to remap it to. On the new server that number may be a different character. The insert does not change the other character's own friend list. The SQL file repeats this above the `character_social` insert. Delete those lines from the file before import if you would rather arrive with an empty friend list.

The name check is case-insensitive (`LOWER(name)`), which is how the core treats names. The column itself is `utf8mb4_bin`. `Foo` and `foo` both count as taken.

## Schema mapping this file reuses

Rows are zipped with the dump's `CREATE TABLE` column order, then written in MySQL 8.4 order by name. Columns the new table does not have are dropped. Columns only the new table has are omitted so the default applies, except the `NOT NULL` fills in `target_schema/notnull_nodefault.txt` (`characters.innTriggerId`, `character_arena_stats.maxMMR`) when the old row lacks them.

For a character dump the changes that actually rewrite values are:

* `character_homebind.posO` is removed. The value is dropped. The remaining columns stay `guid`, `mapId`, `zoneId`, `posX`, `posY`, `posZ`.
* `quest_tracker.id` NULL is written as `0`. Two rows that collapse onto the new unique key make the `INSERT` fail, and the transaction rolls back.
* `recovery_item.DeleteDate` is new and nullable. It is omitted.

`petition.petition_id` and the `mail_server_template` split are implemented in the shared converter and are not used here, because those tables are left out. The full list of auth, character, world, and playerbots differences is [DIFF_REPORT.md](DIFF_REPORT.md).

## Tests

From this directory:

```bash
python3 tests/test_extract_character.py
python3 tests/test_changed_tables.py
```

`test_extract_character.py` covers selection by guid and by name, the other character's rows staying out, item/mail/pet linkage, guid remap (`--new-guid` and `MAX()+1`), the homebind and quest-tracker transforms, name collisions, and a soft-deleted name. The fixture is `tests/one_character_dump.sql`. `test_changed_tables.py` is the column-mapping check for the shared converter (seventeen checks, fixtures `tests/old_auth.sql` and `tests/old_chars.sql`).

Both are synthetic. Neither talks to MySQL.

## Files

| path | role |
|---|---|
| `extract_character.py` | one character in, one SQL file out |
| `convert_mariadb_to_mysql.py` | shared parser and transforms; also the whole-dump converter |
| `schema_diff.py` | column-level diff of two `--no-data` dumps |
| `DIFF_REPORT.md` | the 2026-11-02 diff |
| `source_schema/` | old column lists and raw diff output |
| `target_schema/` | new auth and characters column lists, plus NOT NULL fills |
| `post_import_characters.sql` | charter enchantment update for a full characters load |
| `playerbots_schema_mysql84.sql` | fallback `CREATE TABLE` for `acore_playerbots` |
| `playerbots_characters_tables_mysql84.sql` | fallback `CREATE TABLE` for the three name tables |
| `tests/` | synthetic checks |

## Whole-database converter

`convert_mariadb_to_mysql.py` still converts an entire `mariadb-dump` into data-only SQL. Use it when you really do want every account and every character. `--truncate` empties each table it writes before inserting, which replaces the new server's rows for those tables. That is the wrong tool for moving one character onto a server that already has people on it.

The dumps and the `new_mysql84_backup.sql` from the steps above are the same backups. Keep them. Do not import `acore_world`; `ac-db-import` already loaded the world this core was built with. The 2026-11-02 world diff is `source_schema/diff_world.txt` (72 tables differ).

From this directory, after the backup:

```bash
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

Skip those tables because they record this core's client builds and which SQL updates have already run. Loading the old rows makes the new core skip migrations or reject the client. Compare counts with `python3 tests/count_rows.py` before importing. The output files contain accounts, SRP verifier blobs, and emails. They are gitignored when written in this directory. Do not commit them.

Import order is auth, then `chars.sql`, then `chars_bots.sql`, then playerbots, each with `--max-allowed-packet=1G`. After `chars.sql`, `post_import_characters.sql` copies `petition_id` onto charter items. It updates only items that join to `petition`. Set `realmlist.address` back to the client IP after an auth import, the same statement as the install guide. The one-character path does not load `realmlist`.

On the 2026-11-02 dumps the Python converter preserved 517 auth rows, 508,887 character rows (496,952 in `chars.sql` plus 11,935 name-table rows), and 1,440,986 playerbots rows. **Those runs were not imported into a live MySQL 8.4 server either.** They are that server's counts, not a target for a different database.

If an import goes wrong, `new_mysql84_backup.sql` is a `--databases` file: replaying it restores every database in it, including auth, characters, and world, to the pre-import snapshot. Dump any database you intend to keep before you replay it.
