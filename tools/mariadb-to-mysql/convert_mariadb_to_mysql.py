#!/usr/bin/env python3
"""Convert AzerothCore MariaDB 10.x dumps (mariadb-dump) into data-only SQL for the new
AzerothCore on MySQL 8.4.

Every row is mapped BY NAME: old position -> old column name (from the dump's own CREATE TABLE)
-> new column (target_schema/<db>.cols, taken from the new server's MySQL 8.4 --no-data dumps).
Known schema changes get explicit transforms (see TRANSFORMS / DIFF_REPORT.md).

An acore_world dump is refused. Back that database up, then leave the file as an archive:
do not convert it and do not import it. ac-db-import loads a fresh world.

Usage:
  python3 convert_mariadb_to_mysql.py IN.sql OUT.sql [--dup ignore|replace|error] [--truncate]
         [--skip-tables a,b] [--db acore_characters] [--target-schema new_nodata.sql]
"""
import argparse, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------- streaming statement splitter (quote/comment aware) ----------
LEAD = re.compile(r'^(?:\s+|/\*M!.*?\*/|--[^\n]*(?:\n|$))*', re.S)

def statements(f):
    for s in _raw_statements(f):
        s = LEAD.sub('', s)
        if s: yield s

def _raw_statements(f):
    buf = []; inq = None; esc = False
    while True:
        chunk = f.read(1 << 20)
        if not chunk: break
        start = 0; i = 0; n = len(chunk)
        while i < n:
            c = chunk[i]
            if inq:
                if esc: esc = False
                elif c == '\\': esc = True
                elif c == inq: inq = None
            elif c in ("'", '"', '`'): inq = c
            elif c == '-' and chunk.startswith('-- ', i) and (i == 0 or chunk[i - 1] == '\n'):
                j = chunk.find('\n', i); i = (n - 1) if j < 0 else j   # line comment: ignore quotes/; in it
            elif c == ';':
                buf.append(chunk[start:i + 1]); s = ''.join(buf).strip(); buf = []; start = i + 1
                if s: yield s
            i += 1
        buf.append(chunk[start:])
    s = ''.join(buf).strip()
    if s: yield s

def create_cols(stmt):
    m = re.match(r'CREATE TABLE\s+(?:IF NOT EXISTS\s+)?`([^`]+)`\s*\((.*)\)[^)]*$', stmt.rstrip(';'), re.S)
    if not m: return None, []
    items, depth, cur, q = [], 0, [], None
    for ch in m.group(2):
        if q:
            if ch == q: q = None
        elif ch in "'`\"": q = ch
        elif ch == '(': depth += 1
        elif ch == ')': depth -= 1
        elif ch == ',' and depth == 0: items.append(''.join(cur)); cur = []; continue
        cur.append(ch)
    items.append(''.join(cur))
    return m.group(1), [re.match(r'\s*`([^`]+)`', i).group(1) for i in items if re.match(r'\s*`', i)]

def split_tuples(values):
    rows = []; i = 0; n = len(values)
    while i < n:
        while i < n and values[i] != '(': i += 1
        if i >= n: break
        i += 1; row = []; cur = i; inq = False; esc = False; depth = 0
        while i < n:
            c = values[i]
            if inq:
                if esc: esc = False
                elif c == '\\': esc = True
                elif c == "'": inq = False
            elif c == "'": inq = True
            elif c == '(': depth += 1
            elif c == ')' and depth: depth -= 1
            elif c == ',' and not depth: row.append(values[cur:i].strip()); cur = i + 1
            elif c == ')': row.append(values[cur:i].strip()); i += 1; break
            i += 1
        rows.append(row)
    return rows

def load_cols(path):
    d = {}
    for line in open(path):
        p = line.split()
        if p: d[p[0]] = p[1:]
    return d

# ---------- explicit per-table transforms (row: dict col->raw SQL literal) ----------
LOCALES = ['enUS', 'koKR', 'frFR', 'deDE', 'zhCN', 'zhTW', 'esES', 'esMX', 'ruRU']
def _int(v):
    try: return int(v.strip("'"))
    except ValueError: return None

def t_account(row, extra):
    v = row.get('locale')
    if v is not None and _int(v) is not None:          # old tinyint index -> new varchar(4)
        i = _int(v); row['locale'] = f"'{LOCALES[i]}'" if 0 <= i < len(LOCALES) else "'enUS'"
    return row

