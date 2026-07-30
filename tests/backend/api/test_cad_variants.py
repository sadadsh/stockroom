from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from stockroom.api.errors import ApiError
from stockroom.api.routers.cad_variants import ActivateCadPairBody, _activate_pair
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


def _kicad_artifacts(
    marker: str,
    symbol_names: tuple[str, ...] = ("TPS62130",),
) -> tuple[EvidenceArtifact, ...]:
    return (
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
    )


def _altium_artifacts() -> tuple[EvidenceArtifact, ...]:
    return (
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
    )


def _record_pair(
    store: EvidenceStore,
    identity,
    *,
    provider: str,
    marker: str,
    symbol_names: tuple[str, ...] = ("TPS62130",),
) -> str:
    roles = ("symbol", "footprint", "model", "altium_symbol", "altium_footprint")
    return store.record_role_artifact_success(
        identity=identity,
        operation=KICAD_CAD_OPERATION,
        provider_key=provider,
        adapter_version="test-browser-v1",
        artifacts=(
            *_kicad_artifacts(marker, symbol_names),
            *_altium_artifacts(),
        ),
        validation_report=_report(
            identity=identity,
            operation=KICAD_CAD_OPERATION.label,
            provider=provider,
            roles=roles,
        ),
    )


def _record_split_kicad(
    store: EvidenceStore,
    identity,
    *,
    provider: str,
    marker: str,
) -> str:
    roles = ("symbol", "footprint", "model")
    return store.record_role_artifact_success(
        identity=identity,
        operation=KICAD_CAD_OPERATION,
        provider_key=provider,
        adapter_version="test-browser-v1",
        artifacts=_kicad_artifacts(marker),
        validation_report=_report(
            identity=identity,
            operation=KICAD_CAD_OPERATION.label,
            provider=provider,
            roles=roles,
        ),
    )


