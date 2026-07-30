from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Literal

import pytest

from stockroom.capture.download_broker import DownloadBroker, DownloadTask, RetryPolicy
from stockroom.capture.sources import (
    COHERENT_DUAL_EDA_REQUIREMENTS,
    BrokeredDirectSource,
    CadIngestDecline,
    CoherentCadActivation,
    DirectCadDownload,
    DirectCadOffer,
    GenerationQualification,
    QualifiedDualEdaGeneratorSource,
)
from stockroom.domain.canonical import AuthoritativeEvidence
from stockroom.evidence import EvidenceStore
from stockroom.model.part import Asset, AssetRef, EdaAssets, PartRecord
from stockroom.model.part_class import PartClass
from stockroom.planning import ExactPartIdentity

_IDENTITY = ExactPartIdentity("onsemi", "S1M")
_MANIFEST = "sha256:" + "a" * 64
_ROUTE = "digikey:digikey-manufacturer"
_DETAIL_URL = "https://www.digikey.com/en/products/detail/onsemi/S1M/123"


class _Response:
    def __init__(self, url: str, data: bytes) -> None:
        self.status_code = 200
        self.url = url
        self.headers: dict[str, str] = {}
        self.content = data

    def iter_content(self, *, chunk_size: int):
        del chunk_size
        yield self.content

    def close(self) -> None:
        return None


def _record(
    *,
    identity: ExactPartIdentity = _IDENTITY,
    part_class: PartClass = PartClass.COMPONENT,
    complete: bool = False,
) -> PartRecord:
    assets = {}
    if complete:
        assets = {
            "kicad": EdaAssets(
                symbol=Asset(AssetRef(lib="SR-Diodes", name=identity.mpn_canonical)),
                footprint=Asset(AssetRef(lib="SR-Diodes", name="D_SMA")),
                model=Asset(AssetRef(file=f"{identity.mpn_canonical}.step")),
            ),
            "altium": EdaAssets(
                symbol=Asset(
                    AssetRef(lib="Stockroom.SchLib", name=identity.mpn_canonical)
                ),
                footprint=Asset(AssetRef(lib="Stockroom.PcbLib", name="D_SMA")),
            ),
        }
    return PartRecord(
        id=identity.mpn_canonical.casefold(),
        display_name=identity.mpn_canonical,
        category="Diodes",
        description="Rectifier diode",
        manufacturer=identity.authoritative_manufacturer_key,
        mpn=identity.mpn_canonical,
        part_class=part_class,
        assets=assets,
    )


def _offer(
    *downloads: DirectCadDownload,
    identity: ExactPartIdentity = _IDENTITY,
) -> DirectCadOffer:
    return DirectCadOffer(
        identity=identity,
        provider_key="digikey",
        author_key="digikey-manufacturer",
        detail_url=_DETAIL_URL,
        downloads=downloads
        or (
            DirectCadDownload(
                "https://mm.digikey.com/models/S1M-KiCad.zip?signature=secret",
                "S1M-KiCad.zip",
            ),
            DirectCadDownload(
                "https://mm.digikey.com/models/S1M-Altium.zip?signature=secret",
                "S1M-Altium.zip",
            ),
        ),
    )


def _direct_source(
    tmp_path: Path,
    *,
    resolve_offer,
    ingest,
    http_get,
    verify_activation=lambda _record, digest: digest == _MANIFEST,
):
    staging = tmp_path / "downloads"
    staging.mkdir()
    store = EvidenceStore(tmp_path / "evidence")
    tasks: list[DownloadTask] = []

    def broker_factory(task: DownloadTask) -> DownloadBroker:
        tasks.append(task)
        return DownloadBroker(
            task,
            http_get=http_get,
            retry_policy=RetryPolicy(attempts=1, backoff_seconds=()),
        )

    source = BrokeredDirectSource(
        provider_key="digikey",
        author_key="digikey-manufacturer",
        report_label="DigiKey · Manufacturer Provided",
        admitted_route_ids=frozenset({_ROUTE}),
        staging_root=staging,
        resolve_offer=resolve_offer,
        ingest=ingest,
        evidence_store=store,
        verify_activation=verify_activation,
        broker_factory=broker_factory,
        task_id_factory=lambda: "direct-test-task",
    )
    return source, store, tasks, staging


