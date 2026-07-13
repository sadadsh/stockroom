from stockroom.api.errors import ApiError, error_body, status_for
from stockroom.mutation.library_ops import IncompleteError
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
