import pytest


@pytest.fixture
def personal_config(tmp_path, monkeypatch):
    root = tmp_path / "design-studio-config"
    monkeypatch.setenv("STOCKROOM_CONFIG_DIR", str(root))
    return root


def test_personal_design_api_round_trip_and_delete(client, personal_config):
    missing = client.get("/api/design-studio/personal")
    assert missing.status_code == 200
    assert missing.json() == {"revision": None, "document": None}

    put = client.put(
        "/api/design-studio/personal",
        json={"document": {"schemaVersion": 1}, "expected_revision": None},
    )

    assert put.status_code == 200
    saved = put.json()
    assert saved["document"] == {"schemaVersion": 1}
    assert isinstance(saved["revision"], str)

    get = client.get("/api/design-studio/personal")
    assert get.status_code == 200
    assert get.json() == saved

    deleted = client.request(
        "DELETE",
        "/api/design-studio/personal",
        json={"expected_revision": saved["revision"]},
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}
    assert client.get("/api/design-studio/personal").json() == {
        "revision": None,
        "document": None,
    }


def test_personal_design_api_never_writes_library(client, personal_config):
    before = client.app.state.ctx.repo.status_porcelain()

    response = client.put(
        "/api/design-studio/personal",
        json={"document": {"schemaVersion": 1}, "expected_revision": None},
    )

    assert response.status_code == 200
    assert client.app.state.ctx.repo.status_porcelain() == before
    assert (personal_config / "design-studio.json").is_file()


def test_personal_design_api_rejects_stale_revisions_without_replacing_document(
    client, personal_config
):
    saved = client.put(
        "/api/design-studio/personal",
        json={"document": {"schemaVersion": 1}, "expected_revision": None},
    ).json()

    stale = client.put(
        "/api/design-studio/personal",
        json={"document": {"schemaVersion": 1, "base": {}}, "expected_revision": "stale"},
    )

    assert stale.status_code == 409
    assert client.get("/api/design-studio/personal").json() == saved


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"document": {"schemaVersion": 1}, "expected_revision": None, "extra": True},
        {"document": {"schemaVersion": "1"}, "expected_revision": None},
        {"document": [], "expected_revision": None},
        {"document": {"schemaVersion": 1}, "expected_revision": 1},
    ],
)
def test_personal_design_api_rejects_invalid_request_bodies(client, personal_config, body):
    response = client.put("/api/design-studio/personal", json=body)

    assert response.status_code == 422
    assert client.get("/api/design-studio/personal").json() == {
        "revision": None,
        "document": None,
    }


def test_personal_design_api_requires_authentication(anon_client, personal_config):
    assert anon_client.get("/api/design-studio/personal").status_code == 401
    assert (
        anon_client.put(
            "/api/design-studio/personal",
            json={"document": {"schemaVersion": 1}, "expected_revision": None},
        ).status_code
        == 401
    )
    assert (
        anon_client.request(
            "DELETE",
            "/api/design-studio/personal",
            json={"expected_revision": None},
        ).status_code
        == 401
    )
