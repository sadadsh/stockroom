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
