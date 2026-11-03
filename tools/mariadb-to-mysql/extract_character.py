#!/usr/bin/env python3
"""Copy one character out of a MariaDB acore_characters dump into SQL for MySQL 8.4.

The dump is the usual mariadb-dump shape: CREATE TABLE (so column order is known)
and extended INSERTs with no column list. Rows are mapped by column name with the
same transforms as convert_mariadb_to_mysql.py. The script never talks to a server.

    python3 extract_character.py --dump old_characters.sql --account 42 --guid 5
    python3 extract_character.py --dump old_characters.sql --account 42 --name Foo

Writes one transactional INSERT script. Character, item, pet, mail, and equipment-set
ids are allocated from MAX()+1 at import time (or the character guid is fixed with
--new-guid). Existing rows are not deleted or updated.
"""
import argparse, io, os, re, sys
import convert_mariadb_to_mysql as conv

DB = 'acore_characters'
# HighGuid::Item << 48. character_aura.itemGuid stores ObjectGuid::GetRawValue().
ITEM_GUID_HIGH = 0x4000 << 48

# table -> column that holds this character's low guid. A row is kept when that
# column equals the source guid. Player::DeleteFromDB removes these by the same key
# (see CHAR_DEL_* in AzerothCore CharacterDatabase.cpp), plus the link tables below.
CHAR_TABLES = {
    'characters': 'guid',
    'character_account_data': 'guid',
    'character_achievement': 'guid',
    'character_achievement_offline_updates': 'guid',
    'character_achievement_progress': 'guid',
    'character_action': 'guid',
    'character_arena_stats': 'guid',
    'character_aura': 'guid',
    'character_banned': 'guid',
    'character_battleground_random': 'guid',
    'character_brew_of_the_month': 'guid',
    'character_declinedname': 'guid',
    'character_entry_point': 'guid',
    'character_equipmentsets': 'guid',
    'character_gifts': 'guid',
    'character_glyphs': 'guid',
    'character_homebind': 'guid',
    'character_inventory': 'guid',
    'character_pet': 'owner',
    'character_pet_declinedname': 'owner',
    'character_queststatus': 'guid',
    'character_queststatus_daily': 'guid',
    'character_queststatus_monthly': 'guid',
    'character_queststatus_rewarded': 'guid',
    'character_queststatus_seasonal': 'guid',
    'character_queststatus_weekly': 'guid',
    'character_reputation': 'guid',
    'character_settings': 'guid',
    'character_skills': 'guid',
    'character_social': 'guid',
    'character_spell': 'guid',
    'character_spell_cooldown': 'guid',
    'character_stats': 'guid',
    'character_talent': 'guid',
    'corpse': 'guid',
    'battleground_deserters': 'guid',
    'lfg_data': 'guid',
    'mail': 'receiver',
    'mail_items': 'receiver',
    'item_refund_instance': 'player_guid',
    'quest_tracker': 'character_guid',
    'recovery_item': 'Guid',
}

# Selected by the pet id collected from character_pet / character_pet_declinedname.
PET_TABLES = {
    'pet_aura': 'guid',
    'pet_spell': 'guid',
    'pet_spell_cooldown': 'guid',
}

INCLUDED_TABLES = frozenset(CHAR_TABLES) | frozenset(PET_TABLES) | frozenset({
    'item_instance', 'item_loot_storage',
})

# Auto-increment primary keys that nothing else points at. Omitting them lets MySQL
# assign a free id so a source id cannot collide.
OMIT_COLUMNS = {('recovery_item', 'Id')}

# Columns that store a character low guid but are not how we select the row.
# The new character guid must not match any existing value here, or an orphan row
# already on the target would start pointing at the imported character.
EXTRA_CHAR_GUID_COLS = (
    ('item_instance', 'owner_guid'),
    ('item_instance', 'creatorGuid'),
    ('item_instance', 'giftCreatorGuid'),
    ('character_social', 'friend'),
)

