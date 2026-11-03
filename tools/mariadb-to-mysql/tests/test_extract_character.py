"""Synthetic tests for extract_character.py. Run: python3 tests/test_extract_character.py"""
import os, re, subprocess, sys, tempfile
os.chdir(os.path.dirname(os.path.abspath(__file__)) + '/..')
sys.path.insert(0, '.')
import convert_mariadb_to_mysql as conv
import extract_character as ex

ok = 0
def check(name, cond):
    global ok
    assert cond, name
    ok += 1
    print('PASS', name)

def run(args):
    r = subprocess.run([sys.executable, 'extract_character.py', *args], capture_output=True, text=True)
    return r

def inserts(sql):
    return re.findall(r'^INSERT INTO `(\w+)` \(([^)]*)\) VALUES\n(.*?);\n', sql, re.S | re.M)

def table_body(sql, table):
    for name, cols, body in inserts(sql):
        if name == table:
            return [c.strip('`') for c in cols.split(',')], body
    raise AssertionError(f'no insert for {table}')

DUMP = 'tests/one_character_dump.sql'
ACCOUNT = '4242'

def extract(guid=None, name=None, new_guid=None, dump=DUMP):
    fd, path = tempfile.mkstemp(suffix='.sql')
    os.close(fd)
    args = ['--dump', dump, '--account', ACCOUNT, '--out', path]
    if guid is not None:
        args += ['--guid', str(guid)]
    if name is not None:
        args += ['--name', name]
    if new_guid is not None:
        args += ['--new-guid', str(new_guid)]
    r = run(args)
    sql = open(path, encoding='utf-8').read()
    os.remove(path)
    return r, sql

r, sql = extract(guid=5, new_guid=5000)
check('guid select exits 0', r.returncode == 0)
rn, sql_name = extract(name='foo', new_guid=5000)
check('name select is case-insensitive and matches guid select', rn.returncode == 0 and sql_name == sql)

tables = [name for name, _cols, _body in inserts(sql)]
check('insert tables are unique', len(tables) == len(set(tables)))
expected = {
    'item_instance', 'characters', 'character_account_data', 'character_achievement',
    'character_achievement_progress', 'character_action', 'character_arena_stats', 'character_aura',
    'character_banned', 'character_battleground_random', 'character_brew_of_the_month',
    'character_declinedname', 'character_entry_point', 'character_equipmentsets', 'character_gifts',
    'character_glyphs', 'character_homebind', 'character_inventory', 'character_pet',
    'character_pet_declinedname', 'character_queststatus', 'character_queststatus_daily',
    'character_queststatus_rewarded', 'character_reputation', 'character_settings', 'character_skills',
    'character_social', 'character_spell', 'character_spell_cooldown', 'character_stats',
    'character_talent', 'battleground_deserters', 'corpse', 'lfg_data', 'item_loot_storage',
    'item_refund_instance', 'mail', 'mail_items', 'pet_aura', 'pet_spell', 'pet_spell_cooldown',
    'quest_tracker', 'recovery_item',
}
check('included rows and no excluded tables', set(tables) == expected)
for banned in ('guild_member', 'arena_team_member', 'group_member', 'auctionhouse', 'character_instance',
               'item_soulbound_trade_data', 'pvpstats_players', 'account_data', 'petition',
               'playerbots_names', 'lag_reports'):
    check(f'no insert into {banned}', banned not in tables)

check('one transaction and plain inserts', sql.count('START TRANSACTION;') == 1 and sql.strip().endswith('COMMIT;')
      and not re.search(r'(?im)^\s*(DELETE|TRUNCATE|REPLACE|UPDATE)\b', sql) and 'INSERT IGNORE' not in sql.upper())
check('name and account preconditions',
      'import_aborted_character_name_already_exists' in sql
      and 'import_aborted_account_not_found' in sql
      and 'import_aborted_character_guid_already_exists' in sql
      and 'FROM `acore_auth`.`account`' in sql
      and "LOWER('Foo')" in sql)

check('fixed guid and auto guid',
      'SET @ac_new_guid := 5000;' in sql)
r_auto, sql_auto = extract(guid=5)
check('auto guid uses MAX()+1', r_auto.returncode == 0 and 'SELECT 1 + GREATEST(' in sql_auto
      and 'SET @ac_new_guid :=' not in sql_auto)

cols, body = table_body(sql, 'characters')
check('characters row remapped, online and instance cleared, innTriggerId filled',
      cols == ['guid', 'account', 'name', 'instance_id', 'instance_mode_mask', 'online', 'innTriggerId']
      and body.strip() == "(@ac_new_guid,4242,'Foo',0,0,0,0)")
