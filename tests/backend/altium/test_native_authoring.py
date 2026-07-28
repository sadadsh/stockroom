from __future__ import annotations

import hashlib
import io
import json
import zlib
from pathlib import Path

import pytest

from stockroom.altium.driver import RunOutcome
from stockroom.altium.native_authoring import (
    NativeAuthoringResult,
    author_native_component,
    expected_semantic_report,
    read_embedded_model_payloads,
    render_native_authoring_script,
)
from stockroom.domain import (
    AuthoritativeEvidence,
    CanonicalPassiveBundle,
    build_two_pin_passive_bundle,
)


def _digest(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode()).hexdigest()}"


def _bundle() -> CanonicalPassiveBundle:
    return build_two_pin_passive_bundle(
        authoritative_manufacturer_key="ON Semiconductor",
        mpn_canonical="S1M",
        functional_kind="diode",
        value="1 A 1000 V",
        package="SMA (DO-214AC)",
        value_evidence=AuthoritativeEvidence(
            source_kind="qualified_fixture",
            source_locator="fixture://onsemi/S1M/value",
            content_digest=_digest("value"),
        ),
        package_evidence=AuthoritativeEvidence(
            source_kind="qualified_fixture",
            source_locator="fixture://onsemi/S1M/package",
            content_digest=_digest("package"),
        ),
    )


def _render(*, bootstrap: str = "factory") -> str:
    return render_native_authoring_script(
        _bundle(),
        schlib_win=r"C:\Scratch\S1M.SchLib",
        pcblib_win=r"C:\Scratch\DIOM5227X270N.PcbLib",
        step_win=r"C:\Scratch\S1M.step",
        marker_win=r"C:\Scratch\Native Authoring Result.json",
        bootstrap=bootstrap,
    )


def test_factory_bootstrap_uses_native_in_memory_library_factories():
    script = _render()

    assert "SchServer.CreateSchLibrary" in script
    assert "PCBServer.CreatePCBLibrary" in script
    assert "SchLib.SaveToFile(SchPath)" in script
    assert "PcbLib.SaveComponentWithLibrary(FootprintName, PcbPath)" in script
    assert "DM_CreateNewDocument" not in script


def test_workspace_bootstrap_uses_altiums_new_document_surface():
    script = _render(bootstrap="workspace")

    assert "WorkSpace.DM_CreateNewDocument('SCHLIB')" in script
    assert "WorkSpace.DM_CreateNewDocument('PCBLIB')" in script
    assert "DoSafeChangeFileNameAndSave(SchPath, 'SchLib')" in script
    assert "DoSafeChangeFileNameAndSave(PcbPath, 'PcbLib')" in script
    assert "SchServer.CreateSchLibrary" not in script
    assert "PCBServer.CreatePCBLibrary" not in script


def test_script_builds_both_native_semantics_embeds_then_closes_and_reopens():
    script = _render()

    assert "SchServer.SchObjectFactory(eSchComponent, eCreate_Default)" in script
    assert "SchComponent.SetState_PartCountNoPart0(1)" in script
    assert "SchComponent.PartCountNoPart0 :=" not in script
    assert "SchLib.RemoveSchComponent(SchComponent)" in script
    assert script.count("SchServer.SchObjectFactory(ePin, eCreate_Default)") == 2
    assert "SchComponent.AddSchObject(SchPin)" in script
    assert "Footprint := PCBServer.CreatePCBLibComp" in script
    assert "PcbLib.RegisterComponent(Footprint)" in script
    assert "PcbLib.DeRegisterComponent(Footprint)" in script
    assert "PcbLib.AddComponent(FootprintName)" not in script
    assert script.count("PCBServer.PCBObjectFactory(ePadObject") == 2
    assert "Board.AddPCBObject(PcbPad)" in script
    assert "Body.ModelFactory_FromFilename(StepPath, True)" in script
    assert "Board.AddPCBObject(Body)" in script
    assert "Client.OpenDocument('SCHLIB', SchPath)" in script
    assert "Client.OpenDocument('PCBLIB', PcbPath)" in script
    assert "SchParameter.Name" in script
    assert "PersistedBody.Model.Name" in script
    assert "Report.SaveToFile(MarkerPath)" in script

    success = expected_semantic_report(_bundle(), "S1M.step", "factory")
    assert json.dumps(success, separators=(",", ":"), sort_keys=True) in script


