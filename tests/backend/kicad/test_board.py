"""Board: byte-preserving editor for the .kicad_pcb (setup) block.

These keys physically live in the .kicad_pcb (setup) S-expression, NOT in .kicad_pro
(KiCad ignores mask/paste/tenting/origin keys written there). Domain knowledge is ported
by-behavior from the retired nd_board_setup.py, but every edit routes through Stockroom's
byte-preserving SexpDocument (the only .kicad_* editor), extended for the KiCad-10 nested
via-protection family (tenting / covering / plugging) that nd_board_setup predated.
"""

from stockroom.kicad.board import Board, resolve_key
from stockroom.kicad.errors import KiCadFileError
from stockroom.sexp.document import SexpDocument
from stockroom.verify.semdiff import assert_only_changed, semantic_diff

_STUB = (
    '(kicad_pcb\n\t(version 20260206)\n\t(generator "pcbnew")\n'
    '\t(generator_version "10.0")\n)\n'
)


def _board(text: str) -> Board:
    return Board(SexpDocument.parse(text))


# ------------------------------------------------------------------ read ----


def test_reads_numeric_key(tmp_fixture):
    b = Board.load(tmp_fixture("minimal.kicad_pcb"))
    assert b.setup()["pad_to_mask_clearance"] == 0.0508


def test_reads_flat_bool_keys(tmp_fixture):
    vals = Board.load(tmp_fixture("minimal.kicad_pcb")).setup()
    assert vals["allow_soldermask_bridges_in_footprints"] is False
    assert vals["capping"] is False
    assert vals["filling"] is False


def test_reads_coord_key(tmp_fixture):
    assert Board.load(tmp_fixture("minimal.kicad_pcb")).setup()["aux_axis_origin"] == (
        140.0,
        115.5,
    )


def test_reads_sided_via_protection_family(tmp_fixture):
    vals = Board.load(tmp_fixture("minimal.kicad_pcb")).setup()
    assert vals["tenting_front"] is True and vals["tenting_back"] is True
    assert vals["covering_front"] is False and vals["covering_back"] is False
    assert vals["plugging_front"] is False and vals["plugging_back"] is False


def test_read_mirrors_friendly_aliases(tmp_fixture):
    vals = Board.load(tmp_fixture("minimal.kicad_pcb")).setup()
    # solder_mask_clearance is the audit's friendly name for pad_to_mask_clearance.
    assert vals["solder_mask_clearance"] == 0.0508


def test_read_omits_absent_keys(tmp_fixture):
    vals = Board.load(tmp_fixture("minimal.kicad_pcb")).setup()
    assert "grid_origin" not in vals
    assert "solder_mask_min_width" not in vals


def test_read_without_aliases(tmp_fixture):
    vals = Board.load(tmp_fixture("minimal.kicad_pcb")).setup(include_aliases=False)
    assert "solder_mask_clearance" not in vals
    assert vals["pad_to_mask_clearance"] == 0.0508


def test_read_empty_when_no_setup_block():
    assert _board(_STUB).setup() == {}


# ------------------------------------------------------- write in place ----


def test_set_numeric_in_place_is_minimal_diff(tmp_fixture):
    b = Board.load(tmp_fixture("minimal.kicad_pcb"))
    original = b.serialize()
    b.set_setup({"pad_to_mask_clearance": 0.1})
    assert b.setup()["pad_to_mask_clearance"] == 0.1
    assert_only_changed(original, b.serialize(), allowed_changes=1)


def test_set_alias_writes_the_real_key(tmp_fixture):
    b = Board.load(tmp_fixture("minimal.kicad_pcb"))
    original = b.serialize()
    b.set_setup({"solder_mask_clearance": 0.2})
    out = b.serialize()
    assert "pad_to_mask_clearance 0.2" in out
    assert "solder_mask_clearance" not in out  # only real keys reach the file
    assert_only_changed(original, out, allowed_changes=1)


def test_set_bool_in_place(tmp_fixture):
    b = Board.load(tmp_fixture("minimal.kicad_pcb"))
    original = b.serialize()
    b.set_setup({"capping": True})
    assert "(capping yes)" in b.serialize()
    assert_only_changed(original, b.serialize(), allowed_changes=1)


def test_set_coord_in_place(tmp_fixture):
    b = Board.load(tmp_fixture("minimal.kicad_pcb"))
    original = b.serialize()
    b.set_setup({"aux_axis_origin": (10, 20)})
    assert b.setup()["aux_axis_origin"] == (10.0, 20.0)
    assert_only_changed(original, b.serialize(), allowed_changes=2)


def test_set_sided_side_in_place_is_minimal(tmp_fixture):
    b = Board.load(tmp_fixture("minimal.kicad_pcb"))
    original = b.serialize()
    b.set_setup({"tenting_back": False})
    vals = b.setup()
    assert vals["tenting_back"] is False and vals["tenting_front"] is True
    assert_only_changed(original, b.serialize(), allowed_changes=1)


def test_integral_value_is_formatted_without_decimals(tmp_fixture):
    b = Board.load(tmp_fixture("minimal.kicad_pcb"))
    b.set_setup({"pad_to_mask_clearance": 0})
    assert "(pad_to_mask_clearance 0)" in b.serialize()


