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


def test_dev_save_refuses_without_a_source_tree(client, tmp_path, monkeypatch):
    # a packaged build has no frontend/src: refuse honestly (409), never a silent success
    monkeypatch.setattr(dev_mod, "_FRONTEND_SRC", tmp_path / "nope")
    res = client.post(
        "/api/dev/save",
        json={"tokens": {"root": {}, "light": {}}, "copy": {}},
    )
    assert res.status_code == 409
    assert "packaged build" in res.json()["detail"]