# Item low guids we insert. MAX()+1 has to clear every primary key we write.
ITEM_GUID_COLS = (
    ('item_instance', 'guid'),
    ('character_inventory', 'item'),
    ('mail_items', 'item_guid'),
    ('character_gifts', 'item_guid'),
    ('item_refund_instance', 'item_guid'),
    ('item_loot_storage', 'containerGUID'),
)
PET_ID_COLS = (
    ('character_pet', 'id'),
    ('character_pet_declinedname', 'id'),
    ('pet_spell', 'guid'),
    ('pet_aura', 'guid'),
    ('pet_spell_cooldown', 'guid'),
)
MAIL_ID_COLS = (
    ('mail', 'id'),
    ('mail_items', 'mail_id'),
)
SET_ID_COLS = (
    ('character_equipmentsets', 'setguid'),
)

# Kept out of the file on purpose. Keys are the reason groups documented in README.md.
EXCLUDED_TABLES = {
    'guild': 'shared',
    'guild_bank_eventlog': 'shared',
    'guild_bank_item': 'shared',
    'guild_bank_right': 'shared',
    'guild_bank_tab': 'shared',
    'guild_eventlog': 'shared',
    'guild_member': 'shared',
    'guild_member_withdraw': 'shared',
    'guild_rank': 'shared',
    'arena_team': 'shared',
    'arena_team_member': 'shared',
    'groups': 'shared',
    'group_member': 'shared',
    'auctionhouse': 'shared',
    'petition': 'shared',
    'petition_sign': 'shared',
    'calendar_events': 'shared',
    'calendar_invites': 'shared',
    'channels': 'shared',
    'channels_bans': 'shared',
    'channels_rights': 'shared',
    'instance': 'shared',
    'instance_reset': 'shared',
    'instance_saved_go_state_data': 'shared',
    'character_instance': 'shared',
    'item_soulbound_trade_data': 'shared',
    'pvpstats_battlegrounds': 'shared',
    'pvpstats_players': 'shared',
    'account_data': 'account',
    'account_instance_times': 'account',
    'account_tutorial': 'account',
    'addons': 'global',
    'banned_addons': 'global',
    'bugreport': 'global',
    'chat_filter': 'global',
    'game_event_condition_save': 'global',
    'game_event_save': 'global',
    'creature_respawn': 'global',
    'gameobject_respawn': 'global',
    'pool_quest_save': 'global',
    'profanity_name': 'global',
    'reserved_name': 'global',
    'updates': 'global',
    'updates_include': 'global',
    'warden_action': 'global',
    'worldstates': 'global',
    'world_state': 'global',
    'active_arena_season': 'global',
    'mail_server_template': 'global',
    'mail_server_template_conditions': 'global',
    'mail_server_template_items': 'global',
    'mail_server_character': 'global',
    'playerbots_arena_team_names': 'global',
    'playerbots_guild_names': 'global',
    'playerbots_names': 'global',
    'log_arena_fights': 'log',
    'log_arena_memberstats': 'log',
    'log_encounter': 'log',
    'log_money': 'log',
    'lag_reports': 'log',
    'gm_ticket': 'log',
    'gm_survey': 'log',
    'gm_subsurvey': 'log',
    'spam_reports': 'log',
}

TAIL_ORDER = (
    'character_pet', 'character_pet_declinedname',
    'pet_aura', 'pet_spell', 'pet_spell_cooldown',
    'mail', 'mail_items',
    'item_loot_storage', 'item_refund_instance',
)


def die(msg):
    print(f'extract_character: {msg}', file=sys.stderr)
    raise SystemExit(1)


def sql_unquote(literal):
    if literal is None:
        return None
    s = literal.strip()
    if s.upper() == 'NULL':
        return None
    if len(s) < 2 or s[0] != "'" or s[-1] != "'":
        return None
    body = s[1:-1]
    out = []
    i = 0
    while i < len(body):
        if body[i] == '\\' and i + 1 < len(body):
            out.append(body[i + 1])
            i += 2
            continue
        if body[i:i + 2] == "''":
            out.append("'")
            i += 2
            continue
        out.append(body[i])
        i += 1
    return ''.join(out)


def norm_name(literal):
    text = sql_unquote(literal)
    return '' if text is None else text.casefold()


def lit_int(row, col):
    if col not in row or row[col] is None:
        return None
    return conv._int(row[col])


def add_id(bucket, value):
    if value:
        bucket.add(value)


