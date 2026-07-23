"""Dev-mode save endpoint: it writes the nudged tokens + reworded copy back to the frontend
source (validating every value so nothing can inject code), and refuses honestly when there is
no source tree. The write path is redirected to a tmp dir so the suite never touches real source."""

from __future__ import annotations

import stockroom.api.routers.dev as dev_mod


def test_dev_save_writes_validated_token_and_copy_overrides(client, tmp_path, monkeypatch):
    src = tmp_path / "frontend" / "src"
    (src / "lib").mkdir(parents=True)
    monkeypatch.setattr(dev_mod, "_FRONTEND_SRC", src)

    body = {
        "tokens": {
            "root": {
                "--c-acc": "#e0a458",           # valid colour
                "--r-card": "22px",             # valid length
                "bad key": "#fff",              # invalid var name -> dropped
                "--c-evil": "</script>alert(1)",  # invalid value (has < >) -> dropped
            },
            "light": {"--c-acc": "#1b1b1e"},
        },
        "copy": {
            "detail.complete-part": "Finish setup",  # valid
            "bad id!": "x",                            # invalid id -> dropped
        },
    }
    res = client.post("/api/dev/save", json=body)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    # 2 valid root tokens + 1 valid light token; the bad key and the injection value were dropped
    assert data["tokens"] == 3
    assert data["copy"] == 1

    tokens_ts = (src / "lib" / "token.overrides.ts").read_text(encoding="utf-8")
    assert tokens_ts.startswith("/**")  # regenerated whole, with the doc header
    assert "export const TOKEN_OVERRIDES" in tokens_ts
    assert '"--c-acc": "#e0a458"' in tokens_ts
    assert '"--r-card": "22px"' in tokens_ts
    assert "bad key" not in tokens_ts
    # the injection-ish value never reaches the generated module
    assert "</script>" not in tokens_ts
    assert "--c-evil" not in tokens_ts

    copy_ts = (src / "lib" / "copy.overrides.ts").read_text(encoding="utf-8")
    assert "export const COPY_OVERRIDES" in copy_ts
    assert '"detail.complete-part": "Finish setup"' in copy_ts
    assert "bad id!" not in copy_ts


def test_dev_save_accepts_shadow_and_unitless_number_tokens(client, tmp_path, monkeypatch):
    # v2 adds shadow strings (with var() references) and unitless numbers (icon stroke) to the
    # editable set. They must survive the same validator that drops injection-ish values.
    src = tmp_path / "frontend" / "src"
    (src / "lib").mkdir(parents=True)
    monkeypatch.setattr(dev_mod, "_FRONTEND_SRC", src)

    shadow = (
        "inset 0 1px 0 var(--edge-hi), 0 2px 8px rgba(0, 0, 0, 0.4), "
        "0 28px 64px rgba(0, 0, 0, 0.62)"
    )
    body = {
        "tokens": {
            "root": {
                "--icon-stroke": "2.6",  # unitless number
                "--fs-sm": "13.5px",     # fractional length
            },
            "light": {
                "--shadow-card": shadow,  # a full box-shadow string, including a var() reference
            },
        },
        "copy": {},
    }
    res = client.post("/api/dev/save", json=body)
    assert res.status_code == 200
    assert res.json()["tokens"] == 3  # all three survived validation

    tokens_ts = (src / "lib" / "token.overrides.ts").read_text(encoding="utf-8")
    assert '"--icon-stroke": "2.6"' in tokens_ts
    assert '"--fs-sm": "13.5px"' in tokens_ts
    assert "var(--edge-hi)" in tokens_ts  # the shadow string round-trips intact


def test_dev_save_refuses_without_a_source_tree(client, tmp_path, monkeypatch):
    # a packaged build has no frontend/src: refuse honestly (409), never a silent success
    monkeypatch.setattr(dev_mod, "_FRONTEND_SRC", tmp_path / "nope")
    res = client.post(
        "/api/dev/save",
        json={"tokens": {"root": {}, "light": {}}, "copy": {}},
    )
    assert res.status_code == 409
    assert "packaged build" in res.json()["detail"]


