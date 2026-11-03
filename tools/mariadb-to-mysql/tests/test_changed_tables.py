"""Synthetic tests: one per changed table. Run: python3 tests/test_changed_tables.py"""
import subprocess, sys, re, os
os.chdir(os.path.dirname(os.path.abspath(__file__)) + '/..')
def conv(src, *args):
    r = subprocess.run([sys.executable, 'convert_mariadb_to_mysql.py', src, '/tmp/_t.sql', *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return open('/tmp/_t.sql').read()
def ins(sql, t):
    m = re.search(r'INTO `%s` \(([^)]*)\) VALUES\n(.*?);\n' % t, sql, re.S)
    assert m, f'no insert for {t}'
    return [x.strip('`') for x in m.group(1).split(',')], m.group(2).split(',\n')
ok = 0
def check(name, cond):
    global ok; assert cond, name; ok += 1; print('PASS', name)
a = conv('tests/old_auth.sql')
cols, rows = ins(a, 'account')
check('account: no Flags in list (server default 0), locale 3->deDE, 8->ruRU', 'Flags' not in cols and "'deDE'" in rows[0] and "'ruRU'" in rows[1])
check('account: value count == column count', all(len(r.strip('()').split(',')) >= len(cols) for r in rows))
check('account: empty INSERT stub dropped, sandbox line dropped', 'VALUES ;' not in a and 'M!999999' not in a)
cols, _ = ins(a, 'uptime'); check('uptime: explicit 5 old columns, new ones defaulted', cols == ['realmid','starttime','uptime','maxplayers','revision'])
cols, _ = ins(a, 'motd'); check('motd: realmid,text', cols == ['realmid','text'])
c = conv('tests/old_chars.sql')
cols, _ = ins(c, 'bugreport'); check('bugreport: id,type,content only', cols == ['id','type','content'])
cols, rows = ins(c, 'character_homebind'); check('character_homebind: posO dropped', 'posO' not in cols and rows[0].count(',') == 5)
cols, rows = ins(c, 'mail_server_template'); check('mail_server_template: req*/item* removed', cols == ['id','moneyA','moneyH','subject','body','active'])
_, rows = ins(c, 'mail_server_template_items'); check('mail_server_template_items: A+H rows derived', rows == ["(1,'Alliance',6948,1)", "(1,'Horde',6948,2)"])
_, rows = ins(c, 'mail_server_template_conditions'); check('mail_server_template_conditions: Level+PlayTime derived', rows == ["(1,'Level',10)", "(2,'PlayTime',3600000)"])
check('mail_server_template emitted before its child tables (FK order)', c.index('`mail_server_template` (') < c.index('`mail_server_template_items`'))
cols, rows = ins(c, 'petition'); check('petition: petition_id after petitionguid, 31-bit formula', cols[2] == 'petition_id' and rows[0].startswith('(5,777,777,') and '(6,3000000000,852516352,' in rows[1])
cols, rows = ins(c, 'petition_sign'); check('petition_sign: petition_id filled', cols[2] == 'petition_id' and rows[0] == '(5,777,777,8,2,9)')
cols, _ = ins(c, 'recovery_item'); check('recovery_item: DeleteDate left NULL', 'DeleteDate' not in cols)
_, rows = ins(c, 'quest_tracker'); check('quest_tracker: NULL id -> 0', rows[0].startswith('(0,'))
check('playerbots_names skipped in characters run', 'playerbots_names' not in c)
p = conv('tests/old_chars.sql', '--no-embedded', '--only-tables', 'playerbots_names')
check('playerbots_names via --only-tables', "INTO `playerbots_names` (`name_id`,`name`,`gender`,`in_use`)" in p)
world, world_out = '/tmp/_acore_world_archive.sql', '/tmp/_acore_world_out.sql'
if os.path.exists(world_out): os.remove(world_out)
open(world, 'w').write("-- Host: localhost    Database: acore_world\n"
                       "CREATE TABLE `creature` (`guid` int unsigned NOT NULL);\n"
                       "INSERT INTO `creature` VALUES (1);\n")
r = subprocess.run([sys.executable, 'convert_mariadb_to_mysql.py', world, world_out], capture_output=True, text=True)
r_db = subprocess.run([sys.executable, 'convert_mariadb_to_mysql.py', 'tests/old_auth.sql', world_out, '--db', 'acore_world'], capture_output=True, text=True)
r_override = subprocess.run([sys.executable, 'convert_mariadb_to_mysql.py', world, world_out, '--db', 'acore_auth'], capture_output=True, text=True)
refused = lambda p: p.returncode != 0 and 'refusing to convert acore_world' in p.stderr
check('acore_world dump is refused and no output is written',
      refused(r) and refused(r_db) and refused(r_override) and not os.path.exists(world_out))
print(f'{ok} passed')
