from __future__ import annotations

from dataclasses import dataclass

from stockroom.capture import guided
from stockroom.capture.identity import page_identity, select_exact_candidate
from stockroom.capture.vendors import VendorCapability
from stockroom.ingest.staging import StagingCandidate


@dataclass
class _Record:
    id: str = "SR-TEST-0001"
    mpn: str = "TPD6E05U06RVZR"
    manufacturer: str = "Texas Instruments"


def _candidate(
    mpn: str = "",
    *,
    symbol_name: str = "",
    manufacturer: str = "",
    entry_name: str = "original-entry",
) -> StagingCandidate:
    return StagingCandidate(
        vendor="test",
        symbol_lib_path=None,
        symbol_name=symbol_name,
        footprint_variants=[],
        mpn=mpn,
        manufacturer=manufacturer,
        entry_name=entry_name,
    )


def test_snapmagic_detail_url_decodes_exact_identity():
    identity = page_identity(
        "snapmagic",
        (
            "https://www.snapeda.com/parts/TPD6E05U06RVZR/"
            "Texas%2520Instruments/view-part/"
        ),
    )

    assert identity is not None
    assert identity.mpn == "TPD6E05U06RVZR"
    assert identity.manufacturer == "Texas Instruments"


def test_digikey_product_and_samacsys_detail_urls_decode_exact_identity():
    detail_url = (
        "https://www.digikey.com/en/products/detail/texas-instruments/"
        "TPD6E05U06RVZR/2094564"
    )
    digikey = page_identity("digikey-ultralibrarian", detail_url)
    digikey_snapmagic = page_identity("digikey-snapmagic", detail_url)
    digikey_traceparts = page_identity("digikey-traceparts", detail_url)
    samacsys = page_identity(
        "samacsys",
        (
            "https://componentsearchengine.com/part-view/TPD6E05U06RVZR/"
            "Texas%20Instruments"
        ),
    )

    assert digikey is not None
    assert (digikey.mpn, digikey.manufacturer) == (
        "TPD6E05U06RVZR",
        "texas-instruments",
    )
    assert digikey_snapmagic == digikey
    assert digikey_traceparts == digikey
    assert samacsys is not None
    assert (samacsys.mpn, samacsys.manufacturer) == (
        "TPD6E05U06RVZR",
        "Texas Instruments",
    )


def test_selector_chooses_the_matching_candidate_instead_of_the_first():
    wrong = _candidate("TPD6E05U06RVZ", manufacturer="Texas Instruments")
    right = _candidate(symbol_name="TPD6E05U06RVZR", manufacturer="Texas Instruments")

    selection = select_exact_candidate(
        _Record(),
        [wrong, right],
        vendor_key="snapmagic",
        detail_url=(
            "https://www.snapeda.com/parts/TPD6E05U06RVZR/"
            "Texas%20Instruments/view-part/"
        ),
    )

    assert selection.error == ""
    assert selection.candidate is right
    assert right.entry_name == "original-entry"


def test_selector_rejects_a_near_match_without_renaming_it():
    candidate = _candidate(
        symbol_name="TPD6E05U06RVZ",
        manufacturer="Texas Instruments",
    )

    selection = select_exact_candidate(
        _Record(),
        [candidate],
        vendor_key="unknown",
        detail_url="https://example.invalid/result",
    )

    assert selection.candidate is None
    assert "exact candidate" in selection.error
    assert candidate.entry_name == "original-entry"


def test_selector_rejects_a_vendor_page_for_the_wrong_manufacturer():
    candidate = _candidate(symbol_name="TPD6E05U06RVZR")

    selection = select_exact_candidate(
        _Record(),
        [candidate],
        vendor_key="ultralibrarian",
        detail_url=(
            "https://app.ultralibrarian.com/details/a-guid/"
            "Analog%20Devices/TPD6E05U06RVZR"
        ),
    )

    assert selection.candidate is None
    assert "Analog Devices" in selection.error
    assert "Texas Instruments" in selection.error


