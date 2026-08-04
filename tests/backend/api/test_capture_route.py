"""The guided-capture ROUTE: what the endpoint accepts, refuses, and exposes.

There is one capture mode - a person works the provider page - so this suite asserts the route
contract rather than driving a provider. The browser transport, the download broker, and the
attach path are covered by `tests/backend/capture/`, which exercises them without pretending a
local fixture page can be clicked by nobody.
"""

from __future__ import annotations


def test_the_route_exposes_only_vendors_that_have_an_implementation(client):
    body = client.get("/api/library/capture/vendors").json()
    keys = {v["key"] for v in body["vendors"]}
    assert "ultralibrarian" in keys
    ul = next(v for v in body["vendors"] if v["key"] == "ultralibrarian")
    assert set(ul["tools"]) == {"kicad", "altium"}
    assert ul["needs_login"] is True
    # The person is told the exact provider choices to take; nothing here promises automation.
    assert ul["instruction"]


def test_capture_needs_a_token(anon_client):
    assert anon_client.post("/api/library/capture/run", json={}).status_code == 401


def test_person_driven_capture_requires_one_part_and_refuses_a_batch_limit(client):
    no_part = client.post(
        "/api/library/capture/run",
        json={"vendor": "ultralibrarian"},
    )
    with_limit = client.post(
        "/api/library/capture/run",
        json={"vendor": "ultralibrarian", "part_ids": ["one"], "limit": 5},
    )

    assert no_part.status_code == 400
    assert "exactly one selected part" in no_part.json()["detail"]
    assert with_limit.status_code == 400
    assert "does not accept a batch limit" in with_limit.json()["detail"]


def test_a_legacy_capture_mode_is_accepted_and_means_person_driven(client):
    """Existing callers still send `mode`; every value is the one person-driven run now."""

    response = client.post(
        "/api/library/capture/run",
        json={"mode": "assisted", "vendor": "ultralibrarian"},
    )

    assert response.status_code == 400
    assert "exactly one selected part" in response.json()["detail"]


def test_background_capture_is_refused_because_a_person_must_see_the_page(client):
    response = client.post(
        "/api/library/capture/run",
        json={"vendor": "ultralibrarian", "part_ids": ["one"], "background": True},
    )

    assert response.status_code == 400
    assert "visible provider page" in response.json()["detail"]
