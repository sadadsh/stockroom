"""Serving the bytes of a document this part holds.

The route exists so a datasheet can be READ inside the app instead of handed to a browser. That
makes it the one place in the library API that returns file bytes, so most of these tests are
about what it refuses: it resolves an id through the record's own documents and never joins a
caller-supplied path, it will not serve a path that leaves the library root even when the record
asks it to, and the three ways a document can be absent are three honest 404s rather than a
stack trace.
"""

from __future__ import annotations

from stockroom.dossier.documents import build_documents
from stockroom.model.part import Datasheet, PartDocument, PartRecord

_PART = "erj-p03f1101v"
_PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n"


def _add_part(app_ctx, *, documents=None, datasheet=None) -> PartRecord:
    record = PartRecord(
        id=_PART,
        mpn="ERJ-P03F1101V",
        manufacturer="Panasonic",
        display_name="ERJ-P03F1101V",
        category="Resistors",
        description="RES 1.1K OHM 1% 1/5W 0603 thick film",
        specs={"Resistance": "1.1 kOhms"},
    )
    record.documents = list(documents or [])
    record.datasheet = datasheet
    path = app_ctx.profile.library.parts_dir / f"{record.id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.dumps(), encoding="utf-8")
    app_ctx.rebuild_index()
    return record


def _store(app_ctx, name: str, payload: bytes = _PDF) -> None:
    directory = app_ctx.profile.library.datasheets_dir
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(payload)


def _document_id(record: PartRecord, title: str) -> str:
    for item in build_documents(record)["items"]:
        if item["title"] == title:
            return item["id"]
    raise AssertionError(f"the record serves no document titled {title!r}")


def _url(document_id: str, part_id: str = _PART) -> str:
    return f"/api/library/parts/{part_id}/documents/{document_id}/file"


def _stored_datasheet() -> PartDocument:
    return PartDocument(
        document_type="datasheet",
        title="Datasheet",
        revision="C",
        source_type="manufacturer",
        source="digikey",
        local_path="datasheets/erj.pdf",
        mime_type="application/pdf",
        retrieved_at="2026-08-05T00:00:00+00:00",
    )


# --------------------------------------------------------------- serving


def test_reading_a_document_requires_a_token(anon_client, app_ctx):
    record = _add_part(app_ctx, documents=[_stored_datasheet()])
    _store(app_ctx, "erj.pdf")
    assert anon_client.get(_url(_document_id(record, "Datasheet"))).status_code == 401


def test_a_stored_datasheet_is_served_with_its_real_content_type(client, app_ctx):
    record = _add_part(app_ctx, documents=[_stored_datasheet()])
    _store(app_ctx, "erj.pdf")
    response = client.get(_url(_document_id(record, "Datasheet")))
    assert response.status_code == 200
    assert response.content == _PDF
    assert response.headers["content-type"].startswith("application/pdf")


def test_a_stored_datasheet_is_served_for_reading_rather_than_downloading(client, app_ctx):
    record = _add_part(app_ctx, documents=[_stored_datasheet()])
    _store(app_ctx, "erj.pdf")
    response = client.get(_url(_document_id(record, "Datasheet")))
    assert response.headers["content-disposition"].startswith("inline")


def test_the_legacy_datasheet_slot_is_reachable_by_its_bare_filename(client, app_ctx):
    record = _add_part(app_ctx, datasheet=Datasheet(file="erj.pdf"))
    _store(app_ctx, "erj.pdf")
    response = client.get(_url(_document_id(record, "Datasheet")))
    assert response.status_code == 200
    assert response.content == _PDF


def test_the_id_a_document_is_served_under_is_the_one_the_dossier_published(client, app_ctx):
    record = _add_part(app_ctx, documents=[_stored_datasheet()])
    _store(app_ctx, "erj.pdf")
    published = client.get(f"/api/library/parts/{_PART}/dossier").json()["documents"]["items"]
    assert client.get(_url(published[0]["id"])).status_code == 200
    assert published[0]["id"] == _document_id(record, "Datasheet")