def test_empty_or_unsupported_values_leave_the_board_untouched(tmp_fixture):
    b = Board.load(tmp_fixture("minimal.kicad_pcb"))
    original = b.serialize()
    b.set_setup({})
    b.set_setup({"not_a_real_setup_key": 5})
    assert b.serialize() == original


# ------------------------------------------------------ write insert -------


def test_inserts_absent_flat_key(tmp_fixture):
    b = Board.load(tmp_fixture("minimal.kicad_pcb"))
    original = b.serialize()
    b.set_setup({"solder_mask_min_width": 0.25})
    assert b.setup()["solder_mask_min_width"] == 0.25
    # the pre-existing keys are all still there and unchanged.
    diffs = semantic_diff(original, b.serialize())
    assert all(not d.startswith(("LOST", "CHANGED", "TYPE")) for d in diffs), diffs


def test_inserts_absent_coord_key(tmp_fixture):
    b = Board.load(tmp_fixture("minimal.kicad_pcb"))
    b.set_setup({"grid_origin": (5, 6)})
    assert b.setup()["grid_origin"] == (5.0, 6.0)


def test_normalizes_a_legacy_bare_sided_block_without_corrupting_it():
    # A pre-KiCad-9 bare tenting form (KiCad still READS it but never writes it). Editing
    # must normalize to the canonical nested form, never splice a (front ..) child into the
    # bare node (which would produce the malformed "(tenting yes yes (front no))").
    text = (
        "(kicad_pcb\n\t(version 20260206)\n"
        "\t(setup\n\t\t(tenting yes yes)\n\t)\n)\n"
    )
    b = _board(text)
    b.set_setup({"tenting_front": False, "tenting_back": True})
    out = b.serialize()
    assert "(front no)" in out and "(back yes)" in out
    assert "(tenting yes yes" not in out  # the bare form is gone, not spliced into
    vals = Board(SexpDocument.parse(out)).setup()
    assert vals["tenting_front"] is False and vals["tenting_back"] is True


def test_normalizing_a_legacy_bare_block_preserves_the_unspecified_side():
    # Setting only one side of a legacy bare form must NOT flip the other side to a default:
    # (tenting none) means both sides UNtented; touching only front must leave back untented.
    text = (
        "(kicad_pcb\n\t(version 20260206)\n"
        "\t(setup\n\t\t(tenting none)\n\t)\n)\n"
    )
    b = _board(text)
    b.set_setup({"tenting_front": False})
    vals = Board(SexpDocument.parse(b.serialize())).setup()
    assert vals["tenting_front"] is False
    assert vals["tenting_back"] is False  # preserved, not flipped to KiCad's default (yes)


def test_normalizing_a_legacy_positional_block_preserves_the_unspecified_side():
    # A positional bare form (front tented, back not): touching front keeps back untented.
    text = (
        "(kicad_pcb\n\t(version 20260206)\n"
        "\t(setup\n\t\t(tenting yes no)\n\t)\n)\n"
    )
    b = _board(text)
    b.set_setup({"tenting_front": False})
    vals = Board(SexpDocument.parse(b.serialize())).setup()
    assert vals["tenting_front"] is False and vals["tenting_back"] is False


def test_fresh_block_orders_origins_like_kicad():
    # KiCad 10 writes aux_axis_origin before grid_origin; a fresh block must match to avoid
    # churn on the board's first real KiCad save.
    b = _board(_STUB)
    b.set_setup({"grid_origin": (1, 2), "aux_axis_origin": (3, 4)})
    out = b.serialize()
    assert out.index("aux_axis_origin") < out.index("grid_origin")


def test_inserts_absent_sided_block_with_default_for_unspecified_side():
    # setup exists but has NO tenting block; setting one side creates the block and
    # fills the other side with KiCad's implicit default (tenting is tented by default).
    text = (
        "(kicad_pcb\n\t(version 20260206)\n\t(generator \"pcbnew\")\n"
        "\t(setup\n\t\t(pad_to_mask_clearance 0.05)\n\t)\n)\n"
    )
    b = _board(text)
    b.set_setup({"tenting_front": False})
    vals = b.setup()
    assert vals["tenting_front"] is False
    assert vals["tenting_back"] is True  # KiCad default preserved for the unset side


# ------------------------------------------------- create fresh setup ------


def test_creates_a_setup_block_when_none_exists():
    b = _board(_STUB)
    b.set_setup({"pad_to_mask_clearance": 0.1})
    out = b.serialize()
    assert "(setup" in out
    assert Board(SexpDocument.parse(out)).setup()["pad_to_mask_clearance"] == 0.1


def test_created_setup_block_is_placed_after_the_preamble():
    b = _board(_STUB)
    b.set_setup({"pad_to_mask_clearance": 0.1})
    out = b.serialize()
    # setup must follow generator_version (the last preamble block in the stub).
    assert out.index("generator_version") < out.index("(setup")


