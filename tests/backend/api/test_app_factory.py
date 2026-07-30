from types import SimpleNamespace

from fastapi.testclient import TestClient

from stockroom.api.app import _FRONTEND_DIST, create_app
from stockroom.api.errors import ApiError, error_body, status_for
from stockroom.host.service_authority import (
    SERVICE_CONTROL_HEADER,
    SERVICE_CONTROL_PREFIX,
    install_service_authority_routes,
)
from stockroom.mutation.library_ops import IncompleteError
from stockroom.projects.collaboration import CollaborationError
from stockroom.vcs.repo import GitError


def test_incomplete_error_maps_to_422_with_missing_list():
    exc = IncompleteError(["3D model", "datasheet"])
    assert status_for(exc) == 422
    body = error_body(exc)
    assert body["error"] == "IncompleteError"
    assert body["missing"] == ["3D model", "datasheet"]


def test_git_error_maps_to_503():
    assert status_for(GitError("offline")) == 503


def test_value_error_maps_to_400_and_unknown_to_500():
    assert status_for(ValueError("bad")) == 400
    assert status_for(RuntimeError("boom")) == 500


def test_error_body_has_no_missing_key_for_a_plain_error():
    body = error_body(ValueError("bad"))
    assert body["error"] == "ValueError"
    assert body["detail"] == "bad"
    assert "missing" not in body


def test_api_error_is_exportable():
    assert issubclass(ApiError, Exception)


def test_private_service_routes_precede_the_real_frontend_mount(app_ctx):
    assert _FRONTEND_DIST.is_dir()

    class Authority:
        @staticmethod
        def promote(*, expected_generation: int):
            assert expected_generation == 7
            return SimpleNamespace(
                public=lambda: {
                    "coordinator_status": "active",
                    "generation": 8,
                    "mode": "coordinator",
                }
            )

        @staticmethod
        def demote(*, expected_generation: int):
            raise AssertionError(f"unexpected demotion from generation {expected_generation}")

    def install_private_routes(app):
        install_service_authority_routes(
            app,
            Authority(),
            secret="service-control-secret",
        )

    app = create_app(
        app_ctx,
        before_frontend_mount=install_private_routes,
    )
    route_paths = [getattr(route, "path", None) for route in app.router.routes]
    assert route_paths.index(f"{SERVICE_CONTROL_PREFIX}/promote") < route_paths.index("")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"{SERVICE_CONTROL_PREFIX}/promote",
            headers={SERVICE_CONTROL_HEADER: "service-control-secret"},
            json={"expected_generation": 7},
        )
    assert response.status_code == 200
    assert response.json()["generation"] == 8


def test_collaboration_conflicts_keep_their_machine_readable_code():
    exc = CollaborationError("review_changed", "the reviewed commit changed")

    assert status_for(exc) == 409
    assert error_body(exc) == {
        "error": "CollaborationError",
        "detail": "the reviewed commit changed",
        "code": "review_changed",
    }
