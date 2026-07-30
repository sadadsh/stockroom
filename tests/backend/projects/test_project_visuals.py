from pathlib import Path

from stockroom.model.project import ProjectRecord
from stockroom.projects.project_visuals import render_kicad_project


class _MissingCli:
    available = False


class _FakeCli:
    available = True
    binary = "kicad-cli"

    def version(self) -> str:
        return "10.0-test"

    def _run(self, *args: str) -> str:
        output = Path(args[args.index("--output") + 1])
        if args[:3] == ("sch", "export", "svg"):
            output.mkdir(parents=True, exist_ok=True)
            (output / "page.svg").write_text(
                '<svg viewBox="0 0 297 210"></svg>',
                encoding="utf-8",
            )
        elif args[:3] == ("pcb", "export", "svg"):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                '<svg width="640" height="480"></svg>',
                encoding="utf-8",
            )
        elif args[:3] == ("pcb", "export", "ipc2581"):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                """\
<IPC-2581 xmlns="http://webstds.ipc.org/2581">
  <Profile><Polygon>
    <PolyBegin x="10" y="-20"/>
    <PolyStepSegment x="50" y="-20"/>
    <PolyStepSegment x="50" y="-80"/>
    <PolyStepSegment x="10" y="-80"/>
  </Polygon></Profile>
  <Package name="R"><Outline><Polygon>
    <PolyBegin x="-0.5" y="-0.25"/>
    <PolyStepSegment x="0.5" y="0.25"/>
  </Polygon></Outline></Package>
  <Component refDes="R1" packageRef="R" layerRef="F.Cu">
    <Location x="20" y="-30"/>
  </Component>
</IPC-2581>
""",
                encoding="utf-8",
            )
        return ""


class _BadSchematicCli(_FakeCli):
    def __init__(self, content: str) -> None:
        self.content = content

    def _run(self, *args: str) -> str:
        if args[:3] != ("sch", "export", "svg"):
            return super()._run(*args)
        output = Path(args[args.index("--output") + 1])
        output.mkdir(parents=True, exist_ok=True)
        (output / "page.svg").write_text(self.content, encoding="utf-8")
        return ""


class _BadBottomBoardCli(_FakeCli):
    def _run(self, *args: str) -> str:
        if args[:3] != ("pcb", "export", "svg"):
            return super()._run(*args)
        output = Path(args[args.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "<svg></svg>" if "--mirror" in args else '<svg width="640" height="480"></svg>',
            encoding="utf-8",
        )
        return ""


def _project(tmp_path: Path) -> ProjectRecord:
    for name in ("demo.kicad_sch", "demo.kicad_pcb"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    return ProjectRecord(
        id="demo",
        name="Demo",
        root=tmp_path.as_posix(),
        pro_path="demo.kicad_pro",
        sheet_paths=["demo.kicad_sch"],
        board_paths=["demo.kicad_pcb"],
    )


def test_kicad_visuals_block_honestly_without_the_native_runtime(tmp_path: Path):
    bundle = render_kicad_project(_project(tmp_path), _MissingCli())

    assert bundle.evidence["status"] == "blocked"
    assert "not installed" in bundle.evidence["detail"]
    assert bundle.artifacts == {}


def test_kicad_visuals_normalize_schematic_and_board_views(tmp_path: Path):
    bundle = render_kicad_project(_project(tmp_path), _FakeCli())

    assert bundle.evidence["status"] == "ready"
    assert bundle.evidence["runtime"] == {
        "name": "KiCad CLI",
        "version": "10.0-test",
    }
    assert bundle.evidence["summary"] == {
        "documents": 2,
        "artifacts": 3,
        "blocked": 0,
    }
    views = [
        artifact["view"]
        for document in bundle.evidence["documents"]
        for artifact in document["artifacts"]
    ]
    assert views == ["page-1", "top", "bottom"]
    board = next(
        document
        for document in bundle.evidence["documents"]
        if document["kind"] == "pcb"
    )
    assert board["scene"]["bounds"] == {
        "min_x": 10.0,
        "min_y": -80.0,
        "max_x": 50.0,
        "max_y": -20.0,
        "width": 40.0,
        "height": 60.0,
    }
    assert board["scene"]["components"][0]["reference"] == "R1"
    assert {
        (artifact.media_type, len(artifact.content))
        for artifact in bundle.artifacts.values()
    } == {
        ("image/svg+xml", len('<svg viewBox="0 0 297 210"></svg>')),
        ("image/svg+xml", len('<svg width="640" height="480"></svg>')),
    }


def test_kicad_visual_artifact_ids_are_byte_stable(tmp_path: Path):
    first = render_kicad_project(_project(tmp_path), _FakeCli())
    second = render_kicad_project(_project(tmp_path), _FakeCli())

    assert first.evidence["digest"] == second.evidence["digest"]
    assert first.artifacts == second.artifacts


def test_kicad_visuals_do_not_report_success_before_valid_svg_is_observed(
    tmp_path: Path,
):
    # Known-bad negative controls. The HTML payload even carries plausible dimensions: a detector
    # that only scraped width/height would accept it as a native schematic render.
    for content in (
        '<html width="640" height="480"></html>',
        "<svg></svg>",
        '<svg viewBox="0 0 0 0"></svg>',
        '<svg viewBox="0 0 -640 480"></svg>',
        '<svg viewBox="0 0 Infinity 480"></svg>',
    ):
        bundle = render_kicad_project(_project(tmp_path), _BadSchematicCli(content))

        assert bundle.evidence["status"] == "blocked"
        schematic = next(
            document
            for document in bundle.evidence["documents"]
            if document["kind"] == "schematic"
        )
        assert schematic["status"] == "blocked"
        assert schematic["artifacts"] == []
        assert not any(
            artifact["kind"] == "schematic"
            for document in bundle.evidence["documents"]
            for artifact in document["artifacts"]
        )


def test_kicad_visuals_never_publish_half_of_a_board_view_pair(tmp_path: Path):
    bundle = render_kicad_project(_project(tmp_path), _BadBottomBoardCli())

    assert bundle.evidence["status"] == "blocked"
    board = next(
        document
        for document in bundle.evidence["documents"]
        if document["kind"] == "pcb"
    )
    assert board["status"] == "blocked"
    assert board["artifacts"] == []
    assert all(
        artifact["kind"] != "pcb"
        for document in bundle.evidence["documents"]
        for artifact in document["artifacts"]
    )
    assert len(bundle.artifacts) == 1, "only the independently completed schematic is published"
