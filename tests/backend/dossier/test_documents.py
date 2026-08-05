"""Typed documents, and which datasheet a person should actually open."""

from __future__ import annotations

from stockroom.dossier import component_dossier
from stockroom.dossier.documents import build_documents, document_id
from stockroom.model.part import Datasheet, PartDocument, Provenance
from tests.backend.dossier import records


def _items(record) -> dict:
    return {
        (item["documentType"], item["remoteUrl"] or item["localPath"]): item
        for item in build_documents(record)["items"]
    }


# ------------------------------------------------------------------ the six shapes


def test_a_url_only_datasheet_is_referenced():
    record = records.resistor()
    record.datasheet = Datasheet(source_url="https://industrial.panasonic.com/ds.pdf")
    item = build_documents(record)["items"][0]
    assert item["documentType"] == "datasheet"
    assert item["status"] == "referenced"
    assert item["localPath"] == ""


def test_a_local_file_only_datasheet_is_stored_and_read_as_imported():
    record = records.resistor()
    record.datasheet = Datasheet(file="datasheets/erj.pdf")
    item = build_documents(record)["items"][0]
    assert item["status"] == "stored"
    assert item["sourceType"] == "imported"
    assert item["remoteUrl"] == ""


def test_a_datasheet_with_both_a_file_and_a_url_keeps_both():
    record = records.resistor()
    record.datasheet = Datasheet(
        file="datasheets/erj.pdf", source_url="https://industrial.panasonic.com/ds.pdf"
    )
    item = build_documents(record)["items"][0]
    assert item["localPath"] and item["remoteUrl"]


def test_an_html_product_page_is_typed_as_a_page_not_as_a_datasheet():
    record = records.resistor()
    record.datasheet = Datasheet(source_url="https://industrial.panasonic.com/datasheet-view")
    item = build_documents(record)["items"][0]
    assert item["documentType"] == "datasheet_page"
    assert item["mimeType"] == "text/html"


def test_a_part_with_no_datasheet_says_so_rather_than_omitting_the_section():
    documents = build_documents(records.resistor())
    assert documents["items"] == []
    assert documents["hasDatasheet"] is False
    assert documents["preferredDatasheet"] is None


def test_multiple_revisions_are_all_kept_and_only_the_newest_is_current():
    record = records.resistor()
    record.documents = [
        PartDocument(
            document_type="datasheet", title="Datasheet", revision="A",
            source_type="manufacturer", remote_url="https://panasonic.com/a.pdf",
        ),
        PartDocument(
            document_type="datasheet", title="Datasheet", revision="C",
            source_type="manufacturer", remote_url="https://panasonic.com/c.pdf",
        ),
    ]
    items = _items(record)
    assert len(items) == 2
    assert items[("datasheet", "https://panasonic.com/c.pdf")]["isCurrent"] is True
    assert items[("datasheet", "https://panasonic.com/a.pdf")]["isCurrent"] is False


def test_a_record_that_says_a_revision_is_superseded_is_believed():
    record = records.resistor()
    record.documents = [
        PartDocument(
            document_type="datasheet", title="Datasheet", revision="C", is_current=False,
            source_type="manufacturer", remote_url="https://panasonic.com/c.pdf",
        ),
    ]
    assert build_documents(record)["items"][0]["isCurrent"] is False


# ------------------------------------------------------------------ typing


def test_each_document_kind_is_typed_from_its_own_title():
    record = records.resistor()
    record.catalog = {
        "digikey": {
            "media": [
                {"title": "Package Outline Drawing", "url": "https://x.test/drawing.pdf"},
                {"title": "PCN 2026-04", "url": "https://x.test/pcn.pdf"},
                {"title": "RoHS Declaration", "url": "https://x.test/rohs.pdf"},
                {"title": "UL Certificate", "url": "https://x.test/cert.pdf"},
                {"title": "Application Note AN-42", "url": "https://x.test/an.pdf"},
            ]
        }
    }
    types = {item["documentType"] for item in build_documents(record)["items"]}
    assert types == {
        "package_drawing",
        "pcn",
        "compliance_declaration",
        "certificate",
        "application_note",
    }


