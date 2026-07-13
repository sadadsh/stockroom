from __future__ import annotations


def test_list_profiles_shows_active(client):
    r = client.get("/api/profiles")
    assert r.status_code == 200
    body = r.json()
    assert "Main" in body["profiles"]
    assert body["active"] == "Main"


def test_create_and_activate_a_profile(client):
    assert client.post("/api/profiles", json={"name": "Archive", "archive": True}).status_code == 200
    r = client.post("/api/profiles/Archive/activate")
    assert r.status_code == 200
    assert r.json()["active"] == "Archive"
    # the library list now reflects the (empty) Archive profile
    assert client.get("/api/library/parts").json()["count"] == 0


def test_cannot_delete_the_active_profile(client):
    r = client.delete("/api/profiles/Main")
    assert r.status_code == 400


def test_delete_a_nonactive_profile(client):
    client.post("/api/profiles", json={"name": "Scratch"})
    assert client.delete("/api/profiles/Scratch").status_code == 204