check('other character name is absent', "'Bar'" not in sql and '99999' not in sql)

cols, body = table_body(sql, 'character_homebind')
check('homebind drops posO', 'posO' not in cols and cols == ['guid', 'mapId', 'zoneId', 'posX', 'posY', 'posZ']
      and '0.5' not in body and '@ac_new_guid,0,12,-8949.95,-132.493,83.5312' in body)
check('stderr reports dropped posO', 'character_homebind' in r.stderr and 'posO' in r.stderr)

cols, body = table_body(sql, 'item_instance')
check('items remapped; other owners, the auctioned item, and the guild-bank item stay out',
      body.count('@ac_item_100') == 1 and '@ac_item_101' in body and '@ac_item_102' in body
      and '@ac_item_200' not in sql and '@ac_item_300' not in sql and '@ac_item_201' not in sql
      and '@ac_item_400' not in sql)
check('creator guid kept only for this character',
      '(@ac_item_100,6948,@ac_new_guid,@ac_new_guid,0,1)' in body)
check('stderr reports the auctioned item and the guild-bank item',
      'auctioned' in r.stderr and '300' in r.stderr and 'guild-bank' in r.stderr and '400' in r.stderr)

cols, body = table_body(sql, 'character_inventory')
check('inventory links the new item guids',
      '(@ac_new_guid,0,0,@ac_item_100)' in body and '(@ac_new_guid,0,1,@ac_item_101)' in body)

cols, body = table_body(sql, 'character_equipmentsets')
check('equipment set id and item0 remapped, empty slot stays 0',
      '(@ac_new_guid,@ac_set_3,0,\'Set\',\'icon\',0,@ac_item_100,0)' in body)

cols, body = table_body(sql, 'character_gifts')
check('gift item guid remapped', '(@ac_new_guid,@ac_item_100,6948,0)' in body)

cols, body = table_body(sql, 'mail')
check('own mail and creature mail kept; sender from another player cleared',
      '(@ac_mail_4,0,@ac_new_guid,@ac_new_guid,\'Hi\',1)' in body
      and '(@ac_mail_7,0,0,@ac_new_guid,\'FromOther\',0)' in body
      and '(@ac_mail_8,3,12345,@ac_new_guid,\'FromNpc\',0)' in body
      and '@ac_mail_6' not in sql)
cols, body = table_body(sql, 'mail_items')
check('mail item follows the mail and the item',
      body.strip() == '(@ac_mail_4,@ac_item_102,@ac_new_guid)')

cols, body = table_body(sql, 'character_pet')
check('pet id remapped and the other pet is absent',
      '(@ac_pet_7,123,@ac_new_guid,\'Pet\')' in body and '@ac_pet_8' not in sql)
check('pet spell, aura, and cooldown follow the pet',
      table_body(sql, 'pet_spell')[1].strip() == '(@ac_pet_7,401,1)'
      and '(@ac_pet_7,@ac_new_guid,700)' in table_body(sql, 'pet_aura')[1]
      and table_body(sql, 'pet_spell_cooldown')[1].strip() == '(@ac_pet_7,401,15)'
      and '(@ac_pet_7,@ac_new_guid,\'Pet\')' in table_body(sql, 'character_pet_declinedname')[1])

cols, body = table_body(sql, 'character_aura')
check('aura caster and both item-guid shapes remapped',
      '(@ac_new_guid,@ac_new_guid,@ac_item_100,111,1)' in body
      and f'(@ac_new_guid,@ac_new_guid,(@ac_item_101 + {ex.ITEM_GUID_HIGH}),222,1)' in body)

cols, body = table_body(sql, 'character_social')
check('own social row kept with the old friend guid; the reverse row is not copied',
      body.strip() == "(@ac_new_guid,9,1,'note')")

cols, body = table_body(sql, 'quest_tracker')
check('quest_tracker NULL id becomes 0 and guid is remapped',
      body.strip() == "(0,@ac_new_guid,'2024-01-01 00:00:00',NULL,NULL,0,'h','r')")

cols, body = table_body(sql, 'recovery_item')
check('recovery_item id omitted and DeleteDate left out',
      'Id' not in cols and 'DeleteDate' not in cols and body.strip() == '(@ac_new_guid,6948,1)')

cols, body = table_body(sql, 'character_arena_stats')
check('arena stats maxMMR filled', cols[-1] == 'maxMMR' and body.strip() == '(@ac_new_guid,0,1500,0)')

