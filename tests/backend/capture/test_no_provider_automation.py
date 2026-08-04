"""Nothing in production capture may operate a provider page.

The person performs every provider-page action: navigation after the page opens, clicking, form
filling, format selection, sign-in, licence acceptance, and any security check. Stockroom builds a
safe URL, hosts the provider surface, and stages what the person downloads.

This is asserted mechanically rather than by review because the automation this replaced came back
twice: once as a "reviewed machine-access exception", once as an "operator-authorized lane". Both
looked like policy from the outside and were provider-driving code on the inside. A grep over the
shipped package is the only check that cannot be argued around.
"""

from __future__ import annotations

from pathlib import Path

from stockroom.capture.vendors import all_adapters

_CAPTURE = Path(__file__).resolve().parents[3] / "app" / "backend" / "stockroom" / "capture"

# Every method a provider-driving adapter carried. An adapter is DATA plus URL resolution now, so
# any of these reappearing on one means the driver came back.
_DRIVING_SEAMS = (
    "drive",
    "sign_in",
    "signed_in",
    "open_panel",
    "download_gate",
    "user_clearance_issue",
    "retryable_download_issue",
    "retryable_render_issue",
    "operate_in_user_window",
    "drive_supplementary_route",
    "observe_supplementary_route",
)


def test_no_adapter_or_author_route_exposes_a_provider_driving_seam():
    adapters = all_adapters()
    assert adapters, "the provider registry is empty"
    found: list[str] = []
    for adapter in adapters:
        candidates = [adapter]
        capture_routes = getattr(adapter, "capture_routes", None)
        if callable(capture_routes):
            candidates.extend(capture_routes())
        for candidate in candidates:
            for seam in _DRIVING_SEAMS:
                if hasattr(candidate, seam):
                    found.append(f"{type(candidate).__name__}.{seam}")
    assert found == [], f"provider-driving seams returned: {found}"


def test_the_capture_package_attaches_no_driver_and_rewrites_no_download_behaviour():
    """No driver may connect to the provider surface, and none may rearm its downloads.

    `connect_over_cdp` used to be permitted here because it attached to Stockroom's OWN embedded
    provider window. That allowance is withdrawn: the native host opens no remote-debugging port,
    so there is nothing to connect to, and a re-added `connect_over_cdp` would only be reaching
    for a port someone had to re-open first. `Browser.setDownloadBehavior` is Stockroom operating
    a session rather than observing it. Provider downloads reach Stockroom through the native
    lease journal and nothing else.
    """

    forbidden = ("connect_over_cdp", "Browser.setDownloadBehavior")
    found: list[str] = []
    for path in sorted(_CAPTURE.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        found.extend(f"{path.name}: {marker}" for marker in forbidden if marker in source)
    assert found == [], f"capture still drives a provider browser in: {found}"


def test_the_capture_package_holds_no_provider_website_credentials():
    """A saved provider login only exists to replay it into someone else's sign-in form."""

    from stockroom.store.machine_config import MachineConfig

    config = MachineConfig()
    for retired in (
        "ul_username",
        "ul_password",
        "snapeda_username",
        "snapeda_password",
        "samacsys_username",
        "samacsys_password",
        "digikey_username",
        "digikey_password",
        "ul_private_evaluation_automation",
    ):
        assert not hasattr(config, retired), f"{retired} is a provider website login and must be gone"
    # The official catalogue APIs are not website logins and deliberately remain.
    assert hasattr(config, "mouser_api_key")
    assert hasattr(config, "digikey_client_id")
    assert hasattr(config, "digikey_client_secret")


def test_the_machine_access_authorization_module_is_gone():
    """It existed only to authorize website automation, so it has nothing left to decide."""

    assert not (_CAPTURE / "access_policy.py").exists()
