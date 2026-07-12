"""PoC: span-preserving s-expression edit — tokenizer tracks byte offsets,
edits replace only the target token's span; all other bytes (CRLF, tabs,
number formatting, token order) are untouched.
"""
import re, sys

def tokens_with_spans(text):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c in '()':
            yield (c, i, i + 1)
            i += 1
        elif c == '"':
            j = i + 1
            while j < n:
                if text[j] == '\\':
                    j += 2
                elif text[j] == '"':
                    break
                else:
                    j += 1
            yield ('str', i, j + 1)
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()"':
                j += 1
            yield ('atom', i, j)
            i = j

def parse_spans(text):
    """Return nested lists of (kind, start, end) leaves; lists carry children."""
    toks = list(tokens_with_spans(text))
    pos = 0
    def rd():
        nonlocal pos
        kind, s, e = toks[pos]
        if kind == '(':
            pos += 1
            kids = []
            while toks[pos][0] != ')':
                kids.append(rd())
            pos += 1
            return kids
        pos += 1
        return (kind, s, e)
    return rd()

def atom_text(text, leaf):
    k, s, e = leaf
    v = text[s:e]
    return v[1:-1] if k == 'str' else v

def edit_file(path, out_path):
    text = open(path, encoding='utf-8', newline='').read()  # keep CRLF exactly
    tree = parse_spans(text)
    edits = []  # (start, end, replacement)

    def walk(node):
        if not isinstance(node, list) or not node:
            return
        head = node[0]
        if isinstance(head, tuple) and atom_text(text, head) == 'symbol':
            # find property children
            props = {}
            lib_id = None
            for ch in node[1:]:
                if isinstance(ch, list) and ch and isinstance(ch[0], tuple):
                    nm = atom_text(text, ch[0])
                    if nm == 'property' and len(ch) >= 3 and isinstance(ch[1], tuple):
                        props[atom_text(text, ch[1])] = ch
                    elif nm == 'lib_id':
                        lib_id = ch
            ref = props.get('Reference')
            if ref and atom_text(text, ref[2]) == 'R-PR1T-MUX2':
                val_leaf = props['Value'][2]
                edits.append((val_leaf[1], val_leaf[2], '"TEST_EDIT_42k"'))
                lid_leaf = lib_id[1]
                edits.append((lid_leaf[1], lid_leaf[2], '"MyLib:TestSymbol"'))
        for ch in node:
            if isinstance(ch, list):
                walk(ch)

    walk(tree)
    assert edits, "target not found"
    for s, e, rep in sorted(edits, reverse=True):
        text = text[:s] + rep + text[e:]
    open(out_path, 'w', encoding='utf-8', newline='').write(text)
    print(f"applied {len(edits)} span edits")

if __name__ == '__main__':
    edit_file('testfiles/Power_Supply.kicad_sch', 'rt_out/span_poc.kicad_sch')
