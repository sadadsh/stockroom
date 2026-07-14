"""M7b: structured ERC + DRC for a registered KiCad project.

KiCad's electrical-rules (schematic) and design-rules (board) checkers only run
headlessly through kicad-cli, which since KiCad 7 can emit JSON. This module runs
them and parses that JSON into a flat, severity-ranked list of findings you can
rank, count, and click, instead of a raw tail dump.

Lifted Qt-free from the retired app's `nd_kicad_checks` (COMPUTE only): the JSON
parsers (parse_erc_json / parse_drc_json) are pure and independently testable; the
runners shell out to kicad-cli and hand their output to the parsers. `project_checks`
orchestrates the whole run for a ProjectRecord: ERC once on the root schematic, DRC
on every board, merged into one combined summary the Overview and the Buildability
verdict (M7g) read.

A run that produces no valid report is NEVER reported as a clean board: the
trustworthy signal is a parseable JSON report (kicad-cli exits 0 even with
violations, so the return code alone cannot tell a clean pass from a failed run).

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List


_SEV_ORDER = {"error": 0, "warning": 1, "exclusion": 2, "info": 3}


def _finding(severity, rule, message, where="") -> dict:
    sev = (severity or "").lower()
    if sev not in _SEV_ORDER:
        sev = "warning"
    return {"severity": sev, "rule": rule or "", "message": (message or "").strip(),
            "where": where}


def _pos(items) -> str:
    """Human 'x, y' from a KiCad JSON position/items list, best-effort."""
    if isinstance(items, dict) and "pos" in items and isinstance(items["pos"], dict):
        p = items["pos"]
        return f"({p.get('x')}, {p.get('y')})"
    return ""


def parse_erc_json(text: str) -> List[dict]:
    """Flatten a `kicad-cli sch erc --format json` report into findings. Tolerant of
    the schema drift across KiCad 7/8/10 (sheets[].violations[] with
    type/severity/description/items)."""
    try:
        doc = json.loads(text)
    except (ValueError, TypeError):
        return []
    out = []
    sheets = doc.get("sheets") or ([doc] if "violations" in doc else [])
    for sheet in sheets:
        sheet_name = sheet.get("path") or sheet.get("uuid") or ""
        for v in sheet.get("violations", []) or []:
            sev = v.get("severity") or v.get("severity_level")
            rule = v.get("type") or v.get("rule") or ""
            msg = v.get("description") or v.get("message") or ""
            items = v.get("items") or []
            where = "; ".join(_x for _x in (
                (it.get("description") or "") + (" " + _pos(it) if _pos(it) else "")
                for it in items) if _x.strip()) or (sheet_name or "")
            out.append(_finding(sev, rule, msg, where))
    return sorted(out, key=lambda f: (_SEV_ORDER[f["severity"]], f["rule"]))


def parse_drc_json(text: str) -> List[dict]:
    """Flatten a `kicad-cli pcb drc --format json` report into findings. Merges the
    violations, unconnected_items, and schematic_parity sections KiCad emits."""
    try:
        doc = json.loads(text)
    except (ValueError, TypeError):
        return []
    out = []
    for section in ("violations", "unconnected_items", "schematic_parity"):
        for v in doc.get(section, []) or []:
            sev = v.get("severity") or "error"
            rule = v.get("type") or v.get("rule") or section
            msg = v.get("description") or v.get("message") or ""
            items = v.get("items") or []
            where = "; ".join(_x for _x in (
                (it.get("description") or "") + (" " + _pos(it) if _pos(it) else "")
                for it in items) if _x.strip())
            out.append(_finding(sev, rule, msg, where))
    return sorted(out, key=lambda f: (_SEV_ORDER[f["severity"]], f["rule"]))


def summarize(findings: List[dict]) -> dict:
    """{total, errors, warnings, by_severity, by_rule} for a findings list."""
    by_sev, by_rule = {"error": 0, "warning": 0, "exclusion": 0, "info": 0}, {}
    for f in findings:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
        by_rule[f["rule"]] = by_rule.get(f["rule"], 0) + 1
    return {"total": len(findings), "errors": by_sev["error"],
            "warnings": by_sev["warning"], "by_severity": by_sev, "by_rule": by_rule}


# -- runners (need kicad-cli) -------------------------------------------------
_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0


def _run_json_check(cli: str, args: List[str], src: Path, parser) -> dict:
    """Run a kicad-cli check that writes a JSON report to a temp file, then parse it.
    Returns {ok, findings, summary, error, returncode?}. Never raises."""
    if not cli:
        return {"ok": False, "error": "kicad-cli not found", "findings": [],
                "summary": summarize([])}
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "report.json"
        cmd = [cli] + args + ["--format", "json", "--output", str(out), str(src)]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding="utf-8", errors="replace",
                                  creationflags=_NO_WINDOW, timeout=300)
        except Exception as e:  # noqa: BLE001 - a failed spawn is a labeled honest error
            return {"ok": False, "error": str(e), "findings": [], "summary": summarize([])}
        text = out.read_text(encoding="utf-8", errors="replace") if out.exists() else ""
        # A run that produces no report (bad file / crash / nonzero exit with nothing
        # written) must NOT read as a clean board: that silent pass is exactly what the
        # correctness bar forbids. kicad-cli exits 0 even with violations (no
        # --exit-code-violations here), so a VALID JSON report is the only trustworthy
        # signal of a real run.
        if not text.strip():
            err = (proc.stdout or "").strip() or f"kicad-cli produced no report (exit {proc.returncode})"
            return {"ok": False, "error": err, "findings": [],
                    "summary": summarize([]), "returncode": proc.returncode}
        try:
            json.loads(text)  # a truncated/corrupt report is a failure, not a clean board
        except (ValueError, TypeError):
            return {"ok": False,
                    "error": f"kicad-cli report was not valid JSON (exit {proc.returncode})",
                    "findings": [], "summary": summarize([]), "returncode": proc.returncode}
        findings = parser(text)
        return {"ok": True, "findings": findings, "summary": summarize(findings),
                "error": "", "returncode": proc.returncode}


def run_erc(sch_path, cli: str) -> dict:
    """Run ERC on a .kicad_sch via kicad-cli and return structured findings."""
    return _run_json_check(cli, ["sch", "erc"], Path(sch_path), parse_erc_json)


def run_drc(pcb_path, cli: str) -> dict:
    """Run DRC on a .kicad_pcb via kicad-cli and return structured findings."""
    return _run_json_check(cli, ["pcb", "drc"], Path(pcb_path), parse_drc_json)


# -- orchestrator over a project ----------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def root_sheet(pro_path: str, sheet_paths: List[str], board_paths: List[str]) -> str | None:
    """The project's root schematic. KiCad names the root .kicad_sch after the project,
    so the sheet whose stem matches the .kicad_pro (or, failing that, a board) stem is
    the hierarchy root: ERC runs there ONCE and checks the whole hierarchy, never
    per-sub-sheet (which would double-count). Falls back to the first sheet."""
    stems = []
    if pro_path:
        stems.append(Path(pro_path).stem)
    stems += [Path(b).stem for b in board_paths]
    by_stem = {Path(s).stem: s for s in sheet_paths}
    for stem in stems:
        if stem in by_stem:
            return by_stem[stem]
    return sheet_paths[0] if sheet_paths else None


def _combine_summary(erc: dict | None, drc: List[dict]) -> dict:
    """One verdict over ERC + every board's DRC. `ok` means at least one check actually
    ran AND every check that ran produced a valid report; errors/warnings count
    violations across those checks. A run that verified nothing (checked == 0, e.g. a
    project with no schematic or board) is NEVER a clean pass, so ok is False there:
    that keeps the badge and the M7g Buildability verdict from calling nothing Clean."""
    parts = ([erc] if erc is not None else []) + list(drc)
    errors = warnings = total = 0
    ok = len(parts) > 0  # nothing checked is not a pass
    for p in parts:
        if not p.get("ok"):
            ok = False
            continue
        s = p.get("summary") or {}
        errors += s.get("errors", 0)
        warnings += s.get("warnings", 0)
        total += s.get("total", 0)
    return {"ok": ok, "errors": errors, "warnings": warnings, "total": total,
            "checked": len(parts)}


def project_checks(root, pro_path, board_paths, sheet_paths, cli, name="",
                   progress=None) -> dict:
    """Run ERC on the root schematic + DRC on every board of a registered project.

    Returns {project, erc, drc, summary, ran_at}: `erc` is the single root-sheet run
    (with its `sheet` relpath) or None when the project has no schematic; `drc` is a
    list of per-board runs (each with its `board` relpath); `summary` is the combined
    verdict. `cli` is the kicad-cli path (falsy runs surface an honest cli-absent
    per-check result rather than a fabricated pass)."""
    root = Path(root)

    def _p(pct, msg):
        if progress:
            progress({"pct": pct, "message": msg})

    _p(10, "Running ERC")
    erc = None
    rel_root = root_sheet(pro_path, sheet_paths, board_paths)
    if rel_root:
        erc = run_erc(root / rel_root, cli)
        erc["sheet"] = rel_root

    drc = []
    n = max(len(board_paths), 1)
    for i, board in enumerate(board_paths):
        _p(30 + int(55 * i / n), f"Running DRC on {board}")
        d = run_drc(root / board, cli)
        d["board"] = board
        drc.append(d)

    _p(95, "Summarizing")
    return {
        "project": name,
        "erc": erc,
        "drc": drc,
        "summary": _combine_summary(erc, drc),
        "ran_at": _utc_now_iso(),
    }
