#!/usr/bin/env python3
"""Import each library part's RAW distributor payloads into `sourced/`, then re-derive.

This is the CLI over `stockroom.importer.engine`, and it exists so the owner's requirement 1 -
*"Import everything from that list, its proper data from mouser, digikey, lcsc if possible using
api keys. Import everything so we can change the way the data's manipulated later"* - is something
the app can do rather than something typed by hand into a python shell.

    # what WOULD happen. This is the DEFAULT.
    uv run python scripts/import_library.py

    # the same, against one part, so a live API answer can be eyeballed before a bulk run
    uv run python scripts/import_library.py --only ERJ-P03F1101V --verbose

    # actually write
    uv run python scripts/import_library.py --apply

**DRY RUN IS THE DEFAULT AND `--apply` IS REQUIRED.** This pass mutates a git-backed library of
real parts and spends metered API quota, and the owner's standing rule is that anything which acts
on the world gets a dry run before it acts. A tool whose destructive mode is the default is one
mistyped command away from a bad afternoon.

CREDENTIALS are read from the machine config (`%APPDATA%/Stockroom/config.json` on Windows,
`~/.config/stockroom` otherwise), never from the command line - a key in argv ends up in shell
history and in `ps`. `--config` points at another machine's config file, which is how a WSL session
can drive an import using the keys already configured on the Windows install.

Resumability needs no flag: the worklist is *"which parts have no payload for this source yet"*,
read fresh from the tree, so Ctrl-C and re-run continues where it stopped without spending quota
on parts already imported. `--refetch` is the deliberate opposite.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "app" / "backend"))

from stockroom.enrich.rescan import Pacer  # noqa: E402
from stockroom.importer.engine import Outcome, run_import  # noqa: E402
from stockroom.importer.sources import build_sources  # noqa: E402
from stockroom.model.part import PartRecord  # noqa: E402
from stockroom.store.machine_config import MachineConfig  # noqa: E402


class _FileConfig:
    """A machine config read from an explicit JSON file.

    Deliberately a dumb attribute bag rather than `MachineConfig.load(path)`: this may be pointed
    at ANOTHER machine's config (the Windows install's, from WSL), and that file can carry keys a
    different build wrote. Reading it as data cannot fail on a field this build does not know.
    """

    def __init__(self, path: Path):
        raw = json.loads(path.read_text(encoding="utf-8"))
        self._raw = raw if isinstance(raw, dict) else {}

    def __getattr__(self, name: str):
        return self._raw.get(name, "")


def _load_config(path: Path | None):
    if path is not None:
        return _FileConfig(path)
    return MachineConfig.load()


def _records(parts_dir: Path, only: list[str], limit: int) -> list[PartRecord]:
    """Every library record, oldest-id-first for a deterministic order.

    Deterministic because a partial run must be reproducible: if the pass stops at part 40, the
    same 40 must be the ones already done next time, or "resumable" is only true by accident.
    """
    wanted = {m.strip().upper() for m in only if m.strip()}
    out: list[PartRecord] = []
    for path in sorted(parts_dir.glob("*.json")):
        try:
            record = PartRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:  # a single unreadable record must not stop the pass
            print(f"  SKIP {path.name}: unreadable ({type(exc).__name__}: {exc})")
            continue
        if wanted and record.mpn.strip().upper() not in wanted:
            continue
        out.append(record)
        if limit and len(out) >= limit:
            break
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--library", type=Path, default=None,
                    help="library profile root (default: the active profile under ./libraries)")
    ap.add_argument("--config", type=Path, default=None,
                    help="read credentials from this config.json instead of this machine's")
    ap.add_argument("--apply", action="store_true",
                    help="actually write. Without it this is a DRY RUN and touches nothing.")
    ap.add_argument("--only", action="append", default=[],
                    help="restrict to this MPN (repeatable)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N parts (0 = no limit)")
    ap.add_argument("--refetch", action="store_true",
                    help="re-pull sources this part already has evidence from")
    ap.add_argument("--scheme", default="", help="naming scheme for the re-derive")
    ap.add_argument("--verbose", action="store_true", help="one line per part")
    a = ap.parse_args(argv)

    library = a.library or (REPO / "libraries" / "Stockroom")
    parts_dir = library / "parts"
    if not parts_dir.is_dir():
        print(f"no parts directory at {parts_dir.as_posix()}", file=sys.stderr)
        return 2

    config = _load_config(a.config)
    sources = build_sources(config)
    if not sources:
        # LOUD, and BEFORE any work. A pass that fetched nothing because nothing was configured
        # must never look like a pass that found nothing.
        print("NO USABLE SOURCE: no distributor credentials are configured.", file=sys.stderr)
        print("  Set them in the app's Settings, or pass --config pointing at a machine that has "
              "them.", file=sys.stderr)
        return 2

    records = _records(parts_dir, a.only, a.limit)
    pacer = Pacer({
        "mouser": float(getattr(config, "rescan_mouser_per_min", 0) or 20),
        "digikey": float(getattr(config, "rescan_digikey_per_min", 0) or 60),
    })

    print(f"library : {library.as_posix()}")
    print(f"sources : {', '.join(name for name, _ in sources)}")
    print(f"parts   : {len(records)}")
    print(f"mode    : {'APPLY (writing)' if a.apply else 'DRY RUN (nothing will be written)'}")
    print()

    written_paths: list[Path] = []

    def save(record) -> None:
        path = parts_dir / f"{record.id}.json"
        path.write_text(record.dumps(), encoding="utf-8")
        written_paths.append(path)

    def report_one(result) -> None:
        if a.verbose or result.outcome in (Outcome.FAILED, Outcome.DEFERRED):
            extra = f" -> {result.reclassified_to}" if result.reclassified_to else ""
            print(f"  {result.outcome.value:9s} {result.mpn:24s}{extra}  {result.detail}")

    report = run_import(
        records,
        library_root=library,
        config=config,
        derived_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        scheme=a.scheme or "",
        refetch=a.refetch,
        dry_run=not a.apply,
        pace=pacer.wait,
        on_result=report_one,
        save=save if a.apply else None,
    )

    print()
    print(report.summary())
    for name, why in sorted(report.unusable_sources.items()):
        print(f"  note: {name} unused - {why}")

    reclassified = [r for r in report.results if r.reclassified_to]
    if reclassified:
        print(f"  {len(reclassified)} parts classified off the default:")
        for r in reclassified:
            print(f"    {r.mpn:24s} -> {r.reclassified_to}")

    if a.apply:
        # Left UNCOMMITTED on purpose, and said out loud. A bulk import is exactly the change a
        # person should look at before it enters history, and committing it here would also make
        # this script the second thing in the codebase that knows how to commit a library write.
        print()
        print(f"  {len(written_paths)} record(s) rewritten; sourced/ payloads added.")
        print("  NOT COMMITTED. Review with `git -C "
              f"{library.as_posix()} status`, then commit.")
    else:
        print()
        print("  Nothing was written. Re-run with --apply to perform the import.")

    # A pass whose every part FAILED is a failed pass, and must not exit 0.
    return 1 if report.count(Outcome.FAILED) and not report.count(Outcome.IMPORTED) else 0


if __name__ == "__main__":
    raise SystemExit(main())
