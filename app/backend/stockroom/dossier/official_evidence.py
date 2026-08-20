"""Complete, provider-neutral presentation of retained official API payloads.

The raw JSON remains the authority under ``sourced/``.  This module only flattens that already-read
JSON into lossless leaf paths so the opened component can display every value without knowing a
Mouser or DigiKey response shape. Empty containers and explicit nulls are rows too: they are values
the provider returned, not gaps for Stockroom to fill with "Unknown".
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

from stockroom.enrich.digikey_api import parse_digikey_payload
from stockroom.enrich.mouser import parse_mouser_payload
from stockroom.enrich.schema import SOURCED_FIELDS, EnrichmentResult, mpn_identity_key
from stockroom.providers import provider_label

OFFICIAL_API_PROVIDERS: tuple[str, ...] = ("mouser", "digikey")

_IDENTITY_KEYS: dict[str, str] = {
    "mouser": "ManufacturerPartNumber",
    "digikey": "ManufacturerProductNumber",
}
_SELECTED_SPEC_ALIASES = {
    "package": "Package",
    "lifecycle": "Lifecycle",
    "lead_time": "Lead Time",
    "country_of_origin": "Country of Origin",
    "tariff_rate": "Tariff Rate",
}


def _dict_items(value: object) -> list[dict[str, Any]]:
    return (
        [cast(dict[str, Any], item) for item in value if isinstance(item, dict)]
        if isinstance(value, list)
        else []
    )


def _digikey_products(response: object) -> list[dict[str, Any]]:
    if not isinstance(response, dict):
        return []
    for key in ("Products", "ProductVariations", "SearchResults"):
        products = _dict_items(response.get(key))
        if products:
            return products
    product = response.get("Product")
    if isinstance(product, dict):
        return [cast(dict[str, Any], product)]
    return (
        [cast(dict[str, Any], response)]
        if isinstance(response.get("ManufacturerProductNumber"), str)
        else []
    )


def _provider_result_sets(provider: str, payload: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Canonical product-result collections, excluding related/recommended response branches."""

    if provider == "mouser":
        search = payload.get("SearchResults")
        parts = search.get("Parts") if isinstance(search, dict) else None
        return [_dict_items(parts)]
    details = _digikey_products(payload.get("product_details"))
    search = _digikey_products(payload.get("keyword_search"))
    if details or search:
        return [details, search]
    return [_digikey_products(payload)]


def _exact_result(
    products: list[dict[str, Any]], identity_key: str, target: str
) -> dict[str, Any] | None:
    return next(
        (
            product
            for product in products
            if mpn_identity_key(product.get(identity_key)) == target
        ),
        None,
    )


def _parse_exact_result(
    provider: str, payload: dict[str, Any], committed_mpn: str
) -> tuple[EnrichmentResult, list[str]]:
    """Parse only the exact canonical product row, never a neighboring response object."""

    identity_key = _IDENTITY_KEYS[provider]
    target = mpn_identity_key(committed_mpn)
    result_sets = _provider_result_sets(provider, payload)
    observed = [
        value.strip()
        for products in result_sets
        for product in products
        if isinstance((value := product.get(identity_key)), str) and value.strip()
    ]
    exact = [_exact_result(products, identity_key, target) for products in result_sets]
    if provider == "mouser":
        product = exact[0]
        if product is None:
            return EnrichmentResult(), observed
        isolated = {"SearchResults": {"Parts": [product]}}
        return parse_mouser_payload(isolated, committed_mpn), observed

    details = exact[0] if len(exact) > 1 else None
    search = exact[-1]
    if details is None and search is None:
        return EnrichmentResult(), observed
    # DigiKey's parser starts from keyword_search, then overlays the richer product_details row.
    # Supplying the exact details row as the search fallback also supports a details-only payload.
    isolated: dict[str, Any] = {"keyword_search": {"Product": search or details}}
    if details is not None:
        isolated["product_details"] = {"Product": details}
    return parse_digikey_payload(isolated, committed_mpn), observed


