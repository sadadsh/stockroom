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
    native_authoring_names,
    read_embedded_model_payloads,
    render_native_authoring_script,
)
from stockroom.domain import (
    AuthoritativeEvidence,
    CanonicalPassiveBundle,
    build_two_pin_passive_bundle,
    canonical_model_digest,
)


def _digest(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode()).hexdigest()}"


def _bundle(
    *,
    manufacturer: str = "ON Semiconductor",
    mpn: str = "S1M",
    value: str = "1 A 1000 V",
    functional_kind: str = "diode",
    package: str = "SMA (DO-214AC)",
) -> CanonicalPassiveBundle:
    fixture_key = hashlib.sha256(f"{manufacturer}\0{mpn}".encode()).hexdigest()
    return build_two_pin_passive_bundle(
        authoritative_manufacturer_key=manufacturer,
        mpn_canonical=mpn,
        functional_kind=functional_kind,
        value=value,
        package=package,
        value_evidence=AuthoritativeEvidence(
            source_kind="qualified_fixture",
            source_locator=f"fixture://native/{fixture_key}/value",
            content_digest=_digest(f"{fixture_key}/value"),
        ),
        package_evidence=AuthoritativeEvidence(
            source_kind="qualified_fixture",
            source_locator=f"fixture://native/{fixture_key}/package",
            content_digest=_digest(f"{fixture_key}/package"),
        ),
    )


