import pytest

from stockroom.credentials.windows import WindowsCredentialStore


class _FakeApi:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.targets: list[str] = []

    def read(self, target: str) -> str | None:
        self.targets.append(target)
        return self.values.get(target)

    def write(self, target: str, value: str) -> None:
        self.targets.append(target)
        self.values[target] = value

    def delete(self, target: str) -> None:
        self.targets.append(target)
        self.values.pop(target, None)


def test_windows_store_uses_only_namespaced_nonsecret_targets():
    api = _FakeApi()
    store = WindowsCredentialStore("config-test", api=api)

    store.set("mouser_api_key", "SECRET-VALUE")

    assert store.get("mouser_api_key") == "SECRET-VALUE"
    assert set(api.values) == {"Stockroom/config-test/mouser_api_key"}
    assert all("SECRET-VALUE" not in target for target in api.targets)


def test_windows_store_delete_is_verified():
    api = _FakeApi()
    store = WindowsCredentialStore("config-test", api=api)
    store.set("github_token", "TOKEN")

    store.delete("github_token")

    assert store.get("github_token") is None


@pytest.mark.parametrize(
    "name,value",
    [
        ("", "valid"),
        ("valid", ""),
        ("valid", "contains\x00nul"),
        ("contains\x00nul", "valid"),
    ],
)
def test_windows_store_rejects_invalid_names_and_values(name, value):
    store = WindowsCredentialStore("config-test", api=_FakeApi())

    with pytest.raises(ValueError):
        store.set(name, value)
