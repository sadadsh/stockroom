"""Single source of truth for anti-bot interstitial detection, shared by every fetcher.

A block/challenge SHELL (DataDome, Akamai, Cloudflare, ...) shows one of these phrases while its
JS proof-of-work runs, before the real page loads. Every marker here was VERIFIED absent from real
captured distributor product pages (Mouser + DigiKey), so none makes a settle loop mistake a
cleared page for a challenge, and none leaks as a fabricated part description. Deliberately NOT the
bare vendor names ("datadome"/"cloudflare") - those client scripts persist on the CLEARED page and
would trap settle for the whole timeout."""

from __future__ import annotations

CHALLENGE_MARKERS: tuple[str, ...] = (
    # DataDome
    "captcha-delivery.com",
    # Akamai
    "access to this page has been denied", "access denied",
    # Cloudflare interstitial (the exact leaked text: "Just a moment...")
    "just a moment", "enable javascript and cookies", "attention required",
    # generic human-verification interstitials
    "verifying you are human", "verify you are human", "checking your browser",
    "unusual traffic", "please wait while we verify",
)


def looks_challenge(text: str) -> bool:
    """True when the text carries an UNSOLVED anti-bot challenge marker (any vendor)."""
    low = (text or "").lower()
    return any(marker in low for marker in CHALLENGE_MARKERS)
