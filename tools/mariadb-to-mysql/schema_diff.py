#!/usr/bin/env python3
"""Mechanical table-by-table diff of two --no-data dumps (old MariaDB vs new MySQL)."""
import re, sys, convert_mariadb_to_mysql as c

def norm(d):
    d = re.sub(r'\b(tiny|small|medium|big)?int\(\d+\)', lambda m: (m.group(1) or '') + 'int', d)
    d = d.replace('current_timestamp()', 'CURRENT_TIMESTAMP')
    d = re.sub(r" CHARACTER SET \w+| COLLATE \w+", '', d)
    d = re.sub(r"DEFAULT '(-?\d+(?:\.\d+)?)'", r'DEFAULT \1', d)
    d = re.sub(r" COMMENT '.*'$", '', d)
    return d.strip().rstrip(',')

def parse(path):
    out = {}
    for st in c.statements(open(path, errors='replace')):
        if not st.startswith('CREATE TABLE'): continue
        t, cols = c.create_cols(st)
        defs = {}
        for line in st.split('\n'):
            m = re.match(r'\s*`([^`]+)`\s+(.*)', line)
            if m and m.group(1) in cols and m.group(1) not in defs: defs[m.group(1)] = m.group(2)
        keys = sorted(norm(l.strip()) for l in st.split('\n') if re.match(r'\s*(PRIMARY|UNIQUE|KEY|CONSTRAINT)', l))
        tail = st[st.rindex(')'):]
        opts = {k: (re.search(k + r'=(\w+)', tail) or [None, None])[1] for k in ('ENGINE', 'CHARSET', 'COLLATE', 'ROW_FORMAT')}
        out[t] = (cols, defs, keys, opts)
    return out

old, new = parse(sys.argv[1]), parse(sys.argv[2])
print(f'# {sys.argv[1]} -> {sys.argv[2]}\n')
print('only in OLD:', sorted(set(old) - set(new)) or '-')
print('only in NEW:', sorted(set(new) - set(old)) or '-')
for t in sorted(set(old) & set(new)):
    oc, od, ok, oo = old[t]; nc, nd, nk, no = new[t]; lines = []
    if oc != nc:
        add = [x for x in nc if x not in oc]; rem = [x for x in oc if x not in nc]
        if add: lines.append(f'  + added: {", ".join(f"{x} [{nd[x]}] after {nc[nc.index(x)-1] if nc.index(x) else "FIRST"}" for x in add)}')
        if rem: lines.append(f'  - removed: {", ".join(f"{x} [{od[x]}]" for x in rem)}')
        if [x for x in oc if x in nc] != [x for x in nc if x in oc]: lines.append('  ~ REORDERED')
    for x in oc:
        if x in nd and norm(od[x]) != norm(nd[x]): lines.append(f'  ~ {x}: {od[x]}  ->  {nd[x]}')
    if ok != nk: lines.append(f'  ~ keys: {ok} -> {nk}')
    if (oo['ENGINE'], oo['COLLATE']) != (no['ENGINE'], no['COLLATE']): lines.append(f'  ~ table opts: {oo} -> {no}')
    if lines: print(f'\n## {t}'); print('\n'.join(lines))
