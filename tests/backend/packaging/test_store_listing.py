from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_listing_uses_public_policy_and_exact_store_identity() -> None:
    listing = json.loads((ROOT / "packaging" / "StoreListing.json").read_text(encoding="utf-8"))
    assert listing["store_id"] == "9NQ6HP17PH4H"
    assert listing["msa_app_id"] == "310029eb-7c34-4599-ba31-57ca888d37d0"
    assert listing["store_protocol_uri"] == "ms-windows-store://pdp/?productid=9NQ6HP17PH4H"
    assert listing["privacy_policy"] == "https://sadadsh.github.io/stockroom/privacy/"
    assert listing["support_url"] == "https://github.com/sadadsh/stockroom/issues"
    assert listing["price"] == "free"
    assert listing["architecture"] == "x64"
    assert "automatic provider download" not in listing["description"].casefold()


def test_public_policy_truthfully_describes_local_and_provider_data() -> None:
    policy = (ROOT / "store-site" / "privacy" / "index.html").read_text(encoding="utf-8")
    for phrase in (
        "stored on your PC",
        "Mouser",
        "DigiKey",
        "third-party provider",
        "Windows Credential Manager",
        "no Stockroom-operated advertising, analytics, or telemetry",
    ):
        assert phrase in policy


def test_public_site_exposes_the_one_time_github_channel_install_files() -> None:
    page = (ROOT / "store-site" / "index.html").read_text(encoding="utf-8")

    assert 'href="downloads/Stockroom-GitHub-Signing.cer"' in page
    assert 'href="windows/x64/Stockroom.appinstaller"' in page
    assert "one-time certificate" in page