def _generation_evidence(
    *,
    source_kind: Literal[
        "manufacturer_datasheet",
        "manufacturer_catalog",
        "qualified_fixture",
    ] = "manufacturer_datasheet",
    source_locator: str = "https://www.onsemi.com/download/data-sheet/pdf/s1m-d.pdf",
) -> AuthoritativeEvidence:
    return AuthoritativeEvidence(
        source_kind=source_kind,
        source_locator=source_locator,
        content_digest="sha256:" + "b" * 64,
    )


def _qualification(
    *,
    identity: ExactPartIdentity = _IDENTITY,
    part_class: PartClass = PartClass.COMPONENT,
    evidence: tuple[AuthoritativeEvidence, ...] | None = None,
) -> GenerationQualification:
    return GenerationQualification(
        identity=identity,
        part_class=part_class,
        profile_key="diode.sma.v1",
        evidence=evidence or (_generation_evidence(),),
    )


def _generator_source(
    *,
    qualifications: tuple[GenerationQualification, ...] | None = None,
    verify_evidence=lambda _evidence: True,
    generate=lambda record, qualification: CoherentCadActivation(
        qualification.identity,
        _MANIFEST,
        _record(identity=qualification.identity, part_class=record.part_class, complete=True),
    ),
    verify_activation=lambda _record, digest: digest == _MANIFEST,
    supported_evidence_classes: frozenset[str] = frozenset(
        {"manufacturer_datasheet"}
    ),
) -> QualifiedDualEdaGeneratorSource:
    return QualifiedDualEdaGeneratorSource(
        qualifications=qualifications or (_qualification(),),
        supported_part_classes=frozenset({PartClass.COMPONENT}),
        supported_profiles=frozenset({"diode.sma.v1"}),
        supported_evidence_classes=supported_evidence_classes,
        verify_evidence=verify_evidence,
        generate=generate,
        verify_activation=verify_activation,
    )


@pytest.mark.parametrize(
    "url",
    (
        "http://mm.digikey.com/models/S1M.step",
        "file:///C:/Users/example/S1M.step",
        "https://user:password@mm.digikey.com/models/S1M.step",
    ),
)
def test_direct_download_accepts_only_credential_free_https(url):
    with pytest.raises(ValueError, match="HTTPS URL without embedded credentials"):
        DirectCadDownload(url, "S1M.step")


def test_direct_offer_is_immutable_and_has_no_local_path_seam():
    offer = _offer()

    assert offer.route_id == _ROUTE
    assert {field for field in offer.__dataclass_fields__} == {
        "identity",
        "provider_key",
        "author_key",
        "detail_url",
        "downloads",
    }
    assert {field for field in offer.downloads[0].__dataclass_fields__} == {
        "url",
        "suggested_filename",
    }
    with pytest.raises(FrozenInstanceError):
        setattr(offer, "detail_url", "https://example.invalid/replacement")


def test_direct_source_rejects_a_route_the_policy_did_not_admit(tmp_path):
    staging = tmp_path / "downloads"
    staging.mkdir()

    with pytest.raises(ValueError, match="not policy-admitted"):
        BrokeredDirectSource(
            provider_key="digikey",
            author_key="digikey-manufacturer",
            report_label="Manufacturer Provided",
            admitted_route_ids=frozenset({"digikey:digikey-ultralibrarian"}),
            staging_root=staging,
            resolve_offer=lambda _record, _identity: None,
            ingest=lambda _record, _offer, _receipts: CadIngestDecline("not used"),
            evidence_store=EvidenceStore(tmp_path / "evidence"),
            verify_activation=lambda _record, _digest: False,
        )


