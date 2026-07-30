"""Native Altium schematic and PCB print rendering for exact-commit review."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from stockroom.altium.driver import AltiumDriver
from stockroom.altium.project_scene import export_altium_board_scenes
from stockroom.altium.project_validation import (
    _copy_project,
    _execution_descriptor,
    _pascal,
    _set_line,
)
from stockroom.model.project import ProjectRecord
from stockroom.projects.project_visuals import (
    ProjectVisualBundle,
    VisualArtifact,
    artifact_metadata,
)

_SCHEMA_VERSION = 1


def _digest(value: object) -> str:
    body = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _template_for(driver: AltiumDriver, name: str) -> Path | None:
    if driver.x2 is None:
        return None
    candidate = (
        Path("C:/Users/Public/Documents/Altium")
        / driver.x2.parent.name
        / "OutputJobs"
        / name
    )
    return candidate if candidate.is_file() else None


def _disable_outputs(text: str) -> str:
    text = re.sub(
        r"(?m)^OutputEnabled\d+=.*$",
        lambda match: match.group(0).split("=", 1)[0] + "=0",
        text,
    )
    return re.sub(
        r"(?m)^OutputEnabled\d+_OutputMedium\d+=.*$",
        lambda match: match.group(0).split("=", 1)[0] + "=0",
        text,
    )


def _configure_publish_target(
    text: str,
    *,
    output_index: str,
    medium_index: str,
    medium_name: str,
    document_path: str,
    target_pdf: Path,
) -> str:
    text = _disable_outputs(text)
    text = _set_line(text, "TargetOutputMedium", medium_name)
    text = _set_line(text, f"OutputEnabled{output_index}", "1")
    text = _set_line(
        text,
        f"OutputEnabled{output_index}_OutputMedium{medium_index}",
        "1",
    )
    text = _set_line(text, f"OutputDocumentPath{output_index}", document_path)
    text = _set_line(text, f"OutputFilePath{medium_index}", str(target_pdf))
    text = _set_line(
        text,
        f"OutputBasePath{medium_index}",
        str(target_pdf.parent),
    )
    text = _set_line(text, f"OutputPathMedia{medium_index}", "")
    text = _set_line(text, f"OutputPathMediaValue{medium_index}", "")
    text = _set_line(text, f"OutputPathOutputer{medium_index}", "")
    text = _set_line(text, f"OutputPathOutputerPrefix{medium_index}", "")
    text = _set_line(text, f"OutputPathOutputerValue{medium_index}", "")
    text = _set_line(text, f"RelativeOutputPath{medium_index}", str(target_pdf))
    text = _set_line(text, f"OutputFileName{medium_index}", target_pdf.name)
    text = _set_line(text, f"OutputFileNameMulti{medium_index}", target_pdf.name)
    text = _set_line(text, f"UseOutputNameForMulti{medium_index}", "0")
    text = _set_line(text, f"PublishMethod{medium_index}", "1")
    text = _set_line(text, f"OpenOutput{medium_index}", "0")
    text = _set_line(text, f"OpenOutputs{medium_index}", "0")
    text = _set_line(text, f"AddToProject{medium_index}", "0")
    return text


def _configure_schematic_outjob(
    source: Path,
    target: Path,
    target_pdf: Path,
) -> str:
    raw = source.read_bytes()
    text = raw.decode("latin-1").replace("\r\n", "\n")
    output_match = re.search(r"(?m)^OutputType(\d+)=Schematic Print$", text)
    medium_match = re.search(r"(?m)^OutputMedium(\d+)=Documentation$", text)
    if output_match is None or medium_match is None:
        raise ValueError("installed Assembly.OutJob has no Schematic Prints PDF mapping")
    text = _configure_publish_target(
        text,
        output_index=output_match.group(1),
        medium_index=medium_match.group(1),
        medium_name="Documentation",
        document_path="[Project Physical Documents]",
        target_pdf=target_pdf,
    )
    target.write_text(text, encoding="latin-1", newline="\r\n")
    return hashlib.sha256(raw).hexdigest()


def _pcb_configuration(
    text: str,
    *,
    output_index: str,
    side: str,
) -> str:
    pattern = re.compile(
        rf"(?m)^Configuration{re.escape(output_index)}_Item\d+=(.*)$"
    )
    rows = pattern.findall(text)
    if not rows:
        raise ValueError("installed Fabrication.OutJob has no PCB print configuration")
    allowed = (
        {"TopLayer", "TopOverlay", "MultiLayer"}
        if side == "top"
        else {"BottomLayer", "BottomOverlay", "MultiLayer"}
    )
    kept: list[str] = []
    for row in rows:
        if "Record=PcbPrintLayer" in row:
            layer = re.search(r"(?:^|\|)Layer=([^|]+)", row)
            if layer is None or layer.group(1) not in allowed:
                continue
        if "Record=PcbPrintOut" in row:
            row = re.sub(r"(?:^|\|)Mirror=(?:True|False)", "", row).strip("|")
            row += f"|Mirror={'True' if side == 'bottom' else 'False'}"
            row = re.sub(
                r"(?:^|\|)Name=[^|]*",
                f"|Name={side.title()} copper + overlay",
                row,
            ).strip("|")
        kept.append(row)
    if not any("Record=PcbPrintLayer" in row for row in kept):
        raise ValueError(f"installed Fabrication.OutJob has no {side} PCB layers")
    text = pattern.sub("", text)
    configured = "\n".join(
        f"Configuration{output_index}_Item{index}={row}"
        for index, row in enumerate(kept, 1)
    )
    insertion = re.search(
        rf"(?m)^Configuration{re.escape(output_index)}_Count=.*$",
        text,
    )
    if insertion:
        text = _set_line(text, f"Configuration{output_index}_Count", str(len(kept)))
        return text[: insertion.end()] + "\n" + configured + text[insertion.end() :]
    page_options = re.search(
        rf"(?m)^PageOptions{re.escape(output_index)}=.*$",
        text,
    )
    if page_options is None:
        raise ValueError("installed Fabrication.OutJob has no PCB page options")
    return text[: page_options.end()] + "\n" + configured + text[page_options.end() :]


def _configure_pcb_outjob(
    source: Path,
    target: Path,
    *,
    board_name: str,
    side: str,
    target_pdf: Path,
) -> str:
    raw = source.read_bytes()
    text = raw.decode("latin-1").replace("\r\n", "\n")
    output_match = re.search(r"(?m)^OutputType(\d+)=PCB Print$", text)
    medium_match = re.search(r"(?m)^OutputMedium(\d+)=PDF$", text)
    if output_match is None or medium_match is None:
        raise ValueError("installed Fabrication.OutJob has no PCB Prints PDF mapping")
    output_index = output_match.group(1)
    text = _configure_publish_target(
        text,
        output_index=output_index,
        medium_index=medium_match.group(1),
        medium_name="PDF",
        document_path=board_name,
        target_pdf=target_pdf,
    )
    text = _pcb_configuration(text, output_index=output_index, side=side)
    target.write_text(text, encoding="latin-1", newline="\r\n")
    return hashlib.sha256(raw).hexdigest()


def _render_script(
    *,
    descriptor: Path,
    jobs: list[tuple[Path, str, str, Path, Path]],
    marker: Path,
) -> str:
    steps = []
    for outjob, _medium, document_type, document, output_pdf in jobs:
        steps.append(
            f"""
        SourceDoc := Client.OpenDocument('{_pascal(document_type)}', '{_pascal(document)}');
        If SourceDoc <> Nil Then
            Client.ShowDocument(SourceDoc);
        OutJob := Client.OpenDocument('OUTPUTJOB', '{_pascal(outjob)}');
        If OutJob = Nil Then
            Lines.Add('JOB|{_pascal(outjob.name)}|blocked|output job did not open')
        Else
        Begin
            Client.ShowDocument(OutJob);
            ResetParameters;
            AddStringParameter('Action', 'PublishToPDF');
            AddStringParameter('DisableDialog', 'True');
            AddStringParameter('ObjectKind', 'OutputBatch');
            RunProcess('WorkspaceManager:Print');
            If FileExists('{_pascal(output_pdf)}') Then
                Lines.Add('JOB|{_pascal(outjob.name)}|completed|PDF produced')
            Else
                Lines.Add('JOB|{_pascal(outjob.name)}|completed|PDF generation returned');
            Client.CloseDocument(OutJob);
        End;
        If SourceDoc <> Nil Then
            Client.CloseDocument(SourceDoc);