def _petition_id(guid):                                 # same formula as AC rev_1756841669142726711.sql
    g = _int(guid) or 0
    return str(g if g <= 2147483647 else g - 2147483648)

def t_petition(row, extra):
    row.setdefault('petition_id', _petition_id(row.get('petitionguid', '0')))
    return row

def t_mail_server_template(row, extra):               # AC PR #21590 migration, done per row
    tid = row['id']
    for fac, it, cnt in (('Alliance', 'itemA', 'itemCountA'), ('Horde', 'itemH', 'itemCountH')):
        if (_int(row.get(it, '0')) or 0) > 0:
            extra.append(('mail_server_template_items', ['templateID', 'faction', 'item', 'itemCount'],
                          [tid, f"'{fac}'", row[it], row.get(cnt, '0')]))
    for ctype, col in (('Level', 'reqLevel'), ('PlayTime', 'reqPlayTime')):
        if (_int(row.get(col, '0')) or 0) > 0:
            extra.append(('mail_server_template_conditions', ['templateID', 'conditionType', 'conditionValue'],
                          [tid, f"'{ctype}'", row[col]]))
    return row

def t_quest_tracker(row, extra):                        # id became NOT NULL DEFAULT 0
    if row.get('id', '').upper() == 'NULL': row['id'] = '0'
    return row

TRANSFORMS = {
    'acore_auth': {'account': t_account},
    'acore_characters': {'petition': t_petition, 'petition_sign': t_petition,
                         'mail_server_template': t_mail_server_template, 'quest_tracker': t_quest_tracker},
}
# Explicit renames old->new (none evident in auth/characters; kept for completeness / modules)
RENAMES = {'acore_auth': {}, 'acore_characters': {}}

def load_fills(db):
    fills = {}
    p = os.path.join(HERE, 'target_schema', 'notnull_nodefault.txt')
    if os.path.exists(p):
        for line in open(p):
            if not line.strip() or line.startswith('#'): continue
            d, t, c, v = line.split(None, 3)
            if d == db: fills.setdefault(t, {})[c] = v.strip()
    return fills

def header_database(path):
    """Database name from the mariadb-dump --databases comment in the first 10 lines."""
    with open(path, encoding='utf-8', errors='surrogateescape') as f:
        for _ in range(10):
            m = re.search(r'Database: (\w+)', f.readline())
            if m: return m.group(1)
    return None