def test_brokered_direct_source_downloads_only_the_offer_and_activates_a_reverified_pair(
    tmp_path,
):
    calls: list[str] = []

    def http_get(url, **_kwargs):
        calls.append(url)
        return _Response(url, f"bytes:{url}".encode())

    observed_receipts = []

    def ingest(_record, offer, receipts):
        observed_receipts.extend(receipts)
        return CoherentCadActivation(
            offer.identity,
            _MANIFEST,
            _record_for_offer(offer),
        )

    def _record_for_offer(offer):
        return _record(identity=offer.identity, complete=True)

    offer = _offer()
    source, _store, tasks, staging = _direct_source(
        tmp_path,
        resolve_offer=lambda _record, _identity: offer,
        ingest=ingest,
        http_get=http_get,
    )

    outcome = source.supply(_record())

    assert outcome.satisfied == COHERENT_DUAL_EDA_REQUIREMENTS
    assert outcome.retained == 0
    assert outcome.provider_outcomes[0].route_id == _ROUTE
    assert outcome.provider_outcomes[0].status == "activated"
    assert calls == [download.url for download in offer.downloads]
    assert len(tasks) == 1
    assert tasks[0].manufacturer_key == _IDENTITY.authoritative_manufacturer_key
    assert tasks[0].mpn_canonical == _IDENTITY.mpn_canonical
    assert tasks[0].surface_key == "digikey"
    assert tasks[0].evidence_provider_key == "digikey-manufacturer"
    assert all(receipt.transport == "http" for receipt in observed_receipts)
    assert all(receipt.path.is_relative_to(staging) for receipt in observed_receipts)
    assert all("signature=" not in receipt.source_url for receipt in observed_receipts)


def test_partial_direct_download_is_retained_as_supplementary_and_never_activated(
    tmp_path,
):
    offer = _offer(
        DirectCadDownload(
            "https://mm.digikey.com/models/S1M.step",
            "S1M.step",
        )
    )
    source, store, _tasks, _staging = _direct_source(
        tmp_path,
        resolve_offer=lambda _record, _identity: offer,
        ingest=lambda _record, _offer, _receipts: CadIngestDecline(
            "the route supplied STEP only; native KiCad and Altium libraries are absent"
        ),
        http_get=lambda url, **_kwargs: _Response(url, b"ISO-10303-21;\nEND-ISO-10303-21;"),
    )

    outcome = source.supply(_record())

    assert outcome.satisfied == ()
    assert outcome.retained == 1
    assert "no incomplete CAD bundle was activated" in outcome.skipped
    assert outcome.provider_outcomes[0].status == "succeeded-retained"
    retained = store.list_supplementary_artifacts(identity=_IDENTITY)
    assert len(retained) == 1
    assert retained[0].surface_key == "digikey"
    assert retained[0].provider_key == "digikey-manufacturer"


def test_a_later_download_failure_retains_earlier_bytes_without_calling_ingest(tmp_path):
    first_url = "https://mm.digikey.com/models/S1M.step"
    second_url = "https://mm.digikey.com/models/S1M-Altium.zip"
    offer = _offer(
        DirectCadDownload(first_url, "S1M.step"),
        DirectCadDownload(second_url, "S1M-Altium.zip"),
    )
    ingested = []

    def http_get(url, **_kwargs):
        if url == second_url:
            raise RuntimeError("connection lost")
        return _Response(url, b"ISO-10303-21;\nEND-ISO-10303-21;")

    source, store, _tasks, _staging = _direct_source(
        tmp_path,
        resolve_offer=lambda _record, _identity: offer,
        ingest=lambda *_args: ingested.append(True),
        http_get=http_get,
    )

    outcome = source.supply(_record())

    assert outcome.satisfied == ()
    assert outcome.retained == 1
    assert outcome.error
    assert outcome.provider_outcomes[0].status == "failed"
    assert ingested == []
    assert len(store.list_supplementary_artifacts(identity=_IDENTITY)) == 1


def test_direct_offer_identity_mismatch_fails_before_any_download(tmp_path):
    calls = []
    wrong = ExactPartIdentity("onsemi", "S2M")
    source, _store, _tasks, _staging = _direct_source(
        tmp_path,
        resolve_offer=lambda _record, _identity: _offer(identity=wrong),
        ingest=lambda *_args: pytest.fail("identity mismatch must not reach ingest"),
        http_get=lambda url, **_kwargs: calls.append(url),
    )

    outcome = source.supply(_record())

    assert outcome.satisfied == ()
    assert "identity does not match" in outcome.error
    assert calls == []