def char_guid_columns():
    cols = list(CHAR_TABLES.items()) + list(EXTRA_CHAR_GUID_COLS)
    seen = set()
    out = []
    for pair in cols:
        if pair not in seen:
            seen.add(pair)
            out.append(pair)
    return out


def emit_order():
    head = ('item_instance', 'characters')
    skip = set(head) | set(TAIL_ORDER)
    mid = sorted(t for t in INCLUDED_TABLES if t not in skip)
    return list(head) + mid + [t for t in TAIL_ORDER if t in INCLUDED_TABLES]


def scan_inserts(path, src, tables):
    """Stream the dump. CREATE TABLE always updates `src`. Only `tables` are split into rows."""
    with open(path, encoding='utf-8', errors='surrogateescape') as f:
        for stmt in conv.statements(f):
            head = stmt[:30].upper()
            if head.startswith('CREATE TABLE'):
                table, cols = conv.create_cols(stmt)
                if table:
                    src[table] = cols
                continue
            if not head.startswith('INSERT'):
                continue
            parsed = conv.parse_insert(stmt)
            if not parsed:
                die('could not parse an INSERT (re-export; do not split the dump by line): '
                    + stmt[:180].replace('\n', ' '))
            table, collist, body = parsed
            if table not in tables:
                continue
            if not body.strip():
                continue
            if collist:
                scols = [c.strip().strip('`') for c in collist.strip('()').split(',')]
            else:
                scols = src.get(table)
            if not scols:
                die(f'{table}: INSERT has no column list and the dump has no CREATE TABLE for it')
            for values in conv.split_tuples(body):
                yield table, scols, values


def load_target():
    path = os.path.join(conv.HERE, 'target_schema', f'{DB}.cols')
    if not os.path.exists(path):
        die(f'missing target schema {path}')
    return conv.load_cols(path)


def prepare(table, scols, values, fills):
    extra = []
    row, filled = conv.prepare_row(DB, table, scols, values, fills, extra)
    if row is None:
        die(f'{table}: a row has {len(values)} values but {len(scols)} columns')
    if extra:
        die(f'{table}: transform produced child rows; this tool does not import those')
    return row, filled


def load_characters(path, src, fills):
    found = []
    if conv.detect_db(path) not in (None, DB):
        die(f'{path} is database {conv.detect_db(path)}; this tool only reads {DB}')
    for table, scols, values in scan_inserts(path, src, {'characters'}):
        row, _filled = prepare(table, scols, values, fills)
        found.append(row)
    if 'characters' not in src:
        die('dump has no CREATE TABLE `characters` (re-export without --no-create-info)')
    if not found:
        die('dump has no rows in `characters`')
    return found


def select_character(chars, guid, name):
    if guid is not None:
        hits = [c for c in chars if lit_int(c, 'guid') == guid]
        if not hits:
            die(f'no character with guid {guid}')
        if len(hits) > 1:
            die(f'guid {guid} matched {len(hits)} character rows')
        return hits[0]
    want = name.casefold()
    hits = [c for c in chars if norm_name(c.get('name')) == want]
    if not hits:
        deleted = [c for c in chars
                   if norm_name(c.get('name')) == '' and norm_name(c.get('deleteInfos_Name')) == want]
        if deleted:
            guids = [lit_int(c, 'guid') for c in deleted]
            die(f'no live character named {name!r}; guid(s) {guids} only have that name in '
                f'deleteInfos_Name (soft-deleted). Pass --guid to import one of them')
        die(f'no character named {name!r}')
    if len(hits) > 1:
        guids = [lit_int(c, 'guid') for c in hits]
        die(f'name {name!r} matches {len(hits)} characters (guids {guids}); pass --guid')
    return hits[0]