def _render(
    bundle: CanonicalPassiveBundle | None = None,
    *,
    bootstrap: str = "factory",
) -> str:
    canonical = bundle or _bundle()
    names = native_authoring_names(canonical)
    return render_native_authoring_script(
        canonical,
        schlib_win=rf"C:\Scratch\{names.schlib_filename}",
        pcblib_win=rf"C:\Scratch\{names.pcblib_filename}",
        step_win=r"C:\Scratch\Model.step",
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

    success = expected_semantic_report(_bundle(), "Model.step", "factory")
    assert json.dumps(success, separators=(",", ":"), sort_keys=True) in script


@pytest.mark.parametrize(
    ("manufacturer", "mpn", "value"),
    (
        ("ON Semiconductor", "S1M", "1 A 1000 V"),
        ("Diodes Incorporated", "S1M-13-F", "1 A 1000 V"),
    ),
)
def test_distinct_qualified_identities_drive_names_parameters_and_semantics(
    manufacturer: str,
    mpn: str,
    value: str,
):
    bundle = _bundle(manufacturer=manufacturer, mpn=mpn, value=value)
    names = native_authoring_names(bundle)
    report = expected_semantic_report(bundle, "Package.step", "factory")
    script = _render(bundle)

    assert names.symbol != "S1M"
    assert names.footprint != "DIOM5227X270N"
    assert bundle.identity.component_id in names.symbol
    assert bundle.identity.component_id in names.footprint
    assert report["identity"] == {
        "component_id": bundle.identity.component_id,
        "manufacturer": manufacturer,
        "mpn": mpn,
    }
    assert report["symbol"] == {
        "name": names.symbol,
        "parameters": {"MF": manufacturer, "MP": mpn},
        "pin_count": 2,
        "pins": [
            {"name": "K", "number": "C"},
            {"name": "A", "number": "A"},
        ],
    }
    assert report["footprint"] == {
        "component_body_count": 1,
        "embedded_models": ["Package.step"],
        "name": names.footprint,
        "pad_count": 2,
        "pads": ["C", "A"],
    }
    assert f"SymbolName    := '{names.symbol}'" in script
    assert f"FootprintName := '{names.footprint}'" in script
    assert f"SchParameter.Text := '{manufacturer}'" in script
    assert f"SchParameter.Text := '{mpn}'" in script
    assert "PcbPad.Name := 'C'" in script
    assert "PcbPad.Name := 'A'" in script


def test_identifiers_are_bounded_path_safe_and_collision_safe_for_adversarial_identities():
    bundles = (
        _bundle(manufacturer="ON Semiconductor", mpn="S1M"),
        _bundle(manufacturer="ON Semiconductor", mpn="s1m"),
        _bundle(manufacturer="Other Semiconductor", mpn="S1M"),
        _bundle(manufacturer="ON Semiconductor", mpn=r"..\S1M/CON:?."),
        _bundle(manufacturer="ON Semiconductor", mpn="X" * 200),
    )
    names = [native_authoring_names(bundle) for bundle in bundles]
    identifiers = [
        identifier for derived in names for identifier in (derived.symbol, derived.footprint)
    ]

    assert len({identifier.casefold() for identifier in identifiers}) == len(identifiers)
    for bundle, derived in zip(bundles, names, strict=True):
        for identifier in (derived.symbol, derived.footprint):
            assert len(identifier) <= 104
            assert identifier.replace("_", "").isalnum()
            assert bundle.identity.component_id in identifier
            assert ".." not in identifier
            assert not any(character in identifier for character in r'\/:*?"<>|')
        assert Path(derived.schlib_filename).name == derived.schlib_filename
        assert Path(derived.pcblib_filename).name == derived.pcblib_filename


def test_exact_identity_is_never_replaced_by_the_sanitized_display_slug():
    bundle = _bundle(
        manufacturer="Maker's Semiconductor",
        mpn=r"..\S1M/CON:?.",
    )
    report = expected_semantic_report(bundle, "Package.step", "factory")
    script = _render(bundle)

    assert report["identity"]["manufacturer"] == "Maker's Semiconductor"
    assert report["identity"]["mpn"] == r"..\S1M/CON:?."
    assert report["symbol"]["parameters"] == {
        "MF": "Maker's Semiconductor",
        "MP": r"..\S1M/CON:?.",
    }
    assert "Maker''s Semiconductor" in script
    assert r"..\S1M/CON:?." in script
    assert r"..\S1M/CON:?." not in native_authoring_names(bundle).symbol


def test_exact_text_that_looks_like_a_renderer_token_is_not_recursively_substituted():
    bundle = _bundle(
        manufacturer="Maker __PIN1_NAME__",
        mpn="__BOOTSTRAP__",
        value="__SUCCESS_JSON__",
    )
    names = native_authoring_names(bundle)
    script = render_native_authoring_script(
        bundle,
        schlib_win=rf"C:\Scratch\__STEP_NAME__\{names.schlib_filename}",
        pcblib_win=rf"C:\Scratch\__MARKER__\{names.pcblib_filename}",
        step_win=r"C:\Scratch\__FOOTPRINT__\Package.step",
        marker_win=r"C:\Scratch\__SYMBOL__\Result.json",
    )

    assert "SchParameter.Text := 'Maker __PIN1_NAME__'" in script
    assert "SchParameter.Text := '__BOOTSTRAP__'" in script
    assert "SchComponent.ComponentDescription := '__SUCCESS_JSON__ diode'" in script
    assert rf"SchPath       := 'C:\Scratch\__STEP_NAME__\{names.schlib_filename}'" in script
    assert rf"PcbPath       := 'C:\Scratch\__MARKER__\{names.pcblib_filename}'" in script
    assert r"StepPath      := 'C:\Scratch\__FOOTPRINT__\Package.step'" in script
    assert r"MarkerPath    := 'C:\Scratch\__SYMBOL__\Result.json'" in script
    assert '"manufacturer":"Maker __PIN1_NAME__"' in script
    assert '"mpn":"__BOOTSTRAP__"' in script


def test_render_rejects_a_procedure_name_that_could_inject_script_source():
    with pytest.raises(ValueError, match="DelphiScript identifier"):
        render_native_authoring_script(
            _bundle(),
            schlib_win=r"C:\Scratch\A.SchLib",
            pcblib_win=r"C:\Scratch\A.PcbLib",
            step_win=r"C:\Scratch\A.step",
            marker_win=r"C:\Scratch\Result.json",
            procedure="Run; End; Procedure Injected",
        )


def test_render_rejects_control_characters_in_exact_parameter_text():
    bundle = _bundle(mpn="S1M\nInjected")

    with pytest.raises(ValueError, match="control character"):
        native_authoring_names(bundle)


@pytest.mark.parametrize(
    "bundle",
    (
        _bundle(manufacturer="Dïodes Incorporated"),
        _bundle(mpn="Ｓ1M"),
        _bundle(value="1 A 1000 V—qualified"),
    ),
    ids=("manufacturer", "mpn", "value"),
)
def test_unqualified_unicode_parameter_text_is_rejected_fail_closed(
    bundle: CanonicalPassiveBundle,
):
    with pytest.raises(ValueError, match="non-ASCII.*not been independently qualified"):
        native_authoring_names(bundle)


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
        symbol_name = self.semantic["symbol"]["name"]
        footprint_name = self.semantic["footprint"]["name"]
        (artifacts / f"{symbol_name}.SchLib").write_bytes(b"native-schlib")
        (artifacts / f"{footprint_name}.PcbLib").write_bytes(b"native-pcblib")
        marker.write_text(json.dumps(self.semantic), encoding="utf-8")
        return RunOutcome("ok", "marker written", marker.read_text(encoding="utf-8"))


def _write_inputs(
    tmp_path: Path,
    bundle: CanonicalPassiveBundle | None = None,
) -> tuple[Path, Path]:
    canonical_bundle = bundle or _bundle()
    canonical = tmp_path / "Canonical.json"
    canonical.write_bytes(canonical_bundle.canonical_bytes())
    step = tmp_path / "S1M.step"
    step.write_bytes(b"ISO-10303-21;\r\nDATA;\r\nENDSEC;\r\nEND-ISO-10303-21;\r\n")
    return canonical, step


def _replace_definition(
    bundle: CanonicalPassiveBundle,
    definition,
) -> CanonicalPassiveBundle:
    definition_digest = canonical_model_digest(definition)
    artifacts = bundle.artifacts.model_copy(update={"definition_digest": definition_digest})
    verification = bundle.verification.model_copy(
        update={
            "artifact_set_digest": canonical_model_digest(artifacts),
            "definition_digest": definition_digest,
        }
    )
    return CanonicalPassiveBundle.model_validate(
        bundle.model_copy(
            update={
                "artifacts": artifacts,
                "definition": definition,
                "verification": verification,
            }
        ).model_dump(mode="python")
    )


def _replace_artifacts(
    bundle: CanonicalPassiveBundle,
    artifacts,
) -> CanonicalPassiveBundle:
    verification = bundle.verification.model_copy(
        update={"artifact_set_digest": canonical_model_digest(artifacts)}
    )
    return CanonicalPassiveBundle.model_validate(
        bundle.model_copy(
            update={
                "artifacts": artifacts,
                "verification": verification,
            }
        ).model_dump(mode="python")
    )


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


def test_adapter_revalidates_exact_identity_links_before_spending_an_altium_boot(
    tmp_path: Path,
):
    canonical, step = _write_inputs(tmp_path)
    document = json.loads(canonical.read_text(encoding="utf-8"))
    document["identity"]["mpn_canonical"] = "NOT-S1M"
    canonical.write_text(json.dumps(document), encoding="utf-8")
    driver = _FakeDriver({})

    with pytest.raises(ValueError):
        author_native_component(canonical, step, tmp_path / "Proof", driver=driver)

    assert not driver.calls


def test_canonical_resistor_profile_is_rejected_because_this_renderer_is_diode_only():
    resistor = _bundle(
        functional_kind="resistor",
        package="0603 (1608 Metric)",
        value="10 kOhm",
    )

    with pytest.raises(ValueError, match="two-pin diode/SMA"):
        native_authoring_names(resistor)


def test_relinked_but_different_geometry_is_rejected_fail_closed():
    bundle = _bundle()
    body = bundle.definition.body.model_copy(update={"max_x_nm": 1_100_000})
    definition = bundle.definition.model_copy(update={"body": body})
    changed = _replace_definition(bundle, definition)

    with pytest.raises(ValueError, match="shared-template geometry"):
        expected_semantic_report(changed, "Package.step", "factory")


def test_forged_template_contract_digest_is_rejected_even_when_links_are_repaired():
    bundle = _bundle()
    symbol = bundle.artifacts.shared_templates[0].model_copy(
        update={"contract_digest": f"sha256:{'0' * 64}"}
    )
    artifacts = bundle.artifacts.model_copy(
        update={"shared_templates": (symbol, bundle.artifacts.shared_templates[1])}
    )
    changed = _replace_artifacts(bundle, artifacts)

    with pytest.raises(ValueError, match="shared-template geometry"):
        native_authoring_names(changed)


def test_changed_altium_terminal_binding_is_rejected_even_when_links_are_repaired():
    bundle = _bundle()
    altium = bundle.artifacts.tool_bindings[1]
    terminal = altium.terminal_bindings[0].model_copy(update={"tool_terminal": "K"})
    changed_altium = altium.model_copy(
        update={"terminal_bindings": (terminal, altium.terminal_bindings[1])}
    )
    artifacts = bundle.artifacts.model_copy(
        update={"tool_bindings": (bundle.artifacts.tool_bindings[0], changed_altium)}
    )
    changed = _replace_artifacts(bundle, artifacts)

    with pytest.raises(ValueError, match="Altium C/A terminal contract"):
        render_native_authoring_script(
            changed,
            schlib_win=r"C:\Scratch\A.SchLib",
            pcblib_win=r"C:\Scratch\A.PcbLib",
            step_win=r"C:\Scratch\A.step",
            marker_win=r"C:\Scratch\Result.json",
        )


@pytest.mark.parametrize(
    "bundle",
    (
        _bundle(),
        _bundle(
            manufacturer="Diodes Incorporated",
            mpn="S1M-13-F",
        ),
    ),
    ids=("onsemi-s1m", "diodes-s1m-13-f"),
)
def test_adapter_runs_once_and_requires_native_and_independent_readback(
    tmp_path: Path,
    monkeypatch,
    bundle: CanonicalPassiveBundle,
):
    names = native_authoring_names(bundle)
    canonical, step = _write_inputs(tmp_path, bundle)
    semantic = expected_semantic_report(bundle, step.name, "factory")
    driver = _FakeDriver(semantic)
    monkeypatch.setattr(
        "stockroom.altium.native_authoring.read_symbol_names",
        lambda _path: [names.symbol],
    )
    monkeypatch.setattr(
        "stockroom.altium.native_authoring.read_footprint_names",
        lambda _path: [names.footprint],
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
    assert result.schlib.name == names.schlib_filename
    assert result.pcblib.name == names.pcblib_filename
    assert result.semantic_report == semantic
    evidence = json.loads(result.evidence.read_text(encoding="utf-8"))
    assert evidence["status"] == "ok"
    assert evidence["native_names"] == {
        "footprint": names.footprint,
        "symbol": names.symbol,
    }
    assert evidence["independent_readback"]["symbol_names"] == [names.symbol]
    assert evidence["independent_readback"]["footprint_names"] == [names.footprint]
    assert evidence["independent_readback"]["step_payload_exact_match"] is True
    assert evidence["artifacts"]["schlib"]["sha256"] == hashlib.sha256(b"native-schlib").hexdigest()
    assert (result.output_dir / "Inputs" / "Canonical.json").read_bytes() == canonical.read_bytes()
    assert (result.output_dir / "Inputs" / step.name).read_bytes() == step.read_bytes()


def test_adapter_rejects_an_altium_success_marker_when_ole_bytes_do_not_match(
    tmp_path: Path, monkeypatch
):
    bundle = _bundle()
    names = native_authoring_names(bundle)
    canonical, step = _write_inputs(tmp_path, bundle)
    driver = _FakeDriver(expected_semantic_report(bundle, step.name, "factory"))
    monkeypatch.setattr(
        "stockroom.altium.native_authoring.read_symbol_names",
        lambda _path: [names.symbol],
    )
    monkeypatch.setattr(
        "stockroom.altium.native_authoring.read_footprint_names",
        lambda _path: [names.footprint],
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
    bundle = _bundle()
    names = native_authoring_names(bundle)
    canonical, step = _write_inputs(tmp_path, bundle)

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
    assert not (output / "Artifacts" / names.schlib_filename).exists()
