import pytest

from stockroom.api.errors import ApiError
from stockroom.api.security import make_require_token, mint_token


class _FakeHeaders:
    def __init__(self, mapping):
        self._m = {k.lower(): v for k, v in mapping.items()}

    def get(self, key, default=None):
        return self._m.get(key.lower(), default)


class _FakeRequest:
    def __init__(self, headers):
        self.headers = _FakeHeaders(headers)


def test_mint_token_is_long_and_unique():
    a, b = mint_token(), mint_token()
    assert len(a) >= 32
    assert a != b


def test_bearer_token_accepted():
    dep = make_require_token("secret123")
    # a matching bearer token returns without raising
    dep(_FakeRequest({"Authorization": "Bearer secret123"}))


def test_x_header_token_accepted():
    dep = make_require_token("secret123")
    dep(_FakeRequest({"X-Stockroom-Token": "secret123"}))


def test_missing_token_is_401():
    dep = make_require_token("secret123")
    with pytest.raises(ApiError) as ei:
        dep(_FakeRequest({}))
    assert ei.value.status == 401


def test_wrong_token_is_401():
    dep = make_require_token("secret123")
    with pytest.raises(ApiError) as ei:
        dep(_FakeRequest({"Authorization": "Bearer nope"}))
    assert ei.value.status == 401