def collect_keys(path, src, fills, guid):
    owned, auction, guild_bank, referenced = set(), set(), set(), set()
    pet_ids, mail_ids, set_ids = set(), set(), set()
    # Auction and guild-bank rows are shared. They are read only to keep those items out.
    tables = set(CHAR_TABLES) | {'item_instance', 'auctionhouse', 'guild_bank_item'}
    for table, scols, values in scan_inserts(path, src, tables):
        row, _filled = prepare(table, scols, values, fills)
        if table == 'auctionhouse':
            if lit_int(row, 'itemowner') == guid:
                add_id(auction, lit_int(row, 'itemguid'))
            continue
        if table == 'guild_bank_item':
            # Deposit clears owner_guid on current cores. Older rows can still name the depositor.
            add_id(guild_bank, lit_int(row, 'item_guid'))
            continue
        if table == 'item_instance':
            if lit_int(row, 'owner_guid') == guid:
                add_id(owned, lit_int(row, 'guid'))
            continue
        if lit_int(row, CHAR_TABLES[table]) != guid:
            continue
        if table == 'character_inventory':
            add_id(referenced, lit_int(row, 'item'))
        elif table == 'character_gifts':
            add_id(referenced, lit_int(row, 'item_guid'))
        elif table == 'mail_items':
            add_id(referenced, lit_int(row, 'item_guid'))
        elif table == 'mail':
            add_id(mail_ids, lit_int(row, 'id'))
        elif table == 'character_pet':
            add_id(pet_ids, lit_int(row, 'id'))
        elif table == 'character_pet_declinedname':
            add_id(pet_ids, lit_int(row, 'id'))
        elif table == 'item_refund_instance':
            add_id(referenced, lit_int(row, 'item_guid'))
        elif table == 'character_equipmentsets':
            add_id(set_ids, lit_int(row, 'setguid'))
            for i in range(19):
                add_id(referenced, lit_int(row, f'item{i}'))
    wanted = set(referenced)
    for gid in owned:
        if gid not in auction and gid not in guild_bank:
            wanted.add(gid)
    # A guild-bank slot wins over a bag link. The item is the guild's.
    wanted -= guild_bank
    return {
        'wanted': wanted,
        'owned': owned,
        'auction': auction,
        'guild_bank': guild_bank,
        'referenced': referenced,
        'pet_ids': pet_ids,
        'mail_ids': mail_ids,
        'set_ids': set_ids,
    }


def load_rows(path, src, fills, guid, keys):
    rows = {t: [] for t in INCLUDED_TABLES}
    filled = {}
    wanted, pet_ids = keys['wanted'], keys['pet_ids']
    for table, scols, values in scan_inserts(path, src, INCLUDED_TABLES):
        row, filled_cols = prepare(table, scols, values, fills)
        keep = False
        if table == 'item_instance':
            keep = lit_int(row, 'guid') in wanted
        elif table == 'item_loot_storage':
            keep = lit_int(row, 'containerGUID') in wanted
        elif table in PET_TABLES:
            keep = lit_int(row, PET_TABLES[table]) in pet_ids
        elif table in CHAR_TABLES:
            keep = lit_int(row, CHAR_TABLES[table]) == guid
        if not keep:
            continue
        if filled_cols:
            filled.setdefault(table, set()).update(filled_cols)
        rows[table].append(row)
    return rows, filled


def require_unique(rows, table, col):
    seen = set()
    for row in rows:
        value = lit_int(row, col)
        if value in seen:
            die(f'{table} has two rows with {col}={value} for this character')
        seen.add(value)


class Alloc:
    def __init__(self, ids, prefix):
        self.ids = {i for i in ids if i}
        self.expr = {i: f'@ac_{prefix}_{i}' for i in sorted(self.ids)}

    def of(self, value):
        try:
            return self.expr[value]
        except KeyError:
            die(f'internal: no id variable for {value}')


def rewrite_caster(literal, old_guid):
    raw = conv._int(literal) if literal is not None else None
    if raw is None:
        return literal
    if raw == 0:
        return '0'
    high = (raw >> 48) & 0xFFFF
    low = raw & 0xFFFFFFFF
    # Local players use HighGuid::Player (0), so the raw guid is the low guid,
    # or the low guid with a realm id in bits 32-47. Creature casters keep their value.
    if high == 0 and low == old_guid:
        return '@ac_new_guid'
    return literal


