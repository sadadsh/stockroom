from stockroom.sexp.document import SexpDocument, quote_kicad


def test_quote_kicad_escapes():
    assert quote_kicad('a"b\\c') == '"a\\"b\\\\c"'


def test_parse_exposes_names_and_children():
    doc = SexpDocument.parse('(symbol (property "Value" "10k") (lib_id "L:R"))')
    assert doc.root.name == "symbol"
    prop = doc.root.find("property")
    assert prop is not None
    assert prop.children[1].value == "Value"
    assert prop.children[2].value == "10k"


def test_find_all_returns_every_match():
    doc = SexpDocument.parse('(x (p 1) (p 2) (q 3))')
    ps = doc.root.find_all("p")
    assert [p.children[1].value for p in ps] == ["1", "2"]


def test_serialize_without_edits_is_byte_identical():
    text = '(symbol\r\n\t(property "V" "1")\r\n)'
    doc = SexpDocument.parse(text)
    assert doc.serialize() == text


def test_set_value_records_minimal_edit():
    text = '(symbol (property "Value" "10k"))'
    doc = SexpDocument.parse(text)
    val_leaf = doc.root.find("property").children[2]
    val_leaf.set_value("22k", quote=True)
    assert doc.serialize() == '(symbol (property "Value" "22k"))'


def test_set_value_on_unquoted_atom():
    text = '(at 1.5 2.5 90)'
    doc = SexpDocument.parse(text)
    doc.root.children[3].set_value("180", quote=False)
    assert doc.serialize() == '(at 1.5 2.5 180)'


def test_load_and_save_preserve_crlf(tmp_path):
    text = '(symbol\r\n\t(property "V" "1")\r\n)'
    src = tmp_path / "x.kicad_sym"
    src.write_text(text, encoding="utf-8", newline="")
    doc = SexpDocument.load(src)
    out = tmp_path / "out.kicad_sym"
    doc.save(out)
    assert out.read_bytes() == src.read_bytes()


def test_double_set_value_last_write_wins():
    doc = SexpDocument.parse('(at 90)')
    leaf = doc.root.children[1]
    leaf.set_value("180", quote=False)
    leaf.set_value("270", quote=False)
    assert doc.serialize() == '(at 270)'


def test_insert_child_multiline_matches_indent():
    text = '(symbol\n\t(property "A" "1")\n)'
    doc = SexpDocument.parse(text)
    doc.root.insert_child_text('(property "B" "2")')
    assert doc.serialize() == '(symbol\n\t(property "A" "1")\n\t(property "B" "2")\n)'


def test_insert_after_specific_child():
    text = '(x\n\t(a 1)\n\t(c 3)\n)'
    doc = SexpDocument.parse(text)
    a = doc.root.find("a")
    doc.root.insert_after(a, '(b 2)')
    assert doc.serialize() == '(x\n\t(a 1)\n\t(b 2)\n\t(c 3)\n)'


def test_insert_child_single_line():
    text = '(pts (xy 0 0))'
    doc = SexpDocument.parse(text)
    doc.root.insert_child_text('(xy 1 1)')
    assert doc.serialize() == '(pts (xy 0 0) (xy 1 1))'


def test_remove_child_multiline():
    text = '(x\n\t(a 1)\n\t(b 2)\n)'
    doc = SexpDocument.parse(text)
    doc.root.remove_child(doc.root.find("b"))
    assert doc.serialize() == '(x\n\t(a 1)\n)'
