from dataclasses import dataclass

from stockroom.capture.requirements import Requirement, capture_needs


@dataclass
class _Ref:
    name: str


@dataclass
class _Rec:
    _missing: list[str]
    altium_symbol: object = None
    altium_footprint: object = None

    def missing_assets(self) -> list[str]:
        return list(self._missing)


def test_requirement_values_match_contract():
    assert Requirement.KICAD_SYMBOL.value == "kicad_symbol"
    assert Requirement.KICAD_FOOTPRINT.value == "kicad_footprint"
    assert Requirement.KICAD_MODEL.value == "kicad_model"
    assert Requirement.ALTIUM_SYMBOL.value == "altium_symbol"
    assert Requirement.ALTIUM_FOOTPRINT.value == "altium_footprint"


def test_needs_maps_missing_kicad_labels():
    rec = _Rec(_missing=["symbol", "3D model"])
    needs = capture_needs(rec)
    assert Requirement.KICAD_SYMBOL in needs
    assert Requirement.KICAD_MODEL in needs
    assert Requirement.KICAD_FOOTPRINT not in needs


def test_needs_includes_altium_gaps_when_unset():
    rec = _Rec(_missing=[])
    needs = capture_needs(rec)
    assert Requirement.ALTIUM_SYMBOL in needs
    assert Requirement.ALTIUM_FOOTPRINT in needs


def test_needs_omits_altium_when_present():
    rec = _Rec(_missing=[], altium_symbol=_Ref("U1"), altium_footprint=_Ref("SOIC8"))
    needs = capture_needs(rec)
    assert Requirement.ALTIUM_SYMBOL not in needs
    assert Requirement.ALTIUM_FOOTPRINT not in needs


def test_needs_includes_altium_when_ref_present_but_name_blank():
    rec = _Rec(_missing=[], altium_symbol=_Ref(""), altium_footprint=_Ref(""))
    needs = capture_needs(rec)
    assert Requirement.ALTIUM_SYMBOL in needs
    assert Requirement.ALTIUM_FOOTPRINT in needs
