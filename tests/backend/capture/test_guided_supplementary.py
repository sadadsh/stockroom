from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from stockroom.cad_variants import list_cad_variants
from stockroom.capture.complete import SourceOutcome
from stockroom.capture.download_broker import DownloadReceipt
from stockroom.capture.guided import GuidedCaptureSource, _combine_route_outcomes
from stockroom.evidence import EvidenceStore
from stockroom.planning import ExactPartIdentity

_STEP = (
    b"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('Stockroom fixture'),'2;1');\n"
    b"ENDSEC;\nDATA;\n#1=CARTESIAN_POINT('',(0.,0.,0.));\nENDSEC;\n"
    b"END-ISO-10303-21;\n"
)


class _Pipeline:
    def __init__(self, model_path: Path) -> None:
        self._model_path = model_path
        self.cleaned = False

    def inspect(self, *, inputs):
        assert inputs
        return [SimpleNamespace(model_path=self._model_path)]

    def cleanup(self) -> None:
        self.cleaned = True


class _Record:
    id = "part-traceparts"
    manufacturer = "TE Connectivity AMP Connectors"
    mpn = "5212034-1"


def _receipt(path: Path, *, provider: str = "digikey-traceparts") -> DownloadReceipt:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return DownloadReceipt(
        task_id=_Record.id,
        manufacturer_key=_Record.manufacturer,
        mpn_canonical=_Record.mpn,
        path=path,
        suggested_name=path.name,
        source_url="https://www.digikey.com/en/models/file.step?token=secret",
        final_url="https://www.digikey.com/en/models/file.step?token=secret",
        sha256=f"sha256:{digest}",
        size_bytes=path.stat().st_size,
        transport="playwright",
        attempt=1,
        surface_key="digikey",
        evidence_provider_key=provider,
    )


def test_traceparts_step_is_retained_without_satisfying_or_activating_cad(tmp_path):
    staged = tmp_path / "5212034-1.step"
    staged.write_bytes(_STEP)
    pipeline = _Pipeline(staged)
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    source = GuidedCaptureSource(
        lambda: pipeline,
        vendor="digikey",
        download_root=tmp_path / "Downloads",
        evidence_store=store,
    )

    outcome = source._retain_supplementary(
        _Record(),
        [_receipt(staged)],
        detail_url=(
            "https://www.digikey.com/en/products/detail/"
            "te-connectivity-amp-connectors/5212034-1/2038204"
        ),
        surface_key="digikey",
        evidence_provider_key="digikey-traceparts",
    )

    identity = ExactPartIdentity(_Record.manufacturer, _Record.mpn)
    listed = store.list_supplementary_artifacts(identity=identity)
    assert outcome.retained == 1
    assert outcome.satisfied == ()
    assert outcome.error == ""
    assert "no incomplete CAD bundle was activated" in outcome.skipped
    assert pipeline.cleaned is True
    assert len(listed) == 1
    assert listed[0].provider_key == "digikey-traceparts"
    assert list_cad_variants(store, identity=identity, tool="kicad") == ()
    assert list_cad_variants(store, identity=identity, tool="altium") == ()


def test_traceparts_retention_rejects_invalid_step_and_wrong_route(tmp_path):
    invalid = tmp_path / "not-a-step.bin"
    invalid.write_bytes(b"not STEP")
    pipeline = _Pipeline(invalid)
    source = GuidedCaptureSource(
        lambda: pipeline,
        vendor="digikey",
        download_root=tmp_path / "Downloads",
        evidence_store=EvidenceStore((tmp_path / "Evidence").resolve()),
    )

    invalid_outcome = source._retain_supplementary(
        _Record(),
        [_receipt(invalid)],
        detail_url=(
            "https://www.digikey.com/en/products/detail/"
            "te-connectivity-amp-connectors/5212034-1/2038204"
        ),
        surface_key="digikey",
        evidence_provider_key="digikey-traceparts",
    )
    wrong_route = source._retain_supplementary(
        _Record(),
        [_receipt(invalid, provider="digikey-ultralibrarian")],
        detail_url=(
            "https://www.digikey.com/en/products/detail/"
            "te-connectivity-amp-connectors/5212034-1/2038204"
        ),
        surface_key="digikey",
        evidence_provider_key="digikey-traceparts",
    )

    assert invalid_outcome.retained == 0
    assert "no structurally valid STEP" in invalid_outcome.error
    assert "binding mismatch for evidence provider key" in wrong_route.error


def test_route_outcomes_report_retention_separately_from_satisfaction():
    combined = _combine_route_outcomes(
        [
            ("TraceParts", SourceOutcome(retained=2, skipped="retained")),
            ("Ultra Librarian", SourceOutcome(retained=1)),
        ]
    )

    assert combined.retained == 3
    assert combined.satisfied == ()


def test_catalog_authorized_step_only_snapmagic_download_survives_slug_punctuation_loss(tmp_path):
    class MaximRecord:
        id = "max17608atc-373c"
        manufacturer = "Analog Devices / Maxim Integrated"
        mpn = "MAX17608ATC+"

    staged = tmp_path / "MAX17608ATC.step"
    staged.write_bytes(_STEP)
    store = EvidenceStore((tmp_path / "Evidence").resolve())
    source = GuidedCaptureSource(
        lambda: _Pipeline(staged),
        vendor="digikey",
        download_root=tmp_path / "Downloads",
        evidence_store=store,
    )
    receipt = replace(
        _receipt(staged, provider="digikey-snapmagic"),
        task_id=MaximRecord.id,
        manufacturer_key=MaximRecord.manufacturer,
        mpn_canonical=MaximRecord.mpn,
    )

    outcome = source._retain_incomplete_cad_set(
        MaximRecord(),
        [receipt],
        detail_url=(
            "https://www.snapeda.com/parts/MAX17608ATC-/"
            "Analog-Devices-Maxim-Integrated/view-part/"
        ),
        evidence_provider_key="digikey-snapmagic",
        reason="provider offered only a STEP model",
        catalog_identity_authorized=True,
    )

    assert outcome.retained == 1
    assert outcome.error == ""
    retained = store.list_supplementary_artifacts(
        identity=ExactPartIdentity(MaximRecord.manufacturer, MaximRecord.mpn)
    )
    assert len(retained) == 1
    assert retained[0].provider_key == "digikey-snapmagic"
