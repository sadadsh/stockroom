"""Provider coverage answers "which provider can give me everything for this part?".

Every status here has to be earned. The tests below exist because the failure mode is not a
crash: it is a table that quietly says `not_available` when nobody asked, or `available` because
a page exists, or `validated` for a file whose check failed. Each of those reads as a fact and
is not one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from stockroom.dossier import DATA_DESTINATIONS, component_dossier
from stockroom.evidence import EvidenceArtifact, EvidenceStore
from stockroom.ingest.candidates import ValidationOutcome
from stockroom.model.asset import Asset, AssetOrigin, AssetRef
from stockroom.model.part import PartRecord, ProviderAssertion, Purchase
from stockroom.model.trust import AssetCheck
from stockroom.provider_coverage import (
    _VALIDATED_OUTCOMES,
    COVERAGE_ARTIFACTS,
    COVERAGE_ORIGINS,
    COVERAGE_STATUSES,
    provider_coverage,
    registry_key,
    set_user_assertion,
)
from stockroom.providers import all_providers, search_url


@dataclass(frozen=True)
class _Identity:
    authoritative_manufacturer_key: str = "ON Semiconductor"
    mpn_canonical: str = "S1M"


@dataclass(frozen=True)
class _Operation:
    label: str


_IDENTITY = _Identity()
_KICAD_OP = _Operation("cad:kicad")


def _record(**overrides) -> PartRecord:
    base = {
        "id": "s1m-0000",
        "mpn": "S1M",
        "manufacturer": "ON Semiconductor",
        "display_name": "S1M",
        "category": "Diodes",
        "description": "Surface mount rectifier",
    }
    base.update(overrides)
    return PartRecord(**base)


def _rows(document) -> dict[str, dict]:
    return {row["id"]: row for row in document["rows"]}


def _statuses(document, provider: str) -> dict[str, str]:
    row = _rows(document)[provider]
    return {artifact: row[artifact]["status"] for artifact in COVERAGE_ARTIFACTS}


def _catalog(**availability) -> dict:
    return {"digikey": {"schema_version": 1, "availability": availability}}


# ------------------------------------------------------------------ evidence fixtures


def _role_report(*, provider: str, roles: tuple[str, ...], operation: str) -> bytes:
    return json.dumps(
        {
            "identity": {
                "authoritative_manufacturer_key": _IDENTITY.authoritative_manufacturer_key,
                "mpn_canonical": _IDENTITY.mpn_canonical,
            },
            "operation": operation,
            "provider": provider,
            "roles": sorted(roles),
            "schema": "stockroom.cad-role-validation/1",
            "source_manifests": [],
            "valid": True,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _record_bundle(store: EvidenceStore, *, provider: str, artifacts: dict[str, bytes]) -> str:
    return store.record_role_artifact_success(
        identity=_IDENTITY,
        operation=_KICAD_OP,
        provider_key=provider,
        adapter_version="browser-v1",
        artifacts=tuple(
            EvidenceArtifact(role, data, "application/octet-stream", f"S1M-{role}.bin")
            for role, data in artifacts.items()
        ),
        validation_report=_role_report(
            provider=provider,
            roles=tuple(artifacts),
            operation=_KICAD_OP.label,
        ),
    )


def _kicad_bytes() -> dict[str, bytes]:
    return {
        "symbol": b'(kicad_symbol_lib (version 20231120) (generator "Stockroom"))',
        "footprint": b'(footprint "S1M" (version 20240108) (generator "Stockroom"))',
        "model": b"ISO-10303-21;\nEND-ISO-10303-21;\n",
    }


def _asset(vendor: str, *, checks=()) -> Asset:
    return Asset(
        ref=AssetRef(lib="Diodes", name="S1M", file="Diodes.kicad_sym"),
        origin=AssetOrigin(vendor=vendor),
        checks=list(checks),
    )


# ------------------------------------------------------------------ the default


def test_a_component_nobody_measured_reports_unknown_everywhere():
    document = provider_coverage(_record())
    for row in document["rows"]:
        for artifact in COVERAGE_ARTIFACTS:
            assert row[artifact]["status"] == "unknown"
            assert row[artifact]["origin"] == ""


def test_every_registered_provider_gets_a_row_and_no_others():
    document = provider_coverage(_record())
    assert [row["id"] for row in document["rows"]] == [p.key for p in all_providers()]


def test_the_vocabulary_is_exactly_the_five_statuses():
    assert COVERAGE_STATUSES == (
        "unknown",
        "available",
        "not_available",
        "downloaded",
        "validated",
    )
    assert set(provider_coverage(_record())["statuses"]) == set(COVERAGE_STATUSES)


def test_no_row_carries_a_confidence_number():
    row = _rows(provider_coverage(_record()))["digikey"]
    for artifact in COVERAGE_ARTIFACTS:
        assert set(row[artifact]) == {"status", "origin", "userAssertion"}
        assert row[artifact]["origin"] in ("", *COVERAGE_ORIGINS)


# ------------------------------------------------------------------ catalogue evidence


def test_catalogue_naming_a_provider_and_an_artifact_sets_available():
    record = _record(
        catalog=_catalog(
            cad_model=True,
            three_d_model=True,
            providers=["Ultra Librarian"],
        )
    )
    document = provider_coverage(record)
    assert _statuses(document, "ultralibrarian") == {
        "symbol": "available",
        "footprint": "available",
        "model": "available",
    }
    assert _rows(document)["ultralibrarian"]["symbol"]["origin"] == "official_api"


def test_the_probing_distributor_answers_for_itself_too():
    record = _record(catalog=_catalog(cad_model=True, three_d_model=None, providers=[]))
    assert _statuses(provider_coverage(record), "digikey") == {
        "symbol": "available",
        "footprint": "available",
        "model": "unknown",
    }


def test_a_none_probe_stays_unknown_and_never_becomes_not_available():
    record = _record(
        catalog=_catalog(cad_model=None, three_d_model=None, providers=["Ultra Librarian"])
    )
    document = provider_coverage(record)
    assert set(_statuses(document, "digikey").values()) == {"unknown"}
    assert set(_statuses(document, "ultralibrarian").values()) == {"unknown"}


def test_a_false_probe_is_a_real_answer_for_the_surface_that_ran_it():
    record = _record(catalog=_catalog(cad_model=False, three_d_model=False, providers=[]))
    assert set(_statuses(provider_coverage(record), "digikey").values()) == {"not_available"}


def test_a_false_probe_is_never_spread_onto_a_library_that_never_probed():
    record = _record(
        catalog=_catalog(cad_model=False, three_d_model=False, providers=["SnapMagic"])
    )
    assert set(_statuses(provider_coverage(record), "snapmagic").values()) == {"unknown"}


def test_a_provider_page_existing_is_not_evidence_that_the_part_is_there():
    """A media link naming Ultra Librarian is a page, not a claim about this part."""
    record = _record(
        catalog={
            "digikey": {
                "media": [
                    {
                        "title": "Ultra Librarian",
                        "url": "https://app.ultralibrarian.com/details/abc",
                        "media_type": "EDA Models",
                    }
                ]
            }
        }
    )
    document = provider_coverage(record)
    assert set(_statuses(document, "ultralibrarian").values()) == {"unknown"}
    # ... and yet the page is still reachable, which is the whole point of listing it.
    assert _rows(document)["ultralibrarian"]["url"] == "https://app.ultralibrarian.com/details/abc"
    assert _rows(document)["ultralibrarian"]["urlKind"] == "evidence"


def test_catalogue_evidence_never_claims_an_artifact_the_provider_does_not_author():
    record = _record(
        catalog=_catalog(cad_model=True, three_d_model=True, providers=["TraceParts"])
    )
    assert _statuses(provider_coverage(record), "traceparts") == {
        "symbol": "unknown",
        "footprint": "unknown",
        "model": "available",
    }


# ------------------------------------------------------------------ downloads


def test_an_installed_asset_from_a_provider_reads_downloaded():
    record = _record()
    record.assets_for("kicad").symbol = _asset("ultralibrarian")
    document = provider_coverage(record)
    row = _rows(document)["ultralibrarian"]
    assert row["symbol"]["status"] == "downloaded"
    assert row["symbol"]["origin"] == "native_download"
    assert row["footprint"]["status"] == "unknown"


def test_a_retained_native_download_reads_downloaded(tmp_path: Path):
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    _record_bundle(store, provider="snapmagic", artifacts={"symbol": b"(kicad_symbol_lib)"})
    document = provider_coverage(_record(), evidence=store, identity=_IDENTITY)
    row = _rows(document)["snapmagic"]
    assert row["symbol"]["status"] == "downloaded"
    assert row["symbol"]["origin"] == "native_download"


def test_an_acquisition_surface_prefix_resolves_to_the_library_that_authored_it(tmp_path: Path):
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    _record_bundle(
        store,
        provider="digikey-ultralibrarian",
        artifacts={"symbol": b"(kicad_symbol_lib)"},
    )
    document = provider_coverage(_record(), evidence=store, identity=_IDENTITY)
    assert _rows(document)["ultralibrarian"]["symbol"]["status"] == "downloaded"


def test_registry_key_places_every_spelling_a_provider_arrives_under():
    assert registry_key("ultralibrarian") == "ultralibrarian"
    assert registry_key("digikey-ultralibrarian") == "ultralibrarian"
    assert registry_key("Ultra Librarian") == "ultralibrarian"
    assert registry_key("DigiKey") == "digikey"
    assert registry_key("some-library-nobody-registered") == ""


# ------------------------------------------------------------------ validation


def test_a_successful_inspection_reads_validated():
    record = _record()
    record.assets_for("kicad").symbol = _asset(
        "ultralibrarian",
        checks=[AssetCheck(check="pins_vs_datasheet", measured=2, expected=2, against="rev C")],
    )
    row = _rows(provider_coverage(record))["ultralibrarian"]
    assert row["symbol"]["status"] == "validated"
    assert row["symbol"]["origin"] == "validator"


def test_a_failed_check_does_not_leave_the_artifact_validated():
    record = _record()
    record.assets_for("kicad").symbol = _asset(
        "ultralibrarian",
        checks=[AssetCheck(check="pins_vs_datasheet", measured=2, expected=8, against="rev C")],
    )
    row = _rows(provider_coverage(record))["ultralibrarian"]
    assert row["symbol"]["status"] == "downloaded"
    assert row["symbol"]["origin"] == "native_download"


def test_a_check_that_could_not_measure_does_not_become_validated():
    record = _record()
    record.assets_for("kicad").symbol = _asset(
        "ultralibrarian",
        checks=[AssetCheck(check="pins_vs_datasheet", measured=None, expected=8)],
    )
    assert _rows(provider_coverage(record))["ultralibrarian"]["symbol"]["status"] == "downloaded"


def test_a_complete_reverified_bundle_reads_validated(tmp_path: Path):
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    _record_bundle(store, provider="ultralibrarian", artifacts=_kicad_bytes())
    document = provider_coverage(_record(), evidence=store, identity=_IDENTITY)
    row = _rows(document)["ultralibrarian"]
    assert {row[artifact]["status"] for artifact in COVERAGE_ARTIFACTS} == {"validated"}
    assert row["kicad"]["summary"] == "3/3"


def test_tampered_evidence_still_fails_rather_than_reporting_coverage(tmp_path: Path):
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    _record_bundle(store, provider="ultralibrarian", artifacts=_kicad_bytes())
    target = store.object_path(
        f"sha256:{__import__('hashlib').sha256(_kicad_bytes()['symbol']).hexdigest()}"
    )
    target.write_bytes(b"(kicad_symbol_lib (version 1))")
    with pytest.raises(Exception):
        provider_coverage(_record(), evidence=store, identity=_IDENTITY)


# ------------------------------------------------------------------ retained candidates


@dataclass
class _Candidate:
    component_id: str
    provider_id: str
    artifact_kind: str
    detected_format: str
    validation_result: str
    manual_review_required: bool = False
    rejected: bool = False


def test_the_validated_outcome_strings_match_the_ingest_vocabulary():
    assert _VALIDATED_OUTCOMES == {
        ValidationOutcome.READY_TO_IMPORT.value,
        ValidationOutcome.IMPORTED.value,
    }


def test_an_inspected_retained_candidate_reads_validated():
    candidate = _Candidate(
        component_id="s1m-0000",
        provider_id="samacsys",
        artifact_kind="symbol",
        detected_format="kicad_symbol_library",
        validation_result=ValidationOutcome.READY_TO_IMPORT.value,
    )
    document = provider_coverage(_record(), candidates=[candidate])
    assert _rows(document)["samacsys"]["symbol"]["status"] == "validated"


def test_a_candidate_awaiting_a_person_is_downloaded_but_not_validated():
    candidate = _Candidate(
        component_id="s1m-0000",
        provider_id="samacsys",
        artifact_kind="footprint",
        detected_format="kicad_footprint",
        validation_result=ValidationOutcome.MANUAL_REVIEW_REQUIRED.value,
        manual_review_required=True,
    )
    document = provider_coverage(_record(), candidates=[candidate])
    assert _rows(document)["samacsys"]["footprint"]["status"] == "downloaded"


def test_a_rejected_candidate_proves_nothing():
    candidate = _Candidate(
        component_id="s1m-0000",
        provider_id="samacsys",
        artifact_kind="symbol",
        detected_format="kicad_symbol_library",
        validation_result=ValidationOutcome.INVALID_FILE.value,
        rejected=True,
    )
    document = provider_coverage(_record(), candidates=[candidate])
    assert _rows(document)["samacsys"]["symbol"]["status"] == "unknown"


def test_a_candidate_for_another_component_never_leaks_into_this_one():
    candidate = _Candidate(
        component_id="another-part",
        provider_id="samacsys",
        artifact_kind="symbol",
        detected_format="kicad_symbol_library",
        validation_result=ValidationOutcome.IMPORTED.value,
    )
    document = provider_coverage(_record(), candidates=[candidate])
    assert _rows(document)["samacsys"]["symbol"]["status"] == "unknown"


# ------------------------------------------------------------------ user corrections


def test_a_user_correction_sets_available_and_is_attributed_to_the_person():
    record = _record()
    set_user_assertion(
        record,
        provider="snapmagic",
        artifact="model",
        status="available",
        noted_at="2026-08-04T00:00:00Z",
    )
    row = _rows(provider_coverage(record))["snapmagic"]
    assert row["model"]["status"] == "available"
    assert row["model"]["origin"] == "user"
    assert row["model"]["userAssertion"] == {
        "status": "available",
        "origin": "user",
        "notedAt": "2026-08-04T00:00:00Z",
        "note": "",
        "applied": True,
    }


def test_a_user_correction_can_say_not_available_over_a_catalogue_claim():
    record = _record(
        catalog=_catalog(cad_model=True, three_d_model=None, providers=["SnapMagic"])
    )
    assert _statuses(provider_coverage(record), "snapmagic")["symbol"] == "available"
    set_user_assertion(record, provider="snapmagic", artifact="symbol", status="not_available")
    row = _rows(provider_coverage(record))["snapmagic"]
    assert row["symbol"]["status"] == "not_available"
    assert row["symbol"]["origin"] == "user"


def test_a_user_correction_cannot_downgrade_a_downloaded_artifact():
    record = _record()
    record.assets_for("kicad").symbol = _asset("ultralibrarian")
    set_user_assertion(
        record, provider="ultralibrarian", artifact="symbol", status="not_available"
    )
    row = _rows(provider_coverage(record))["ultralibrarian"]
    assert row["symbol"]["status"] == "downloaded"
    assert row["symbol"]["origin"] == "native_download"
    # The disagreement is kept and shown rather than discarded.
    assert row["symbol"]["userAssertion"]["applied"] is False
    assert row["symbol"]["userAssertion"]["status"] == "not_available"


def test_a_user_correction_cannot_downgrade_a_validated_artifact():
    record = _record()
    record.assets_for("kicad").footprint = _asset(
        "ultralibrarian",
        checks=[AssetCheck(check="pads_vs_package", measured=2, expected=2, against="MO-220")],
    )
    set_user_assertion(
        record, provider="ultralibrarian", artifact="footprint", status="not_available"
    )
    row = _rows(provider_coverage(record))["ultralibrarian"]
    assert row["footprint"]["status"] == "validated"
    assert row["footprint"]["userAssertion"]["applied"] is False


def test_a_person_may_not_assert_a_status_only_bytes_can_prove():
    record = _record()
    for status in ("downloaded", "validated", "unknown"):
        with pytest.raises(ValueError):
            set_user_assertion(
                record, provider="snapmagic", artifact="model", status=status
            )


def test_an_unknown_provider_or_artifact_is_loud_rather_than_a_silent_no_op():
    record = _record()
    with pytest.raises(KeyError):
        set_user_assertion(
            record, provider="not-a-provider", artifact="model", status="available"
        )
    with pytest.raises(ValueError):
        set_user_assertion(record, provider="snapmagic", artifact="netlist", status="available")


def test_an_empty_status_withdraws_a_previous_claim():
    record = _record()
    set_user_assertion(record, provider="snapmagic", artifact="model", status="available")
    set_user_assertion(record, provider="snapmagic", artifact="model", status="")
    assert record.provider_assertions == {}
    assert _statuses(provider_coverage(record), "snapmagic")["model"] == "unknown"


# ------------------------------------------------------------------ summaries and sort


def test_the_tool_summaries_count_out_of_three():
    record = _record()
    empty = _rows(provider_coverage(record))["ultralibrarian"]
    assert empty["kicad"]["summary"] == "0/3"
    assert empty["altium"]["summary"] == "0/3"
    assert empty["complete"] is False

    record.assets_for("kicad").symbol = _asset("ultralibrarian")
    assert _rows(provider_coverage(record))["ultralibrarian"]["kicad"]["summary"] == "1/3"

    record.assets_for("kicad").footprint = _asset("ultralibrarian")
    assert _rows(provider_coverage(record))["ultralibrarian"]["kicad"]["summary"] == "2/3"

    record.assets_for("kicad").model = _asset("ultralibrarian")
    row = _rows(provider_coverage(record))["ultralibrarian"]
    assert row["kicad"]["summary"] == "3/3"
    assert row["kicad"]["complete"] is True
    assert row["kicad"]["total"] == 3


def test_a_provider_supplying_all_three_is_identifiable_as_complete():
    record = _record(
        catalog=_catalog(cad_model=True, three_d_model=True, providers=["SamacSys"])
    )
    document = provider_coverage(record)
    assert _rows(document)["samacsys"]["complete"] is True
    # DigiKey ran the probe, so its own page carries the set too; both are honest answers.
    assert document["completeProviders"] == ["digikey", "samacsys"]
    assert _rows(document)["cadenas"]["complete"] is False


def test_a_provider_with_no_tool_export_reports_zero_of_three_honestly():
    record = _record(catalog=_catalog(cad_model=None, three_d_model=True, providers=["CADENAS"]))
    row = _rows(provider_coverage(record))["cadenas"]
    assert row["model"]["status"] == "available"
    assert row["kicad"] == {
        "count": 0,
        "total": 3,
        "summary": "0/3",
        "complete": False,
        "supported": False,
    }


def test_validated_sorts_above_downloaded_above_available_above_registry_order():
    record = _record(
        catalog=_catalog(cad_model=True, three_d_model=None, providers=["SnapMagic"])
    )
    # SamacSys is validated, Mouser holds bytes, SnapMagic is only named by the catalogue.
    record.assets_for("kicad").symbol = _asset(
        "samacsys",
        checks=[AssetCheck(check="pins_vs_datasheet", measured=2, expected=2, against="rev C")],
    )
    record.assets_for("altium").symbol = _asset("mouser")
    order = [row["id"] for row in provider_coverage(record)["rows"]]
    # DigiKey ran the probe, so it is explicitly-available for two artifacts exactly as
    # SnapMagic is, and the tie is broken by the registry's own order rather than at random.
    assert order[:4] == ["samacsys", "mouser", "digikey", "snapmagic"]
    # Everything with nothing recorded keeps the registry's declared order.
    assert order[4:] == [
        p.key
        for p in all_providers()
        if p.key not in {"samacsys", "mouser", "digikey", "snapmagic"}
    ]


def test_with_no_evidence_at_all_the_order_is_the_registry_order():
    assert [row["id"] for row in provider_coverage(_record())["rows"]] == [
        p.key for p in all_providers()
    ]


# ------------------------------------------------------------------ provider access


def test_a_provider_with_a_search_surface_is_reachable_by_mpn():
    row = _rows(provider_coverage(_record()))["digikey"]
    assert row["url"] == search_url("digikey", "S1M")
    assert row["urlKind"] == "search"


def test_a_provider_with_no_measured_search_surface_reports_no_url():
    document = provider_coverage(_record())
    for key in ("manufacturer", "traceparts", "cadenas"):
        row = _rows(document)[key]
        assert row["url"] == ""
        assert row["urlKind"] == ""


def test_an_mpn_carrying_url_characters_is_encoded_rather_than_mangled():
    row = _rows(provider_coverage(_record(mpn="MAX6817EUT+T")))["digikey"]
    assert "MAX6817EUT%2BT" in row["url"]


def test_a_catalogue_product_url_beats_a_search_url_for_that_distributor():
    record = _record(
        catalog={"digikey": {"product_url": "https://www.digikey.com/en/products/detail/1"}}
    )
    row = _rows(provider_coverage(record))["digikey"]
    assert row["url"] == "https://www.digikey.com/en/products/detail/1"
    assert row["urlKind"] == "evidence"


def test_a_stored_purchase_link_reaches_its_distributor():
    record = _record(
        purchase=[Purchase(vendor="Mouser", url="https://www.mouser.com/ProductDetail/1")]
    )
    row = _rows(provider_coverage(record))["mouser"]
    assert row["url"] == "https://www.mouser.com/ProductDetail/1"
    assert row["urlKind"] == "evidence"


def test_provider_rows_distinguish_task_bound_capture_from_a_useful_url():
    rows = _rows(provider_coverage(_record()))
    assert rows["ultralibrarian"]["captureAvailable"] is True
    assert rows["mouser"]["captureAvailable"] is False


def test_every_provider_carries_its_own_instruction_and_sign_in_fact():
    document = provider_coverage(_record())
    for provider in all_providers():
        row = _rows(document)[provider.key]
        assert row["instruction"] == provider.instruction
        assert row["needsLogin"] == provider.needs_login


# ------------------------------------------------------------------ persistence


def test_a_user_assertion_survives_a_record_round_trip():
    record = _record()
    set_user_assertion(
        record,
        provider="snapmagic",
        artifact="model",
        status="available",
        noted_at="2026-08-04T00:00:00Z",
        note="Downloaded it by hand last week.",
    )
    reloaded = PartRecord.loads(record.dumps())
    assertion = reloaded.provider_assertions["snapmagic"]["model"]
    assert assertion == ProviderAssertion(
        status="available",
        origin="user",
        noted_at="2026-08-04T00:00:00Z",
        note="Downloaded it by hand last week.",
    )


def test_a_record_with_no_assertions_does_not_gain_a_key():
    assert "provider_assertions" not in json.loads(_record().dumps())


def test_an_unknown_key_inside_a_stored_assertion_survives_a_rewrite():
    document = json.loads(_record().dumps())
    document["provider_assertions"] = {
        "snapmagic": {"model": {"status": "available", "origin": "user", "future": 7}}
    }
    reloaded = PartRecord.loads(json.dumps(document))
    assert reloaded.provider_assertions["snapmagic"]["model"].extra == {"future": 7}
    assert json.loads(reloaded.dumps())["provider_assertions"]["snapmagic"]["model"]["future"] == 7


def test_the_record_field_has_a_declared_product_destination():
    assert DATA_DESTINATIONS["provider_assertions"] == "cadSourceCoverage.rows"


# ------------------------------------------------------------------ dossier


def test_the_dossier_carries_provider_coverage_without_a_store():
    view = component_dossier(_record())
    assert [row["id"] for row in view["cadSourceCoverage"]["rows"]] == [
        p.key for p in all_providers()
    ]


def test_the_dossier_uses_the_coverage_a_caller_computed_with_a_store(tmp_path: Path):
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    _record_bundle(store, provider="ultralibrarian", artifacts=_kicad_bytes())
    record = _record()
    coverage = provider_coverage(record, evidence=store, identity=_IDENTITY)
    view = component_dossier(record, coverage=coverage)
    assert view["cadSourceCoverage"]["completeProviders"] == ["ultralibrarian"]
