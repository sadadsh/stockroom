"""Complete, provider-neutral presentation of retained official API payloads.

The raw JSON remains the authority under ``sourced/``.  This module only flattens that already-read
JSON into lossless leaf paths so the opened component can display every value without knowing a
Mouser or DigiKey response shape. Empty containers and explicit nulls are rows too: they are values
the provider returned, not gaps for Stockroom to fill with "Unknown".
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from stockroom.providers import provider_label

OFFICIAL_API_PROVIDERS: tuple[str, ...] = ("mouser", "digikey")


def _display(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _pointer_token(value: object) -> str:
    """RFC 6901 escaping keeps keys containing dots, slashes, or tildes unambiguous."""
    return str(value).replace("~", "~0").replace("/", "~1")


def _join(base: str, key: object) -> str:
    return f"{base}/{_pointer_token(key)}"


def flatten_payload(payload: Any) -> list[dict[str, Any]]:
    """Every scalar and empty container, in source order, addressed by JSON Pointer."""
    rows: list[dict[str, Any]] = []

    def visit(value: Any, path: str, endpoint: str) -> None:
        if isinstance(value, dict):
            if not value:
                rows.append(
                    {
                        "path": path or "$",
                        "endpoint": endpoint or "$",
                        "kind": "object",
                        "value": {},
                        "displayValue": "{}",
                    }
                )
                return
            for key, child in value.items():
                child_path = _join(path, key)
                visit(child, child_path, endpoint or str(key))
            return
        if isinstance(value, list):
            if not value:
                rows.append(
                    {
                        "path": path or "$",
                        "endpoint": endpoint or "$",
                        "kind": "array",
                        "value": [],
                        "displayValue": "[]",
                    }
                )
                return
            for index, child in enumerate(value):
                visit(child, _join(path, index), endpoint or "$")
            return
        rows.append(
            {
                "path": path or "$",
                "endpoint": endpoint or "$",
                "kind": _kind(value),
                "value": value,
                "displayValue": _display(value),
            }
        )

    visit(payload, "", "")
    return rows


def build_official_evidence(
    payloads: Mapping[str, Any] | None,
    *,
    source_entries: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Complete official payload rows, grouped only for navigation and never filtered."""
    providers: list[dict[str, Any]] = []
    payloads = payloads or {}
    entries = source_entries or {}
    for provider in OFFICIAL_API_PROVIDERS:
        if provider not in payloads:
            continue
        rows = flatten_payload(payloads[provider])
        entry = entries.get(provider)
        state = str((getattr(entry, "extra", None) or {}).get("state", "")).strip()
        providers.append(
            {
                "provider": provider,
                "providerLabel": provider_label(provider) or provider,
                "state": state,
                "fetchedAt": str(getattr(entry, "fetched_at", "") or ""),
                "payloadRef": str(getattr(entry, "file", "") or ""),
                "fieldCount": len(rows),
                "rows": rows,
            }
        )
    return {
        "providers": providers,
        "providerCount": len(providers),
        "fieldCount": sum(item["fieldCount"] for item in providers),
    }


__all__ = [
    "OFFICIAL_API_PROVIDERS",
    "build_official_evidence",
    "flatten_payload",
]
