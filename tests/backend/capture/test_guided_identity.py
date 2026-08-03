from __future__ import annotations

from dataclasses import dataclass

from stockroom.capture import guided
from stockroom.capture.identity import (
    PageIdentity,
    exact_catalog_observation_error,
    exact_observation_error,
    page_identity,
    provider_url_allowed,
    select_exact_candidate,
)
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
        ("https://www.snapeda.com/parts/TPD6E05U06RVZR/Texas%2520Instruments/view-part/"),
    )

    assert identity is not None
    assert identity.mpn == "TPD6E05U06RVZR"
    assert identity.manufacturer == "Texas Instruments"


def test_digikey_snapmagic_route_accepts_the_external_author_detail_identity():
    identity = page_identity(
        "digikey-snapmagic",
        "https://www.snapeda.com/parts/TPS62130RGTR/Texas%20Instruments/view-part/",
    )

    assert identity is not None
    assert identity.mpn == "TPS62130RGTR"
    assert identity.manufacturer == "Texas Instruments"


def test_digikey_product_and_samacsys_detail_urls_decode_exact_identity():
    detail_url = (
        "https://www.digikey.com/en/products/detail/texas-instruments/TPD6E05U06RVZR/2094564"
    )
    digikey = page_identity("digikey-ultralibrarian", detail_url)
    digikey_snapmagic = page_identity("digikey-snapmagic", detail_url)
    digikey_traceparts = page_identity("digikey-traceparts", detail_url)
    digikey_manufacturer = page_identity("digikey-manufacturer", detail_url)
    digikey_cadenas = page_identity("digikey-cadenas", detail_url)
    samacsys = page_identity(
        "samacsys",
        ("https://componentsearchengine.com/part-view/TPD6E05U06RVZR/Texas%20Instruments"),
    )

    assert digikey is not None
    assert (digikey.mpn, digikey.manufacturer) == (
        "TPD6E05U06RVZR",
        "texas-instruments",
    )
    assert digikey_snapmagic == digikey
    assert digikey_traceparts == digikey
    assert digikey_manufacturer == digikey
    assert digikey_cadenas == digikey
    assert samacsys is not None
    assert (samacsys.mpn, samacsys.manufacturer) == (
        "TPD6E05U06RVZR",
        "Texas Instruments",
    )


def test_exact_observation_accepts_only_a_provable_manufacturer_abbreviation():
    record = _Record()

    assert (
        exact_observation_error(
            record,
            PageIdentity(mpn=record.mpn, manufacturer="TI"),
        )
        == ""
    )
    assert "manufacturer" in exact_observation_error(
        record,
        PageIdentity(mpn=record.mpn, manufacturer="Toshiba"),
    )


