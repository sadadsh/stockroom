"""Design Mode Phase 4: POST /api/dev/save writes the committed ARRANGEMENT, the deviation list that
travels with it, and the owner-authored copy provenance record.

The layout module is the sixth thing the save endpoint writes and the only one whose payload is a
TREE. Two properties carry the weight: the emitted module must ROUND-TRIP (the document that comes
back out of the generated text is the document that went in, or a redesign is corrupted silently on
its way to source), and a payload that is not a layout document must be refused before anything is
written.

THE SERVER-SIDE CHECK IS STRUCTURAL ONLY, and these tests are written to that boundary.
``validateLayout`` / ``validateDocument`` are frontend TypeScript and are deliberately not
re-implemented here - a second copy of the design rules in Python is the thing that drifts. The
backend proves the payload is JSON-serialisable and parses as a document (node kinds, required
fields, closed enums) and rebuilds it from validated fields; the DESIGN judgement is computed by the
frontend validator at save time and ships beside the document as ``committedIssues``.

WHAT GATES RUN, as a finding rather than an assumption: /api/dev/save runs none. It validates and
writes. The layout module joins the regime the other five slices have always used - path ownership
here, then ``POST /api/dev/publish``'s locked install + typecheck + production build, then CI. The
last test in this file pins the ownership half, which is the part that lives in this router.

---------------------------------------------------------------------------------------------
NON-VACUITY. Three mutations were run for real and reverted:

  1. THE EMITTED TEMPLATE WAS BROKEN. Removing the trailing ``;`` from ``_emit_layout`` failed
     ``test_dev_save_round_trips_a_committed_layout_document`` in ``_emitted_json`` - the round trip
     cannot find the end of the value. Changing the header's ``export const LAYOUT_OVERRIDES`` name
     fails the same test at the marker search.
  2. THE WRITER ECHOED RAW INPUT. Returning the payload document unchanged from
     ``_clean_layout_document`` failed ``test_dev_save_writes_only_validated_layout_fields``: the
     smuggled field reached the generated module.
  3. THE PROVENANCE RECORD WAS NOT CAPPED. Dropping the ``value in written_copy`` clause from
     ``_clean_owner_authored_copy`` failed
     ``test_dev_save_records_owner_authored_copy_ids_only_for_written_overrides`` - an id with no
     rewording became a standing letter-rule exemption.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import stockroom.api.routers.dev as dev_mod

_COMMITTED_LIB = Path(dev_mod.__file__).resolve().parents[4] / "frontend" / "src" / "lib"


def _src_with_lib(tmp_path, monkeypatch):
    src = tmp_path / "frontend" / "src"
    (src / "lib").mkdir(parents=True)
    monkeypatch.setattr(dev_mod, "_FRONTEND_SRC", src)
    return src


def _layout_document(document_id="workspace.component.redesigned"):
    """A small but complete document: a region with a splitter, a rich placement, an empty slot."""
    return {
        "schemaVersion": 1,
        "id": document_id,
        "root": {
            "kind": "region",
            "id": "workspace.root",
            "mode": "column",
            "devId": "workspace",
            "size": {"grow": True, "when": {"sparse": {"fraction": 0.5}}},
            "scroll": "vertical",
            "splitters": [
                {
                    "id": "workspace.split",
                    "between": ["workspace.slot.a", "workspace.slot.b"],
                    "keyStep": 16,
                    "lineThickness": 1,
                    "grabWidth": 9,
                    "persistenceKey": "workspace.split",
                }
            ],
            "slots": [
                {
                    "kind": "slot",
                    "id": "workspace.slot.a",
                    "content": {
                        "kind": "placement",
                        "id": "workspace.place.offers",
                        "piece": "sourcing.offers",
                        "hidden": True,
                        "size": {"min": 120, "preferred": 240},
                        "styleRoles": {"heading": "label"},
                        "params": {"kind": "symbol", "index": 2, "primary": False},
                        "visibility": {"anyOf": ["has-content", "show-empty"]},
                        "repeat": {"over": "offers"},
                    },
                },
                {"kind": "slot", "id": "workspace.slot.b", "content": None},
            ],
        },
    }


def _committed_issue():
    """One row as `layout/validatorIssues.ts` builds it, including the folded structural tier."""
    return {
        "code": "unknown-piece",
        "severity": "warning",
        "copy": {
            "id": "layout-issues.unknown-piece",
            "fallback": "No registered piece answers to this id.",
        },
        "subject": {"kind": "placement", "id": "workspace.place.offers"},
        "detail": {"piece": "sourcing.offers", "tier": "error"},
        "path": ["workspace.root", "workspace.slot.a", "workspace.place.offers"],
    }


def _emitted_json(module_text: str, export_name: str):
    """The JSON body of one ``export const NAME: Type = {...};`` in a generated module.

    Deliberately parses the EMITTED TEXT rather than trusting the payload - that is what makes the
    assertion a round trip. Break the writer's template (the trailing ``;``, the ``= ``, the export
    line) and this raises rather than quietly comparing the input to itself."""
    marker = f"export const {export_name}"
    start = module_text.index(marker)
    body_start = module_text.index(" = ", start) + len(" = ")
    end = module_text.index(";\n", body_start)
    return json.loads(module_text[body_start:end])


def _ts_value(module_text: str, export_name: str) -> str:
    """The raw text of one `export const NAME: Type = <value>;`, for a prettier-formatted module."""
    marker = f"export const {export_name}"
    start = module_text.index(marker)
    body_start = module_text.index(" = ", start) + len(" = ")
    return module_text[body_start : module_text.index(";\n", body_start)]


def test_dev_save_round_trips_a_committed_layout_document(client, tmp_path, monkeypatch):
    src = _src_with_lib(tmp_path, monkeypatch)
    document = _layout_document()
    res = client.post(
        "/api/dev/save",
        json={
            "tokens": {"root": {}, "light": {}},
            "copy": {},
            "layout": {"workspace": document},
            "committedIssues": {"workspace": [_committed_issue()]},
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["layouts"] == 1
    assert data["committedIssues"] == 1
    assert "app/frontend/src/lib/layout.overrides.ts" in data["written"]

    layout_ts = (src / "lib" / "layout.overrides.ts").read_text(encoding="utf-8")
    assert layout_ts.startswith("/**")  # regenerated whole, with the doc header
    assert 'import type { LayoutDocument } from "../layout/document";' in layout_ts
    assert 'import type { ValidatorIssue } from "../layout/validatorIssues";' in layout_ts
    assert "export const LAYOUT_OVERRIDES: LayoutOverrides = " in layout_ts
    assert "export const LAYOUT_COMMITTED_ISSUES: LayoutCommittedIssues = " in layout_ts

    assert _emitted_json(layout_ts, "LAYOUT_OVERRIDES") == {"workspace": document}
    assert _emitted_json(layout_ts, "LAYOUT_COMMITTED_ISSUES") == {
        "workspace": [_committed_issue()]
    }


def test_dev_save_round_trips_approved_arrange_visibility_and_grid_fields(
    client, tmp_path, monkeypatch
):
    src = _src_with_lib(tmp_path, monkeypatch)
    document = _layout_document()
    document["root"]["positioning"] = "free"
    document["root"]["grid"] = {"columns": 4, "rows": 3}
    placement = document["root"]["slots"][0]["content"]
    placement["size"].update({"width": 360, "height": 180})
    placement["position"] = {"x": 24, "y": -16}
    placement["gridSlot"] = {"column": 2, "row": 3}

    res = client.post(
        "/api/dev/save",
        json={
            "tokens": {"root": {}, "light": {}},
            "copy": {},
            "layout": {"workspace": document},
        },
    )

    assert res.status_code == 200, res.text
    written = _emitted_json(
        (src / "lib" / "layout.overrides.ts").read_text(encoding="utf-8"),
        "LAYOUT_OVERRIDES",
    )["workspace"]
    assert written["root"]["positioning"] == "free"
    assert written["root"]["grid"] == {"columns": 4, "rows": 3}
    written_placement = written["root"]["slots"][0]["content"]
    assert written_placement["size"] == {
        "min": 120,
        "preferred": 240,
        "width": 360,
        "height": 180,
    }
    assert written_placement["position"] == {"x": 24, "y": -16}
    assert written_placement["gridSlot"] == {"column": 2, "row": 3}


def test_dev_save_with_no_layout_reproduces_the_committed_file(client, tmp_path, monkeypatch):
    # An omitted layout block is "nothing committed", written as the shipped-default state - the same
    # state the lib/layout.overrides.ts in the repository is in, so a save that touched no arrangement
    # commits no arrangement.
    #
    # SEMANTIC rather than byte equality, and the difference is prettier. The writer emits JSON (quoted
    # keys, no trailing comma) and pre-commit runs prettier over app/frontend/src, which rewrites it to
    # the repository's TypeScript style - which is why lib/token.overrides.ts has read `root: {}` since
    # long before this phase. Asserting bytes here would be asserting that prettier never runs.
    src = _src_with_lib(tmp_path, monkeypatch)
    res = client.post("/api/dev/save", json={"tokens": {"root": {}, "light": {}}, "copy": {}})
    assert res.status_code == 200
    assert res.json()["layouts"] == 0
    layout_ts = (src / "lib" / "layout.overrides.ts").read_text(encoding="utf-8")
    assert _emitted_json(layout_ts, "LAYOUT_OVERRIDES") == {"workspace": None}
    assert _emitted_json(layout_ts, "LAYOUT_COMMITTED_ISSUES") == {"workspace": []}

    committed = (_COMMITTED_LIB / "layout.overrides.ts").read_text(encoding="utf-8")
    assert _ts_value(committed, "LAYOUT_OVERRIDES") == "{\n  workspace: null,\n}"
    assert _ts_value(committed, "LAYOUT_COMMITTED_ISSUES") == "{\n  workspace: [],\n}"
    # The prose and the declarations are the writer's, verbatim: the module in the repository is one
    # this endpoint produced, not one somebody wrote to look like it.
    for marker in (
        "export interface LayoutOverrides {",
        "export interface LayoutCommittedIssues {",
        'import type { ValidatorIssue } from "../layout/validatorIssues";',
        "THE DEVIATION LIST THAT SHIPS WITH THE COMMIT",
    ):
        assert marker in committed
        assert marker in layout_ts


def test_dev_save_writes_only_validated_layout_fields(client, tmp_path, monkeypatch):
    # The writer re-serialises from validated fields, so a field nobody declared never reaches source.
    src = _src_with_lib(tmp_path, monkeypatch)
    document = _layout_document()
    document["root"]["smuggled"] = "</script>"
    document["root"]["slots"][0]["content"]["alsoSmuggled"] = {"nested": True}
    res = client.post(
        "/api/dev/save",
        json={"tokens": {"root": {}, "light": {}}, "copy": {}, "layout": {"workspace": document}},
    )
    assert res.status_code == 200, res.text
    layout_ts = (src / "lib" / "layout.overrides.ts").read_text(encoding="utf-8")
    assert "smuggled" not in layout_ts
    assert "</script>" not in layout_ts
    # ...and every declared field survived the rebuild.
    written = _emitted_json(layout_ts, "LAYOUT_OVERRIDES")["workspace"]
    placement = written["root"]["slots"][0]["content"]
    assert placement["piece"] == "sourcing.offers"
    assert placement["params"] == {"kind": "symbol", "index": 2, "primary": False}
    assert written["root"]["splitters"][0]["between"] == ["workspace.slot.a", "workspace.slot.b"]


def test_dev_save_refuses_a_malformed_layout_document(client, tmp_path, monkeypatch):
    # Structural refusals only, and nothing is written on any of them: the six files stay as they
    # were rather than half-updated with an arrangement that is not a document.
    src = _src_with_lib(tmp_path, monkeypatch)
    region = {"kind": "region", "id": "r", "mode": "row", "slots": []}
    cases = [
        ("not a document", "a string where the document goes"),
        ({"schemaVersion": 1, "id": "x"}, "no root"),
        ({"schemaVersion": 1, "id": "x", "root": {"kind": "slot", "id": "s"}}, "root not a region"),
        ({"schemaVersion": "one", "id": "x", "root": region}, "schemaVersion not an integer"),
        ({"schemaVersion": 1, "id": "", "root": region}, "an empty document id"),
        (
            {"schemaVersion": 1, "id": "x", "root": {**region, "mode": "diagonal"}},
            "an unknown arrangement mode",
        ),
        ({"schemaVersion": 1, "id": "x", "root": {**region, "slots": {}}}, "slots not a list"),
        (
            {
                "schemaVersion": 1,
                "id": "x",
                "root": {
                    **region,
                    "slots": [
                        {"kind": "slot", "id": "s", "content": {"kind": "widget", "id": "w"}}
                    ],
                },
            },
            "a node that is neither a region nor a placement",
        ),
        (
            {
                "schemaVersion": 1,
                "id": "x",
                "root": {
                    **region,
                    "slots": [
                        {"kind": "slot", "id": "s", "content": {"kind": "placement", "id": "p"}}
                    ],
                },
            },
            "a placement naming no piece",
        ),
        (
            {"schemaVersion": 1, "id": "x", "root": {**region, "scroll": "sideways"}},
            "an unknown scroll axis",
        ),
    ]
    for document, why in cases:
        res = client.post(
            "/api/dev/save",
            json={
                "tokens": {"root": {}, "light": {}},
                "copy": {},
                "layout": {"workspace": document},
            },
        )
        assert res.status_code == 400, f"expected 400 for {why}: {res.text}"
        assert not (src / "lib" / "layout.overrides.ts").exists(), why
        # ...and the refusal came BEFORE any file was written, so no slice is half-updated.
        assert not (src / "lib" / "token.overrides.ts").exists(), why


def test_dev_save_refuses_a_non_finite_number_in_a_layout(client, tmp_path, monkeypatch):
    # `Infinity` and `NaN` are not JSON, but Python's parser accepts them, so they can arrive in a raw
    # body even though a conforming client cannot send them. Written out they would produce a module
    # this test's own round trip could not re-read, so they are refused. Posted as raw content because
    # the test client's serialiser refuses them on the way out, which is the point.
    src = _src_with_lib(tmp_path, monkeypatch)
    body = (
        '{"tokens": {"root": {}, "light": {}}, "copy": {}, "layout": {"workspace": '
        '{"schemaVersion": 1, "id": "x", "root": {"kind": "region", "id": "r", "mode": "row", '
        '"size": {"fraction": Infinity}, "slots": []}}}}'
    )
    res = client.post("/api/dev/save", content=body, headers={"content-type": "application/json"})
    assert res.status_code == 400, res.text
    assert not (src / "lib" / "layout.overrides.ts").exists()


def test_dev_save_refuses_a_layout_that_is_too_deep_or_too_large(client, tmp_path, monkeypatch):
    # A document is a tree off the wire; without bounds a pathological one is a write that never ends.
    src = _src_with_lib(tmp_path, monkeypatch)
    node = {"kind": "region", "id": "leaf", "mode": "column", "slots": []}
    for _ in range(dev_mod._MAX_LAYOUT_DEPTH + 2):
        node = {
            "kind": "region",
            "id": "nest",
            "mode": "column",
            "slots": [{"kind": "slot", "id": "s", "content": node}],
        }
    res = client.post(
        "/api/dev/save",
        json={
            "tokens": {"root": {}, "light": {}},
            "copy": {},
            "layout": {"workspace": {"schemaVersion": 1, "id": "deep", "root": node}},
        },
    )
    assert res.status_code == 400
    assert not (src / "lib" / "layout.overrides.ts").exists()


def test_dev_save_refuses_a_malformed_committed_issue(client, tmp_path, monkeypatch):
    # The deviation list is emitted verbatim into a TYPED module, so a row outside the model would be
    # a module that does not compile. It is refused here instead of at the publish typecheck.
    src = _src_with_lib(tmp_path, monkeypatch)
    issue = _committed_issue()
    cases = [
        ({**issue, "severity": "error"}, "a severity outside warning / info"),
        ({**issue, "subject": {"kind": "widget", "id": "x"}}, "a subject kind the model lacks"),
        ({k: v for k, v in issue.items() if k != "copy"}, "an issue with no copy id"),
        ({**issue, "code": "Unknown Piece"}, "a code that is not a slug"),
        ({**issue, "path": "workspace.root"}, "a path that is not a list"),
    ]
    for bad, why in cases:
        res = client.post(
            "/api/dev/save",
            json={
                "tokens": {"root": {}, "light": {}},
                "copy": {},
                "layout": {"workspace": _layout_document()},
                "committedIssues": {"workspace": [bad]},
            },
        )
        assert res.status_code == 400, f"expected 400 for {why}: {res.text}"
        assert not (src / "lib" / "layout.overrides.ts").exists(), why


def test_dev_save_accepts_an_issue_code_this_build_has_not_heard_of(client, tmp_path, monkeypatch):
    # The closed list lives in `layout/validatorIssues.ts`, not here. A code added on the frontend has
    # to reach committed source or the owner's known issues would be quietly shorter than the truth;
    # an id that is not a code at all still fails the publish typecheck against the union.
    src = _src_with_lib(tmp_path, monkeypatch)
    future = {**_committed_issue(), "code": "focus-order-crossed"}
    res = client.post(
        "/api/dev/save",
        json={
            "tokens": {"root": {}, "light": {}},
            "copy": {},
            "layout": {"workspace": _layout_document()},
            "committedIssues": {"workspace": [future]},
        },
    )
    assert res.status_code == 200, res.text
    layout_ts = (src / "lib" / "layout.overrides.ts").read_text(encoding="utf-8")
    assert _emitted_json(layout_ts, "LAYOUT_COMMITTED_ISSUES")["workspace"][0]["code"] == (
        "focus-order-crossed"
    )


def test_dev_save_records_owner_authored_copy_ids_only_for_written_overrides(
    client, tmp_path, monkeypatch
):
    # The letter-rule lint exempts these ids, so the record is capped by construction: an id with no
    # committed rewording has nothing to exempt and is dropped rather than written as a standing
    # exemption for a string that is not there.
    src = _src_with_lib(tmp_path, monkeypatch)
    res = client.post(
        "/api/dev/save",
        json={
            "tokens": {"root": {}, "light": {}},
            "copy": {"detail.owner-typed": "Check the part"},
            "ownerAuthoredCopy": [
                "detail.owner-typed",
                "detail.never-overridden",  # no override to exempt -> dropped
                "bad id!",  # malformed -> dropped
            ],
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["ownerAuthoredCopy"] == 1

    copy_ts = (src / "lib" / "copy.overrides.ts").read_text(encoding="utf-8")
    assert "export const COPY_OVERRIDES" in copy_ts
    assert "export const OWNER_AUTHORED_COPY_IDS: readonly string[] = " in copy_ts
    assert _emitted_json(copy_ts, "OWNER_AUTHORED_COPY_IDS") == ["detail.owner-typed"]
    assert "never-overridden" not in copy_ts
    assert "bad id!" not in copy_ts


def test_dev_save_reproduces_the_committed_copy_and_provenance(
    client, tmp_path, monkeypatch
):
    # A save regenerates copy.overrides.ts as the repository has it, provenance record and all - so
    # existing owner edits cannot quietly disappear the first time somebody saves a token nudge.
    # Semantic rather than byte equality for the prettier reason recorded on the layout test above.
    src = _src_with_lib(tmp_path, monkeypatch)
    committed = (_COMMITTED_LIB / "copy.overrides.ts").read_text(encoding="utf-8")
    expected_copy = _emitted_json(committed, "COPY_OVERRIDES")
    expected_owner_authored = _emitted_json(committed, "OWNER_AUTHORED_COPY_IDS")
    res = client.post(
        "/api/dev/save",
        json={
            "tokens": {"root": {}, "light": {}},
            "copy": expected_copy,
            "ownerAuthoredCopy": expected_owner_authored,
        },
    )
    assert res.status_code == 200
    assert res.json()["ownerAuthoredCopy"] == len(expected_owner_authored)
    copy_ts = (src / "lib" / "copy.overrides.ts").read_text(encoding="utf-8")
    for text in (copy_ts, committed):
        assert _emitted_json(text, "COPY_OVERRIDES") == expected_copy
        assert _emitted_json(text, "OWNER_AUTHORED_COPY_IDS") == expected_owner_authored
        assert "OWNER-AUTHORED PROVENANCE" in text


def test_dev_publish_owns_the_layout_module(tmp_path):
    # Path ownership is the gate regime the layout module joins. Publish commits exactly
    # _DEV_SOURCE_PATHS and refuses when anything else is dirty, so a module missing from that tuple
    # would be written by Save and then left behind by Publish - a redesign that never ships.
    assert "app/frontend/src/lib/layout.overrides.ts" in dev_mod._DEV_SOURCE_PATHS

    layout = tmp_path / "app" / "frontend" / "src" / "lib" / "layout.overrides.ts"
    stray = tmp_path / "app" / "frontend" / "src" / "lib" / "somethingElse.ts"
    repo = SimpleNamespace(root=tmp_path, dirty_paths=lambda: [layout])
    assert dev_mod._foreign_dev_paths(repo) == []

    repo_with_stray = SimpleNamespace(root=tmp_path, dirty_paths=lambda: [layout, stray])
    assert dev_mod._foreign_dev_paths(repo_with_stray) == ["app/frontend/src/lib/somethingElse.ts"]