def test_an_unrecognised_link_is_other_and_is_never_called_a_datasheet():
    record = records.resistor()
    record.catalog = {"digikey": {"media": [{"title": "Video", "url": "https://x.test/v"}]}}
    assert build_documents(record)["items"][0]["documentType"] == "other"


def test_an_import_package_is_its_own_document_type():
    record = records.resistor()
    record.provenance = Provenance(
        source="ultralibrarian", source_url="https://ul.test/p", original_zip_sha256="abc",
        ingested_at="2026-01-01",
    )
    item = build_documents(record)["items"][0]
    assert item["documentType"] == "attachment"
    assert item["status"] == "verified"


# ------------------------------------------------------------------ preferred order


def _preferred(record) -> tuple[str, str]:
    documents = build_documents(record)
    preferred = documents["preferredDatasheet"]
    return (preferred["remoteUrl"] or preferred["localPath"], documents["preferredDatasheetReason"])


def test_a_verified_local_manufacturer_pdf_wins_everything():
    record = records.resistor()
    record.documents = [
        PartDocument(document_type="datasheet", source_type="manufacturer",
                     local_path="datasheets/erj.pdf", verified_at="2026-01-01"),
        PartDocument(document_type="datasheet", source_type="manufacturer",
                     remote_url="https://industrial.panasonic.com/ds.pdf"),
        PartDocument(document_type="datasheet", source_type="distributor",
                     remote_url="https://www.mouser.com/ds.pdf"),
    ]
    url, reason = _preferred(record)
    assert url == "datasheets/erj.pdf"
    assert reason == "verified local manufacturer PDF"


def test_the_official_manufacturer_url_beats_a_distributor_copy():
    record = records.resistor()
    record.documents = [
        PartDocument(document_type="datasheet", source_type="distributor",
                     remote_url="https://www.mouser.com/ds.pdf"),
        PartDocument(document_type="datasheet", source_type="manufacturer",
                     remote_url="https://industrial.panasonic.com/ds.pdf"),
    ]
    url, reason = _preferred(record)
    assert url == "https://industrial.panasonic.com/ds.pdf"
    assert reason == "official manufacturer PDF URL"


def test_a_verified_imported_pdf_beats_a_distributor_copy():
    record = records.resistor()
    record.documents = [
        PartDocument(document_type="datasheet", source_type="distributor",
                     remote_url="https://www.mouser.com/ds.pdf"),
        PartDocument(document_type="datasheet", source_type="imported",
                     local_path="datasheets/erj.pdf", verified_at="2026-01-01"),
    ]
    assert _preferred(record)[1] == "verified imported PDF"


def test_a_distributor_copy_is_used_when_nothing_better_exists_and_says_so():
    record = records.resistor()
    record.documents = [
        PartDocument(document_type="datasheet", source_type="distributor",
                     remote_url="https://www.mouser.com/ds.pdf"),
    ]
    assert _preferred(record)[1] == "trusted distributor copy of the manufacturer PDF"


def test_any_other_referenced_document_is_the_last_resort():
    record = records.resistor()
    record.catalog = {"digikey": {"media": [{"title": "Video", "url": "https://x.test/v"}]}}
    assert _preferred(record)[1] == "other referenced document"


def test_only_one_document_is_ever_marked_preferred():
    record = records.resistor()
    record.documents = [
        PartDocument(document_type="datasheet", source_type="manufacturer",
                     remote_url="https://industrial.panasonic.com/a.pdf", revision="A"),
        PartDocument(document_type="datasheet", source_type="manufacturer",
                     remote_url="https://industrial.panasonic.com/b.pdf", revision="B"),
    ]
    items = build_documents(record)["items"]
    assert sum(1 for item in items if item["isPreferred"]) == 1


def test_the_dossier_carries_the_documents_region():
    record = records.resistor()
    record.datasheet = Datasheet(source_url="https://industrial.panasonic.com/ds.pdf")
    documents = component_dossier(record)["documents"]
    assert documents["count"] == 1
    assert documents["hasDatasheet"] is True