class _FakeHost:
    def to_windows_path(self, path: str) -> str:
        return path

    def windows_temp(self) -> Path:
        raise AssertionError("the adapter owns an explicit isolated work directory")


class _FakeDriver:
    def __init__(self, semantic: dict) -> None:
        self.host = _FakeHost()
        self.semantic = semantic
        self.calls: list[dict] = []

    def run_script(self, **kwargs) -> RunOutcome:
        self.calls.append(kwargs)
        marker = Path(kwargs["marker"])
        root = marker.parents[1]
        artifacts = root / "Artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "S1M.SchLib").write_bytes(b"native-schlib")
        (artifacts / "DIOM5227X270N.PcbLib").write_bytes(b"native-pcblib")
        marker.write_text(json.dumps(self.semantic), encoding="utf-8")
        return RunOutcome("ok", "marker written", marker.read_text(encoding="utf-8"))


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    canonical = tmp_path / "Canonical.json"
    canonical.write_bytes(_bundle().canonical_bytes())
    step = tmp_path / "S1M.step"
    step.write_bytes(b"ISO-10303-21;\r\nDATA;\r\nENDSEC;\r\nEND-ISO-10303-21;\r\n")
    return canonical, step


def test_nonempty_output_is_refused_before_spending_an_altium_boot(tmp_path: Path):
    canonical, step = _write_inputs(tmp_path)
    output = tmp_path / "Proof"
    output.mkdir()
    (output / "belongs-to-user.txt").write_text("keep", encoding="utf-8")
    driver = _FakeDriver(expected_semantic_report(_bundle(), step.name, "factory"))

    with pytest.raises(ValueError, match="empty"):
        author_native_component(canonical, step, output, driver=driver)

    assert not driver.calls
    assert (output / "belongs-to-user.txt").read_text(encoding="utf-8") == "keep"


def test_adapter_requires_the_exact_qualified_canonical_slice(tmp_path: Path):
    canonical, step = _write_inputs(tmp_path)
    document = json.loads(canonical.read_text(encoding="utf-8"))
    document["identity"]["mpn_canonical"] = "NOT-S1M"
    canonical.write_text(json.dumps(document), encoding="utf-8")
    driver = _FakeDriver({})

    with pytest.raises(ValueError):
        author_native_component(canonical, step, tmp_path / "Proof", driver=driver)

    assert not driver.calls


def test_adapter_runs_once_and_requires_native_and_independent_readback(
    tmp_path: Path, monkeypatch
):
    canonical, step = _write_inputs(tmp_path)
    semantic = expected_semantic_report(_bundle(), step.name, "factory")
    driver = _FakeDriver(semantic)
    monkeypatch.setattr(
        "stockroom.altium.native_authoring.read_symbol_names",
        lambda _path: ["S1M"],
    )
    monkeypatch.setattr(
        "stockroom.altium.native_authoring.read_footprint_names",
        lambda _path: ["DIOM5227X270N"],
    )
    monkeypatch.setattr(
        "stockroom.altium.native_authoring.read_model_index",
        lambda _path: ({"EMBED": "TRUE", "NAME": step.name},),
    )
    monkeypatch.setattr(
        "stockroom.altium.native_authoring.read_embedded_model_payloads",
        lambda _path: (step.read_bytes(),),
    )

    result = author_native_component(
        canonical,
        step,
        tmp_path / "Proof",
        driver=driver,
    )

    assert isinstance(result, NativeAuthoringResult)
    assert result.ok
    assert len(driver.calls) == 1
    assert result.schlib.name == "S1M.SchLib"
    assert result.pcblib.name == "DIOM5227X270N.PcbLib"
    assert result.semantic_report == semantic
    evidence = json.loads(result.evidence.read_text(encoding="utf-8"))
    assert evidence["status"] == "ok"
    assert evidence["independent_readback"]["symbol_names"] == ["S1M"]
    assert evidence["independent_readback"]["footprint_names"] == ["DIOM5227X270N"]
    assert evidence["independent_readback"]["step_payload_exact_match"] is True
    assert evidence["artifacts"]["schlib"]["sha256"] == hashlib.sha256(b"native-schlib").hexdigest()
    assert (result.output_dir / "Inputs" / "Canonical.json").read_bytes() == canonical.read_bytes()
    assert (result.output_dir / "Inputs" / step.name).read_bytes() == step.read_bytes()


