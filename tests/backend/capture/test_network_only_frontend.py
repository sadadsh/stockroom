"""The Complete Part capture surface is network-owned, never a local-path attach shortcut."""

from pathlib import Path

_ROOT = Path(__file__).parents[3]
_FORBIDDEN_CAPTURE_CONTRACTS = (
    "assetsInspect",
    "assetsCommit",
    "altiumAttach",
    "altiumRegenerate",
    "__STOCKROOM_CAD_DOWNLOAD__",
    "submitPaths",
)


def _forbidden_capture_contracts(source: str) -> list[str]:
    """Return every retired local/manual contract found in injected source."""

    return [
        contract for contract in _FORBIDDEN_CAPTURE_CONTRACTS if contract in source
    ]


def test_capture_provider_has_no_local_inspect_commit_or_host_callback_dispatch() -> None:
    source = (_ROOT / "app" / "frontend" / "src" / "lib" / "capture.tsx").read_text(
        encoding="utf-8"
    )
    found = _forbidden_capture_contracts(source)

    assert found == [], f"capture provider still dispatches local/manual seams: {found}"


def test_network_only_detector_rejects_an_independent_known_bad_surface() -> None:
    known_bad = """
        const inspected = await api.assetsInspect(paths)
        return submitPaths(inspected)
    """

    assert _forbidden_capture_contracts(known_bad) == [
        "assetsInspect",
        "submitPaths",
    ]


def test_network_only_detector_accepts_a_clean_network_surface() -> None:
    clean = "return api.startCapture({ partId, provider: 'ultra-librarian' })"

    assert _forbidden_capture_contracts(clean) == []