def test_creates_setup_with_a_sided_key():
    b = _board(_STUB)
    b.set_setup({"tenting_front": False, "tenting_back": False})
    vals = Board(SexpDocument.parse(b.serialize())).setup()
    assert vals["tenting_front"] is False and vals["tenting_back"] is False


# ------------------------------------------------- reload-on-fresh-node -----


def test_can_edit_an_inserted_key_after_reload(tmp_fixture):
    b = Board.load(tmp_fixture("minimal.kicad_pcb"))
    b.set_setup({"solder_mask_min_width": 0.25})  # inserts a fresh node
    b.set_setup({"solder_mask_min_width": 0.30})  # re-edits it (needs a reload)
    assert b.setup()["solder_mask_min_width"] == 0.30
    assert b.serialize().count("solder_mask_min_width") == 1  # not duplicated


# ------------------------------------------------------ byte preservation --


def test_untouched_board_serializes_byte_identically(tmp_fixture):
    path = tmp_fixture("minimal.kicad_pcb")
    # read the EXACT bytes (the layer preserves line endings via newline=""); a
    # newline-normalizing read_text would spuriously differ on a CRLF checkout.
    original = path.read_bytes().decode("utf-8")
    assert Board.load(path).serialize() == original


def test_set_setup_key_convenience(tmp_fixture):
    b = Board.load(tmp_fixture("minimal.kicad_pcb"))
    b.set_setup_key("filling", True)
    assert "(filling yes)" in b.serialize()


# ------------------------------------------------ (general) / thickness ----

# A .kicad_pcb whose (general) block carries both thickness and a sibling key, so
# a thickness edit is provably minimal (the sibling must survive untouched).
_GENERAL_TWO = (
    '(kicad_pcb\n\t(version 20260206)\n\t(generator "pcbnew")\n'
    '\t(generator_version "10.0")\n'
    "\t(general\n\t\t(thickness 1.6)\n\t\t(legacy_teardrops no)\n\t)\n"
    '\t(paper "A4")\n)\n'
)


def test_reads_board_thickness(tmp_fixture):
    assert Board.load(tmp_fixture("minimal.kicad_pcb")).thickness() == 1.6


def test_general_returns_thickness(tmp_fixture):
    assert Board.load(tmp_fixture("minimal.kicad_pcb")).general()["thickness"] == 1.6


def test_thickness_is_none_when_no_general_block():
    b = _board(_STUB)
    assert b.general() == {}
    assert b.thickness() is None


def test_set_thickness_in_place_is_minimal(tmp_fixture):
    b = Board.load(tmp_fixture("minimal.kicad_pcb"))
    original = b.serialize()
    b.set_thickness(0.8)
    out = b.serialize()
    assert "(thickness 0.8)" in out
    assert Board(SexpDocument.parse(out)).thickness() == 0.8
    assert_only_changed(original, out, allowed_changes=1)


def test_set_thickness_integral_formatting():
    b = _board(_GENERAL_TWO)
    b.set_thickness(2)
    assert "(thickness 2)" in b.serialize()


def test_set_thickness_preserves_sibling_general_keys():
    b = _board(_GENERAL_TWO)
    original = b.serialize()
    b.set_thickness(1.2)
    out = b.serialize()
    assert "(legacy_teardrops no)" in out  # sibling untouched
    assert Board(SexpDocument.parse(out)).thickness() == 1.2
    assert_only_changed(original, out, allowed_changes=1)


def test_set_thickness_inserts_into_a_general_without_thickness():
    text = (
        '(kicad_pcb\n\t(version 20260206)\n\t(generator "pcbnew")\n'
        '\t(generator_version "10.0")\n'
        "\t(general\n\t\t(legacy_teardrops no)\n\t)\n)\n"
    )
    b = _board(text)
    b.set_thickness(1.6)
    out = b.serialize()
    assert Board(SexpDocument.parse(out)).thickness() == 1.6
    assert "(legacy_teardrops no)" in out


def test_set_thickness_creates_a_general_block_when_none_exists():
    b = _board(_STUB)
    b.set_thickness(1.6)
    out = b.serialize()
    assert "(general" in out
    assert Board(SexpDocument.parse(out)).thickness() == 1.6
    # (general) must precede a (setup) that a later edit could add (KiCad's order).
    assert out.index("generator_version") < out.index("(general")


def test_can_edit_thickness_after_a_fresh_general(tmp_fixture):
    b = _board(_STUB)
    b.set_thickness(1.6)  # creates the block (needs a reload)
    b.set_thickness(0.8)  # re-edits it
    assert b.thickness() == 0.8
    assert b.serialize().count("(thickness") == 1  # not duplicated


# --------------------------------------------------------- validation ------


def test_rejects_a_non_pcb_document():
    try:
        _board('(kicad_sch\n\t(version 20260206)\n)\n')
    except KiCadFileError:
        return
    raise AssertionError("expected KiCadFileError for a non-.kicad_pcb document")


def test_resolve_key_maps_aliases_and_passes_real_keys():
    assert resolve_key("solder_mask_clearance") == "pad_to_mask_clearance"
    assert resolve_key("pad_to_mask_clearance") == "pad_to_mask_clearance"
    assert resolve_key("not_a_key") is None