def test_selector_rejects_multiple_exact_candidates():
    first = _candidate("TPD6E05U06RVZR", manufacturer="Texas Instruments")
    second = _candidate(symbol_name="TPD6E05U06RVZR", manufacturer="Texas Instruments")

    selection = select_exact_candidate(
        _Record(),
        [first, second],
        vendor_key="unknown",
        detail_url="",
    )

    assert selection.candidate is None
    assert "refusing to choose by file order" in selection.error


def test_altium_only_download_requires_an_exact_recognized_provider_page():
    exact = select_exact_candidate(
        _Record(),
        [],
        vendor_key="snapmagic",
        detail_url=(
            "https://www.snapeda.com/parts/TPD6E05U06RVZR/"
            "Texas%20Instruments/view-part/"
        ),
    )
    unknown = select_exact_candidate(
        _Record(),
        [],
        vendor_key="snapmagic",
        detail_url="https://www.snapeda.com/search/?q=TPD6E05U06RVZR",
    )

    assert exact.error == ""
    assert unknown.candidate is None
    assert "Altium-only" in unknown.error


def test_guided_attach_does_not_call_either_attach_seam_on_identity_failure(
    monkeypatch,
    tmp_path,
):
    candidate = _candidate(
        symbol_name="TPD6E05U06RVZ",
        manufacturer="Texas Instruments",
    )
    kicad_attaches: list[object] = []
    altium_attaches: list[object] = []

    class _Pipeline:
        def inspect(self, inputs):
            return [candidate]

        def attach_assets(self, *args, **kwargs):
            kicad_attaches.append((args, kwargs))

        def cleanup(self):
            return None

    capability = VendorCapability(
        key="faketron",
        label="Faketron",
        tools=("kicad", "altium"),
        formats_exclusive=False,
        aggregator=False,
        needs_login=False,
        instruction="",
        version_pins={"kicad": "kicad", "altium": "altium"},
    )
    monkeypatch.setattr(
        guided,
        "get_adapter",
        lambda key: type("_Adapter", (), {"capability": capability})(),
    )
    source = guided.GuidedCaptureSource(
        lambda: _Pipeline(),
        vendor="faketron",
        download_root=tmp_path,
        attach_altium=lambda *args, **kwargs: altium_attaches.append((args, kwargs)),
    )

    outcome = source._attach(
        _Record(),
        [],
        "https://example.invalid/search",
        detail_url="",
    )

    assert outcome.error and "exact candidate" in outcome.error
    assert not kicad_attaches
    assert not altium_attaches
    assert candidate.entry_name == "original-entry"


def test_guided_attach_rejects_mixed_digikey_route_receipts(monkeypatch, tmp_path):
    capability = VendorCapability(
        key="digikey",
        label="DigiKey CAD Models",
        tools=("kicad", "altium"),
        formats_exclusive=True,
        aggregator=True,
        needs_login=True,
        instruction="",
        machine_format_labels={"kicad": "KiCad v6+"},
    )
    monkeypatch.setattr(
        guided,
        "get_adapter",
        lambda _key: type(
            "_Adapter",
            (),
            {
                "capability": capability,
                "evidence_provider_key": "digikey-ultralibrarian",
            },
        )(),
    )
    source = guided.GuidedCaptureSource(
        lambda: (_ for _ in ()).throw(AssertionError("mixed routes must fail before inspect")),
        vendor="digikey",
        download_root=tmp_path,
    )
    landed = [
        type("_Receipt", (), {"evidence_provider_key": "digikey-snapmagic"})(),
        type("_Receipt", (), {"evidence_provider_key": "digikey-ultralibrarian"})(),
    ]

    outcome = source._attach(
        _Record(),
        landed,
        "https://www.digikey.com/en/products/result?keywords=TPD6E05U06RVZR",
        evidence_provider_key="digikey-snapmagic",
    )

    assert "route attribution mismatch" in outcome.error
