"""ONE tool per job. Enforced, because prose did not hold it.

Owner, 2026-07-27: *"we need a way to actually use the tools we built, to not regress, like make it
so that we only have one specific tool for each thing that we must use and if it doesnt work we
update that specific tool rather than build other ones."*

WHAT WENT WRONG, measured in ONE session
"Drive a browser" acquired six owners: `scripts/windrive.py`, `scripts/uishot.py`,
`scripts/vendorprobe.py`, `scripts/capturerec.py`, `host/cdp_probe.py`, and
`capture/browser.py`. Each was reasonable alone; together they mean a fix to one reaches none of
the others, and a passing test on one says nothing about the one actually running.

RESOLVED, not merely registered: `scripts/vendorprobe.py` was DELETED and its control survey,
persistent profile, vendor-URL resolution and real-signal readiness moved into
`scripts/webread.py`, which no longer launches a browser of its own - it goes through
`capture/browser.py` like everything else. Owner, 2026-07-27: *"one tool for each purpose that gets
updated or deleted, make sure no other tools exist."* A registry entry is the fallback for a
genuine difference, never a place to park a duplicate.

WHAT THIS GATE ACTUALLY CHECKS, and what it deliberately does not
It checks the ONE mechanically detectable fact: which modules LAUNCH a browser. Launching is the
expensive, drift-prone part - profiles, stealth engine, download handling, teardown - and it is the
part that must live in a single place. Modules that merely CONNECT to an already-running browser
(CDP) are a different job and are listed separately rather than lumped in, because pretending they
are the same would make this gate lie.

Adding a new launcher is not forbidden by fiat - it is forbidden SILENTLY. Put it in the registry
with a reason, and the reason is then reviewable.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# The ONE module allowed to launch a browser for the app, plus every deliberate exception with the
# reason it is not simply a mode on that module. A new entry here is a decision, not an accident.
_LAUNCHERS = {
    "app/backend/stockroom/capture/browser.py": (
        "THE owner of 'launch a browser'. Engine is a parameter (chromium / camoufox / cloak), "
        "so a stealth need is a mode on this, never a second class beside it."
    ),
    "app/backend/stockroom/scrape/fetch/camoufox_browser.py": (
        "The scrape render tier. Pre-dates the capture engine, is ASYNC and implements the "
        "BrowserFetcher interface. Folding the two together is real work, logged in the Punch "
        "List, not something to fake as done here."
    ),
    "app/backend/stockroom/scrape/fetch/browser.py": (
        "The scrape Chromium tier, same interface and same story as the Camoufox one."
    ),
    "app/backend/stockroom/host/window_runtime.py": (
        "The release-owned native application window. It launches the packaged WebView2 host for "
        "Stockroom's own UI and never performs provider browsing or downloads."
    ),
    "scripts/capturerec.py": (
        "Launches HEADED for a human to drive, and must NOT save downloads into the library the "
        "way the capture engine does. Kept separate deliberately; if it grows a third difference "
        "it should become a mode on capture/browser.py instead."
    ),
    "scripts/uishot.py": (
        "Substitutes a browser for pywebview to boot the REAL app for screenshots. Not a vendor "
        "browser at all."
    ),
}

# Launch a browser, in any of the shapes our stack uses.
_LAUNCH = re.compile(
    r"\.launch\s*\(|\.launch_persistent_context\s*\(|AsyncCamoufox\s*\(|Camoufox\s*\(",
)

_SEARCH_ROOTS = ("app/backend/stockroom", "scripts")
_SKIP_PARTS = {"__pycache__", "node_modules", ".venv"}


def _python_files():
    for root in _SEARCH_ROOTS:
        for path in (REPO / root).rglob("*.py"):
            if any(part in _SKIP_PARTS for part in path.parts):
                continue
            yield path


def _launcher_modules_from(sources: Iterable[tuple[str, str]]) -> set[str]:
    """Detect launcher modules from injected ``(path, source)`` pairs."""

    found = set()
    for path, text in sources:
        # Ignore the registry in THIS file and any line that is a comment.
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if _LAUNCH.search(stripped):
                found.add(path)
                break
    return found


def _launcher_modules() -> set[str]:
    return _launcher_modules_from(
        (
            path.relative_to(REPO).as_posix(),
            path.read_text(encoding="utf-8", errors="replace"),
        )
        for path in _python_files()
    )


def _unregistered_launchers(
    found: set[str],
    allowed: Iterable[str],
) -> list[str]:
    return sorted(found - set(allowed))


def test_no_unregistered_module_launches_a_browser():
    found = _launcher_modules()
    unregistered = _unregistered_launchers(found, _LAUNCHERS)
    assert not unregistered, (
        "these modules launch a browser without being registered as owning that job: "
        f"{unregistered}.\nExtend `capture/browser.py` instead - a different engine or target is "
        "an ARGUMENT, not a new tool. If it genuinely cannot be a mode on it, add it to "
        "`_LAUNCHERS` in this file WITH the reason, so the exception is reviewable."
    )


def test_the_registry_has_no_dead_entries():
    """A registry that lists tools which no longer launch anything slowly stops meaning anything,
    and would let a real duplicate hide behind a stale allowance."""
    found = _launcher_modules()
    dead = sorted(set(_LAUNCHERS) - found)
    assert not dead, (
        f"these are registered as browser launchers but launch nothing any more: {dead}. "
        "Remove them from the registry."
    )


def test_the_detector_can_actually_see_launchers():
    """Anti-vacuous guard. If the pattern matched nothing, the test above would pass by seeing an
    empty world - which is exactly how a duplication gate becomes decoration."""
    found = _launcher_modules()
    assert found, "the launch detector found NO browser launchers at all; the pattern is broken"
    assert "app/backend/stockroom/capture/browser.py" in found, found


def test_launcher_detector_rejects_each_independent_known_bad_shape() -> None:
    known_bad = (
        ("rogue/basic.py", "browser.launch(headless=True)"),
        (
            "rogue/persistent.py",
            "browser.launch_persistent_context('profile')",
        ),
        ("rogue/async_camoufox.py", "session = AsyncCamoufox(headless=True)"),
        ("rogue/camoufox.py", "session = Camoufox(headless=True)"),
    )

    found = _launcher_modules_from(known_bad)

    assert found == {path for path, _source in known_bad}
    assert _unregistered_launchers(found, ()) == sorted(found)


def test_launcher_detector_ignores_comment_only_controls() -> None:
    found = _launcher_modules_from(
        (
            ("clean/comments.py", "# browser.launch()\n# Camoufox()"),
            ("clean/no-launch.py", "def connect():\n    return 'existing session'"),
        )
    )

    assert found == set()


def test_every_exception_states_why_it_is_not_a_mode():
    """The rule's obligation, made mechanical: an exception carries a REASON. A bare allow-list
    entry is how 'one tool per job' quietly becomes 'as many as we felt like'."""
    for module, reason in _LAUNCHERS.items():
        assert len(reason) > 40, f"{module} is registered with no real justification: {reason!r}"


# --- the whole tool inventory ------------------------------------------------------------------
#
# EVERY script, and the ONE job it owns. Owner, 2026-07-27: *"one tool for each purpose that gets
# updated or deleted, make sure no other tools exist"* and *"i feel like a lot of these slowdowns
# regressions are because u dont stay organized enough on ur own work"*.
#
# This is not documentation - documentation rots and nobody reads it at the moment it matters. It
# is a GATE that fails the instant an unregistered script appears, which is exactly the moment to
# ask "does something already do this?". It exists because on 2026-07-27 `vendorprobe.py` was
# written to survey vendor pages while `webread.py`, written EARLIER THE SAME DAY, already drove a
# browser to read pages. Nothing caught it; the duplicate shipped and had to be merged back out.
_TOOLS = {
    "altium.py": "Drive the installed Altium Designer (CLI entry).",
    "altium_dblib_verify.py": "Prove the shipped .DbLib actually connects through Altium's ODBC chain.",
    "altium_install.py": "Install a library into Altium's Installed Libraries list.",
    "altium_native_authoring_proof.py": "Prove Stockroom's supported native Altium authoring profile.",
    "altium_place_verify.py": "Resolve, place and read back a component in real Altium.",
    "altium_probe.py": "Inspect Altium binary libraries from outside Altium.",
    "bake_stm_index.py": "Build the STM part index used by the stm viewer.",
    "catalog_search_benchmark.py": (
        "Benchmark the production LibraryIndex search projection over a deterministic local "
        "catalog."
    ),
    "capturerec.py": "THE recorder: a human drives a vendor page, this writes down the workflow.",
    "cad_capture_canary.py": (
        "Prove one live CAD route through Stockroom's broker, evidence store, and API."
    ),
    "deploy.py": "Deploy to the Windows install AND prove the code arrived.",
    "export_stm_target_definition.py": "Compile an STM target definition from explicit policy.",
    "gen_eda_registry_ts.py": "Generate the TS EDA registry from the Python one (single source).",
    "import_library.py": "Bulk-import parts into the library from a register/BOM.",
    "library_audit.py": "Audit the library's records on disk.",
    "migrate_library_v3.py": "One-shot migration to v3 part ids.",
    "pixelprobe.py": "Measure pixels in a screenshot (colour/geometry assertions).",
    "progress.py": "THE plan: render docs/progress and tick its steps.",
    "s8_cold_rebuild.py": "Cold-rebuild verification of the library from source payloads.",
    "shotcrop.py": "Crop a screenshot to a region.",
    "uishot.py": "THE app screenshotter: boots the REAL app headlessly, both themes.",
    "verify_derive.py": "Verify the derive engine reproduces records byte-identically.",
    "verify_3d_rotation_corpus.py": (
        "Compare Stockroom's production 3D placement transform with native KiCad geometry "
        "across the immutable historical footprint/model corpus."
    ),
    "webread.py": "THE page reader: render a page and report its text / controls / links.",
    "windesk.py": "Real Windows pointer + desktop capture (what CDP cannot do).",
    "windrive.py": "THE app driver on Windows: one CDP connection, click/shot/text.",
    "wingui.py": "Windows window management: move, focus, occluded capture.",
}


def test_every_script_is_registered_with_the_job_it_owns():
    """A new script must declare its job. If another entry already describes that job, the answer
    is to EXTEND that tool - the whole point of the rule this enforces."""
    present = {p.name for p in (REPO / "scripts").glob("*.py")}
    unregistered = sorted(present - set(_TOOLS))
    assert not unregistered, (
        f"new script(s) with no declared job: {unregistered}.\n"
        "Before registering: read the list in this file and check nothing already owns this job. "
        "If something does, extend IT and delete the new file. If nothing does, add a one-line "
        "entry saying what it owns."
    )


def test_the_registry_lists_no_script_that_was_deleted():
    """A stale entry lets a future duplicate hide behind a name that no longer exists."""
    present = {p.name for p in (REPO / "scripts").glob("*.py")}
    ghosts = sorted(set(_TOOLS) - present)
    assert not ghosts, f"registered but gone: {ghosts}. Remove them."


def test_no_two_tools_claim_the_same_job():
    """The duplicate check itself. Identical purpose strings mean two tools for one job."""
    seen = {}
    for name, job in _TOOLS.items():
        key = job.strip().lower()
        assert key not in seen, f"{name} and {seen[key]} both claim: {job}"
        seen[key] = name
