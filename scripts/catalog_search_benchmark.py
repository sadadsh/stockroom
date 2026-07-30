"""Measure Stockroom's exact warm catalog-search projection at release scale.

The benchmark seeds the production SQLite schema directly because generating
100,000 source JSON records would measure fixture construction rather than the
query path.  Every timed sample calls ``LibraryIndex.search`` and therefore
includes row hydration plus the registry-keyed KiCad/Altium readiness
projection used by the application.

This is an acceptance tool, not a synthetic claim about provider or UI
latency.  It writes a machine-readable receipt and exits non-zero if any query
family exceeds the configured p95 budget.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from stockroom.store.index import _SCHEMA, LibraryIndex  # noqa: E402

RECEIPT_SCHEMA = "stockroom-catalog-search-benchmark/1"
DEFAULT_ROWS = 100_000
DEFAULT_SAMPLES = 40
DEFAULT_BUDGET_MS = 150.0
_INSERT_BATCH = 2_000


def _chunks(total: int, size: int) -> Iterable[range]:
    for start in range(0, total, size):
        yield range(start, min(start + size, total))


def _part_row(index: int) -> tuple[object, ...]:
    identity = f"bench-{index:06d}"
    display_name = f"Benchmark Component {index:06d}"
    mpn = f"BENCH{index:06d}"
    manufacturer = f"Maker {index % 100:03d}"
    category = f"Category {index % 20:02d}"
    search_blob = (
        f"{display_name} {mpn} {manufacturer} synthetic catalog row "
        f"token{index % 1000:03d}"
    ).lower()
    return (
        identity,
        display_name,
        category,
        "Synthetic catalog benchmark row",
        mpn,
        manufacturer,
        "component",
        "",
        "",
        "",
        "",
        0,
        "symbol,footprint,model",
        search_blob,
        "0" * 64,
        "catalog-search-benchmark",
    )


def _seed_catalog(connection: sqlite3.Connection, rows: int) -> None:
    insert_part = (
        "INSERT INTO parts "
        "(id, display_name, category, description, mpn, manufacturer, part_class, "
        "footprint_name, model_file, datasheet_file, purchase_url, is_complete, "
        "missing, search_blob, source_hash, derived_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )
    insert_requirement = (
        "INSERT INTO part_requirements (part_id, tool, required_json) VALUES (?,?,?)"
    )
    required = '["symbol","footprint","model"]'
    for indexes in _chunks(rows, _INSERT_BATCH):
        materialized = list(indexes)
        connection.executemany(insert_part, (_part_row(index) for index in materialized))
        connection.executemany(
            insert_requirement,
            (
                (f"bench-{index:06d}", tool, required)
                for index in materialized
                for tool in ("kicad", "altium")
            ),
        )
    connection.commit()


def _percentile_95(samples: list[float]) -> float:
    if not samples:
        raise ValueError("at least one timing sample is required")
    if len(samples) == 1:
        return samples[0]
    return statistics.quantiles(samples, n=100, method="inclusive")[94]


def _measure_family(
    library: LibraryIndex,
    *,
    name: str,
    queries: list[str],
    samples: int,
    expected_matches: int,
    budget_ms: float,
) -> dict[str, object]:
    if not queries:
        raise ValueError("query family must not be empty")

    # Warm both SQLite pages and Python's registry path before timing.
    warm = library.search(queries[0])
    if len(warm) != expected_matches:
        raise RuntimeError(
            f"{name} warm-up returned {len(warm)} rows, expected {expected_matches}"
        )

    timings: list[float] = []
    for sample in range(samples):
        query = queries[sample % len(queries)]
        started = time.perf_counter_ns()
        result = library.search(query)
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        if len(result) != expected_matches:
            raise RuntimeError(
                f"{name} query returned {len(result)} rows, expected {expected_matches}"
            )
        timings.append(elapsed_ms)

    p95_ms = _percentile_95(timings)
    return {
        "name": name,
        "expected_matches": expected_matches,
        "samples": len(timings),
        "minimum_ms": round(min(timings), 6),
        "median_ms": round(statistics.median(timings), 6),
        "p95_ms": round(p95_ms, 6),
        "maximum_ms": round(max(timings), 6),
        "budget_ms": budget_ms,
        "budget_met": p95_ms <= budget_ms,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_state() -> tuple[str, bool]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=REPOSITORY_ROOT,
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
        )
        return revision, dirty
    except (OSError, subprocess.SubprocessError):
        return "", True


def run_benchmark(
    *,
    rows: int,
    samples: int,
    budget_ms: float,
) -> dict[str, object]:
    if not 1_000 <= rows <= 1_000_000:
        raise ValueError("rows must be between 1,000 and 1,000,000")
    if not 1 <= samples <= 1_000:
        raise ValueError("samples must be between 1 and 1,000")
    if not 0 < budget_ms <= 60_000:
        raise ValueError("budget_ms must be positive and at most 60,000")

    with tempfile.TemporaryDirectory(prefix="stockroom-catalog-benchmark-") as temporary:
        database = Path(temporary) / "Catalog.sqlite"
        connection = sqlite3.connect(str(database), check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.executescript(_SCHEMA)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        _seed_catalog(connection, rows)
        library = LibraryIndex(connection)

        unique_indexes = [round((rows - 1) * step / 19) for step in range(20)]
        token_match_count = rows // 1000
        maker_match_count = rows // 100
        if token_match_count < 1 or maker_match_count < 1:
            raise RuntimeError("benchmark row count is too small for its query families")

        query_families = [
            _measure_family(
                library,
                name="unique-mpn",
                queries=[f"BENCH{index:06d}" for index in unique_indexes],
                samples=samples,
                expected_matches=1,
                budget_ms=budget_ms,
            ),
            _measure_family(
                library,
                name="hundred-row-token" if rows == DEFAULT_ROWS else "token",
                queries=[f"token{index:03d}" for index in range(0, 1000, 50)],
                samples=samples,
                expected_matches=token_match_count,
                budget_ms=budget_ms,
            ),
            _measure_family(
                library,
                name="thousand-row-manufacturer" if rows == DEFAULT_ROWS else "manufacturer",
                queries=[f"Maker {index:03d}" for index in range(0, 100, 5)],
                samples=samples,
                expected_matches=maker_match_count,
                budget_ms=budget_ms,
            ),
        ]
        catalog_count = library.count()
        library.close()

    revision, dirty = _git_state()
    index_source = BACKEND_ROOT / "stockroom" / "store" / "index.py"
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "catalog_rows": catalog_count,
        "samples_per_family": samples,
        "p95_budget_ms": budget_ms,
        "budget_met": all(bool(family["budget_met"]) for family in query_families),
        "query_families": query_families,
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "processor": platform.processor(),
            "logical_processors": os.cpu_count(),
        },
        "git": {
            "revision": revision,
            "tracked_dirty": dirty,
        },
        "source_sha256": {
            "app/backend/stockroom/store/index.py": _sha256(index_source),
            "scripts/catalog_search_benchmark.py": _sha256(Path(__file__).resolve()),
        },
    }
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure the warm Stockroom catalog-search projection."
    )
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--budget-ms", type=float, default=DEFAULT_BUDGET_MS)
    parser.add_argument("--receipt", required=True, type=Path)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    receipt = run_benchmark(
        rows=arguments.rows,
        samples=arguments.samples,
        budget_ms=arguments.budget_ms,
    )
    destination = arguments.receipt.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["budget_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