def rewrite_aura_item(literal, items, warnings):
    raw = conv._int(literal) if literal is not None else None
    if raw is None:
        return literal
    if raw == 0:
        return '0'
    high = (raw >> 48) & 0xFFFF
    low = raw & 0xFFFFFFFF
    if low in items.ids and high in (0, 0x4000):
        if high == 0x4000:
            return f'({items.of(low)} + {ITEM_GUID_HIGH})'
        return items.of(low)
    warnings.append(f'cleared an aura itemGuid {raw}; that item is not moving with this character')
    return '0'


def final_name_literal(row):
    if sql_unquote(row.get('name')):
        return row['name'], False
    restored = row.get('deleteInfos_Name')
    if sql_unquote(restored):
        return restored, True
    return None, False


def rewrite(table, row, ctx):
    row = dict(row)
    owner = CHAR_TABLES.get(table)
    if owner:
        row[owner] = '@ac_new_guid'
    if table == 'characters':
        name_lit, restored = final_name_literal(row)
        if not name_lit:
            die(f'character guid {ctx.old_guid} has an empty name and no deleteInfos_Name; refusing to import it')
        if restored:
            ctx.restored_name = sql_unquote(name_lit)
        row['name'] = name_lit
        ctx.name_literal = name_lit
        row['account'] = str(ctx.account)
        if 'online' in row:
            row['online'] = '0'
        # Old instance ids belong to the old server's instance table, which is not copied.
        if 'instance_id' in row:
            row['instance_id'] = '0'
        if 'instance_mode_mask' in row:
            row['instance_mode_mask'] = '0'
        for col in ('deleteDate', 'deleteInfos_Account', 'deleteInfos_Name'):
            if col in row:
                row[col] = 'NULL'
        return row
    if table == 'item_instance':
        gid = lit_int(row, 'guid')
        row['guid'] = ctx.items.of(gid)
        row['owner_guid'] = '@ac_new_guid'
        for col in ('creatorGuid', 'giftCreatorGuid'):
            if col not in row:
                continue
            row[col] = '@ac_new_guid' if lit_int(row, col) == ctx.old_guid else '0'
        return row
    if table == 'character_inventory':
        gid = lit_int(row, 'item')
        if gid not in ctx.items.ids:
            if gid in ctx.guild_bank:
                ctx.warnings.append(f'skipped an inventory slot; item {gid} is in the guild bank')
            else:
                ctx.warnings.append(f'skipped an inventory slot; item {gid} has no item_instance row')
            return None
        row['item'] = ctx.items.of(gid)
        return row
    if table == 'character_gifts':
        gid = lit_int(row, 'item_guid')
        if gid not in ctx.items.ids:
            ctx.warnings.append(f'skipped character_gifts for missing item {gid}')
            return None
        row['item_guid'] = ctx.items.of(gid)
        return row
    if table == 'mail':
        row['id'] = ctx.mails.of(lit_int(row, 'id'))
        if 'messageType' not in row:
            ctx.warnings.append('a mail row has no messageType; sender was left as dumped')
            return row
        if lit_int(row, 'messageType') == 0:
            sender = lit_int(row, 'sender')
            # Other players' guids would name whoever now has that guid. Blank those.
            row['sender'] = '@ac_new_guid' if sender == ctx.old_guid else '0'
        return row
    if table == 'mail_items':
        mid = lit_int(row, 'mail_id')
        gid = lit_int(row, 'item_guid')
        if mid not in ctx.mail_ids:
            ctx.warnings.append(f'skipped mail_items for mail {mid}; that mail is not in the dump')
            return None
        if gid not in ctx.items.ids:
            ctx.warnings.append(f'skipped mail_items for missing item {gid}')
            return None
        row['mail_id'] = ctx.mails.of(mid)
        row['item_guid'] = ctx.items.of(gid)
        return row
    if table == 'character_equipmentsets':
        row['setguid'] = ctx.sets.of(lit_int(row, 'setguid'))
        for i in range(19):
            col = f'item{i}'
            if col not in row:
                continue
            gid = lit_int(row, col) or 0
            if gid == 0:
                row[col] = '0'
            elif gid in ctx.items.ids:
                row[col] = ctx.items.of(gid)
            else:
                row[col] = '0'
                ctx.warnings.append(f'cleared equipment set {col}; item {gid} is not moving')
        return row
    if table == 'character_pet':
        row['id'] = ctx.pets.of(lit_int(row, 'id'))
        return row
    if table == 'character_pet_declinedname':
        row['id'] = ctx.pets.of(lit_int(row, 'id'))
        return row
    if table in PET_TABLES:
        row['guid'] = ctx.pets.of(lit_int(row, 'guid'))
        if table == 'pet_aura' and 'casterGuid' in row:
            row['casterGuid'] = rewrite_caster(row['casterGuid'], ctx.old_guid)
        return row
    if table == 'character_aura':
        if 'casterGuid' in row:
            row['casterGuid'] = rewrite_caster(row['casterGuid'], ctx.old_guid)
        if 'itemGuid' in row:
            row['itemGuid'] = rewrite_aura_item(row['itemGuid'], ctx.items, ctx.warnings)
        return row
    if table == 'character_social':
        friend = lit_int(row, 'friend')
        if friend == ctx.old_guid:
            row['friend'] = '@ac_new_guid'
        return row
    if table == 'corpse':
        if 'guildId' in row:
            row['guildId'] = '0'
        if 'instanceId' in row:
            row['instanceId'] = '0'
        return row
    if table == 'item_loot_storage':
        gid = lit_int(row, 'containerGUID')
        if gid not in ctx.items.ids:
            ctx.warnings.append(f'skipped item_loot_storage for missing container {gid}')
            return None
        row['containerGUID'] = ctx.items.of(gid)
        return row
    if table == 'item_refund_instance':
        gid = lit_int(row, 'item_guid')
        if gid not in ctx.items.ids:
            ctx.warnings.append(f'skipped item_refund_instance for missing item {gid}')
            return None
        row['item_guid'] = ctx.items.of(gid)
        return row
    return row