# --------------------------------------------------------------- refusals


def test_an_id_this_part_references_no_document_for_is_not_found(client, app_ctx):
    _add_part(app_ctx, documents=[_stored_datasheet()])
    _store(app_ctx, "erj.pdf")
    assert client.get(_url("0000000000000000")).status_code == 404


def test_a_document_of_another_part_is_not_reachable_through_this_one(client, app_ctx):
    record = _add_part(app_ctx, documents=[_stored_datasheet()])
    _store(app_ctx, "erj.pdf")
    other = client.get(_url(_document_id(record, "Datasheet"), part_id="tps62130"))
    assert other.status_code == 404


def test_a_document_of_an_unknown_part_is_not_found(client, app_ctx):
    record = _add_part(app_ctx, documents=[_stored_datasheet()])
    assert client.get(_url(_document_id(record, "Datasheet"), part_id="nope")).status_code == 404


def test_a_url_only_document_says_to_open_its_source_instead(client, app_ctx):
    record = _add_part(
        app_ctx,
        documents=[
            PartDocument(
                document_type="datasheet",
                title="Datasheet",
                source_type="manufacturer",
                remote_url="https://industrial.panasonic.com/erj.pdf",
            )
        ],
    )
    response = client.get(_url(_document_id(record, "Datasheet")))
    assert response.status_code == 404
    assert "source page" in response.json()["detail"]


def test_a_stored_file_that_has_gone_missing_is_reported_not_crashed(client, app_ctx):
    record = _add_part(app_ctx, documents=[_stored_datasheet()])
    response = client.get(_url(_document_id(record, "Datasheet")))
    assert response.status_code == 404
    assert "no longer in the library" in response.json()["detail"]


def test_a_recorded_path_that_climbs_out_of_the_library_is_refused(client, app_ctx, tmp_path):
    """The path is record data, not request data - and it is still refused.

    A record can be wrong, hand-edited, or written by a build with a bug, and a projection is not
    a permission check. Nothing outside the library root is readable through this route however
    the path got onto the record.
    """
    secret = tmp_path / "secret.pdf"
    secret.write_bytes(b"%PDF-1.4\nnot yours\n")
    record = _add_part(
        app_ctx,
        documents=[
            PartDocument(
                document_type="datasheet",
                title="Datasheet",
                local_path="../../../../../../../../secret.pdf",
            )
        ],
    )
    response = client.get(_url(_document_id(record, "Datasheet")))
    assert response.status_code == 404
    assert response.content != secret.read_bytes()


def test_an_absolute_recorded_path_is_refused(client, app_ctx, tmp_path):
    secret = tmp_path / "secret.pdf"
    secret.write_bytes(b"%PDF-1.4\nnot yours\n")
    record = _add_part(
        app_ctx,
        documents=[
            PartDocument(
                document_type="datasheet", title="Datasheet", local_path=secret.as_posix()
            )
        ],
    )
    assert client.get(_url(_document_id(record, "Datasheet"))).status_code == 404


def test_a_traversal_in_the_document_id_reaches_no_file(client, app_ctx):
    _add_part(app_ctx, documents=[_stored_datasheet()])
    _store(app_ctx, "erj.pdf")
    # An id is matched against the record's own documents, so it is never a path fragment. The
    # route below does not even exist as a shape; what matters is that no file comes back.
    for attempt in ("..%2F..%2Fsecret.pdf", "....//secret.pdf", "datasheets%2Ferj.pdf"):
        response = client.get(_url(attempt))
        assert response.status_code == 404
        assert response.content != _PDF


def test_no_filesystem_path_appears_in_a_refusal(client, app_ctx):
    record = _add_part(app_ctx, documents=[_stored_datasheet()])
    detail = client.get(_url(_document_id(record, "Datasheet"))).json()["detail"]
    assert "datasheets" not in detail
    assert str(app_ctx.profile.library.root) not in detail
