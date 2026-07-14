import pytest

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


def test_insert_child_preserves_crlf():
    text = '(symbol\r\n\t(property "A" "1")\r\n)'
    doc = SexpDocument.parse(text)
    doc.root.insert_child_text('(property "B" "2")')
    out = doc.serialize()
    assert out == '(symbol\r\n\t(property "A" "1")\r\n\t(property "B" "2")\r\n)'
    assert "\n\t" not in out.replace("\r\n\t", "")  # no bare-LF indent introduced


def test_remove_child_preserves_crlf():
    text = '(x\r\n\t(a 1)\r\n\t(b 2)\r\n)'
    doc = SexpDocument.parse(text)
    doc.root.remove_child(doc.root.find("b"))
    out = doc.serialize()
    assert out == '(x\r\n\t(a 1)\r\n)'
    assert "\r\r" not in out  # no orphaned CR left behind


def test_set_value_is_visible_to_reads():
    doc = SexpDocument.parse('(property "Value" "10k")')
    doc.root.children[2].set_value("22k", quote=True)
    assert doc.root.children[2].value == "22k"


def test_inserted_child_is_visible_to_reads():
    doc = SexpDocument.parse('(symbol\n\t(property "Value" "10k")\n)')
    doc.root.insert_child_text('(property "MPN" "RC0603")')
    mpns = [p for p in doc.root.find_all("property") if p.children[1].value == "MPN"]
    assert len(mpns) == 1 and mpns[0].children[2].value == "RC0603"


def test_removed_child_is_not_visible_to_reads():
    doc = SexpDocument.parse('(x\n\t(a 1)\n\t(b 2)\n)')
    doc.root.remove_child(doc.root.find("b"))
    assert doc.root.find("b") is None


def test_two_inserts_on_same_node_stack_in_order():
    doc = SexpDocument.parse('(symbol\n\t(property "A" "1")\n)')
    doc.root.insert_child_text('(property "B" "2")')
    doc.root.insert_child_text('(property "C" "3")')
    out = doc.serialize()
    assert out == (
        '(symbol\n\t(property "A" "1")\n\t(property "B" "2")\n\t(property "C" "3")\n)'
    )
    SexpDocument.parse(out)  # re-parses cleanly, proving no corruption


def test_two_inserts_preserve_crlf():
    doc = SexpDocument.parse('(symbol\r\n\t(property "A" "1")\r\n)')
    doc.root.insert_child_text('(property "B" "2")')
    doc.root.insert_child_text('(property "C" "3")')
    out = doc.serialize()
    assert out == (
        '(symbol\r\n\t(property "A" "1")'
        '\r\n\t(property "B" "2")\r\n\t(property "C" "3")\r\n)'
    )
    assert "\r\r" not in out


def test_remove_then_insert_at_same_anchor():
    doc = SexpDocument.parse('(x\n\t(a 1)\n\t(b 2)\n)')
    doc.root.remove_child(doc.root.find("b"))
    doc.root.insert_child_text('(c 3)')
    out = doc.serialize()
    assert out == '(x\n\t(a 1)\n\t(c 3)\n)', repr(out)
    SexpDocument.parse(out)


def test_insert_then_remove_still_correct():
    doc = SexpDocument.parse('(x\n\t(a 1)\n\t(b 2)\n)')
    doc.root.insert_child_text('(c 3)')
    doc.root.remove_child(doc.root.find("b"))
    out = doc.serialize()
    assert out == '(x\n\t(a 1)\n\t(c 3)\n)', repr(out)


def test_remove_inserted_node_raises():
    doc = SexpDocument.parse('(x\n\t(a 1)\n)')
    doc.root.insert_child_text('(b 2)')
    with pytest.raises(ValueError):
        doc.root.remove_child(doc.root.children[-1])


def test_overlapping_edits_raise():
    doc = SexpDocument.parse('(x\n\t(p "V" "10k")\n\t(q 1)\n)')
    doc.root.find("p").children[2].set_value("LONGER", quote=True)
    doc.root.remove_child(doc.root.find("p"))
    with pytest.raises(ValueError):
        doc.serialize()


def test_truncated_input_raises():
    with pytest.raises(ValueError):
        SexpDocument.parse('(a (b')


def test_trailing_tokens_raise():
    with pytest.raises(ValueError):
        SexpDocument.parse('(a 1) (b 2)')


def test_iter_descendants_walks_every_nested_list_node_pre_order():
    # The shared bulk-edit traversal (roadmap #6/#7): every descendant LIST node, pre-order,
    # at any depth. Atoms and the node itself are excluded; a nested match is reached.
    doc = SexpDocument.parse('(root (a (b 1) (c (b 2))) (b 3))')
    names = [n.name for n in doc.root.iter_descendants()]
    assert names == ["a", "b", "c", "b", "b"]  # a, a/b, a/c, a/c/b, root/b
    # a fp_text buried inside a footprint is reachable, a bare atom is never yielded
    twos = [n for n in doc.root.iter_descendants() if n.name == "b"]
    assert [t.children[1].value for t in twos] == ["1", "2", "3"]


def test_iter_descendants_on_a_leaf_is_empty():
    doc = SexpDocument.parse('(root 1 "x")')
    assert list(doc.root.children[1].iter_descendants()) == []
