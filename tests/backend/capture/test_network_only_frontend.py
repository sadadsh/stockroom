"""The Complete Part capture surface is network-owned, never a local-path attach shortcut."""

from pathlib import Path

_ROOT = Path(__file__).parents[3]


def test_capture_provider_has_no_local_inspect_commit_or_host_callback_dispatch() -> None:
    source = (_ROOT / "app" / "frontend" / "src" / "lib" / "capture.tsx").read_text(
        encoding="utf-8"
    )

    forbidden = (
        "assetsInspect",
        "assetsCommit",
        "altiumAttach",
        "altiumRegenerate",
        "__STOCKROOM_CAD_DOWNLOAD__",
        "submitPaths",
    )
    found = [contract for contract in forbidden if contract in source]

    assert found == [], f"capture provider still dispatches local/manual seams: {found}"
