"""CAD assets: what this part holds for each EDA tool, and what proved it.

Four things stay strictly separate here, because collapsing any two of them is what made a CAD
column impossible to act on:

    the SOURCE      which provider supplied the file, and the page it came from;
    the PROVIDER    what that provider is and whether it exports for this tool at all;
    the FORMAT      which tool the file is native to, per registered EDA tool;
    the COMPATIBILITY  whether the tool can hold this kind of asset separately at all.

Altium is the case that proves the last one matters: it embeds a 3D body inside the footprint
library rather than storing it separately, so a missing standalone Altium model is not a gap - it
is a tool that does not have that slot. Reporting it as missing demanded a file that cannot
exist. Nothing here touches the cross-provider rule: one verified set per provider is deliberate
and is enforced elsewhere, untouched.
"""

from __future__ import annotations

from typing import Any

from stockroom.eda.registry import all_tools
from stockroom.model.asset import ASSET_KINDS, Asset
from stockroom.model.trust import Verdict, asset_verdict
from stockroom.providers import provider_label

# One representation's readiness. "review" means Stockroom TRIED to measure and could not, which
# is a different and weaker statement than "this is wrong" (`failed`).
REPRESENTATION_STATUSES: frozenset[str] = frozenset(
    {"ready", "review", "missing", "failed", "not_required"}
)

# Worst first: one failing tool must not be hidden behind another tool's clean result.
_STATUS_RANK: tuple[str, ...] = ("failed", "review", "missing", "ready", "not_required")


def _asset_status(asset: Asset | None, *, required: bool) -> str:
    if asset is None or not asset.is_present():
        return "missing" if required else "not_required"
    verdict = asset_verdict(asset)
    if verdict is Verdict.FAIL:
        return "failed"
    # An asset carrying checks that could not measure is honestly unreviewed, which is a weaker
    # claim than ready. An asset nobody ever measured is not accused of anything.
    if verdict is Verdict.UNKNOWN and asset.checks:
        return "review"
    return "ready"


def _tool_supports(tool, kind: str) -> bool:
    if kind in getattr(tool, "unsupported_assets", {}):
        return False
    return kind in ASSET_KINDS


def representation(record, kind: str) -> dict[str, Any]:
    """One asset kind across every registered tool, worst status first."""
    tools: list[dict[str, Any]] = []
    statuses: list[str] = []
    for tool in all_tools():
        if not _tool_supports(tool, kind):
            continue
        needed = kind in record.needs(tool.key)
        asset = record.assets_for(tool.key).get(kind)
        status = _asset_status(asset, required=needed)
        statuses.append(status)
        origin = asset.origin if asset is not None else None
        tools.append(
            {
                "tool": tool.key,
                "toolLabel": tool.label,
                "status": status,
                "present": bool(asset is not None and asset.is_present()),
                # The tool carries this asset INSIDE another file rather than separately.
                "embedded": kind in getattr(tool, "embedded_assets", {}),
                "reference": {
                    "lib": asset.ref.lib if asset else "",
                    "name": asset.ref.name if asset else "",
                    "file": asset.ref.file if asset else "",
                },
                "sourceId": origin.vendor if origin else "",
                "sourceLabel": provider_label(origin.vendor) if origin else "",
                "sourceUrl": origin.url if origin else "",
                "capturedAt": origin.captured_at if origin else "",
                "checks": [
                    {
                        "check": check.check,
                        "measured": check.measured,
                        "expected": check.expected,
                        "against": check.against,
                        "checkedAt": check.checked_at,
                        "note": check.note,
                    }
                    for check in (asset.checks if asset else [])
                ],
            }
        )

    status = next((item for item in _STATUS_RANK if item in statuses), "not_required")
    selected = next(
        (view for view in tools if view["status"] == "ready"),
        next((view for view in tools if view["present"]), None),
    )
    issue = None
    if status == "missing":
        issue = "No file is attached yet."
    elif status == "failed":
        issue = "A recorded check did not pass."
    elif status == "review":
        issue = "A recorded check could not be measured."
    return {
        "kind": kind,
        "status": status,
        "selectedTool": (selected or {}).get("tool", "") or "shared",
        "tools": tools,
        "sourceLabel": (selected or {}).get("sourceLabel", ""),
        "issue": issue,
    }


def build_cad_assets(record, schema, coverage: Any = None) -> dict[str, Any]:
    """Every asset kind, plus the specifications each artifact can be validated against.

    `coverage` is the same provider-coverage document the dossier already carries, passed in so
    the preferred-source decision is answered against the five-state vocabulary that screen
    speaks rather than a second reading of the same evidence. Omitting it leaves the preference
    with no options to offer, which is the honest answer for a caller that has no coverage.
    """
    kinds = {kind: representation(record, kind) for kind in ASSET_KINDS}
    # Imported here rather than at module scope because `cad_preference` reads `representation`
    # from this module; keeping the edge one-directional at import time keeps the two readable
    # in either order.
    from stockroom.dossier.cad_preference import build_cad_preference

    return {
        "kinds": kinds,
        "preference": build_cad_preference(record, coverage),
        "tools": [{"key": tool.key, "label": tool.label} for tool in all_tools()],
        # Named by the category schema, so what a footprint is checked against on a connector
        # (positions and pitch) is not what it is checked against on a microcontroller.
        "validationRelationships": [
            {
                "field": item.field_key,
                "artifact": item.artifact,
                "check": item.check,
                "note": item.note,
            }
            for item in schema.cad_relationships
        ],
    }


__all__ = ["REPRESENTATION_STATUSES", "build_cad_assets", "representation"]