# ------------------------------------------------------------------ identity


def test_every_document_carries_an_id_derived_from_what_makes_it_that_document():
    record = records.resistor()
    record.documents = [
        PartDocument(document_type="datasheet", source_type="manufacturer",
                     remote_url="https://industrial.panasonic.com/a.pdf"),
        PartDocument(document_type="package_drawing", title="Package Outline",
                     remote_url="https://industrial.panasonic.com/b.pdf"),
    ]
    ids = [item["id"] for item in build_documents(record)["items"]]
    assert len(set(ids)) == 2
    assert all(id_ for id_ in ids)


def test_reading_one_record_twice_gives_a_document_the_same_id():
    record = records.resistor()
    record.datasheet = Datasheet(source_url="https://industrial.panasonic.com/ds.pdf")
    first = build_documents(record)["items"][0]["id"]
    assert build_documents(record)["items"][0]["id"] == first


def test_a_new_catalogue_link_never_renames_the_documents_beside_it():
    record = records.resistor()
    record.datasheet = Datasheet(source_url="https://industrial.panasonic.com/ds.pdf")
    before = build_documents(record)["items"][0]["id"]
    record.catalog = {"digikey": {"media": [{"title": "PCN 2026-04",
                                             "url": "https://x.test/pcn.pdf"}]}}
    after = {item["title"]: item["id"] for item in build_documents(record)["items"]}
    assert after["Datasheet"] == before


def test_a_typed_document_and_the_legacy_slot_for_one_file_are_one_row():
    """The legacy slot's bare filename means "under `datasheets/`", so the two spellings of one
    path are folded together and the typed entry - the only one that can name a revision - keeps
    the slot."""
    record = records.resistor()
    record.datasheet = Datasheet(file="erj.pdf")
    record.documents = [
        PartDocument(document_type="datasheet", revision="C", source_type="imported",
                     local_path="datasheets/erj.pdf")
    ]
    documents = build_documents(record)
    assert documents["count"] == 1
    assert documents["items"][0]["revision"] == "C"


def test_the_legacy_slot_reports_a_library_relative_path():
    record = records.resistor()
    record.datasheet = Datasheet(file="erj.pdf")
    assert build_documents(record)["items"][0]["localPath"] == "datasheets/erj.pdf"


def test_a_legacy_path_that_already_names_its_directory_is_left_alone():
    record = records.resistor()
    record.datasheet = Datasheet(file="datasheets/erj.pdf")
    assert build_documents(record)["items"][0]["localPath"] == "datasheets/erj.pdf"


def test_a_documents_id_is_derived_from_its_own_identity_and_nothing_else():
    """Five facts decide it: what the document is, who supplied it, which revision, and where
    it lives. Nothing about the LIST it happens to be in takes part, which is the whole reason
    an id can be handed back in a URL and still name the same document a second later."""
    base = ("datasheet", "digikey", "C", "", "https://x.test/ds.pdf")
    assert document_id(*base) == document_id(*base)
    assert document_id("datasheet", "digikey", "D", "", "https://x.test/ds.pdf") != document_id(
        *base
    )
    assert document_id("datasheet", "mouser", "C", "", "https://x.test/ds.pdf") != document_id(
        *base
    )
    assert document_id("package_drawing", "digikey", "C", "", "https://x.test/ds.pdf") != (
        document_id(*base)
    )
    assert document_id("datasheet", "digikey", "C", "datasheets/a.pdf", "") != document_id(*base)


def test_two_revisions_of_one_document_are_never_addressable_as_each_other():
    record = records.resistor()
    record.documents = [
        PartDocument(document_type="datasheet", title="Datasheet", revision="A",
                     source="digikey", remote_url="https://panasonic.com/a.pdf"),
        PartDocument(document_type="datasheet", title="Datasheet", revision="C",
                     source="digikey", remote_url="https://panasonic.com/c.pdf"),
    ]
    ids = [item["id"] for item in build_documents(record)["items"]]
    assert len(set(ids)) == 2


