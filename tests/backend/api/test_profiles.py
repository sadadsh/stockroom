from __future__ import annotations


def test_list_profiles_shows_active(client):
    r = client.get("/api/profiles")
    assert r.status_code == 200
    body = r.json()
    assert "Main" in body["profiles"]
    assert body["active"] == "Main"


def test_profile_list_excludes_the_git_dir(client):
    # The libraries root is itself a git repo, so <root>/.git is a real subdirectory;
    # it must NEVER surface as a phantom profile in the switcher (regression lock).
    body = client.get("/api/profiles").json()
    assert ".git" not in body["profiles"]
    assert all(not name.startswith(".") for name in body["profiles"])


def test_cannot_activate_the_git_dir(client):
    # Even by crafting the name directly, .git can never be activated.
    assert client.post("/api/profiles/.git/activate").status_code in (400, 404)


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