# --- dev-mode v2: icon overrides --------------------------------------------------------------


def _src_with_lib(tmp_path, monkeypatch):
    src = tmp_path / "frontend" / "src"
    (src / "lib").mkdir(parents=True)
    monkeypatch.setattr(dev_mod, "_FRONTEND_SRC", src)
    return src


def test_dev_save_writes_validated_icon_overrides(client, tmp_path, monkeypatch):
    # a valid inner-SVG body + a glyph swap both survive and land in lib/icon.overrides.ts,
    # regenerated whole (the doc header + IconOverride interface + the const export).
    src = _src_with_lib(tmp_path, monkeypatch)
    body = {
        "tokens": {"root": {}, "light": {}},
        "copy": {},
        "icons": {
            "nav.parts": {
                "body": '<path d="M4 4 L20 20" stroke="currentColor" stroke-width="2"/>'
                "<circle cx=\"12\" cy=\"12\" r=\"6\" fill=\"none\"/>",
            },
            "nav.home": {"swapToId": "nav.projects"},
            "bad id!": {"body": '<path d="M0 0"/>'},  # malformed key -> dropped, not a 400
        },
    }
    res = client.post("/api/dev/save", json=body)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["icons"] == 2  # nav.parts + nav.home; the malformed key was dropped

    icon_ts = (src / "lib" / "icon.overrides.ts").read_text(encoding="utf-8")
    assert icon_ts.startswith("/**")
    assert "export interface IconOverride" in icon_ts
    assert "export const ICON_OVERRIDES" in icon_ts
    # the body round-trips through the sanitiser (re-serialised, not echoed raw)
    assert "M4 4 L20 20" in icon_ts
    assert '"swapToId": "nav.projects"' in icon_ts
    assert "bad id!" not in icon_ts


def test_dev_save_empty_icons_reproduces_the_committed_file(client, tmp_path, monkeypatch):
    # with no icons block the file is regenerated whole as an empty map (mirroring tokens/copy),
    # matching the shipped lib/icon.overrides.ts skeleton exactly.
    src = _src_with_lib(tmp_path, monkeypatch)
    res = client.post("/api/dev/save", json={"tokens": {"root": {}, "light": {}}, "copy": {}})
    assert res.status_code == 200
    assert res.json()["icons"] == 0
    icon_ts = (src / "lib" / "icon.overrides.ts").read_text(encoding="utf-8")
    assert icon_ts.rstrip().endswith("export const ICON_OVERRIDES: Record<string, IconOverride> = {};")


def test_dev_save_rejects_malicious_svg_bodies(client, tmp_path, monkeypatch):
    # every classic SVG-injection vector is a 4xx, and nothing is written on rejection
    src = _src_with_lib(tmp_path, monkeypatch)
    malicious = [
        "<script>alert(1)</script>",                       # script element
        '<path d="M0 0" onload="alert(1)"/>',              # on* event handler
        "<foreignObject><div>x</div></foreignObject>",     # foreignObject
        '<use href="https://evil.example/x#a"/>',          # external href
        '<rect fill="url(https://evil.example/x)"/>',       # remote url() ref
        '<image href="#a"/>',                              # non-whitelisted element
        "<!DOCTYPE svg><path d=\"M0 0\"/>",                # DOCTYPE / entities vector
    ]
    for m in malicious:
        res = client.post(
            "/api/dev/save",
            json={"tokens": {"root": {}, "light": {}}, "copy": {}, "icons": {"nav.parts": {"body": m}}},
        )
        assert res.status_code == 400, f"expected 400 for {m!r}, got {res.status_code}"
        # a rejected payload leaves the override files untouched (validated before any write)
        assert not (src / "lib" / "icon.overrides.ts").exists()


def test_dev_save_rejects_bad_icon_swap_id(client, tmp_path, monkeypatch):
    _src_with_lib(tmp_path, monkeypatch)
    res = client.post(
        "/api/dev/save",
        json={
            "tokens": {"root": {}, "light": {}},
            "copy": {},
            "icons": {"nav.parts": {"swapToId": "not a valid id!"}},
        },
    )
    assert res.status_code == 400


