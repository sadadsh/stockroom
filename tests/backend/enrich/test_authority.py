from stockroom.api.routers.enrich import _result_dto
from stockroom.dossier import component_dossier
from stockroom.enrich.apply import spec_updates
from stockroom.enrich.pipeline import _copy_specs, fill_category, refile_category
from stockroom.enrich.schema import EnrichmentResult, Sourced
from stockroom.ingest.staging import StagingCandidate
from stockroom.model.part import EnrichmentField, PartRecord, SourcedValue


def _updates(result: EnrichmentResult) -> dict[str, tuple[object, str]]:
    return {key: (value, sourced.source) for key, value, sourced in spec_updates(result)}


def test_mouser_then_digikey_then_datasheet_are_the_only_specification_authorities():
    result = EnrichmentResult(category="Other")
    result.identity_authorities.append("manufacturer_datasheet")
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


def test_browser_copies_of_provider_pages_are_discovery_not_api_fact_authority():
    result = EnrichmentResult(category="Other")
    result.specs = {
        "Mouser Page Fact": Sourced("page", "mouser_web", "medium"),
        "DigiKey Page Fact": Sourced("page", "digikey_web", "medium"),
    }
    result.description = Sourced("Analog Switch ICs", "mouser_web", "medium")

    assert _updates(result) == {}
    fill_category(result)
    assert result.category == "Other"


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


def test_official_agreement_survives_an_earlier_discovery_value_for_specs_and_category():
    result = EnrichmentResult(category="Other")
    result.specs = {
        "Supply Voltage": Sourced("5 V", "lcsc", "medium"),
        "Product Category": Sourced("Analog Switch ICs", "lcsc", "medium"),
    }
    result.official_evidence["mouser"] = {
        "provider": "mouser",
        "queried_mpn": "PART-A",
        "canonical_mpn": "PART-A",
        "selected_values": {
            "Product Category": "Analog Switch ICs",
        },
    }
    result.official_evidence["digikey"] = {
        "provider": "digikey",
        "queried_mpn": "PART-A",
        "canonical_mpn": "PART-A",
        "selected_values": {"Supply Voltage": "5 V"},
    }

    assert _updates(result)["Supply Voltage"] == ("5 V", "digikey")
    assert _result_dto(result)["selected_spec_conflicts"]["Supply Voltage"] == [
        {"value": "5 V", "source": "digikey", "confidence": "high"}
    ]

    fill_category(result)
    assert result.category == "Switches"


def test_refile_ignores_discovery_classification_until_an_official_source_confirms_it():
    record = PartRecord(
        id="authority-legacy",
        mpn="PART-A",
        manufacturer="Example",
        display_name="PART-A",
        category="Other",
        description="Analog switch",
        specs={"Product Category": "Analog Switch ICs"},
        enrichment={
            "Product Category": EnrichmentField(source="lcsc", confidence="medium"),
            "description": EnrichmentField(source="scrape", confidence="low"),
        },
        alternates={
            "Product Category": [
                SourcedValue(value="Analog Switch ICs", source="lcsc", confidence="medium")
            ],
            "description": [
                SourcedValue(value="Analog switch", source="scrape", confidence="low")
            ],
        },
    )

    assert refile_category(record) == ""

    record.alternates["Product Category"].append(
        SourcedValue(value="Analog Switch ICs", source="digikey", confidence="high")
    )
    assert refile_category(record) == "Switches"


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


def test_result_dto_projects_identity_with_the_fixed_fact_authority():
    result = EnrichmentResult(category="ICs")
    result.manufacturer = Sourced("LCSC label", "lcsc", "medium")
    result.description = Sourced("Scraped description", "scrape", "low")
    result.datasheet_url = Sourced("https://lcsc.invalid/data.pdf", "lcsc", "medium")
    result.field_conflicts = {
        "manufacturer": [
            result.manufacturer,
            Sourced("DigiKey label", "digikey", "high"),
            Sourced("Mouser label", "mouser", "high"),
        ],
        "description": [
            result.description,
            Sourced("Datasheet description", "datasheet", "high"),
            Sourced("Mouser description", "mouser", "high"),
        ],
        "datasheet_url": [
            result.datasheet_url,
            Sourced("https://manufacturer.invalid/data.pdf", "datasheet", "high"),
            Sourced("https://digikey.invalid/data.pdf", "digikey", "high"),
        ],
    }

    dto = _result_dto(result)

    assert dto["manufacturer"] == {
        "value": "Mouser label",
        "source": "mouser",
        "confidence": "high",
    }
    assert dto["description"]["value"] == "Mouser description"
    assert dto["datasheet_url"]["value"] == "https://digikey.invalid/data.pdf"


def test_result_dto_uses_one_official_provider_and_rejects_discovery_only_identity():
    result = EnrichmentResult(category="Other")
    result.manufacturer = Sourced("Discovery manufacturer", "lcsc", "medium")
    result.description = Sourced("Discovery description", "scrape", "low")
    result.datasheet_url = Sourced("https://lcsc.invalid/data.pdf", "lcsc", "medium")
    result.official_evidence["digikey"] = {
        "provider": "digikey",
        "queried_mpn": "PART-A",
        "canonical_mpn": "PART-A",
        "selected_values": {
            "manufacturer": "Official manufacturer",
            "description": "Official description",
        },
    }

    dto = _result_dto(result)

    assert dto["manufacturer"]["value"] == "Official manufacturer"
    assert dto["manufacturer"]["source"] == "digikey"
    assert dto["description"]["value"] == "Official description"
    assert dto["datasheet_url"] is None
    assert dto["official_evidence"]["digikey"]["selected_values"] == {
        "manufacturer": "Official manufacturer",
        "description": "Official description",
    }


def test_result_dto_leaves_sparse_discovery_only_identity_missing():
    result = EnrichmentResult(category="Other")
    result.manufacturer = Sourced("Discovery manufacturer", "lcsc", "medium")
    result.description = Sourced("Discovery description", "scrape", "low")

    dto = _result_dto(result)

    assert dto["manufacturer"] is None
    assert dto["description"] is None
    assert dto["datasheet_url"] is None


def test_result_dto_rejects_datasheet_identity_until_the_pdf_matches_the_part():
    result = EnrichmentResult(category="Other")
    result.manufacturer = Sourced("Datasheet manufacturer", "datasheet", "high")

    assert _result_dto(result)["manufacturer"] is None


def test_unmatched_datasheet_cannot_fill_specifications_for_another_part():
    result = EnrichmentResult(category="Other")
    result.package = Sourced("QFN-32", "datasheet", "high")
    result.specs["Pin Count"] = Sourced("32", "datasheet", "high")

    assert _updates(result) == {}


def test_exact_manufacturer_datasheet_can_fill_only_identity_the_extractor_produced():
    result = EnrichmentResult(category="Other")
    result.manufacturer = Sourced("Datasheet manufacturer", "datasheet", "high")
    result.identity_authorities.append("manufacturer_datasheet")

    dto = _result_dto(result)

    assert dto["manufacturer"] == {
        "value": "Datasheet manufacturer",
        "source": "datasheet",
        "confidence": "high",
    }
    assert dto["description"] is None
    assert dto["datasheet_url"] is None


def test_add_commit_keeps_only_allowed_specification_evidence():
    result = EnrichmentResult(category="Other")
    result.identity_authorities.append("manufacturer_datasheet")
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