def test_adapter_rejects_an_altium_success_marker_when_ole_bytes_do_not_match(
    tmp_path: Path, monkeypatch
):
    canonical, step = _write_inputs(tmp_path)
    driver = _FakeDriver(expected_semantic_report(_bundle(), step.name, "factory"))
    monkeypatch.setattr(
        "stockroom.altium.native_authoring.read_symbol_names",
        lambda _path: ["S1M"],
    )
    monkeypatch.setattr(
        "stockroom.altium.native_authoring.read_footprint_names",
        lambda _path: ["DIOM5227X270N"],
    )
    monkeypatch.setattr(
        "stockroom.altium.native_authoring.read_model_index",
        lambda _path: ({"EMBED": "TRUE", "NAME": step.name},),
    )
    monkeypatch.setattr(
        "stockroom.altium.native_authoring.read_embedded_model_payloads",
        lambda _path: (b"different STEP bytes",),
    )

    result = author_native_component(
        canonical,
        step,
        tmp_path / "Proof",
        driver=driver,
    )

    assert not result.ok
    assert result.status == "verification-failed"
    assert "payload" in result.detail.lower()


def test_model_payload_reader_decompresses_altiums_numbered_ole_stream(monkeypatch):
    payload = b"ISO-10303-21;\r\nDATA;\r\nENDSEC;\r\nEND-ISO-10303-21;\r\n"
    compressed = zlib.compress(payload)

    class _Ole:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def listdir(self, *, streams: bool):
            assert streams is True
            return [
                ["Library", "Models", "0"],
                ["Library", "Models", "Data"],
                ["Library", "Models", "Header"],
            ]

        def openstream(self, name):
            assert name == ["Library", "Models", "0"]
            return io.BytesIO(compressed)

    monkeypatch.setattr(
        "stockroom.altium.native_authoring.olefile.OleFileIO",
        lambda _path: _Ole(),
    )

    assert read_embedded_model_payloads(Path("proof.PcbLib")) == (payload,)


def test_real_known_altium_payload_round_trips_to_its_source_when_available():
    pcblib = Path(r"C:\srprobe\run\board-add.PcbLib")
    step = Path(r"C:\srprobe\lib\TPD6E05U06RVZR.stp")
    if not pcblib.exists() or not step.exists():
        pytest.skip("requires the retained real AD26 embedding probe")

    payloads = read_embedded_model_payloads(pcblib)

    assert step.read_bytes() in payloads


def test_adapter_preserves_inputs_if_the_driver_fails(tmp_path: Path, monkeypatch):
    canonical, step = _write_inputs(tmp_path)

    class _FailingDriver(_FakeDriver):
        def run_script(self, **kwargs) -> RunOutcome:
            self.calls.append(kwargs)
            return RunOutcome("busy", "A windowed Altium holds the license seat.")

    driver = _FailingDriver({})
    output = tmp_path / "Proof"
    result = author_native_component(canonical, step, output, driver=driver)

    assert not result.ok
    assert result.status == "busy"
    assert (output / "Inputs" / "Canonical.json").read_bytes() == canonical.read_bytes()
    assert (output / "Inputs" / step.name).read_bytes() == step.read_bytes()
    assert not (output / "Artifacts" / "S1M.SchLib").exists()
