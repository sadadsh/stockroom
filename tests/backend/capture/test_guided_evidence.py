from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from stockroom.capture.evidence import (
    BROWSER_CAPTURE_ADAPTER_VERSION,
    record_browser_cad_evidence,
)
from stockroom.capture.guided import GuidedCaptureSource
from stockroom.capture.requirements import Requirement
from stockroom.evidence import EvidenceStore
from stockroom.ingest.staging import StagingCandidate
from stockroom.planning import KICAD_CAD_OPERATION, ExactPartIdentity

_CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_DETAIL_URL = "https://www.snapeda.com/parts/S1M/ON%20Semiconductor/view-part/"


@dataclass
class _Record:
    id: str = "s1m"
    manufacturer: str = "ON Semiconductor"
    mpn: str = "S1M"


def _candidate(tmp_path: Path, *, model: bool = True) -> StagingCandidate:
    symbol = tmp_path / "S1M.kicad_sym"
    footprint = tmp_path / "S1M.kicad_mod"
    step = tmp_path / "S1M.step"
    symbol.write_bytes(b'(kicad_symbol_lib (version 20231120) (symbol "S1M"))')
    footprint.write_bytes(b'(footprint "D_SMA" (pad "1" smd rect))')
    step.write_bytes(b"ISO-10303-21;\nHEADER;\nENDSEC;\nEND-ISO-10303-21;\n")
    return StagingCandidate(
        vendor="snapmagic",
        symbol_lib_path=symbol,
        symbol_name="S1M",
        footprint_variants=[footprint],
        model_path=step if model else None,
        mpn="S1M",
        manufacturer="ON Semiconductor",
    )


def _altium_pair(tmp_path: Path) -> tuple[Path, Path]:
    symbol = tmp_path / "S1M.SchLib"
    footprint = tmp_path / "S1M.PcbLib"
    symbol.write_bytes(_CFB_MAGIC + b"symbol")
    footprint.write_bytes(_CFB_MAGIC + b"footprint")
    return symbol, footprint


def test_browser_cad_installs_exact_actual_files_with_provider_per_artifact(
    tmp_path: Path,
) -> None:
    store = EvidenceStore(tmp_path / "Evidence")
    candidate = _candidate(tmp_path)
    altium = _altium_pair(tmp_path)

    digest, cross_eda_verified = record_browser_cad_evidence(
        store=store,
        record=_Record(),
        candidate=candidate,
        provider_key="snapmagic",
        detail_url=_DETAIL_URL,
        altium_sources=altium,
    )

    manifest = store.verify_provider_success(
        digest,
        identity=ExactPartIdentity("ON Semiconductor", "S1M"),
        operation=KICAD_CAD_OPERATION,
        provider_key="snapmagic",
        adapter_version=BROWSER_CAPTURE_ADAPTER_VERSION,
    )
    objects = {item["role"]: item for item in manifest["objects"]}
    assert set(objects) == {
        "altium_footprint",
        "altium_symbol",
        "footprint",
        "model",
        "symbol",
        "validation_report",
    }
    assert {item["provider"] for item in objects.values()} == {"snapmagic"}
    assert store.object_bytes(objects["model"]["digest"]) == candidate.model_path.read_bytes()
    report = json.loads(store.object_bytes(objects["validation_report"]["digest"]))
    assert report["identity"] == {
        "authoritative_manufacturer_key": "ON Semiconductor",
        "mpn_canonical": "S1M",
    }
    assert report["cross_eda"]["status"] == "not_verified"
    assert cross_eda_verified is False


def test_browser_cad_cannot_record_a_partial_or_near_match(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "Evidence")
    incomplete = _candidate(tmp_path, model=False)
    with pytest.raises(ValueError, match="missing STEP model"):
        record_browser_cad_evidence(
            store=store,
            record=_Record(),
            candidate=incomplete,
            provider_key="snapmagic",
            detail_url=_DETAIL_URL,
        )

    near = _candidate(tmp_path)
    near.mpn = "S1M-13-F"
    near.symbol_name = "S1M-13-F"
    with pytest.raises(ValueError, match="exact candidate"):
        record_browser_cad_evidence(
            store=store,
            record=_Record(),
            candidate=near,
            provider_key="snapmagic",
            detail_url=_DETAIL_URL,
        )


def test_cross_eda_success_requires_explicit_equivalence_proof(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "Evidence")
    candidate = _candidate(tmp_path)
    altium = _altium_pair(tmp_path)

    with pytest.raises(ValueError, match="terminal, pad, and package"):
        record_browser_cad_evidence(
            store=store,
            record=_Record(),
            candidate=candidate,
            provider_key="snapmagic",
            detail_url=_DETAIL_URL,
            altium_sources=altium,
            cross_eda_verifier=lambda **_kwargs: {"valid": False},
        )

    digest, verified = record_browser_cad_evidence(
        store=store,
        record=_Record(),
        candidate=candidate,
        provider_key="snapmagic",
        detail_url=_DETAIL_URL,
        altium_sources=altium,
        cross_eda_verifier=lambda **_kwargs: {
            "valid": True,
            "terminal_equivalence": True,
            "pad_equivalence": True,
            "package_equivalence": True,
        },
    )
    assert digest.startswith("sha256:")
    assert verified is True


def test_guided_attach_persists_digest_and_refuses_unverified_altium(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    bundle = tmp_path / "download.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("S1M.SchLib", _CFB_MAGIC + b"symbol")
        archive.writestr("S1M.PcbLib", _CFB_MAGIC + b"footprint")

    origins = []
    altium_calls = []

    class _Pipeline:
        def inspect(self, inputs):
            assert inputs == [bundle]
            return [candidate]

        def attach_assets(self, part_id, selected, origin=None):
            assert part_id == "s1m"
            assert selected is candidate
            origins.append(origin)

        def cleanup(self):
            return None

    monkeypatch.setattr(
        "stockroom.capture.guided.get_adapter",
        lambda _key: type(
            "_Adapter",
            (),
            {"capability": type("_Capability", (), {"label": "SnapMagic"})()},
        )(),
    )
    source = GuidedCaptureSource(
        lambda: _Pipeline(),
        vendor="snapmagic",
        download_root=tmp_path / "Downloads",
        attach_altium=lambda *_args, **_kwargs: altium_calls.append(True),
        evidence_store=EvidenceStore(tmp_path / "Evidence"),
        now_iso=lambda: "2026-07-28T00:00:00Z",
    )
    landed = [type("_Captured", (), {"path": bundle})()]

    outcome = source._attach(
        _Record(),
        landed,
        _DETAIL_URL,
        detail_url=_DETAIL_URL,
    )

    assert set(outcome.satisfied) == {
        Requirement.KICAD_SYMBOL,
        Requirement.KICAD_FOOTPRINT,
        Requirement.KICAD_MODEL,
    }
    assert "cross-EDA terminal, pad, and package equivalence is not verified" in outcome.error
    assert not altium_calls
    assert len(origins) == 1
    digest = origins[0].extra["evidence_manifest_digest"]
    assert digest.startswith("sha256:")
    assert origins[0].extra["evidence_operation"] == "cad:kicad"