def test_activation_without_same_manifest_reverification_is_retained_not_claimed(
    tmp_path,
):
    offer = _offer()
    source, store, _tasks, _staging = _direct_source(
        tmp_path,
        resolve_offer=lambda _record, _identity: offer,
        ingest=lambda _record, offer, _receipts: CoherentCadActivation(
            offer.identity,
            _MANIFEST,
            _record_for_identity(offer.identity),
        ),
        http_get=lambda url, **_kwargs: _Response(url, b"CAD bytes"),
        verify_activation=lambda _record, _digest: False,
    )

    outcome = source.supply(_record())

    assert outcome.satisfied == ()
    assert outcome.retained == len(offer.downloads)
    assert "not reverified" in outcome.error
    assert len(store.list_supplementary_artifacts(identity=_IDENTITY)) == 1


def _record_for_identity(
    identity: ExactPartIdentity,
    *,
    complete: bool = True,
) -> PartRecord:
    return _record(identity=identity, complete=complete)


def test_generation_qualification_rejects_fixture_and_local_evidence():
    fixture = _generation_evidence(
        source_kind="qualified_fixture",
        source_locator="https://example.invalid/fixture.json",
    )
    with pytest.raises(ValueError, match="only network manufacturer evidence"):
        _qualification(evidence=(fixture,))

    local = _generation_evidence(source_locator="C:/Evidence/S1M.pdf")
    with pytest.raises(ValueError, match="HTTPS URL"):
        _qualification(evidence=(local,))


def test_generator_runs_only_one_explicit_exact_qualification():
    calls = []

    def generate(record, qualification):
        calls.append((record.mpn, qualification.profile_key))
        return CoherentCadActivation(
            qualification.identity,
            _MANIFEST,
            _record(identity=qualification.identity, complete=True),
        )

    source = _generator_source(generate=generate)

    outcome = source.supply(_record())

    assert outcome.satisfied == COHERENT_DUAL_EDA_REQUIREMENTS
    assert outcome.provider_outcomes[0].status == "activated"
    assert calls == [("S1M", "diode.sma.v1")]


def test_generator_does_not_claim_arbitrary_mpn_support():
    calls = []
    source = _generator_source(generate=lambda *_args: calls.append(True))
    other = ExactPartIdentity("onsemi", "S2M")

    outcome = source.supply(_record(identity=other))

    assert outcome.satisfied == ()
    assert "no qualified deterministic generator profile" in outcome.skipped
    assert outcome.provider_outcomes[0].status == "not-attempted"
    assert calls == []


def test_generator_fails_closed_when_network_evidence_is_not_reverified():
    calls = []
    source = _generator_source(
        verify_evidence=lambda _evidence: False,
        generate=lambda *_args: calls.append(True),
    )

    outcome = source.supply(_record())

    assert outcome.satisfied == ()
    assert "not present and digest-verified" in outcome.error
    assert calls == []


def test_generator_configuration_rejects_unqualified_evidence_classes():
    qualification = _qualification(evidence=(_generation_evidence(
        source_kind="manufacturer_catalog",
        source_locator="https://www.onsemi.com/products/discrete-power-modules/S1M",
    ),))

    with pytest.raises(ValueError, match="unsupported evidence class"):
        _generator_source(
            qualifications=(qualification,),
            supported_evidence_classes=frozenset({"manufacturer_datasheet"}),
        )


def test_generated_activation_must_be_complete_and_reverified():
    source = _generator_source(
        generate=lambda _current, qualification: CoherentCadActivation(
            qualification.identity,
            _MANIFEST,
            _record_for_identity(qualification.identity, complete=False),
        ),
    )

    incomplete = source.supply(_record())

    assert incomplete.satisfied == ()
    assert "activation is incomplete" in incomplete.error

    unverified_source = _generator_source(
        verify_activation=lambda _record, _digest: False,
    )
    unverified = unverified_source.supply(_record())
    assert unverified.satisfied == ()
    assert "not reverified" in unverified.error
