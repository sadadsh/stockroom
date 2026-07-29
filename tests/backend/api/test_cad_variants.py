from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from stockroom.api.errors import ApiError
from stockroom.api.routers.cad_variants import ActivateCadVariantBody, _activate
from stockroom.capture.download_broker import DownloadReceipt
from stockroom.capture.evidence import exact_identity
from stockroom.evidence import EvidenceArtifact, EvidenceStore
from stockroom.planning import ALTIUM_CAD_OPERATION, KICAD_CAD_OPERATION

ALTIUM_FIXTURES = Path(__file__).parents[1] / "altium" / "fixtures"


def _report(
    *,
    identity,
    operation: str,
    provider: str,
    roles: tuple[str, ...],
    source_manifests: tuple[str, ...] = (),
) -> bytes:
    return json.dumps(
        {
            "identity": {
                "authoritative_manufacturer_key": identity.authoritative_manufacturer_key,
                "mpn_canonical": identity.mpn_canonical,
            },
            "operation": operation,
            "provider": provider,
            "roles": sorted(roles),
            "schema": "stockroom.cad-role-validation/1",
            "source_manifests": sorted(source_manifests),
            "valid": True,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _symbol_library(*names: str, marker: str) -> bytes:
    symbols = "".join(
        (
            f'(symbol "{name}"\n'
            '  (property "Reference" "U" (at 0 0 0))\n'
            f'  (property "Value" "{name}" (at 0 0 0))\n'
            f'  (property "VariantMarker" "{marker}" (at 0 0 0))\n'
            ")\n"
        )
        for name in names
    )
    return (
        "(kicad_symbol_lib\n"
        "  (version 20251024)\n"
        '  (generator "Stockroom")\n'
        f"{symbols})\n"
    ).encode()


def _footprint(marker: str) -> bytes:
    return (
        '(footprint "VendorFootprint"\n'
        "  (version 20240108)\n"
        '  (generator "Stockroom")\n'
        '  (layer "F.Cu")\n'
        f'  (property "VariantMarker" "{marker}")\n'
        '  (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))\n'
        ")\n"
    ).encode()


def _record_kicad(
    store: EvidenceStore,
    identity,
    *,
    provider: str,
    marker: str,
    symbol_names: tuple[str, ...] = ("TPS62130",),
) -> str:
    roles = ("symbol", "footprint", "model")
    return store.record_role_artifact_success(
        identity=identity,
        operation=KICAD_CAD_OPERATION,
        provider_key=provider,
        adapter_version="test-browser-v1",
        artifacts=(
            EvidenceArtifact(
                "symbol",
                _symbol_library(*symbol_names, marker=marker),
                "application/vnd.kicad.symbol-library",
                "TPS62130.kicad_sym",
            ),
            EvidenceArtifact(
                "footprint",
                _footprint(marker),
                "application/vnd.kicad.footprint",
                "TPS62130.kicad_mod",
            ),
            EvidenceArtifact(
                "model",
                f"ISO-10303-21;\n/* {marker} */\nEND-ISO-10303-21;\n".encode(),
                "model/step",
                "TPS62130.step",
            ),
        ),
        validation_report=_report(
            identity=identity,
            operation=KICAD_CAD_OPERATION.label,
            provider=provider,
            roles=roles,
        ),
    )


def _record_altium(
    store: EvidenceStore,
    identity,
    *,
    provider: str,
    kicad_manifest: str,
) -> str:
    roles = ("altium_symbol", "altium_footprint")
    sources = (kicad_manifest,)
    return store.record_role_artifact_success(
        identity=identity,
        operation=ALTIUM_CAD_OPERATION,
        provider_key=provider,
        adapter_version="test-browser-v1",
        artifacts=(
            EvidenceArtifact(
                "altium_symbol",
                (ALTIUM_FIXTURES / "sample.SchLib").read_bytes(),
                "application/vnd.altium.schlib",
                "TPS62130.SchLib",
            ),
            EvidenceArtifact(
                "altium_footprint",
                (ALTIUM_FIXTURES / "sample.PcbLib").read_bytes(),
                "application/vnd.altium.pcblib",
                "TPS62130.PcbLib",
            ),
        ),
        validation_report=_report(
            identity=identity,
            operation=ALTIUM_CAD_OPERATION.label,
            provider=provider,
            roles=roles,
            source_manifests=sources,
        ),
        source_manifests=sources,
    )


def _record_supplementary(
    store: EvidenceStore,
    identity,
    staging: Path,
) -> tuple[str, bytes]:
    data = b"ISO-10303-21;\nTRACEPARTS ORIGINAL\nEND-ISO-10303-21;\n"
    path = staging / "TPS62130-traceparts.step"
    path.write_bytes(data)
    artifact_digest = f"sha256:{hashlib.sha256(data).hexdigest()}"
    manifest_digest = store.record_supplementary_artifacts(
        identity=identity,
        surface_key="digikey",
        provider_key="digikey-traceparts",
        adapter_version="digikey-models/1",
        receipts=(
            DownloadReceipt(
                task_id="capture-traceparts",
                manufacturer_key=identity.authoritative_manufacturer_key,
                mpn_canonical=identity.mpn_canonical,
                path=path,
                suggested_name=path.name,
                source_url="https://www.digikey.com/en/models/123?token=removed",
                final_url="https://cdn.example.invalid/TPS62130.step?key=removed",
                sha256=artifact_digest,
                size_bytes=len(data),
                transport="playwright",
                attempt=1,
                surface_key="digikey",
                evidence_provider_key="digikey-traceparts",
            ),
        ),
    )
    return manifest_digest, data


def _evidence(app_ctx, tmp_path: Path, monkeypatch) -> tuple[EvidenceStore, object]:
    capture_root = tmp_path / "Capture"
    monkeypatch.setenv("STOCKROOM_CAPTURE_DIR", str(capture_root))
    store = EvidenceStore((capture_root / "Evidence").resolve())
    identity = exact_identity(app_ctx.ops.load_record("tps62130"))
    return store, identity


def _activate_api(client, tool: str, variant: str, expected: str | None):
    return client.post(
        "/api/library/parts/tps62130/cad-variants/activate",
        json={
            "tool": tool,
            "variantId": variant,
            "expectedActiveVariantId": expected,
        },
    )


def test_inventory_is_authenticated_ul_first_and_activation_materializes_all_kicad_roles(
    client,
    anon_client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, identity = _evidence(app_ctx, tmp_path, monkeypatch)
    snap = _record_kicad(
        store,
        identity,
        provider="snapmagic",
        marker="snap",
    )
    ultra = _record_kicad(
        store,
        identity,
        provider="ultralibrarian",
        marker="ul",
    )

    assert anon_client.get(
        "/api/library/parts/tps62130/cad-variants"
    ).status_code == 401
    inventory = client.get("/api/library/parts/tps62130/cad-variants")
    assert inventory.status_code == 200
    kicad = inventory.json()["inventories"][0]
    assert [item["id"] for item in kicad["variants"]] == [ultra, snap]
    assert kicad["variants"][0]["provider"] == "Ultra Librarian"
    assert kicad["variants"][0]["trustRank"] == 0

    head = app_ctx.repo.head()
    response = _activate_api(client, "kicad", ultra, None)
    assert response.status_code == 200, response.text
    assert response.json()["inventories"][0]["activeVariantId"] == ultra
    assert app_ctx.repo.head() != head

    record = app_ctx.ops.load_record("tps62130")
    assert record.cad_variants.selection_for("kicad").manifest_digest == ultra
    library = app_ctx.profile.library
    symbol = library.symbol_lib_path("ICs").read_text(encoding="utf-8")
    footprint = (
        library.footprint_lib_path("ICs") / "TPS62130.kicad_mod"
    ).read_text(encoding="utf-8")
    model = (library.models_dir / "TPS62130.step").read_bytes()
    assert '"VariantMarker" "ul"' in symbol
    assert '"VariantMarker" "ul"' in footprint
    assert b"/* ul */" in model


def test_inventory_lists_supplementary_originals_separately_and_downloads_exact_bytes(
    client,
    anon_client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, identity = _evidence(app_ctx, tmp_path, monkeypatch)
    manifest_digest, data = _record_supplementary(
        store,
        identity,
        tmp_path,
    )

    response = client.get("/api/library/parts/tps62130/cad-variants")

    assert response.status_code == 200
    document = response.json()
    assert all(not inventory["variants"] for inventory in document["inventories"])
    assert len(document["supplementary"]) == 1
    supplementary = document["supplementary"][0]
    assert supplementary == {
        "id": manifest_digest,
        "provider": "DigiKey · TraceParts",
        "surface": "DigiKey",
        "adapterVersion": "digikey-models/1",
        "evidenceDigest": manifest_digest,
        "canActivate": False,
        "artifacts": [
            {
                "id": supplementary["artifacts"][0]["id"],
                "fileName": "TPS62130-traceparts.step",
                "sizeBytes": len(data),
                "mediaType": "application/octet-stream",
                "evidenceDigest": supplementary["artifacts"][0]["id"],
                "canActivate": False,
                "downloadUrl": supplementary["artifacts"][0]["downloadUrl"],
            }
        ],
    }
    download_url = supplementary["artifacts"][0]["downloadUrl"]
    assert anon_client.get(download_url).status_code == 401
    downloaded = client.get(download_url)
    assert downloaded.status_code == 200
    assert downloaded.content == data
    assert "TPS62130-traceparts.step" in downloaded.headers["content-disposition"]

    head = app_ctx.repo.head()
    not_projectable = _activate_api(client, "kicad", manifest_digest, None)
    assert not_projectable.status_code == 404
    assert app_ctx.repo.head() == head


def test_activation_stale_compare_and_failed_materialization_leave_zero_trace(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, identity = _evidence(app_ctx, tmp_path, monkeypatch)
    ultra = _record_kicad(
        store,
        identity,
        provider="ultralibrarian",
        marker="ul",
    )
    snap = _record_kicad(
        store,
        identity,
        provider="snapmagic",
        marker="snap",
    )
    assert _activate_api(client, "kicad", ultra, None).status_code == 200

    head = app_ctx.repo.head()
    stale = _activate_api(client, "kicad", snap, None)
    assert stale.status_code == 409
    assert app_ctx.repo.head() == head

    symbol_path = app_ctx.profile.library.symbol_lib_path("ICs")
    symbol_before = symbol_path.read_bytes()
    record_before = app_ctx.ops.load_record("tps62130").dumps()
    import stockroom.ingest.pipeline as pipeline_module

    def fail_footprint(*_args, **_kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(pipeline_module, "place_footprint", fail_footprint)
    failed = _activate_api(client, "kicad", snap, ultra)
    assert failed.status_code == 500
    assert app_ctx.repo.head() == head
    assert symbol_path.read_bytes() == symbol_before
    assert app_ctx.ops.load_record("tps62130").dumps() == record_before


def test_altium_materialization_requires_and_preserves_cross_tool_source_closure(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, identity = _evidence(app_ctx, tmp_path, monkeypatch)
    kicad_a = _record_kicad(
        store,
        identity,
        provider="ultralibrarian",
        marker="a",
    )
    kicad_b = _record_kicad(
        store,
        identity,
        provider="snapmagic",
        marker="b",
    )
    altium_a = _record_altium(
        store,
        identity,
        provider="ultralibrarian",
        kicad_manifest=kicad_a,
    )
    altium_b = _record_altium(
        store,
        identity,
        provider="snapmagic",
        kicad_manifest=kicad_b,
    )

    missing_binding = _activate_api(client, "altium", altium_a, None)
    assert missing_binding.status_code == 409
    assert "compatible KiCad" in missing_binding.json()["detail"]

    assert _activate_api(client, "kicad", kicad_a, None).status_code == 200
    activated = _activate_api(client, "altium", altium_a, None)
    assert activated.status_code == 200, activated.text
    assert activated.json()["inventories"][1]["activeVariantId"] == altium_a
    altium_dir = app_ctx.profile.library.parts_dir.parent / "altium"
    assert (altium_dir / "tps62130.SchLib").read_bytes() == (
        ALTIUM_FIXTURES / "sample.SchLib"
    ).read_bytes()
    assert (altium_dir / "tps62130.PcbLib").read_bytes() == (
        ALTIUM_FIXTURES / "sample.PcbLib"
    ).read_bytes()

    # Neither direction may break the cross-EDA proof while leaving the other tool active.
    assert _activate_api(client, "kicad", kicad_b, kicad_a).status_code == 409
    assert _activate_api(client, "altium", altium_b, altium_a).status_code == 409


def test_repo_lock_makes_two_null_expected_activations_a_real_compare_and_switch(
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, identity = _evidence(app_ctx, tmp_path, monkeypatch)
    variants = [
        _record_kicad(
            store,
            identity,
            provider=provider,
            marker=provider,
        )
        for provider in ("ultralibrarian", "snapmagic")
    ]
    head = app_ctx.repo.head()

    def run(variant: str):
        try:
            _activate(
                app_ctx,
                "tps62130",
                ActivateCadVariantBody(
                    tool="kicad",
                    variantId=variant,
                    expectedActiveVariantId=None,
                ),
                store,
            )
            return 200
        except ApiError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(run, variants))

    assert sorted(statuses) == [200, 409]
    assert app_ctx.repo.head() != head
    assert len(app_ctx.repo.log_paths(
        [app_ctx.profile.library.parts_dir / "tps62130.json"],
        max_count=3,
    )) == 2  # seed + exactly one activation


def test_installed_readback_reactivation_uses_the_stable_entry_in_a_whole_library(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, identity = _evidence(app_ctx, tmp_path, monkeypatch)
    record = app_ctx.ops.load_record("tps62130")
    record.assets_for("kicad").symbol.ref.name = "StableHumanName"
    symbol_path = app_ctx.profile.library.symbol_lib_path("ICs")
    symbol_path.write_bytes(
        _symbol_library("StableHumanName", "UnrelatedNeighbour", marker="old")
    )
    record_path = app_ctx.profile.library.parts_dir / "tps62130.json"
    record_path.write_text(record.dumps(), encoding="utf-8")
    app_ctx.repo.commit("seed stable human entry", [symbol_path, record_path])
    manifest = _record_kicad(
        store,
        identity,
        provider="ultralibrarian",
        marker="readback",
        symbol_names=("StableHumanName", "UnrelatedNeighbour"),
    )

    response = _activate_api(client, "kicad", manifest, None)

    assert response.status_code == 200, response.text
    saved = app_ctx.ops.load_record("tps62130")
    assert saved.assets_for("kicad").symbol.name == "StableHumanName"
    text = symbol_path.read_text(encoding="utf-8")
    assert '"StableHumanName"' in text
    assert '"VariantMarker" "readback"' in text
    assert '"UnrelatedNeighbour"' in text
