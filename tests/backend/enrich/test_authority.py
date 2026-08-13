from stockroom.api.routers.enrich import _result_dto
from stockroom.dossier import component_dossier
from stockroom.enrich.apply import spec_updates
from stockroom.enrich.pipeline import _copy_specs, fill_category
from stockroom.enrich.schema import EnrichmentResult, Sourced
from stockroom.ingest.staging import StagingCandidate
from stockroom.model.part import EnrichmentField, PartRecord, SourcedValue


def _updates(result: EnrichmentResult) -> dict[str, tuple[object, str]]:
    return {key: (value, sourced.source) for key, value, sourced in spec_updates(result)}


def test_mouser_then_digikey_then_datasheet_are_the_only_specification_authorities():
    result = EnrichmentResult(category="Other")
    result.specs = {
        "Supply Voltage": Sourced("3.3 V", "lcsc", "medium"),
        "Only LCSC": Sourced("discard me", "lcsc", "medium"),
        "Only DigiKey": Sourced("keep me", "digikey", "high"),
        "Datasheet Fact": Sourced("verified", "datasheet", "high"),
    }
    result.spec_conflicts = {
        "Supply Voltage": [
            Sourced("3.3 V", "lcsc", "medium"),
            Sourced("4.5 V", "datasheet", "high"),
            Sourced("4.8 V", "digikey", "high"),
            Sourced("5 V", "mouser", "high"),
        ]
    }

    updates = _updates(result)

    assert updates["Supply Voltage"] == ("5 V", "mouser")
    assert updates["Only DigiKey"] == ("keep me", "digikey")
    assert updates["Datasheet Fact"] == ("verified", "datasheet")
    assert "Only LCSC" not in updates


def test_category_uses_the_same_mouser_first_authority_without_inventing_a_value():
    result = EnrichmentResult(category="Other")
    result.specs["Product Category"] = Sourced("Rectifier Diodes", "lcsc", "medium")
    result.spec_conflicts["Product Category"] = [
        Sourced("Rectifier Diodes", "lcsc", "medium"),
        Sourced("Analog Switch ICs", "mouser", "high"),
        Sourced("Integrated Circuits", "digikey", "high"),
    ]

    fill_category(result)

    assert result.category == "Switches"

    missing = EnrichmentResult(category="Other")
    missing.specs["Product Category"] = Sourced("Vendor Bucket 19", "lcsc", "medium")
    fill_category(missing)
    assert missing.category == "Other"


def test_result_dto_exposes_the_exact_selected_specs_the_add_commit_must_use():
    result = EnrichmentResult(category="Other")
    result.specs["Voltage"] = Sourced("3.3 V", "lcsc", "medium")
    result.spec_conflicts["Voltage"] = [
        Sourced("3.3 V", "lcsc", "medium"),
        Sourced("5 V", "mouser", "high"),
    ]
    result.lifecycle = Sourced("Active", "mouser", "high")

    selected = _result_dto(result)["selected_specs"]
    evidence = _result_dto(result)["selected_spec_conflicts"]

    assert selected["Voltage"] == {
        "value": "5 V",
        "source": "mouser",
        "confidence": "high",
    }
    assert selected["Lifecycle"]["value"] == "Active"
    assert [entry["source"] for entry in evidence["Voltage"]] == ["mouser"]


def test_add_commit_keeps_only_allowed_specification_evidence():
    result = EnrichmentResult(category="Other")
    result.specs["Supply Voltage"] = Sourced("3.3 V", "lcsc", "medium")
    result.spec_conflicts["Supply Voltage"] = [
        Sourced("3.3 V", "lcsc", "medium"),
        Sourced("4.5 V", "datasheet", "high"),
        Sourced("4.8 V", "digikey", "high"),
        Sourced("5 V", "mouser", "high"),
    ]
    candidate = StagingCandidate(
        vendor="network", symbol_lib_path=None, symbol_name="", footprint_variants=[]
    )

    _copy_specs(candidate, result, set())

    assert candidate.specs["Supply Voltage"] == "5 V"
    assert [item["source"] for item in candidate.alternates["Supply Voltage"]] == [
        "mouser",
        "digikey",
        "datasheet",
    ]


def test_opened_component_keeps_mouser_as_the_fixed_specification_winner():
    record = PartRecord(
        id="authority-0001",
        mpn="AUTHORITY-1",
        manufacturer="Example",
        display_name="AUTHORITY-1",
        category="ICs",
        description="Authority fixture",
        specs={"Supply Voltage": "5 V"},
        enrichment={
            "Supply Voltage": EnrichmentField(source="mouser", confidence="high")
        },
        alternates={
            "Supply Voltage": [
                SourcedValue(value="5 V", source="mouser", confidence="high"),
                SourcedValue(value="4.8 V", source="digikey", confidence="high"),
                SourcedValue(value="4.5 V", source="datasheet", confidence="high"),
            ]
        },
    )

    dossier = component_dossier(record)
    rows = [
        *dossier["keySpecifications"],
        *[
            item
            for group in dossier["specificationGroups"]
            for item in group["specifications"]
        ],
    ]
    voltage = next(item for item in rows if item["key"] == "supply_voltage")

    assert voltage["displayValue"] == "5 V"
    assert voltage["preferredSource"]["sourceId"] == "mouser"
    assert [item["sourceId"] for item in voltage["sourceCandidates"]] == [
        "mouser",
        "digikey",
        "datasheet",
    ]