def greatest_expr(pairs):
    parts = [f"IFNULL((SELECT MAX(`{col}`) FROM `{table}`),0)" for table, col in pairs]
    if len(parts) == 1:
        return parts[0]
    return 'GREATEST(' + ', '.join(parts) + ')'


def emit_check(out, condition_ok, procedure):
    out.write(f"SET @ac_sql := IF({condition_ok}, 'DO 0', 'CALL `{procedure}`()');\n")
    out.write('PREPARE ac_check FROM @ac_sql;\nEXECUTE ac_check;\nDEALLOCATE PREPARE ac_check;\n')


def emit_alloc(out, base_name, pairs, alloc):
    if not alloc.ids:
        return
    out.write(f'SELECT {greatest_expr(pairs)} INTO {base_name};\n')
    for n, old in enumerate(sorted(alloc.ids), start=1):
        out.write(f'SET {alloc.expr[old]} := {base_name} + {n};\n')


def emit_insert(out, table, cols, tuples):
    colsql = ','.join(f'`{c}`' for c in cols)
    body = ',\n'.join('(' + ','.join(vals) + ')' for vals in tuples)
    out.write(f'INSERT INTO `{table}` ({colsql}) VALUES\n{body};\n')


def build_sql(ctx, rows, target, dropped):
    buf = io.StringIO()
    w = buf.write
    name = sql_unquote(ctx.name_literal) or ''
    w('-- One character from a MariaDB acore_characters dump, column-mapped for MySQL 8.4.\n')
    w(f'-- Source guid {ctx.old_guid}, name {ctx.name_literal}. Imports onto account {ctx.account}.\n')
    if ctx.new_guid is None:
        w('-- @ac_new_guid and item, pet, mail, and equipment-set ids are MAX(existing)+1 at import.\n')
    else:
        w(f'-- Character guid is fixed at {ctx.new_guid} (--new-guid). Other ids are still MAX(existing)+1.\n')
    w('-- Inserts only. No DELETE, UPDATE, REPLACE, or TRUNCATE.\n')
    w('-- Stop ac-worldserver before importing so its guid counter cannot race this file.\n')
    w('-- Do not pass --force. The first error stops the mysql client and the open transaction\n')
    w('-- rolls back when the client disconnects.\n')
    if ctx.restored_name:
        w(f'-- Source row was soft-deleted. Name restored from deleteInfos_Name ({ctx.name_literal}) and deleteDate cleared.\n')
    w('\n')
    w("SET NAMES utf8mb4;\nSET time_zone='+00:00';\nSET autocommit=0;\nSTART TRANSACTION;\n\n")
    w(f'SELECT COUNT(*) INTO @ac_acct FROM `acore_auth`.`account` WHERE `id` = {ctx.account};\n')
    w(f'SELECT COUNT(*) INTO @ac_name_taken FROM `characters` WHERE LOWER(`name`) = LOWER({ctx.name_literal});\n')
    if ctx.new_guid is None:
        w(f'SELECT 1 + {greatest_expr(char_guid_columns())} INTO @ac_new_guid;\n')
    else:
        w(f'SET @ac_new_guid := {ctx.new_guid};\n')
    taken_terms = ' + '.join(
        f'(SELECT COUNT(*) FROM `{table}` WHERE `{col}` = @ac_new_guid)'
        for table, col in char_guid_columns())
    w(f'SELECT {taken_terms} INTO @ac_guid_taken;\n\n')
    emit_check(buf, '@ac_acct = 1', 'import_aborted_account_not_found')
    emit_check(buf, '@ac_name_taken = 0', 'import_aborted_character_name_already_exists')
    emit_check(buf, '@ac_guid_taken = 0', 'import_aborted_character_guid_already_exists')
    w('\n')
    emit_alloc(buf, '@ac_item_base', ITEM_GUID_COLS, ctx.items)
    emit_alloc(buf, '@ac_pet_base', PET_ID_COLS, ctx.pets)
    emit_alloc(buf, '@ac_mail_base', MAIL_ID_COLS, ctx.mails)
    emit_alloc(buf, '@ac_set_base', SET_ID_COLS, ctx.sets)
    w('\n')

    for table in emit_order():
        projected = []
        cols = None
        for row in rows.get(table) or []:
            use = {k: v for k, v in row.items() if (table, k) not in OMIT_COLUMNS}
            if table not in target:
                die(f'{table} is not in the bundled MySQL 8.4 character schema')
            tcols, vals, drop = conv.project_row(use, target[table])
            if drop:
                dropped.setdefault(table, set()).update(drop)
            if cols is None:
                cols = tcols
            elif tcols != cols:
                die(f'{table}: rows disagree on columns after mapping')
            projected.append(vals)
        if not projected:
            continue
        if table == 'character_social':
            w('-- character_social.friend is the guid from the OLD server. It is not remapped\n')
            w('-- (other characters are not in this file). On the new server that number may be\n')
            w('-- a different character. The row does not change anyone else\'s friend list.\n')
        emit_insert(buf, table, cols, projected)
    w('\nCOMMIT;\n')
    return buf.getvalue()


