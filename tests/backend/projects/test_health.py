"""Audit of a KiCad schematic, lifted Qt-free from the retired nd_project_health and
fed by Stockroom's sexp layer."""

from stockroom.projects.health import audit_project, audit_report_markdown, audit_schematic


def _sym(lib_id, ref, value="", footprint=None, extra=""):
    fp = "" if footprint is None else footprint
    return (
        f'  (symbol\n'
        f'    (lib_id "{lib_id}")\n'
        f'    (property "Reference" "{ref}" (at 0 0 0))\n'
        f'    (property "Value" "{value}" (at 0 0 0))\n'
        f'    (property "Footprint" "{fp}" (at 0 0 0))\n'
        f'    {extra}\n'
        f'  )\n'
    )


_LIBSYMS_R2 = (
    '  (lib_symbols\n'
    '    (symbol "Device:R"\n'
    '      (symbol "R_0_1" (pin passive line (at 0 0 0)) (pin passive line (at 0 0 0)))\n'
    '    )\n'
    '  )\n'
)


def _write_sch(path, *symbols, lib_symbols=_LIBSYMS_R2):
    body = "(kicad_sch\n" + lib_symbols + "".join(symbols) + ")\n"
    path.write_text(body, encoding="utf-8")
    return path


def test_audit_flags_the_core_issues_and_excludes_power(tmp_path):
    sch = _write_sch(
        tmp_path / "board.kicad_sch",
        _sym("Device:R", "R1", "10k", "Resistor_SMD:R_0402", '(property "MPN" "RC0402FR-0710KL" (at 0 0 0))'),
        _sym("Device:C", "C1", "100n", ""),  # no footprint + no MPN
        _sym("Device:R", "R?", "1k", "Resistor_SMD:R_0402"),  # unannotated
        _sym("power:GND", "#PWR01", "GND"),  # excluded (power)
    )
    au = audit_schematic(sch)
    assert au["components"] == 3  # power symbol excluded
    kinds = {(f["ref"], f["kind"]) for f in au["findings"]}
    assert ("R?", "unannotated") in kinds
    assert ("C1", "no_footprint") in kinds
    assert ("C1", "no_mpn") in kinds
    # R1 is fully specified => not flagged
    assert not any(f["ref"] == "R1" for f in au["findings"])
    assert au["counts"]["by_severity"]["error"] >= 1  # the unannotated one
    assert au["healthy"] == 1  # only R1 has no findings


def test_duplicate_reference_is_an_error(tmp_path):
    sch = _write_sch(
        tmp_path / "dup.kicad_sch",
        _sym("Device:R", "R1", "10k", "Resistor_SMD:R_0402", '(property "MPN" "A" (at 0 0 0))'),
        _sym("Device:R", "R1", "10k", "Resistor_SMD:R_0402", '(property "MPN" "A" (at 0 0 0))'),
    )
    au = audit_schematic(sch)
    dup = [f for f in au["findings"] if f["kind"] == "duplicate_ref"]
    assert len(dup) == 1
    assert dup[0]["ref"] == "R1"
    assert dup[0]["severity"] == "error"


def test_audit_project_spans_sheets_and_counts_them(tmp_path):
    s1 = _write_sch(
        tmp_path / "root.kicad_sch",
        _sym("Device:R", "R1", "10k", "Resistor_SMD:R_0402", '(property "MPN" "A" (at 0 0 0))'),
    )
    s2 = _write_sch(
        tmp_path / "power.kicad_sch",
        _sym("Device:C", "C?", "1u", ""),  # unannotated + no footprint on the second sheet
    )
    au = audit_project([s1, s2])
    assert au["sheets"] == 2
    assert au["components"] == 2
    kinds = {(f["ref"], f["kind"]) for f in au["findings"]}
    assert ("C?", "unannotated") in kinds
    assert ("C?", "no_footprint") in kinds


def test_pin_pad_mismatch_and_missing_model(tmp_path):
    # a footprint library dir with a 3-pad R_0402 (mismatched against the 2-pin symbol)
    fp_dir = tmp_path / "footprints"
    fp_dir.mkdir()
    (fp_dir / "R_0402.kicad_mod").write_text(
        '(footprint "R_0402" (pad "1" smd rect) (pad "2" smd rect) (pad "3" smd rect))',
        encoding="utf-8",
    )
    model_dir = tmp_path / "models"
    model_dir.mkdir()  # empty => the footprint's (model) is missing on disk (none referenced here)
    sch = _write_sch(
        tmp_path / "board.kicad_sch",
        _sym("Device:R", "R1", "10k", "Resistor_SMD:R_0402", '(property "MPN" "A" (at 0 0 0))'),
    )
    au = audit_schematic(sch, footprint_dirs=[fp_dir], model_dirs=[model_dir])
    kinds = {(f["ref"], f["kind"]) for f in au["findings"]}
    assert ("R1", "pin_pad_mismatch") in kinds  # 2 pins vs 3 pads
    assert au["checked_footprints"] == 1


def test_audit_report_markdown_is_shareable(tmp_path):
    sch = _write_sch(
        tmp_path / "board.kicad_sch",
        _sym("Device:R", "R?", "1k", ""),
    )
    md = audit_report_markdown(audit_schematic(sch))
    assert md.startswith("# Project Health")
    assert "Errors" in md
    assert "R?" in md


def test_report_says_no_issues_when_clean(tmp_path):
    sch = _write_sch(
        tmp_path / "clean.kicad_sch",
        _sym("Device:R", "R1", "10k", "Resistor_SMD:R_0402", '(property "MPN" "A" (at 0 0 0))'),
    )
    au = audit_schematic(sch)
    assert au["findings"] == []
    assert "No issues found." in audit_report_markdown(au)


def test_non_kicad_or_empty_file_is_empty(tmp_path):
    p = tmp_path / "notsch.kicad_sch"
    p.write_text("(kicad_pcb (setup))", encoding="utf-8")
    au = audit_schematic(p)
    assert au["components"] == 0
    assert au["findings"] == []