cols, body = table_body(sql, 'corpse')
check('corpse guid remapped and guild/instance cleared', body.strip() == '(@ac_new_guid,0,0,0)')

check('item_loot_storage and refund follow the moved item',
      table_body(sql, 'item_loot_storage')[1].strip() == '(@ac_item_100,2589,1)'
      and '(@ac_item_100,@ac_new_guid,10,0)' in table_body(sql, 'item_refund_instance')[1])

check('spell cooldown item column is an entry, not a guid',
      table_body(sql, 'character_spell_cooldown')[1].strip() == '(@ac_new_guid,133,6948,80)')

# The other character does not pick up Foo's rows.
rb, barb = extract(name='Bar', new_guid=80)
check('Bar select keeps Bar and not Foo', rb.returncode == 0 and "'Bar'" in barb and "'Foo'" not in barb
      and '@ac_item_200' in barb and '@ac_item_100' not in barb and '@ac_mail_6' in barb and '@ac_pet_8' in barb)

missing = run(['--dump', DUMP, '--account', ACCOUNT, '--name', 'Nobody'])
check('unknown name fails', missing.returncode != 0 and 'no character named' in missing.stderr)
bad_guid = run(['--dump', DUMP, '--account', ACCOUNT, '--guid', '404'])
check('unknown guid fails', bad_guid.returncode != 0 and 'no character with guid 404' in bad_guid.stderr)
need_acct = run(['--dump', DUMP, '--guid', '5'])
check('account is required', need_acct.returncode != 0)

amb = tempfile.NamedTemporaryFile('w', suffix='.sql', delete=False)
amb.write("""-- Host: localhost    Database: acore_characters
CREATE TABLE `characters` (`guid` int unsigned NOT NULL, `account` int unsigned NOT NULL, `name` varchar(12) NOT NULL);
INSERT INTO `characters` VALUES (3,7,'Foo'),(4,7,'foo');
""")
amb.close()
amb_r = run(['--dump', amb.name, '--account', ACCOUNT, '--name', 'Foo'])
check('ambiguous name fails and lists guids', amb_r.returncode != 0 and '3' in amb_r.stderr and '4' in amb_r.stderr)
os.remove(amb.name)

soft = tempfile.NamedTemporaryFile('w', suffix='.sql', delete=False)
soft.write("""-- Host: localhost    Database: acore_characters
CREATE TABLE `characters` (`guid` int unsigned NOT NULL, `account` int unsigned NOT NULL, `name` varchar(12) NOT NULL, `deleteInfos_Name` varchar(12) DEFAULT NULL, `deleteDate` int unsigned DEFAULT NULL);
INSERT INTO `characters` VALUES (3,7,'','Zap',100);
""")
soft.close()
soft_r, soft_sql = extract(guid=3, dump=soft.name, new_guid=90)
check('soft-deleted character restores the name and clears deleteDate',
      soft_r.returncode == 0 and "(@ac_new_guid,4242,'Zap',NULL,NULL)" in soft_sql
      and 'deleteInfos_Name' in soft_r.stderr or 'soft-deleted' in soft_sql)
os.remove(soft.name)
# The restored name is what the collision check uses.
check('restored name is the collision check', "LOWER('Zap')" in soft_sql)

wrong_db = tempfile.NamedTemporaryFile('w', suffix='.sql', delete=False)
wrong_db.write("-- Host: localhost    Database: acore_auth\nCREATE TABLE `characters` (`guid` int unsigned NOT NULL);\nINSERT INTO `characters` VALUES (1);\n")
wrong_db.close()
wrong_r = run(['--dump', wrong_db.name, '--account', ACCOUNT, '--guid', '1'])
check('non-character dump is rejected', wrong_r.returncode != 0 and 'acore_auth' in wrong_r.stderr)
os.remove(wrong_db.name)

src = set(conv.load_cols('source_schema/acore_characters.cols'))
tgt = set(conv.load_cols('target_schema/acore_characters.cols'))
known = src | tgt
check('every schema table is included or excluded', known == ex.INCLUDED_TABLES | set(ex.EXCLUDED_TABLES)
      and not (ex.INCLUDED_TABLES & set(ex.EXCLUDED_TABLES)))
readme = open('README.md', encoding='utf-8').read()
missing_names = [t for t in sorted(known) if f'`{t}`' not in readme]
check('README names every character table', missing_names == [])

print(f'{ok} passed')