def _record_split_altium(
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
        artifacts=_altium_artifacts(),
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


def _activate_single_api(client, tool: str, variant: str, expected: str | None):
    return client.post(
        "/api/library/parts/tps62130/cad-variants/activate",
        json={
            "tool": tool,
            "variantId": variant,
            "expectedActiveVariantId": expected,
        },
    )


def _activate_pair_api(
    client,
    variant: str,
    expected_kicad: str | None,
    expected_altium: str | None,
):
    return client.post(
        "/api/library/parts/tps62130/cad-variants/activate-pair",
        json={
            "kicadVariantId": variant,
            "altiumVariantId": variant,
            "expectedActiveKicadVariantId": expected_kicad,
            "expectedActiveAltiumVariantId": expected_altium,
        },
    )


def test_inventory_lists_every_variant_but_only_exact_shared_manifests_as_pairs(
    client,
    anon_client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, identity = _evidence(app_ctx, tmp_path, monkeypatch)
    ultra = _record_pair(
        store,
        identity,
        provider="ultralibrarian",
        marker="ul",
    )
    snap = _record_pair(
        store,
        identity,
        provider="snapmagic",
        marker="snap",
    )
    split_kicad = _record_split_kicad(
        store,
        identity,
        provider="digikey-ultralibrarian",
        marker="split",
    )
    split_altium = _record_split_altium(
        store,
        identity,
        provider="digikey-ultralibrarian",
        kicad_manifest=split_kicad,
    )

    assert anon_client.get(
        "/api/library/parts/tps62130/cad-variants"
    ).status_code == 401
    response = client.get("/api/library/parts/tps62130/cad-variants")
    assert response.status_code == 200
    document = response.json()
    inventories = {item["tool"]: item for item in document["inventories"]}
    assert {item["id"] for item in inventories["kicad"]["variants"]} == {
        ultra,
        snap,
        split_kicad,
    }
    assert {item["id"] for item in inventories["altium"]["variants"]} == {
        ultra,
        snap,
        split_altium,
    }
    assert {
        (pair["kicadVariantId"], pair["altiumVariantId"])
        for pair in document["pairs"]
    } == {(ultra, ultra), (snap, snap)}
    variants = [
        variant
        for inventory in inventories.values()
        for variant in inventory["variants"]
    ]
    assert variants
    assert all(variant["verificationState"] == "reverified" for variant in variants)
    assert all("validationChecks" not in variant for variant in variants)
    assert all(
        pair["verificationState"] == "reverified"
        for pair in document["pairs"]
    )
    assert all(
        pair["trustLabel"] == "Same-Download Validated Pair"
        for pair in document["pairs"]
    )


def test_tampered_evidence_cannot_emit_a_reverified_inventory(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, identity = _evidence(app_ctx, tmp_path, monkeypatch)
    _record_pair(
        store,
        identity,
        provider="ultralibrarian",
        marker="tamper-target",
    )
    symbol = store.list_role_variants(identity=identity, role="symbol")[0]
    store.object_path(symbol.artifact_digest).write_bytes(b"tampered")

    response = client.get("/api/library/parts/tps62130/cad-variants")

    assert response.status_code == 500
    assert "reverified" not in response.text


def test_pair_activation_materializes_all_five_roles_and_both_pointers(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, identity = _evidence(app_ctx, tmp_path, monkeypatch)
    ultra = _record_pair(
        store,
        identity,
        provider="ultralibrarian",
        marker="ul",
    )

    head = app_ctx.repo.head()
    response = _activate_pair_api(client, ultra, None, None)

    assert response.status_code == 200, response.text
    assert app_ctx.repo.head() != head
    inventories = {item["tool"]: item for item in response.json()["inventories"]}
    assert inventories["kicad"]["activeVariantId"] == ultra
    assert inventories["altium"]["activeVariantId"] == ultra
    record = app_ctx.ops.load_record("tps62130")
    assert record.cad_variants.selection_for("kicad").manifest_digest == ultra
    assert record.cad_variants.selection_for("altium").manifest_digest == ultra
    library = app_ctx.profile.library
    assert '"VariantMarker" "ul"' in library.symbol_lib_path("ICs").read_text(
        encoding="utf-8"
    )
    assert '"VariantMarker" "ul"' in (
        library.footprint_lib_path("ICs") / "TPS62130.kicad_mod"
    ).read_text(encoding="utf-8")
    assert b"/* ul */" in (library.models_dir / "TPS62130.step").read_bytes()
    altium_dir = library.parts_dir.parent / "altium"
    assert (altium_dir / "tps62130.SchLib").read_bytes() == (
        ALTIUM_FIXTURES / "sample.SchLib"
    ).read_bytes()
    assert (altium_dir / "tps62130.PcbLib").read_bytes() == (
        ALTIUM_FIXTURES / "sample.PcbLib"
    ).read_bytes()


def test_legacy_single_tool_activation_fails_closed_without_any_mutation(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, identity = _evidence(app_ctx, tmp_path, monkeypatch)
    variant = _record_pair(
        store,
        identity,
        provider="ultralibrarian",
        marker="ul",
    )
    head = app_ctx.repo.head()
    record_before = app_ctx.ops.load_record("tps62130").dumps()

    response = _activate_single_api(client, "kicad", variant, None)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "single-tool CAD activation is disabled; choose one retained same-source "
        "KiCad and Altium pair"
    )
    assert app_ctx.repo.head() == head
    assert app_ctx.ops.load_record("tps62130").dumps() == record_before


def test_supplementary_originals_remain_downloadable_but_never_activatable(
    client,
    anon_client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, identity = _evidence(app_ctx, tmp_path, monkeypatch)
    manifest_digest, data = _record_supplementary(store, identity, tmp_path)

    response = client.get("/api/library/parts/tps62130/cad-variants")

    assert response.status_code == 200
    document = response.json()
    assert all(not inventory["variants"] for inventory in document["inventories"])
    assert document["pairs"] == []
    supplementary = document["supplementary"][0]
    download_url = supplementary["artifacts"][0]["downloadUrl"]
    assert supplementary["canActivate"] is False
    assert anon_client.get(download_url).status_code == 401
    downloaded = client.get(download_url)
    assert downloaded.status_code == 200
    assert downloaded.content == data
    head = app_ctx.repo.head()
    rejected = _activate_single_api(client, "kicad", manifest_digest, None)
    assert rejected.status_code == 409
    assert app_ctx.repo.head() == head


def test_stale_or_failed_pair_switch_leaves_both_tools_and_pointers_unchanged(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, identity = _evidence(app_ctx, tmp_path, monkeypatch)
    ultra = _record_pair(
        store,
        identity,
        provider="ultralibrarian",
        marker="ul",
    )
    snap = _record_pair(
        store,
        identity,
        provider="snapmagic",
        marker="snap",
    )
    assert _activate_pair_api(client, ultra, None, None).status_code == 200

    head = app_ctx.repo.head()
    stale = _activate_pair_api(client, snap, None, None)
    assert stale.status_code == 409
    assert app_ctx.repo.head() == head

    library = app_ctx.profile.library
    altium_dir = library.parts_dir.parent / "altium"
    targets = (
        library.parts_dir / "tps62130.json",
        library.symbol_lib_path("ICs"),
        library.footprint_lib_path("ICs") / "TPS62130.kicad_mod",
        library.models_dir / "TPS62130.step",
        altium_dir / "tps62130.SchLib",
        altium_dir / "tps62130.PcbLib",
    )
    before = {path: path.read_bytes() for path in targets}
    import stockroom.ingest.pipeline as pipeline_module

    def fail_footprint(*_args, **_kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(pipeline_module, "place_footprint", fail_footprint)
    failed = _activate_pair_api(client, snap, ultra, ultra)
    assert failed.status_code == 500
    assert app_ctx.repo.head() == head
    assert {path: path.read_bytes() for path in targets} == before
    record = app_ctx.ops.load_record("tps62130")
    assert record.cad_variants.selection_for("kicad").manifest_digest == ultra
    assert record.cad_variants.selection_for("altium").manifest_digest == ultra


def test_same_provider_and_source_reference_cannot_substitute_for_one_download(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, identity = _evidence(app_ctx, tmp_path, monkeypatch)
    kicad = _record_split_kicad(
        store,
        identity,
        provider="digikey-ultralibrarian",
        marker="split",
    )
    altium = _record_split_altium(
        store,
        identity,
        provider="digikey-ultralibrarian",
        kicad_manifest=kicad,
    )

    response = client.post(
        "/api/library/parts/tps62130/cad-variants/activate-pair",
        json={
            "kicadVariantId": kicad,
            "altiumVariantId": altium,
            "expectedActiveKicadVariantId": None,
            "expectedActiveAltiumVariantId": None,
        },
    )

    assert response.status_code == 409
    assert "one exact provider download evidence set" in response.json()["detail"]
    assert app_ctx.ops.load_record("tps62130").cad_variants.is_empty()


def test_repo_lock_makes_two_null_expected_pair_switches_a_real_compare_and_switch(
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, identity = _evidence(app_ctx, tmp_path, monkeypatch)
    variants = [
        _record_pair(store, identity, provider=provider, marker=provider)
        for provider in ("ultralibrarian", "snapmagic")
    ]
    head = app_ctx.repo.head()

    def run(variant: str):
        try:
            _activate_pair(
                app_ctx,
                "tps62130",
                ActivateCadPairBody(
                    kicadVariantId=variant,
                    altiumVariantId=variant,
                    expectedActiveKicadVariantId=None,
                    expectedActiveAltiumVariantId=None,
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
    record = app_ctx.ops.load_record("tps62130")
    assert (
        record.cad_variants.selection_for("kicad").manifest_digest
        == record.cad_variants.selection_for("altium").manifest_digest
    )


def test_pair_reactivation_uses_the_stable_symbol_entry_in_a_whole_library(
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
    manifest = _record_pair(
        store,
        identity,
        provider="ultralibrarian",
        marker="readback",
        symbol_names=("StableHumanName", "UnrelatedNeighbour"),
    )

    response = _activate_pair_api(client, manifest, None, None)

    assert response.status_code == 200, response.text
    saved = app_ctx.ops.load_record("tps62130")
    assert saved.assets_for("kicad").symbol.name == "StableHumanName"
    text = symbol_path.read_text(encoding="utf-8")
    assert '"StableHumanName"' in text
    assert '"VariantMarker" "readback"' in text
    assert '"UnrelatedNeighbour"' in text
