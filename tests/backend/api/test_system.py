def test_health_needs_no_token(anon_client):
    r = anon_client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_system_info_requires_a_token(anon_client):
    r = anon_client.get("/api/system/info")
    assert r.status_code == 401


def test_system_info_reports_active_profile_and_count(client):
    r = client.get("/api/system/info")
    assert r.status_code == 200
    body = r.json()
    assert body["active_profile"] == "Main"
    assert body["part_count"] == 2