def test_two_sources_copies_of_one_document_are_never_addressable_as_each_other():
    record = records.resistor()
    record.documents = [
        PartDocument(document_type="datasheet", title="Datasheet", source="digikey",
                     remote_url="https://www.digikey.com/ds.pdf"),
        PartDocument(document_type="datasheet", title="Datasheet", source="mouser",
                     remote_url="https://www.mouser.com/ds.pdf"),
    ]
    ids = [item["id"] for item in build_documents(record)["items"]]
    assert len(set(ids)) == 2


def test_no_two_documents_on_one_part_share_an_id():
    record = records.resistor()
    record.datasheet = Datasheet(source_url="https://industrial.panasonic.com/ds.pdf")
    record.documents = [
        PartDocument(document_type="package_drawing", title="Outline", source="digikey",
                     remote_url="https://x.test/drawing.pdf"),
        PartDocument(document_type="datasheet", title="Datasheet", revision="C",
                     source="mouser", local_path="datasheets/erj.pdf"),
    ]
    record.catalog = {"digikey": {"media": [{"title": "PCN 2026-04",
                                             "url": "https://x.test/pcn.pdf"}]}}
    items = build_documents(record)["items"]
    assert len({item["id"] for item in items}) == len(items)


def test_adding_a_different_document_leaves_every_other_id_unchanged():
    """The exact case that breaks addressing by position: a document arrives, every index after
    it shifts, and a viewer opened a moment ago would fetch the wrong file."""
    record = records.resistor()
    record.documents = [
        PartDocument(document_type="datasheet", title="Datasheet", revision="C",
                     source="digikey", remote_url="https://panasonic.com/c.pdf"),
        PartDocument(document_type="package_drawing", title="Outline", source="digikey",
                     remote_url="https://panasonic.com/outline.pdf"),
    ]
    before = {item["title"]: item["id"] for item in build_documents(record)["items"]}
    record.documents.insert(
        0,
        PartDocument(document_type="application_note", title="AN-42", source="mouser",
                     remote_url="https://panasonic.com/an42.pdf"),
    )
    after = {item["title"]: item["id"] for item in build_documents(record)["items"]}
    assert before.items() <= after.items()


def test_an_id_needs_no_escaping_to_sit_in_a_url_path():
    record = records.resistor()
    record.datasheet = Datasheet(file="datasheets/erj.pdf")
    document = build_documents(record)["items"][0]
    assert document["id"].isalnum()
    assert document["id"] == document["id"].casefold()


def test_the_documents_read_primary_datasheet_first_whatever_order_they_were_stored_in():
    """Source order put an import package above the datasheet on any imported part.

    The list a person reads leads with the copy the header's Datasheet action opens, then takes
    the remaining kinds in the order they matter in - which is the order `DOCUMENT_TYPES` declares
    and never the order the record happened to accumulate them.
    """
    record = records.resistor()
    record.provenance = Provenance(
        source="ultralibrarian", source_url="https://ul.test/p", original_zip_sha256="abc",
        ingested_at="2026-01-01",
    )
    record.documents = [
        PartDocument(document_type="package_drawing", title="Outline",
                     remote_url="https://industrial.panasonic.com/drawing.pdf"),
        PartDocument(document_type="datasheet", title="Datasheet", source_type="manufacturer",
                     remote_url="https://industrial.panasonic.com/ds.pdf"),
    ]
    items = build_documents(record)["items"]
    assert [item["documentType"] for item in items] == [
        "datasheet",
        "package_drawing",
        "attachment",
    ]
    assert items[0]["isPreferred"] is True


def test_a_superseded_revision_sorts_under_the_current_one_it_supersedes():
    record = records.resistor()
    record.documents = [
        PartDocument(document_type="datasheet", title="Datasheet", revision="A",
                     source_type="manufacturer",
                     remote_url="https://industrial.panasonic.com/a.pdf"),
        PartDocument(document_type="datasheet", title="Datasheet", revision="B",
                     source_type="manufacturer",
                     remote_url="https://industrial.panasonic.com/b.pdf"),
    ]
    assert [item["revision"] for item in build_documents(record)["items"]] == ["B", "A"]
