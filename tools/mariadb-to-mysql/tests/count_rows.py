import sys, re, collections; sys.path.insert(0, '.'); import convert_mariadb_to_mysql as c
R = re.compile(r'(?:INSERT|REPLACE)\s+(?:IGNORE\s+)?INTO\s+`(\w+)`\s*(?:\([^)]*\))?\s*VALUES\s*(.*);$', re.S)
def counts(p):
    d = collections.Counter()
    for st in c.statements(open(p, errors='surrogateescape')):
        m = R.match(st)
        if m: d[m.group(1)] += len(c.split_tuples(m.group(2)))
    return d
a, b = counts(sys.argv[1]), counts(sys.argv[2])
print(sys.argv[2], 'rows', sum(a.values()), '->', sum(b.values()), 'per-table mismatches:', {t: (a[t], b[t]) for t in set(a) | set(b) if a[t] != b[t]})
