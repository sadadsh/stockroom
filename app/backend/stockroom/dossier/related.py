"""Related parts, each carrying WHY it is related.

An unexplained "related" row is not information. It asks the reader to work out for themselves
whether the suggestion is the same part in a different body, the same function in a faster logic
family, a reel instead of a cut tape, or a distributor's cross-sell - and those have completely
different consequences for a design.

So every row here states its reason, and the reason is derived from the normalized differences
between this part and the suggested one rather than copied from a distributor's own label. Where
the only honest reason IS the distributor's suggestion, that is said plainly: "DigiKey suggests
this" is a real, checkable why, and it is not the same claim as "these are interchangeable".
Stockroom has validated nothing about electrical or mechanical equivalence and never implies it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from stockroom.providers import provider_label

# The catalogue relationship keys, and the product concept each becomes.
RELATION_KINDS: tuple[tuple[str, str, str], ...] = (
    ("alternate_packaging", "alternatePackaging", "Alternate Packaging"),
    ("substitutions", "substitutions", "Potential Substitutions"),
    ("recommended_products", "recommendations", "Recommendations"),
    ("associations", "associations", "Associated Products"),
)

# Every reason a row may carry, and what it actually claims.
REASONS: tuple[tuple[str, str], ...] = (
    ("same_function_different_package", "Same function, different package"),
    ("same_function_different_logic_family", "Same function, different logic family"),
    ("alternate_packaging", "Same part, different packaging"),
    ("substitution", "Offered as a substitution"),
    ("distributor_recommendation", "Suggested by the distributor"),
    ("distributor_association", "Associated by the distributor"),
)
REASON_LABELS: dict[str, str] = dict(REASONS)

# Package names as they appear inside a description or hang off an MPN. Compared with all
# punctuation removed, so `SOT-23` and `SOT23` are one token.
_PACKAGE_TOKENS: tuple[str, ...] = (
    "0201", "0402", "0603", "0805", "1206", "1210", "2010", "2512",
    "sot23", "sot223", "sot323", "sot363", "sc70", "sc88",
    "soic", "sop", "ssop", "tssop", "msop", "vssop", "qsop",
    "qfn", "dfn", "udfn", "wson", "lga", "bga", "wlcsp", "csp",
    "lqfp", "tqfp", "qfp", "pdip", "dip", "sip",
    "to220", "to252", "to263", "to92", "sod123", "sod323", "sod523", "dpak",
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
# A 74-series logic type: an optional vendor prefix, the 74, the family letters, an optional
# gate-count infix (`1G` on a single-gate part), then the type number. The family letters are
# what separates HC from LVC from AHCT at the same function, and the type number is the function
# itself - `08` is an AND gate whichever family implements it.
_LOGIC_TYPE = re.compile(
    r"(?:sn|mc|cd|tc|nl|hd)?74([a-z]{0,6})(?:\dg)?(\d{2,4})", re.IGNORECASE
)


def _fold(text: object) -> str:
    return _NON_ALNUM.sub("", str(text or "").casefold())


def _package_token(text: object) -> str:
    folded = _fold(text)
    for token in _PACKAGE_TOKENS:
        if token in folded:
            return token
    return ""


def _logic_type(mpn: object) -> tuple[str, str]:
    match = _LOGIC_TYPE.search(str(mpn or ""))
    if match is None:
        return "", ""
    return match.group(1).upper(), match.group(2)


def _shared_root(left: object, right: object) -> int:
    """How many leading characters two MPNs share once punctuation is folded away."""
    a, b = _fold(left), _fold(right)
    shared = 0
    for x, y in zip(a, b):
        if x != y:
            break
        shared += 1
    return shared


def _same_base_part(ours: object, theirs: object) -> bool:
    """True when two MPNs are plainly variants of one base part number.

    Four shared leading characters is not enough on its own - `STM32` alone would match half a
    catalogue - so the shared run must also cover most of the shorter number.
    """
    shared = _shared_root(ours, theirs)
    shorter = min(len(_fold(ours)), len(_fold(theirs)))
    return shared >= 4 and shorter > 0 and shared / shorter >= 0.6


def _reason(
    kind: str,
    *,
    our_mpn: str,
    our_package: str,
    their_mpn: str,
    their_text: str,
) -> tuple[str, list[dict[str, str]]]:
    """The reason this row is related, and the differences that proved it."""
    our_family, our_type = _logic_type(our_mpn)
    their_family, their_type = _logic_type(their_mpn)
    if our_type and our_type == their_type and our_family != their_family:
        return "same_function_different_logic_family", [
            {"field": "logic_family", "ours": our_family or "(none)", "theirs": their_family
             or "(none)"},
            {"field": "gate_function", "ours": our_type, "theirs": their_type},
        ]
    if kind == "alternate_packaging":
        return "alternate_packaging", []
    their_package = _package_token(f"{their_text} {their_mpn}")
    if our_package and their_package and our_package != their_package:
        if _same_base_part(our_mpn, their_mpn):
            return "same_function_different_package", [
                {"field": "package", "ours": our_package, "theirs": their_package},
            ]
    if kind == "substitutions":
        return "substitution", []
    if kind == "recommended_products":
        return "distributor_recommendation", []
    return "distributor_association", []


def _our_package(specifications) -> str:
    for item in getattr(specifications, "records", ()) or ():
        if item.get("key") == "package" and item.get("displayValue"):
            return _package_token(item["displayValue"]) or _fold(item["displayValue"])
    return ""


def build_related_parts(record, specifications) -> list[dict[str, Any]]:
    """Every catalogue relationship, normalized into product concepts with a stated reason."""
    our_mpn = str(getattr(record, "mpn", "") or "")
    our_package = _our_package(specifications)
    out: list[dict[str, Any]] = []
    for source_key, view_key, label in RELATION_KINDS:
        for provider_key, payload in (getattr(record, "catalog", None) or {}).items():
            if not isinstance(payload, Mapping):
                continue
            for item in payload.get(source_key) or []:
                if not isinstance(item, Mapping):
                    continue
                their_mpn = str(
                    item.get("manufacturer_product_number") or item.get("mpn") or ""
                )
                description = str(item.get("description") or "")
                reason, evidence = _reason(
                    source_key,
                    our_mpn=our_mpn,
                    our_package=our_package,
                    their_mpn=their_mpn,
                    their_text=description,
                )
                out.append(
                    {
                        "mpn": their_mpn,
                        "manufacturer": str(item.get("manufacturer") or ""),
                        "description": description,
                        "url": str(item.get("product_url") or item.get("url") or ""),
                        "provider": str(provider_key),
                        "providerLabel": provider_label(str(provider_key)),
                        "relation": view_key,
                        "relationLabel": label,
                        "reason": reason,
                        "reasonLabel": REASON_LABELS[reason],
                        # What the reason was read off. Empty for a reason that IS the
                        # provenance - a distributor's own suggestion needs no measurement.
                        "evidence": evidence,
                        # Stated on every row: a suggestion is a suggestion. Stockroom has not
                        # checked that either part can replace the other.
                        "validated": False,
                    }
                )
    return out


__all__ = ["REASONS", "REASON_LABELS", "RELATION_KINDS", "build_related_parts"]