# --- dev-mode v2: per-element overrides -------------------------------------------------------


def test_dev_save_writes_validated_element_overrides(client, tmp_path, monkeypatch):
    # size + spacing + layout (order / grid-column) all pass the safe grammar and land in
    # lib/element.overrides.ts, keyed by data-dev-id.
    src = _src_with_lib(tmp_path, monkeypatch)
    body = {
        "tokens": {"root": {}, "light": {}},
        "copy": {},
        "elements": {
            "detail.spec-sheet": {
                "width": "240px",
                "padding": "8px",
                "order": "2",
                "grid-column": "1 / 3",
            },
            "bad id!": {"width": "10px"},  # malformed dev id -> dropped, not a 400
        },
    }
    res = client.post("/api/dev/save", json=body)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["elements"] == 1  # only the well-formed dev id survives

    elem_ts = (src / "lib" / "element.overrides.ts").read_text(encoding="utf-8")
    assert elem_ts.startswith("/**")
    assert "export const ELEMENT_OVERRIDES" in elem_ts
    assert '"width": "240px"' in elem_ts
    assert '"padding": "8px"' in elem_ts
    assert '"order": "2"' in elem_ts
    assert '"grid-column": "1 / 3"' in elem_ts
    assert "bad id!" not in elem_ts


def test_dev_save_empty_elements_reproduces_the_committed_file(client, tmp_path, monkeypatch):
    src = _src_with_lib(tmp_path, monkeypatch)
    res = client.post("/api/dev/save", json={"tokens": {"root": {}, "light": {}}, "copy": {}})
    assert res.status_code == 200
    assert res.json()["elements"] == 0
    elem_ts = (src / "lib" / "element.overrides.ts").read_text(encoding="utf-8")
    assert elem_ts.rstrip().endswith(
        "export const ELEMENT_OVERRIDES: Record<string, Record<string, string>> = {};"
    )


def test_dev_save_rejects_malicious_css_values(client, tmp_path, monkeypatch):
    # the CSS-value grammar rejects arbitrary CSS: remote url(), expression(), a `;`-injection,
    # a non-length value, and a non-whitelisted property.
    src = _src_with_lib(tmp_path, monkeypatch)
    cases = [
        {"width": "url(https://evil.example/x)"},   # remote url()
        {"width": "expression(alert(1))"},          # legacy IE expression()
        {"width": "240px; color: red"},             # ;-injection past the value
        {"width": "red"},                            # not a length / keyword
        {"padding": "10px<script>"},                # angle-bracket injection
        {"color": "red"},                            # property not on the whitelist
        {"grid-column": "1 / 2 / 3"},               # malformed grid slot
        {"order": "99999"},                          # not a small integer
    ]
    for props in cases:
        res = client.post(
            "/api/dev/save",
            json={
                "tokens": {"root": {}, "light": {}},
                "copy": {},
                "elements": {"detail.spec-sheet": props},
            },
        )
        assert res.status_code == 400, f"expected 400 for {props!r}, got {res.status_code}"
        assert not (src / "lib" / "element.overrides.ts").exists()


def test_dev_save_refuses_new_blocks_without_a_source_tree(client, tmp_path, monkeypatch):
    # the 409-with-no-source-tree contract holds for the icon + element blocks too (the gate is
    # before any validation, so a packaged build refuses honestly even for a v2 payload).
    monkeypatch.setattr(dev_mod, "_FRONTEND_SRC", tmp_path / "nope")
    res = client.post(
        "/api/dev/save",
        json={
            "tokens": {"root": {}, "light": {}},
            "copy": {},
            "icons": {"nav.parts": {"body": '<path d="M0 0"/>'}},
            "elements": {"detail.spec-sheet": {"width": "240px"}},
        },
    )
    assert res.status_code == 409
    assert "packaged build" in res.json()["detail"]