def test_selector_chooses_the_matching_candidate_instead_of_the_first():
    wrong = _candidate("TPD6E05U06RVZ", manufacturer="Texas Instruments")
    right = _candidate(symbol_name="TPD6E05U06RVZR", manufacturer="Texas Instruments")

    selection = select_exact_candidate(
        _Record(),
        [wrong, right],
        vendor_key="snapmagic",
        detail_url=("https://www.snapeda.com/parts/TPD6E05U06RVZR/Texas%20Instruments/view-part/"),
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


def test_exact_task_bound_page_accepts_one_archive_candidate_without_repeated_mpn():
    candidate = _candidate(
        symbol_name="SOT-23-5",
        manufacturer="TI",
    )

    selection = select_exact_candidate(
        _Record(mpn="SN74LVC1G08DBVR", manufacturer="Texas Instruments"),
        [candidate],
        vendor_key="ultralibrarian",
        detail_url=(
            "https://app.ultralibrarian.com/details/catalogue/"
            "Texas-Instruments/SN74LVC1G08DBVR"
        ),
    )

    assert selection.error == ""
    assert selection.candidate is candidate


def test_exact_task_bound_page_owns_the_archive_despite_stale_internal_identity():
    candidate = _candidate(
        "OTHER-PART",
        manufacturer="Texas Instruments",
    )

    selection = select_exact_candidate(
        _Record(mpn="SN74LVC1G08DBVR", manufacturer="Texas Instruments"),
        [candidate],
        vendor_key="ultralibrarian",
        detail_url=(
            "https://app.ultralibrarian.com/details/catalogue/"
            "Texas-Instruments/SN74LVC1G08DBVR"
        ),
    )

    assert selection.error == ""
    assert selection.candidate is candidate


def test_manual_picker_cannot_give_a_wrong_archive_the_open_pages_identity():
    candidate = _candidate(
        "OTHER-PART",
        manufacturer="Texas Instruments",
    )

    selection = select_exact_candidate(
        _Record(mpn="SN74LVC1G08DBVR", manufacturer="Texas Instruments"),
        [candidate],
        vendor_key="ultralibrarian",
        detail_url=(
            "https://app.ultralibrarian.com/details/catalogue/"
            "Texas-Instruments/SN74LVC1G08DBVR"
        ),
        trust_detail_url=False,
    )

    assert selection.candidate is None
    assert "exact candidate" in selection.error


def test_digikey_snapmagic_does_not_select_the_unsupported_snapmagic_domain():
    url = "https://www.snapmagic.com/parts/TPD6E05U06RVZR/Texas-Instruments/view-part/"

    assert provider_url_allowed("digikey-snapmagic", url) is False
    assert page_identity("digikey-snapmagic", url) is None


def test_selector_rejects_a_vendor_page_for_the_wrong_manufacturer():
    candidate = _candidate(symbol_name="TPD6E05U06RVZR")

    selection = select_exact_candidate(
        _Record(),
        [candidate],
        vendor_key="ultralibrarian",
        detail_url=(
            "https://app.ultralibrarian.com/details/a-guid/Analog%20Devices/TPD6E05U06RVZR"
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
        detail_url=("https://www.snapeda.com/parts/TPD6E05U06RVZR/Texas%20Instruments/view-part/"),
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
    )

    outcome = source._attach(
        _Record(),
        [],
        "https://example.invalid/search",
        detail_url="",
    )

    assert outcome.error and "exact candidate" in outcome.error
    assert not kicad_attaches
    assert candidate.entry_name == "original-entry"


def test_guided_manual_picker_rejects_wrong_archive_even_on_the_exact_provider_page(
    monkeypatch,
    tmp_path,
):
    wrong = _candidate("OTHER-PART", manufacturer="Texas Instruments")
    selected = tmp_path / "OTHER-PART.kicad_sym"
    selected.write_text("manual archive", encoding="utf-8")

    class _Pipeline:
        def inspect(self, inputs):
            assert inputs == [selected]
            return [wrong]

        def cleanup(self):
            return None

    capability = VendorCapability(
        key="snapmagic",
        label="SnapMagic",
        tools=("kicad", "altium"),
        formats_exclusive=True,
        aggregator=False,
        needs_login=True,
        instruction="",
        version_pins={"kicad": "kicad", "altium": "altium"},
    )
    monkeypatch.setattr(
        guided,
        "get_adapter",
        lambda _key: type("_Adapter", (), {"capability": capability})(),
    )
    source = guided.GuidedCaptureSource(
        lambda: _Pipeline(),
        vendor="snapmagic",
        download_root=tmp_path,
    )
    receipt = type("_Receipt", (), {"path": selected})()

    outcome = source._attach(
        _Record(),
        [receipt],
        "https://www.snapeda.com/parts/TPD6E05U06RVZR/Texas%20Instruments/view-part/",
        detail_url=(
            "https://www.snapeda.com/parts/TPD6E05U06RVZR/"
            "Texas%20Instruments/view-part/"
        ),
        manual_identity_paths=(selected,),
    )

    assert "manually selected CAD was not attached" in outcome.error
    assert "exact candidate" in outcome.error


def test_catalog_authorized_manual_file_uses_the_same_task_bound_selection(
    monkeypatch,
    tmp_path,
):
    generated = _candidate("generic-package-name", manufacturer="")
    selected = tmp_path / "provider-download.zip"
    selected.write_text("task-bound provider archive", encoding="utf-8")

    class _Pipeline:
        def inspect(self, inputs):
            assert inputs == [selected]
            return [generated]

        def cleanup(self):
            return None

    capability = VendorCapability(
        key="ultralibrarian",
        label="Ultra Librarian",
        tools=("kicad", "altium"),
        formats_exclusive=True,
        aggregator=False,
        needs_login=True,
        instruction="",
        version_pins={"kicad": "kicad", "altium": "altium"},
    )
    monkeypatch.setattr(
        guided,
        "get_adapter",
        lambda _key: type("_Adapter", (), {"capability": capability})(),
    )
    source = guided.GuidedCaptureSource(
        lambda: _Pipeline(),
        vendor="ultralibrarian",
        download_root=tmp_path,
    )
    monkeypatch.setattr(
        source,
        "_retain_incomplete_cad_set",
        lambda *_args, **_kwargs: guided.SourceOutcome(retained=1),
    )
    receipt = type("_Receipt", (), {"path": selected})()

    outcome = source._attach(
        _Record(),
        [receipt],
        "https://app.ultralibrarian.com/details/catalog/Texas-Instruments/TPD6E05U06RVZR",
        detail_url=(
            "https://app.ultralibrarian.com/details/catalog/"
            "Texas-Instruments/TPD6E05U06RVZR"
        ),
        manual_identity_paths=(selected,),
        catalog_identity_authorized=True,
    )

    assert outcome.retained == 1
    assert outcome.error == ""


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
    def receipt(provider_key: str):
        return type(
            "_Receipt",
            (),
            {
                "task_id": _Record.id,
                "manufacturer_key": _Record.manufacturer,
                "mpn_canonical": _Record.mpn,
                "surface_key": "digikey",
                "evidence_provider_key": provider_key,
            },
        )()

    landed = [
        receipt("digikey-snapmagic"),
        receipt("digikey-ultralibrarian"),
    ]

    outcome = source._attach(
        _Record(),
        landed,
        "https://www.digikey.com/en/products/result?keywords=TPD6E05U06RVZR",
        evidence_provider_key="digikey-snapmagic",
    )

    assert "binding mismatch for evidence provider key" in outcome.error


@dataclass
class _Requested:
    mpn: str
    manufacturer: str


def test_a_legal_entity_form_is_not_a_different_manufacturer():
    """"Abracon LLC" and "Abracon" are one company, and an exact MPN match must survive it.

    Distributor records carry the registered form; model libraries usually carry the brand. The
    owner's own ABM13W-32.0000MHZ-5-DH7G-T5 is stored as "Abracon LLC" while Ultra Librarian
    lists "Abracon", and the exact-MPN candidate was being discarded over that alone, reported
    as "showed the requested MPN only under a different manufacturer".
    """
    requested = _Requested(mpn="ABM13W-32.0000MHZ-5-DH7G-T5", manufacturer="Abracon LLC")
    observed = PageIdentity(mpn="ABM13W-32.0000MHZ-5-DH7G-T5", manufacturer="Abracon")

    assert exact_observation_error(requested, observed) == ""


def test_entity_forms_do_not_merge_unrelated_manufacturers():
    """The guard still fails closed: this is what stops another vendor's footprint landing."""
    requested = _Requested(mpn="PART-1", manufacturer="Abracon LLC")
    for other in ("Aptina", "Maruwa", "Toshiba", "Semiconductor Components"):
        observed = PageIdentity(mpn="PART-1", manufacturer=other)
        assert exact_observation_error(requested, observed) != "", other


def test_a_bare_entity_form_identifies_nobody():
    """"LLC" must never compare equal to a real manufacturer, however it normalizes."""
    requested = _Requested(mpn="PART-1", manufacturer="LLC")
    observed = PageIdentity(mpn="PART-1", manufacturer="Abracon")

    assert exact_observation_error(requested, observed) != ""


def test_a_url_slug_separator_does_not_reject_an_exact_part():
    """Ultra Librarian publishes ABM13W-32.0000MHZ-5-DH7G-T5 with the period slugged to a hyphen.

    The observed identity is parsed out of a detail URL, so the separator was already lost before
    this comparison ran. Demanding punctuation fidelity from a lossy carrier rejected an exact
    match on every MPN containing a period, and the caller then reported it as a MANUFACTURER
    mismatch, which is a different fault entirely.
    """
    requested = _Requested(mpn="ABM13W-32.0000MHZ-5-DH7G-T5", manufacturer="Abracon LLC")
    observed = PageIdentity(mpn="ABM13W-32-0000MHZ-5-DH7G-T5", manufacturer="Abracon")

    assert exact_observation_error(requested, observed) == ""


def test_candidate_gate_uses_the_shared_slug_aware_page_identity():
    requested = _Record(
        id="abm13w",
        mpn="ABM13W-32.0000MHZ-5-DH7G-T5",
        manufacturer="Abracon LLC",
    )

    selection = select_exact_candidate(
        requested,
        [],
        vendor_key="ultralibrarian",
        detail_url=(
            "https://app.ultralibrarian.com/details/catalogue/Abracon/"
            "ABM13W-32-0000MHZ-5-DH7G-T5"
        ),
    )

    assert selection.error == ""


def test_slug_folding_never_merges_two_different_parts():
    """Only separators fold. Alphanumerics, their order, and separator POSITIONS still bind."""
    requested = _Requested(mpn="ABM13W-32.0000MHZ", manufacturer="Abracon")
    for other in (
        "ABM13W-33-0000MHZ",  # a different frequency
        "ABM13W320000MHZ",  # separator dropped entirely, not substituted
        "ABM13W-32-0000MHZ-X",  # an extra segment
    ):
        observed = PageIdentity(mpn=other, manufacturer="Abracon")
        assert exact_observation_error(requested, observed) != "", other


def test_exact_catalog_route_may_recover_punctuation_lost_by_provider_url_slugs():
    requested = _Requested(
        mpn="MAX17608ATC+",
        manufacturer="Analog Devices / Maxim Integrated",
    )

    for observed_mpn in ("MAX17608ATC-", "MAX17608ATC"):
        observed = PageIdentity(
            mpn=observed_mpn,
            manufacturer="Analog Devices Inc Maxim Integrated",
        )
        assert exact_observation_error(requested, observed) != ""
        assert exact_catalog_observation_error(requested, observed) == ""


def test_exact_catalog_route_still_rejects_a_different_alphanumeric_mpn():
    requested = _Requested(
        mpn="MAX17608ATC+",
        manufacturer="Analog Devices / Maxim Integrated",
    )
    observed = PageIdentity(
        mpn="MAX17609ATC-",
        manufacturer="Analog Devices Inc Maxim Integrated",
    )

    assert exact_catalog_observation_error(requested, observed) != ""


def test_catalog_authorized_detail_url_survives_provider_slug_punctuation_loss():
    requested = _Record(
        id="max17608atc-373c",
        mpn="MAX17608ATC+",
        manufacturer="Analog Devices / Maxim Integrated",
    )

    selection = select_exact_candidate(
        requested,
        [],
        vendor_key="ultralibrarian",
        detail_url=(
            "https://app.ultralibrarian.com/details/fixture/"
            "Analog-Devices-Inc/MAX17608ATC-?ref=digikey"
        ),
        catalog_identity_authorized=True,
    )

    assert selection.error == ""


def test_a_trailing_descriptor_is_not_a_different_manufacturer():
    """A model library lists the brand; a distributor record appends what it trades under.

    Murata Electronics, Vishay Intertechnology, Nexperia USA and Wurth Elektronik eiSos are each
    one company with the catalogue's own suffix, and every one of them was discarding an exact
    MPN match and sending the person to do the part by hand.
    """
    for stored, listed in (
        ("Murata Electronics", "Murata"),
        ("Vishay Intertechnology Inc.", "Vishay"),
        ("Nexperia USA Inc.", "Nexperia"),
        ("Wurth Elektronik eiSos", "Wurth Elektronik"),
    ):
        requested = _Requested(mpn="PART-1", manufacturer=stored)
        observed = PageIdentity(mpn="PART-1", manufacturer=listed)
        assert exact_observation_error(requested, observed) == "", (stored, listed)


def test_a_differing_first_word_is_still_a_different_manufacturer():
    """Leading-words only. A trailing difference is a descriptor; a leading one is a company."""
    for stored, listed in (
        ("Micro", "Microchip"),  # a truncation the shared abbreviation proof used to accept
        ("ON Semiconductor", "Semiconductor Components"),
        ("Texas Instruments", "Texas Advanced Optoelectronic"),
        ("Murata", "Maruwa"),
    ):
        requested = _Requested(mpn="PART-1", manufacturer=stored)
        observed = PageIdentity(mpn="PART-1", manufacturer=listed)
        assert exact_observation_error(requested, observed) != "", (stored, listed)


def test_a_real_initialism_still_resolves():
    """TI is not a truncation of TexasInstruments, so the abbreviation proof still applies."""
    requested = _Requested(mpn="PART-1", manufacturer="Texas Instruments")
    observed = PageIdentity(mpn="PART-1", manufacturer="TI")
    assert exact_observation_error(requested, observed) == ""


def test_a_real_initialism_resolves_against_a_provider_url_slug_in_either_direction():
    """A provider's hyphens are presentation, not extra identity-bearing name content."""
    for requested_name, observed_name in (
        ("TI", "Texas-Instruments"),
        ("Texas Instruments", "TI"),
    ):
        requested = _Requested(mpn="PART-1", manufacturer=requested_name)
        observed = PageIdentity(mpn="PART-1", manufacturer=observed_name)
        assert exact_observation_error(requested, observed) == "", (
            requested_name,
            observed_name,
        )