"""
        )
    return f"""{{ GENERATED by stockroom.altium.project_visuals. }}
Procedure RunStockroomProjectVisuals;
Var
    WS      : IWorkspace;
    Prj     : IProject;
    SourceDoc : IServerDocument;
    OutJob : IServerDocument;
    Lines  : TStringList;
Begin
    Lines := TStringList.Create;
    Try
        ResetParameters;
        AddStringParameter('ObjectKind', 'Project');
        AddStringParameter('FileName', '{_pascal(descriptor)}');
        RunProcess('WorkspaceManager:OpenObject');
        ResetParameters;
        WS := GetWorkspace;
        If WS = Nil Then
        Begin
            Lines.Add('STATUS|blocked|workspace unavailable');
            Lines.SaveToFile('{_pascal(marker)}');
            Exit;
        End;
        Prj := WS.DM_FocusedProject;
        If Prj = Nil Then
        Begin
            Lines.Add('STATUS|blocked|project did not become focused');
            Lines.SaveToFile('{_pascal(marker)}');
            Exit;
        End;
        Prj.DM_Compile;
{''.join(steps)}
        Lines.Add('STATUS|completed|native documentation generation returned');
        Lines.SaveToFile('{_pascal(marker)}');
    Except
        Lines.Add('STATUS|blocked|Altium visual script exception');
        Lines.SaveToFile('{_pascal(marker)}');
    End;
    Lines.Free;
    ResetParameters;
    AddStringParameter('ObjectKind', 'All');
    RunProcess('WorkspaceManager:CloseObject');
    ResetParameters;
    RunProcess('DXP:Exit');