class Ctx:
    def __init__(self, old_guid, account, new_guid):
        self.old_guid = old_guid
        self.account = account
        self.new_guid = new_guid
        self.warnings = []
        self.restored_name = None
        self.name_literal = None
        self.items = None
        self.pets = None
        self.mails = None
        self.sets = None
        self.mail_ids = set()
        self.guild_bank = set()


def default_out(guid, name_literal):
    text = sql_unquote(name_literal) or str(guid)
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', text).strip('._') or str(guid)
    return f'character_{guid}_{safe}.sql'


def extract(dump, account, guid=None, name=None, new_guid=None, out_path=None):
    fills = conv.load_fills(DB)
    target = load_target()
    src = {}
    chars = load_characters(dump, src, fills)
    chosen = select_character(chars, guid, name)
    old_guid = lit_int(chosen, 'guid')
    if not old_guid:
        die('selected character has no usable guid')
    keys = collect_keys(dump, src, fills, old_guid)
    stored, filled = load_rows(dump, src, fills, old_guid, keys)
    if len(stored['characters']) != 1:
        die(f'expected one characters row, found {len(stored["characters"])}')
    require_unique(stored['item_instance'], 'item_instance', 'guid')
    require_unique(stored['character_pet'], 'character_pet', 'id')
    require_unique(stored['mail'], 'mail', 'id')
    require_unique(stored['character_equipmentsets'], 'character_equipmentsets', 'setguid')

    present = {lit_int(r, 'guid') for r in stored['item_instance']}
    missing = sorted(keys['wanted'] - present)
    ctx = Ctx(old_guid, account, new_guid)
    for gid in missing:
        ctx.warnings.append(f'item {gid} is referenced but has no item_instance row; links to it were dropped or cleared')
    auction_left = sorted((keys['owned'] & keys['auction']) - keys['wanted'] - keys['guild_bank'])
    if auction_left:
        ctx.warnings.append(f'left {len(auction_left)} auctioned item(s) on the old server (not copied): {auction_left}')
    bank_left = sorted((keys['owned'] | keys['referenced']) & keys['guild_bank'])
    if bank_left:
        ctx.warnings.append(f'left {len(bank_left)} guild-bank item(s) on the old server (not copied): {bank_left}')
    ctx.guild_bank = keys['guild_bank']
    ctx.items = Alloc(present, 'item')
    ctx.pets = Alloc(keys['pet_ids'], 'pet')
    ctx.mails = Alloc({lit_int(r, 'id') for r in stored['mail']}, 'mail')
    ctx.sets = Alloc({lit_int(r, 'setguid') for r in stored['character_equipmentsets']}, 'set')
    ctx.mail_ids = set(ctx.mails.ids)

    rewritten = {}
    for table, table_rows in stored.items():
        kept = []
        for row in table_rows:
            new = rewrite(table, row, ctx)
            if new is not None:
                kept.append(new)
        rewritten[table] = kept
    if not ctx.name_literal:
        die('character name was not resolved')
    dropped = {}
    sql = build_sql(ctx, rewritten, target, dropped)
    dest = out_path or default_out(old_guid, ctx.name_literal)
    with open(dest, 'w', encoding='utf-8', errors='surrogateescape') as f:
        f.write(sql)
    counts = {t: len(v) for t, v in rewritten.items() if v}
    def n(count, word):
        return f'{count} {word}' if count == 1 else f'{count} {word}s'
    print(f'extract_character: guid {old_guid} name {ctx.name_literal} account {account} '
          f'-> {dest} ({n(sum(counts.values()), "row")}, {n(len(ctx.items.ids), "item")}, '
          f'{n(len(ctx.pets.ids), "pet")}, {n(len(ctx.mails.ids), "mail")})', file=sys.stderr)
    for table, cols in sorted(dropped.items()):
        print(f'  dropped old-only columns {table}: {sorted(cols)}', file=sys.stderr)
    for table, cols in sorted(filled.items()):
        sample = rewritten.get(table) or []
        if not sample:
            continue
        present_cols = sorted(c for c in cols if c in sample[0])
        if present_cols:
            print(f'  filled new NOT NULL columns {table}: {present_cols}', file=sys.stderr)
    for msg in ctx.warnings:
        print(f'  {msg}', file=sys.stderr)
    return dest