def _trusted_selected_values(provider: str, partial: EnrichmentResult) -> dict[str, object]:
    trusted: dict[str, object] = {}
    for name in SOURCED_FIELDS:
        sourced = getattr(partial, name, None)
        if sourced is not None and str(sourced.source).strip().casefold() == provider:
            trusted[name] = sourced.value
    for label, sourced in partial.specs.items():
        if str(sourced.source).strip().casefold() == provider:
            trusted[str(label)] = sourced.value
    for canonical, label in _SELECTED_SPEC_ALIASES.items():
        if canonical in trusted:
            trusted.setdefault(label, trusted[canonical])
    return trusted


def _same_selected_value(key: str, actual: object, claimed: object) -> bool:
    if key == "mpn":
        return mpn_identity_key(actual) == mpn_identity_key(claimed)
    return str(actual).strip() == str(claimed).strip()


def validate_official_payloads(
    committed_mpn: str,
    payloads: Mapping[str, Any] | None,
    bindings: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Validate and normalize raw evidence before any library mutation.

    A client-provided binding is not proof by itself. The committed MPN must match both the
    binding's canonical identity and a manufacturer-part-number field inside the raw official
    response. This makes a forged ``PART-B`` binding unable to relabel ``PART-A`` response bytes.
    """

    payloads = payloads or {}
    bindings = bindings or {}
    if not payloads:
        if bindings:
            raise ValueError("official evidence bindings require matching official payloads")
        return {}
    if set(payloads) != set(bindings):
        raise ValueError("every official payload requires one matching evidence binding")

    target = mpn_identity_key(committed_mpn)
    if not target:
        raise ValueError("official evidence requires a committed MPN")
    clean: dict[str, dict[str, Any]] = {}
    for provider, payload in payloads.items():
        if provider not in OFFICIAL_API_PROVIDERS or not isinstance(payload, dict):
            raise ValueError(f"official evidence provider {provider!r} is invalid")
        binding = bindings.get(provider)
        if not isinstance(binding, dict):
            raise ValueError(f"official evidence binding for {provider} is invalid")
        if str(binding.get("provider", "")).strip().lower() != provider:
            raise ValueError(f"official evidence provider binding does not match {provider}")
        queried_mpn = str(binding.get("queried_mpn", "")).strip()
        canonical_mpn = str(binding.get("canonical_mpn", "")).strip()
        selected_values = binding.get("selected_values")
        if not queried_mpn or not canonical_mpn or not isinstance(selected_values, dict):
            raise ValueError(f"official evidence binding for {provider} is incomplete")
        if mpn_identity_key(canonical_mpn) != target:
            raise ValueError(
                f"official evidence for {provider} belongs to {canonical_mpn}, not {committed_mpn}"
            )
        partial, payload_mpns = _parse_exact_result(provider, payload, committed_mpn)
        trusted_values = _trusted_selected_values(provider, partial)
        trusted_mpn = trusted_values.get("mpn")
        if trusted_mpn is None or mpn_identity_key(trusted_mpn) != target:
            observed = payload_mpns[0] if payload_mpns else "an unnamed part"
            raise ValueError(
                f"official evidence for {provider} belongs to {observed}, not {committed_mpn}"
            )
        server_selected: dict[str, object] = {}
        for key, claimed in selected_values.items():
            if not isinstance(key, str) or key not in trusted_values:
                raise ValueError(
                    f"official evidence selected value {key} is absent from the exact {provider} result"
                )
            actual = trusted_values[key]
            if not _same_selected_value(key, actual, claimed):
                raise ValueError(
                    f"official evidence selected value {key} does not match the exact {provider} result"
                )
            server_selected[key] = actual
        clean[provider] = {
            "provider": provider,
            "queried_mpn": queried_mpn,
            "canonical_mpn": str(trusted_mpn),
            "selected_values": server_selected,
        }
    return clean


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
    "validate_official_payloads",
]
