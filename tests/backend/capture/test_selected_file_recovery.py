from pathlib import Path
from types import SimpleNamespace

from stockroom.capture.complete import Requirement, SourceOutcome
from stockroom.capture.guided import GuidedCaptureSource


def test_selected_files_are_copied_into_the_task_bound_broker(monkeypatch, tmp_path: Path) -> None:
    selected = tmp_path / "Downloaded.zip"
    selected.write_bytes(b"selected CAD bytes")
    observed = {}
    source = GuidedCaptureSource(
        lambda: object(),
        vendor="digikey",
        download_root=tmp_path / "Task Downloads",
    )

    def attach(record, landed, url, **options):
        observed["record"] = record
        observed["receipt"] = landed[0]
        observed["url"] = url
        observed["options"] = options
        return SourceOutcome(satisfied=(Requirement.KICAD_SYMBOL,))

    monkeypatch.setattr(source, "_attach", attach)
    record = SimpleNamespace(
        id="part-1",
        manufacturer="Texas Instruments",
        mpn="TPS62130",
    )
    detail_url = "https://www.digikey.com/en/products/detail/ti/TPS62130"

    outcome = source.attach_selected_files(
        record,
        (selected,),
        detail_url=detail_url,
        evidence_provider_key="digikey-snapmagic",
    )

    receipt = observed["receipt"]
    assert outcome.satisfied == (Requirement.KICAD_SYMBOL,)
    assert selected.read_bytes() == b"selected CAD bytes"
    assert receipt.path != selected
    assert receipt.path.read_bytes() == selected.read_bytes()
    assert receipt.task_id == "part-1"
    assert receipt.manufacturer_key == "Texas Instruments"
    assert receipt.mpn_canonical == "TPS62130"
    assert receipt.surface_key == "digikey"
    assert receipt.evidence_provider_key == "digikey-snapmagic"
    assert receipt.transport == "manual-file-picker"
    assert observed["url"] == detail_url
    assert observed["options"]["detail_url"] == detail_url