def main():
    ap = argparse.ArgumentParser(description='Extract one AzerothCore character from a MariaDB acore_characters dump.')
    ap.add_argument('--dump', required=True, help='mariadb-dump of acore_characters (with CREATE TABLE)')
    ap.add_argument('--account', required=True, type=int, help='account id on the NEW acore_auth that should own the character')
    sel = ap.add_mutually_exclusive_group(required=True)
    sel.add_argument('--guid', type=int, help='characters.guid on the old server')
    sel.add_argument('--name', help='characters.name on the old server (case-insensitive)')
    ap.add_argument('--new-guid', type=int, help='force the character guid instead of MAX(guid)+1')
    ap.add_argument('--out', help='output SQL path (default: ./character_<guid>_<name>.sql)')
    a = ap.parse_args()
    if a.account <= 0 or a.account > 0xFFFFFFFF:
        ap.error('--account must be a positive account id')
    if a.guid is not None and a.guid <= 0:
        ap.error('--guid must be a positive character guid')
    if a.name is not None and not a.name:
        ap.error('--name must not be empty')
    if a.new_guid is not None and (a.new_guid <= 0 or a.new_guid > 0xFFFFFFFF):
        ap.error('--new-guid must be a positive character guid')
    if not os.path.isfile(a.dump):
        die(f'no such dump {a.dump}')
    extract(a.dump, a.account, guid=a.guid, name=a.name, new_guid=a.new_guid, out_path=a.out)


if __name__ == '__main__':
    main()