def main():
    ap = argparse.ArgumentParser(
        description='Convert an AzerothCore MariaDB dump to data-only SQL for MySQL 8.4. '
                    'Refuses an acore_world dump: back that database up and keep the file as an archive. '
                    'Do not convert it and do not import it; ac-db-import loads a fresh world.')
    ap.add_argument('inp'); ap.add_argument('out')
    ap.add_argument('--target-schema', help='mysqldump --no-data of the new DB (overrides bundled)')
    ap.add_argument('--db'); ap.add_argument('--no-embedded', action='store_true')
    ap.add_argument('--dup', choices=['ignore', 'replace', 'error'], default='ignore')
    ap.add_argument('--truncate', action='store_true')
    ap.add_argument('--skip-tables', default='')
    ap.add_argument('--only-tables', default='', help='convert only these tables (comma list)')
    a = ap.parse_args()
    skip = {t for t in a.skip_tables.split(',') if t}
    only = {t for t in a.only_tables.split(',') if t}
    header_db = header_database(a.inp)
    db = a.db or header_db
    if db == 'acore_world' or header_db == 'acore_world':
        print('refusing to convert acore_world: that dump is an archive only. '
              'Keep the file. Do not convert it and do not import it into MySQL 8.4. '
              'ac-db-import loads a fresh world.', file=sys.stderr)
        sys.exit(2)
    target = None
    if a.target_schema:
        target = {}
        with open(a.target_schema, encoding='utf-8', errors='surrogateescape') as f:
            for st in statements(f):
                if st.upper().startswith('CREATE TABLE'):
                    t, c = create_cols(st)
                    if t: target[t] = c
    elif not a.no_embedded and db and os.path.exists(os.path.join(HERE, 'target_schema', f'{db}.cols')):
        target = load_cols(os.path.join(HERE, 'target_schema', f'{db}.cols'))
        print(f'using bundled target schema for {db} ({len(target)} tables)', file=sys.stderr)
    else:
        print(f'no target schema for {db!r}: columns pass through unmapped', file=sys.stderr)
    fills = load_fills(db); tf = TRANSFORMS.get(db, {}); ren = RENAMES.get(db, {})
    verb = {'ignore': 'INSERT IGNORE', 'replace': 'REPLACE', 'error': 'INSERT'}[a.dup]
    ins_re = re.compile(r'INSERT\s+(?:IGNORE\s+)?INTO\s+`?(\w+)`?\s*(\([^)]*\))?\s*VALUES\s*(.*);$', re.S | re.I)
    src = {}; truncated = set()
    st = {'stmts': 0, 'rows': 0, 'stubs': 0, 'dropped': {}, 'filled': {}, 'skipped': set(), 'bad': 0, 'extra': 0}

    def emit(o, t, cols, rows):
        if a.truncate and t not in truncated:
            o.write(f'TRUNCATE TABLE `{t}`;\n'); truncated.add(t)
        o.write(f"{verb} INTO `{t}` ({','.join('`%s`' % c for c in cols)}) VALUES\n"
                + ',\n'.join('(' + ','.join(r) + ')' for r in rows) + ';\n')

    with open(a.inp, encoding='utf-8', errors='surrogateescape') as f, \
         open(a.out, 'w', encoding='utf-8', errors='surrogateescape') as o:
        o.write("SET NAMES utf8mb4;\nSET FOREIGN_KEY_CHECKS=0;\nSET UNIQUE_CHECKS=0;\n"
                "SET SESSION sql_mode='NO_AUTO_VALUE_ON_ZERO';\nSET TIME_ZONE='+00:00';\n\n")
        for s in statements(f):
            u = s[:30].upper()
            if u.startswith('CREATE TABLE'):
                t, c = create_cols(s)
                if t: src[t] = c
                continue
            if not u.startswith('INSERT'):
                continue                                   # DDL / sandbox / session SETs dropped: new schema is authoritative
            m = ins_re.match(s)
            if not m: o.write('-- UNPARSED: ' + s[:200].replace('\n', ' ') + '\n'); continue
            t, collist, body = m.groups()
            if not body.strip():
                st['stubs'] += 1; continue
            if t in skip or (only and t not in only) or (target is not None and t not in target):
                st['skipped'].add(t); continue
            scols = [x.strip().strip('`') for x in collist.strip('()').split(',')] if collist else src.get(t)
            rows = split_tuples(body)
            if not scols or target is None:
                emit(o, t, scols or [], rows) if scols else o.write(f'{verb} INTO `{t}` VALUES {body};\n')
                st['stmts'] += 1; st['rows'] += len(rows); continue
            tcols = target[t]; rmap = ren.get(t, {})
            out, extra = [], []
            for r in rows:
                if len(r) != len(scols): st['bad'] += 1; continue
                d = {rmap.get(c, c): v for c, v in zip(scols, r)}
                if t in tf: d = tf[t](d, extra)
                for c, v in fills.get(t, {}).items():
                    if c not in d: d[c] = v; st['filled'].setdefault(t, set()).add(c)
                out.append(d)
            if not out: continue
            dropped = [c for c in out[0] if c not in tcols]
            if dropped: st['dropped'].setdefault(t, set()).update(dropped)
            cols = [c for c in tcols if c in out[0]]       # new-schema order
            emit(o, t, cols, [[d[c] for c in cols] for d in out])
            st['stmts'] += 1; st['rows'] += len(out)
            groups = {}
            for et, ec, ev in extra: groups.setdefault((et, tuple(ec)), []).append(ev)
            for (et, ec), evs in groups.items():
                emit(o, et, list(ec), evs); st['extra'] += len(evs)
        o.write('\nSET FOREIGN_KEY_CHECKS=1;\nSET UNIQUE_CHECKS=1;\n')
    p = lambda *x: print(*x, file=sys.stderr)
    p(f"{a.inp} [{db}]: {st['stmts']} INSERT stmts, {st['rows']} rows, {st['stubs']} empty stubs removed, "
      f"{st['extra']} derived rows, {st['bad']} rows with wrong value count SKIPPED")
    for t, c in sorted(st['dropped'].items()): p(f'  dropped old-only columns {t}: {sorted(c)}')
    for t, c in sorted(st['filled'].items()): p(f'  filled new NOT NULL columns {t}: {sorted(c)}')
    if st['skipped']: p(f"  skipped tables not in target schema: {sorted(st['skipped'])}")

if __name__ == '__main__':
    main()
