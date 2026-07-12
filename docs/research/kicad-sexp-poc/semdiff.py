"""Semantic s-expression diff: independent minimal parser -> canonical tree compare.

Distinguishes pure reformatting (harmless) from token loss/mutation/reordering (data loss).
"""
import sys, re

def tokenize(text):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c == '(' or c == ')':
            yield c, c
            i += 1
        elif c == '"':
            j = i + 1
            buf = []
            while j < n:
                if text[j] == '\\' and j + 1 < n:
                    buf.append(text[j:j+2]); j += 2
                elif text[j] == '"':
                    break
                else:
                    buf.append(text[j]); j += 1
            yield 'str', ''.join(buf)
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()"':
                j += 1
            yield 'atom', text[i:j]
            i = j

NUM_RE = re.compile(r'^-?\d+(\.\d+)?$')

def norm_atom(kind, val):
    """Normalize: numbers to canonical float repr, unquoted vs quoted atoms kept distinct only by value."""
    if kind == 'atom' and NUM_RE.match(val):
        f = float(val)
        return ('num', f)
    if kind == 'str':
        # unescape for comparison
        v = val.replace('\\"', '"').replace('\\\\', '\\')
        if NUM_RE.match(v):
            return ('num', float(v))  # numbers sometimes quoted vs not
        return ('s', v)
    return ('s', val)

def parse(text):
    toks = list(tokenize(text))
    pos = 0
    def rd():
        nonlocal pos
        kind, val = toks[pos]
        if kind == '(':
            pos += 1
            lst = []
            while toks[pos][0] != ')':
                lst.append(rd())
            pos += 1
            return tuple(lst)
        else:
            pos += 1
            return norm_atom(kind, val)
    root = rd()
    assert pos == len(toks), f"trailing tokens at {pos}/{len(toks)}"
    return root

def count_nodes(t):
    if isinstance(t, tuple) and t and not (len(t) == 2 and t[0] in ('num', 's')):
        return 1 + sum(count_nodes(c) for c in t)
    return 1

def is_atom(t):
    return isinstance(t, tuple) and len(t) == 2 and t[0] in ('num', 's') and not isinstance(t[1], tuple)

def node_name(t):
    if not is_atom(t) and isinstance(t, tuple) and t and is_atom(t[0]):
        return t[0][1]
    return None

def diff_trees(a, b, path="", out=None, maxreport=40):
    """Order-sensitive structural diff. Reports missing/extra/changed nodes."""
    if out is None:
        out = []
    if len(out) >= maxreport:
        return out
    if is_atom(a) and is_atom(b):
        if a != b:
            # tolerate float repr noise
            if a[0] == 'num' and b[0] == 'num' and abs(a[1] - b[1]) < 1e-9:
                return out
            out.append(f"CHANGED {path}: {a[1]!r} -> {b[1]!r}")
        return out
    if is_atom(a) != is_atom(b):
        out.append(f"TYPE-CHANGED {path}: {'atom' if is_atom(a) else 'list'} -> {'atom' if is_atom(b) else 'list'}")
        return out
    # both lists
    name = node_name(a) or ''
    # match children: try order-sensitive pairing with alignment on (name) for lists
    import difflib
    def sig(t):
        if is_atom(t):
            return ('A', t)
        return ('L', node_name(t), len(t))
    sa, sb = [sig(c) for c in a], [sig(c) for c in b]
    sm = difflib.SequenceMatcher(None, sa, sb, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if len(out) >= maxreport:
            break
        if tag == 'equal':
            for k in range(i2 - i1):
                diff_trees(a[i1 + k], b[j1 + k], f"{path}/{name}[{i1+k}]", out, maxreport)
        elif tag == 'replace' and (i2 - i1) == (j2 - j1):
            for k in range(i2 - i1):
                diff_trees(a[i1 + k], b[j1 + k], f"{path}/{name}[{i1+k}]", out, maxreport)
        else:
            for k in range(i1, i2):
                nn = node_name(a[k]) or (a[k][1] if is_atom(a[k]) else '?')
                out.append(f"LOST {path}/{name}: child ({nn} ...) [{count_nodes(a[k])} nodes]")
                if len(out) >= maxreport: break
            for k in range(j1, j2):
                nn = node_name(b[k]) or (b[k][1] if is_atom(b[k]) else '?')
                out.append(f"ADDED {path}/{name}: child ({nn} ...) [{count_nodes(b[k])} nodes]")
                if len(out) >= maxreport: break
    return out

def compare(orig_path, new_path, label):
    a = parse(open(orig_path, encoding='utf-8').read())
    b = parse(open(new_path, encoding='utf-8').read())
    na, nb = count_nodes(a), count_nodes(b)
    diffs = diff_trees(a, b)
    lost = sum(1 for d in diffs if d.startswith('LOST'))
    added = sum(1 for d in diffs if d.startswith('ADDED'))
    changed = sum(1 for d in diffs if d.startswith('CHANGED') or d.startswith('TYPE'))
    if not diffs:
        print(f"{label}: SEMANTICALLY IDENTICAL ({na} nodes) — differences are formatting-only")
    else:
        print(f"{label}: {na} -> {nb} nodes | first-40 report: {lost} LOST, {added} ADDED, {changed} CHANGED (truncated at 40)")
        for d in diffs[:12]:
            print(f"    {d}")
    return diffs

if __name__ == '__main__':
    compare(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'cmp')
