"""Plan 03: verbatim port of the F0-F7 cited family tables (DATA-06).

Zero-logic, zero-risk structural + citation-integrity lock. families.py must NOT
be wired into any Phase 1 build code and must import nothing beyond stdlib.
"""

import ast
import inspect
from pathlib import Path

from stockroom.stm import families as families_mod

_F_KEYS = {"STM32F0", "STM32F1", "STM32F2", "STM32F3", "STM32F4", "STM32F7"}


def test_all_six_f_families_present_in_every_table():
    assert _F_KEYS <= set(families_mod.FAMILY_ELECTRICAL)
    assert _F_KEYS <= set(families_mod.FAMILY_POWER)
    assert _F_KEYS <= set(families_mod.FAMILY_NOT_5V)
    assert _F_KEYS <= set(families_mod.BOOTLOADER_PINS)


def test_spot_checked_value_matches_legacy_source_exactly():
    # legacy/tools/stm32_authority.py:181 - STM32F2 FAMILY_NOT_5V
    assert families_mod.FAMILY_NOT_5V["STM32F2"] == {"PA4", "PA5"}
    # legacy/tools/stm32_authority.py:187/188 - F4/F7 share the same pair
    assert families_mod.FAMILY_NOT_5V["STM32F4"] == {"PA4", "PA5"}
    assert families_mod.FAMILY_NOT_5V["STM32F7"] == {"PA4", "PA5"}
    # legacy/tools/stm32_authority.py:97 - STM32F0 electrical spec spot-check
    assert families_mod.FAMILY_ELECTRICAL["STM32F0"]["io_ma"] == 25
    assert families_mod.FAMILY_ELECTRICAL["STM32F0"]["ft_5v"] is True
    # legacy/tools/stm32_authority.py:154 - STM32F2 needs external VCAP caps
    assert families_mod.FAMILY_POWER["STM32F2"]["vcap"] is True
    assert families_mod.FAMILY_POWER["STM32F0"]["vcap"] is False


def test_osc_caveat_pins_ported():
    assert families_mod._OSC_CAVEAT_PINS == {"PC14", "PC15", "PH0", "PH1"}


def test_module_has_no_computation_no_five_v_no_netdeck_vocab():
    src = inspect.getsource(families_mod)
    for forbidden in ("def _five_v", "def _part_draw_ma", "switch_identity", "ADG714"):
        assert forbidden not in src, f"families.py must not contain {forbidden!r}"


def test_module_imports_only_stdlib():
    path = Path(families_mod.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed_modules = {"re", "__future__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name in allowed_modules, f"unexpected import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            assert node.module in allowed_modules, f"unexpected import from: {node.module}"


def test_families_not_referenced_from_db_geometry_or_source_modules():
    """families.py is a Phase 1 deliverable nothing in Phase 1 wires in yet -
    Phase 3's _five_v (stm/authority.py) is the first consumer."""
    from stockroom.stm import db as db_mod
    from stockroom.stm import geometry as geometry_mod
    from stockroom.stm import source as source_mod

    for mod in (db_mod, geometry_mod, source_mod):
        src = inspect.getsource(mod)
        assert "import families" not in src
        assert "stm.families" not in src
