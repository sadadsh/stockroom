from stockroom.ingest.naming import (
    propose_category,
    propose_display_name,
    propose_entry_name,
)
from stockroom.model.category import CATEGORIES


def test_entry_name_prefers_mpn():
    assert propose_entry_name("SYM_TIMESTAMP", "TPS62130RGTR") == "TPS62130RGTR"


def test_entry_name_falls_back_to_symbol_name():
    assert propose_entry_name("LM358", "") == "LM358"


def test_entry_name_sanitizes_forbidden_chars():
    out = propose_entry_name("weird {name} here", "")
    assert "{" not in out and "}" not in out and " " not in out


def test_entry_name_never_empty():
    assert propose_entry_name("", "") == "Part"


def test_display_name_prefers_mpn():
    assert propose_display_name("SYM", "MPN123") == "MPN123"


def test_category_keyword_heuristic():
    assert propose_category("0.1uF ceramic capacitor X7R") == "Capacitors"
    assert propose_category("USB Type-C connector receptacle") == "Connectors"
    assert propose_category("LDO voltage regulator IC") == "ICs"
    assert propose_category("something with no hint") == "Other"


def test_category_result_is_always_valid():
    assert propose_category("anything") in CATEGORIES


def test_category_matches_distributor_plural_category_strings():
    # Distributor "Product Category" strings are plural (Resistors, Capacitors, ...); the
    # classifier must match them, not fall through to Other (A4: non-passive categorization).
    assert propose_category("Thick Film Resistors - SMD") == "Resistors"
    assert propose_category("Ceramic Capacitors") == "Capacitors"
    assert propose_category("Rectangular Connectors - Headers, Male Pins") == "Connectors"
    assert propose_category("Fixed Inductors") == "Inductors"
    assert propose_category("Microcontrollers - MCU") == "ICs"


def test_led_driver_is_an_ic_not_a_diode():
    # "LED ... Driver" is a switching IC; "driver" must win over the bare "led" -> Diodes,
    # while a plain LED emitter still classifies as a diode (review finding).
    assert propose_category("LED Lighting Drivers") == "ICs"
    assert propose_category("LED Driver IC 40V 1.5A Buck") == "ICs"
    assert propose_category("Red LED 620nm") == "Diodes"
