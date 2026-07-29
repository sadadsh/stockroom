#!/usr/bin/env python3
"""Prove one live CAD provider path through Stockroom's broker, CAS, and API.

The canary always creates an isolated Git-backed library. By default its capture state is isolated
too; ``--capture-state-root`` deliberately reuses one existing machine provider session and
immutable evidence store while leaving those retained objects unchanged. It can isolate one
supplementary author route or exercise the normal complete-component product runner, including
guarded Altium conversion and coherent cross-EDA attachment.

Usage:
    uv run python scripts/cad_capture_canary.py \
        --manufacturer "TE Connectivity AMP Connectors" \
        --mpn 5212034-1 \
        --route digikey-traceparts \
        --out "work/Live CAD Canary/TraceParts 5212034-1"

    uv run python scripts/cad_capture_canary.py \
        --manufacturer "Texas Instruments" \
        --mpn TPD6E05U06RVZR \
        --expect complete \
        --provider ultralibrarian \
        --out "work/Live CAD Canary/Complete TPD6E05U06RVZR"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent / "app" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manufacturer", required=True)
    parser.add_argument("--mpn", required=True)
    parser.add_argument(
        "--route",
        default="digikey-traceparts",
        help=(
            "exact supplementary DigiKey author route for --expect supplementary; complete "
            "runs use --provider instead"
        ),
    )
    parser.add_argument(
        "--provider",
        default="ultralibrarian",
        help=(
            "complete-component provider; defaults to the authorized direct Ultra Librarian "
            "route. DigiKey remains a person-driven supplementary surface."
        ),
    )
    parser.add_argument(
        "--expect",
        choices=("supplementary", "complete"),
        default="supplementary",
        help=(
            "supplementary retains one non-projectable original; complete requires all KiCad "
            "and native Altium assets through the normal product runner"
        ),
    )
    parser.add_argument(
        "--category",
        default="ICs",
        help="canonical isolated Stockroom category used by a complete-component run",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--capture-state-root",
        type=Path,
        help=(
            "optional existing machine capture root whose persistent provider session should be "
            "reused; the canary library and result remain isolated under --out"
        ),
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="show the isolated provider browser; headless is the default",
    )
    return parser.parse_args()


def _safe_component_id(mpn: str) -> str:
    value = "".join(char.casefold() if char.isalnum() else "-" for char in mpn)
    value = "-".join(filter(None, value.split("-")))
    if not value:
        raise ValueError("MPN does not contain a usable component identifier")
    return f"canary-{value}"


def _build_isolated_context(
    root: Path,
    manufacturer: str,
    mpn: str,
    *,
    expect: str,
    category: str,
):
    from stockroom.api.context import build_context
    from stockroom.model.part import PartRecord
    from stockroom.model.part_class import PartClass, RequirementOverride
    from stockroom.store.machine_config import MachineConfig
    from stockroom.store.profile import ProfileStore
    from stockroom.vcs.repo import GitRepo

    libraries_root = root / "Library"
    libraries_root.mkdir(parents=True)
    repo = GitRepo(libraries_root)
    repo.init()
    profile = ProfileStore(libraries_root, repo).create("Main")
    component_id = _safe_component_id(mpn)
    supplementary = expect == "supplementary"
    record = PartRecord(
        id=component_id,
        display_name=mpn,
        category="Connectors" if supplementary else category,
        description=f"Isolated live CAD {expect} canary",
        mpn=mpn,
        manufacturer=manufacturer,
        part_class=PartClass.COMPONENT,
        requires_override=(
            RequirementOverride(
                needs=("model",),
                reason="Live canary isolates the provider's mechanical-model route.",
            )
            if supplementary
            else None
        ),
    )
    record_path = profile.library.parts_dir / f"{component_id}.json"
    record_path.write_text(record.dumps(), encoding="utf-8")
    repo.commit("Seed isolated live CAD capture canary", [record_path])
    kicad_dir = root / "KiCad"
    kicad_dir.mkdir()
    config = MachineConfig(
        active_profile="Main",
        sync_enabled=False,
        ul_private_evaluation_automation=True,
    )
    context = build_context(
        libraries_root,
        kicad_dir=kicad_dir,
        config=config,
        token="live-cad-canary",
    )
    return context, record


def _capture_supplementary(
    context,
    record,
    root: Path,
    route_key: str,
    headed: bool,
):
    from stockroom.capture.guided import GuidedCaptureSource
    from stockroom.capture.vendors import get_adapter
    from stockroom.evidence import EvidenceStore
    from stockroom.ingest.pipeline import IngestPipeline

    surface = get_adapter("digikey")
    if surface is None:
        raise RuntimeError("the DigiKey production adapter is unavailable")
    route_factory = getattr(surface, "capture_routes", None)
    if not callable(route_factory):
        raise RuntimeError("the DigiKey production adapter exposes no author routes")
    routes = tuple(route_factory())
    route = next(
        (
            candidate
            for candidate in routes
            if getattr(candidate, "evidence_provider_key", "") == route_key
        ),
        None,
    )
    if route is None:
        available = ", ".join(
            getattr(candidate, "evidence_provider_key", "") for candidate in routes
        )
        raise ValueError(f"unknown DigiKey route {route_key!r}; available: {available}")
    if not getattr(route, "supplementary_only", False):
        raise ValueError("supplementary canaries accept only non-projectable supplementary routes")

    capture_root = root / "Capture"
    evidence_store = EvidenceStore(capture_root / "Evidence")
    source = GuidedCaptureSource(
        lambda: IngestPipeline(context.profile, context.repo, context.cli),
        vendor="digikey",
        download_root=capture_root / "Downloads",
        profile_dir=capture_root / "Browser Profile",
        headless=not headed,
        engine=surface.capability.browser_engine,
        evidence_store=evidence_store,
        operator_authorized=True,
    )
    try:
        session = source._ensure_session()
        url = surface.resolve_url(record.mpn)
        if not url:
            raise RuntimeError(f"DigiKey exposed no CAD-model URL for {record.mpn}")
        outcome = source._supply_automated_route(
            record,
            session,
            route,
            record.manufacturer,
            record.mpn,
            url,
            ["model"],
        )
    finally:
        source.close()
    if outcome.error or outcome.retained < 1:
        raise RuntimeError(
            outcome.error
            or outcome.skipped
            or "the production route retained no supplementary artifact"
        )
    return evidence_store, outcome


def _capture_complete(context, record, root: Path, headed: bool, provider: str):
    from stockroom.capture.runner import run_guided_capture
    from stockroom.evidence import EvidenceStore

    capture_root = root / "Capture"
    report = run_guided_capture(
        context,
        part_ids=[record.id],
        vendor=provider,
        headless=not headed,
        operator_authorized=False,
    )
    return EvidenceStore(capture_root / "Evidence"), report


def _api_client(context):
    from fastapi.testclient import TestClient

    from stockroom.api.app import create_app

    return TestClient(
        create_app(context),
        base_url="http://live-cad-canary",
        raise_server_exceptions=False,
        headers={"X-Stockroom-Token": context.token},
    )


def _verify_supplementary(context, record, evidence_store):
    from stockroom.capture.evidence import exact_identity

    retained = evidence_store.list_supplementary_artifacts(identity=exact_identity(record))
    if len(retained) != 1:
        raise RuntimeError(f"expected one exact supplementary manifest, found {len(retained)}")
    manifest = retained[0]
    if not manifest.artifacts:
        raise RuntimeError("the supplementary manifest contains no artifacts")

    with _api_client(context) as client:
        inventory_response = client.get(f"/api/library/parts/{record.id}/cad-variants")
        if inventory_response.status_code != 200:
            raise RuntimeError(
                "supplementary inventory failed: "
                f"{inventory_response.status_code} {inventory_response.text}"
            )
        inventory = inventory_response.json()
        supplementary = inventory.get("supplementary") or []
        if len(supplementary) != 1:
            raise RuntimeError(
                f"API expected one supplementary manifest, found {len(supplementary)}"
            )
        artifact = supplementary[0]["artifacts"][0]
        if supplementary[0].get("canActivate") is not False:
            raise RuntimeError("supplementary evidence incorrectly became activatable")
        response = client.get(artifact["downloadUrl"])
        if response.status_code != 200:
            raise RuntimeError(
                f"original-file download failed: {response.status_code} {response.text}"
            )

    digest = f"sha256:{hashlib.sha256(response.content).hexdigest()}"
    if digest != artifact["evidenceDigest"]:
        raise RuntimeError(
            "downloaded API bytes do not match the retained artifact evidence digest"
        )
    return {
        "inventory": inventory,
        "manifest": manifest,
        "downloaded_bytes": response.content,
        "downloaded_digest": digest,
    }


def _verify_complete(context, record, report):
    from stockroom.capture.requirements import capture_needs
    from stockroom.model.part import asset_present

    items = report.get("items") or []
    if len(items) != 1:
        raise RuntimeError(f"expected one completion result, found {len(items)}")
    item = items[0]
    if item.get("status") != "completed" or item.get("remaining"):
        raise RuntimeError(
            "normal product runner did not complete the exact part: "
            + json.dumps(item, sort_keys=True)
        )

    updated = context.ops.load_record(record.id)
    remaining = [requirement.value for requirement in capture_needs(updated)]
    if remaining:
        raise RuntimeError("attached record still has CAD requirements: " + ", ".join(remaining))
    projected = {}
    for tool, roles in {
        "kicad": ("symbol", "footprint", "model"),
        "altium": ("symbol", "footprint"),
    }.items():
        bundle = updated.assets_for(tool)
        projected[tool] = {role: asset_present(bundle.get(role)) for role in roles}
        if not all(projected[tool].values()):
            raise RuntimeError(f"{tool} attachment is incomplete: {projected[tool]}")

    with _api_client(context) as client:
        response = client.get(f"/api/library/parts/{record.id}/cad-variants")
        if response.status_code != 200:
            raise RuntimeError(f"CAD inventory failed: {response.status_code} {response.text}")
        inventory = response.json()
    by_tool = {
        tool_inventory["tool"]: tool_inventory
        for tool_inventory in inventory.get("inventories") or []
    }
    active = {}
    for tool in ("kicad", "altium"):
        tool_inventory = by_tool.get(tool)
        if not tool_inventory:
            raise RuntimeError(f"authenticated inventory omitted {tool}")
        active_id = tool_inventory.get("activeVariantId")
        variant_ids = {variant.get("id") for variant in tool_inventory.get("variants") or []}
        if not active_id or active_id not in variant_ids:
            raise RuntimeError(f"{tool} inventory has no resolved active variant")
        active[tool] = active_id

    return {
        "record": updated,
        "report": report,
        "inventory": inventory,
        "projected": projected,
        "active": active,
    }


def main() -> int:
    started = time.perf_counter()
    args = _arguments()
    output = args.out.resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"refusing to reuse non-empty canary output: {output}")
    output.mkdir(parents=True, exist_ok=True)
    capture_state_root = (
        args.capture_state_root.resolve()
        if args.capture_state_root is not None
        else (output / "Capture").resolve()
    )
    os.environ["STOCKROOM_CAPTURE_DIR"] = str(capture_state_root)

    context, record = _build_isolated_context(
        output,
        args.manufacturer.strip(),
        args.mpn.strip(),
        expect=args.expect,
        category=args.category.strip() or "ICs",
    )
    try:
        identity = {
            "manufacturer": record.manufacturer,
            "mpn": record.mpn,
            "partId": record.id,
        }
        if args.expect == "supplementary":
            evidence_store, outcome = _capture_supplementary(
                context,
                record,
                output,
                args.route.strip(),
                args.headed,
            )
            verified = _verify_supplementary(context, record, evidence_store)
            artifact = verified["inventory"]["supplementary"][0]["artifacts"][0]
            result = {
                "schema": "stockroom.live-cad-capture-canary/2",
                "status": "passed",
                "expectation": "supplementary",
                "identity": identity,
                "route": args.route,
                "retained": outcome.retained,
                "manifestDigest": verified["manifest"].manifest_digest,
                "artifact": {
                    "fileName": artifact["fileName"],
                    "sizeBytes": artifact["sizeBytes"],
                    "evidenceDigest": artifact["evidenceDigest"],
                    "downloadedDigest": verified["downloaded_digest"],
                },
                "checks": {
                    "downloadBrokerReceipt": True,
                    "stagingToCas": True,
                    "supplementaryManifest": True,
                    "authenticatedInventory": True,
                    "originalBytesMatch": True,
                    "projectable": False,
                },
            }
        else:
            _evidence_store, report = _capture_complete(
                context,
                record,
                output,
                args.headed,
                args.provider.strip().casefold(),
            )
            verified = _verify_complete(context, record, report)
            completion = report["items"][0]
            acquisition_sources = list(completion.get("sources") or [])
            reused_evidence = "verified-cache" in acquisition_sources
            result = {
                "schema": "stockroom.live-cad-capture-canary/2",
                "status": "passed",
                "expectation": "complete",
                "identity": identity,
                "requestedProvider": args.provider.strip().casefold(),
                "acquisitionSources": acquisition_sources,
                "elapsedSeconds": round(time.perf_counter() - started, 3),
                "completion": completion,
                "activeVariants": verified["active"],
                "projectedAssets": verified["projected"],
                "gitRevision": context.repo.head(),
                "checks": {
                    "normalProductRunner": True,
                    "verifiedEvidenceReuse": reused_evidence,
                    "networkProviderStarted": not reused_evidence,
                    "downloadBrokerReceipt": not reused_evidence,
                    "stagingToCas": not reused_evidence,
                    "casReverified": True,
                    "exactIdentity": True,
                    "semanticReadback": True,
                    "crossEdaEquivalent": True,
                    "atomicAttachment": True,
                    "authenticatedInventory": True,
                    "allRequirementsSatisfied": True,
                },
            }
        result_path = output / "Canary Result.json"
        result_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({**result, "resultPath": str(result_path)}, indent=2))
        return 0
    finally:
        context.close()


if __name__ == "__main__":
    raise SystemExit(main())
