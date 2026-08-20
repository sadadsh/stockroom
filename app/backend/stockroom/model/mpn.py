"""Canonical manufacturer-part-number identity used by catalog reads and writes."""

from __future__ import annotations


def mpn_identity_key(text: str) -> str:
    """Return the catalog's case/separator-insensitive exact-MPN token."""

    return "".join(ch for ch in text.lower() if ch.isalnum())