End;
"""


def _edge_components(mask: Image.Image, marker: int = 128) -> Image.Image:
    """Mark every white component connected to an image edge."""

    pixels = mask.load()
    width, height = mask.size
    for x in range(width):
        for y in (0, height - 1):
            if pixels[x, y] == 255:
                ImageDraw.floodfill(mask, (x, y), marker)
    for y in range(height):
        for x in (0, width - 1):
            if pixels[x, y] == 255:
                ImageDraw.floodfill(mask, (x, y), marker)
    return mask


def _crop_board_page(image: Image.Image) -> Image.Image:
    """Crop Altium's PDF paper and make only the exterior page transparent.

    Native PCB prints are monochrome: white copper and overlay can reach a board
    edge, so clearing every edge-connected white pixel would erase real artwork.
    A closed non-paper mask first seals those narrow feature gaps. Flood filling
    its exterior then removes the page while preserving enclosed and edge-touching
    board detail byte-for-byte; only alpha is added.
    """

    rgb = image.convert("RGB")
    dark = rgb.convert("L").point(lambda value: 255 if value < 80 else 0)
    bounds = dark.getbbox()
    if bounds is None:
        paper = Image.new("RGB", rgb.size, "white")
        bounds = ImageChops.difference(rgb, paper).getbbox()
        paper.close()
    dark.close()
    rgb.close()
    if bounds is None:
        return image

    cropped = image.crop(bounds).convert("RGBA")
    image.close()
    cropped_rgb = cropped.convert("RGB")
    channels = [
        channel.point(lambda value: 255 if value < 248 else 0)
        for channel in cropped_rgb.split()
    ]
    non_paper = ImageChops.lighter(
        ImageChops.lighter(channels[0], channels[1]),
        channels[2],
    )
    for channel in channels:
        channel.close()
    cropped_rgb.close()

    shortest = min(cropped.size)
    kernel = min(31, shortest if shortest % 2 else shortest - 1)
    if kernel >= 3:
        closed = non_paper.filter(ImageFilter.MaxFilter(kernel))
        sealed = closed.filter(ImageFilter.MinFilter(kernel))
        closed.close()
    else:
        sealed = non_paper.copy()
    non_paper.close()

    exterior = _edge_components(ImageOps.invert(sealed))
    sealed.close()
    alpha = exterior.point(lambda value: 0 if value == 128 else 255)
    exterior.close()
    cropped.putalpha(alpha)
    alpha.close()
    return cropped


def _rasterize_pdf(
    path: Path,
    *,
    crop_board: bool = False,
) -> list[tuple[bytes, int, int]]:
    document = pdfium.PdfDocument(path)
    rendered: list[tuple[bytes, int, int]] = []
    try:
        for page_index in range(len(document)):
            page = document[page_index]
            bitmap = page.render(scale=1.5)
            image = bitmap.to_pil()
            if crop_board:
                image = _crop_board_page(image)
            stream = BytesIO()
            image.save(stream, format="PNG", optimize=True)
            rendered.append((stream.getvalue(), image.width, image.height))
            image.close()
            bitmap.close()
            page.close()
    finally:
        document.close()
    return rendered


def _blocked(version: str, detail: str) -> ProjectVisualBundle:
    body = {
        "schema_version": _SCHEMA_VERSION,
        "adapter": "altium",
        "status": "blocked",
        "runtime": {"name": "Altium Designer", "version": version},
        "documents": [],
        "summary": {"documents": 0, "artifacts": 0, "blocked": 1},
        "detail": detail,
    }
    body["digest"] = _digest(body)
    return ProjectVisualBundle(body, {})


def render_altium_project(
    project: ProjectRecord,
    driver: AltiumDriver | None = None,
    *,
    timeout: int = 300,
    allow_unqualified_pdf_publish: bool = True,
) -> ProjectVisualBundle:
    """Generate native Altium print outputs in a disposable project copy."""

    drv = driver or AltiumDriver()
    if not drv.installed:
        return _blocked("", "Altium Designer is not installed on this reviewer machine.")
    version = drv.x2.parent.name if drv.x2 else ""
    if not allow_unqualified_pdf_publish:
        return _blocked(
            version,
            "Altium native PDF publishing is not qualified for unattended review on "
            "this host. Exact-commit visual comparison remains disabled.",
        )
    scene_result = export_altium_board_scenes(project, drv, timeout=timeout)
    if scene_result["status"] != "ready":
        return _blocked(version, scene_result["detail"])
    assembly = _template_for(drv, "Assembly.OutJob")
    fabrication = _template_for(drv, "Fabrication.OutJob")
    if project.sheet_paths and assembly is None:
        return _blocked(version, "The installed Altium Assembly.OutJob template was not found.")
    if project.board_paths and fabrication is None:
        return _blocked(
            version,
            "The installed Altium Fabrication.OutJob template was not found.",
        )

    source = Path(project.root).resolve()
    artifacts: dict[str, VisualArtifact] = {}
    with tempfile.TemporaryDirectory(prefix="stockroom-altium-visual-") as raw:
        run_root = Path(raw) / "project"
        _copy_project(source, run_root)
        project_output_name = (
            Path(project.pro_path).stem if project.pro_path else project.name
        )
        # AD26 honors the requested PDF filename but resolves publish outputs under
        # the project's conventional output folder. Expect that native location so
        # each job completes as soon as its file appears instead of waiting for a
        # fallback search after the fact.
        output_root = run_root / f"Project Outputs for {project_output_name}"
        output_root.mkdir(exist_ok=True)
        jobs: list[tuple[Path, str, str, Path, Path]] = []
        expected: list[dict] = []
        templates: dict[str, str] = {}
        try:
            if project.sheet_paths:
                if assembly is None:
                    raise AssertionError("schematic render template disappeared")
                pdf = output_root / "schematic.pdf"
                outjob = run_root / "Stockroom Schematic Visual.OutJob"
                templates["schematic"] = _configure_schematic_outjob(
                    assembly,
                    outjob,
                    pdf,
                )
                jobs.append(
                    (
                        outjob,
                        "Documentation",
                        "SCH",
                        run_root / project.sheet_paths[0],
                        pdf,
                    )
                )
                expected.append(
                    {
                        "kind": "schematic",
                        "path": project.pro_path or project.name,
                        "view": "schematic",
                        "label": "Schematic page",
                        "pdf": pdf,
                    }
                )
            for board_index, relative in enumerate(project.board_paths, 1):
                if fabrication is None:
                    raise AssertionError("PCB render template disappeared")
                for side in ("top", "bottom"):
                    pdf = output_root / f"pcb-{board_index}-{side}.pdf"
                    outjob = run_root / f"Stockroom PCB Visual {board_index} {side}.OutJob"
                    templates["pcb"] = _configure_pcb_outjob(
                        fabrication,
                        outjob,
                        board_name=Path(relative).name,
                        side=side,
                        target_pdf=pdf,
                    )
                    jobs.append((outjob, "PDF", "PCB", run_root / relative, pdf))
                    expected.append(
                        {
                            "kind": "pcb",
                            "path": relative,
                            "view": side,
                            "label": f"{side.title()} copper + overlay",
                            "pdf": pdf,
                        }
                    )
        except (OSError, ValueError) as exc:
            return _blocked(version, str(exc))

        descriptor = _execution_descriptor(
            project,
            run_root,
            [
                outjob
                for outjob, _medium, _document_type, _document, _output_pdf in jobs
            ],
        )
        marker = Path(raw) / "Stockroom Project Visuals.txt"
        script = Path(raw) / "StockroomProjectVisuals.pas"
        script_project = Path(raw) / "StockroomProjectVisuals.PrjScr"
        script.write_text(
            _render_script(descriptor=descriptor, jobs=jobs, marker=marker),
            encoding="utf-8",
            newline="\r\n",
        )
        script_project.write_text(
            "[Design]\r\nVersion=1.0\r\nHierarchyMode=0\r\n"
            f"[Document1]\r\nDocumentPath={script.name}\r\n",
            encoding="utf-8",
        )
        outcome = drv.run_script(
            project=script_project,
            proc=f"{script.name}>RunStockroomProjectVisuals",
            marker=marker,
            timeout=timeout,
        )
        if not outcome.ok:
            return _blocked(version, outcome.detail)

        documents_by_key: dict[tuple[str, str], dict] = {}
        for row in expected:
            key = (row["kind"], row["path"])
            document = documents_by_key.setdefault(
                key,
                {
                    "kind": row["kind"],
                    "path": row["path"],
                    "status": "ready",
                    "detail": "Native print views are ready",
                    "artifacts": [],
                },
            )
            if row["kind"] == "pcb":
                document["scene"] = scene_result["scenes"].get(row["path"])
            pdf = row["pdf"]
            if not pdf.is_file():
                discovered = sorted(run_root.rglob(pdf.name))
                if len(discovered) == 1:
                    pdf = discovered[0]
            if not pdf.is_file() or not pdf.stat().st_size:
                document["status"] = "blocked"
                document["detail"] = f"Altium returned without producing {pdf.name}."
                continue
            try:
                pages = _rasterize_pdf(pdf, crop_board=row["kind"] == "pcb")
            except Exception as exc:
                document["status"] = "blocked"
                document["detail"] = f"{pdf.name} could not be rasterized: {exc}"
                continue
            if not pages:
                document["status"] = "blocked"
                document["detail"] = f"{pdf.name} contained no pages."
                continue
            for page_number, (content, width, height) in enumerate(pages, 1):
                view = (
                    f"page-{page_number}"
                    if row["kind"] == "schematic"
                    else row["view"]
                )
                label = (
                    f"Schematic page {page_number}"
                    if row["kind"] == "schematic"
                    else row["label"]
                )
                document["artifacts"].append(
                    artifact_metadata(
                        artifacts=artifacts,
                        adapter="altium",
                        kind=row["kind"],
                        path=row["path"],
                        view=view,
                        label=label,
                        page=page_number,
                        content=content,
                        media_type="image/png",
                        width=width,
                        height=height,
                    )
                )

        documents = list(documents_by_key.values())
        blocked = sum(row["status"] == "blocked" for row in documents)
        status = "ready" if documents and not blocked and artifacts else "blocked"
        body = {
            "schema_version": _SCHEMA_VERSION,
            "adapter": "altium",
            "status": status,
            "runtime": {"name": "Altium Designer", "version": version},
            "template_sha256": templates,
            "scene_digest": scene_result["digest"],
            "documents": documents,
            "summary": {
                "documents": len(documents),
                "artifacts": len(artifacts),
                "blocked": blocked,
            },
            "detail": (
                "Native schematic and PCB views are ready"
                if status == "ready"
                else "One or more native views could not be rendered"
            ),
        }
        body["digest"] = _digest(body)
        return ProjectVisualBundle(body, artifacts)
