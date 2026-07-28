from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from stockroom.planning import (
    SYNTHETIC_SCALE_SCOPE,
    ScaleSimulationHarness,
)
from stockroom.workflow import StageName, WorkflowStore


@pytest.mark.parametrize(
    ("identity_count", "batch_size", "claim_limit", "worker_count"),
    (
        (100, 50, 24, 4),
        (1_000, 100, 256, 8),
    ),
)
def test_synthetic_scale_reopens_and_settles_exactly_once(
    tmp_path: Path,
    identity_count: int,
    batch_size: int,
    claim_limit: int,
    worker_count: int,
) -> None:
    run_root = tmp_path / f"Scale Run {identity_count}"
    run_root.mkdir()
    database = run_root / f"Scale Simulation {identity_count}.sqlite"
    harness = ScaleSimulationHarness(
        WorkflowStore(database),
        claim_limit=claim_limit,
        worker_count=worker_count,
        retry_every=17,
        fallback_every=19,
    )

    with harness:
        report = harness.run(
            identity_count,
            batch_size=batch_size,
            reopen_mid_run=True,
        )

    expected_batches = (identity_count + batch_size - 1) // batch_size
    expected_retries = sum(index % 17 == 0 for index in range(identity_count))
    expected_fallbacks = sum(index % 19 == 0 for index in range(identity_count))
    assert report.scope == SYNTHETIC_SCALE_SCOPE
    assert report.production_asset_proof is False
    assert report.synthetic_external_effects is True
    assert report.durability_profile == (
        "sqlite_wal_normal_process_reopen_simulation_not_production_power_loss_proof"
    )
    assert report.identity_count == identity_count
    assert report.batch_count == expected_batches
    assert report.item_count == identity_count
    assert report.stage_count == identity_count * len(StageName)
    assert report.publication_count == identity_count
    assert report.receipt_count == identity_count
    assert report.retry_injection_count == expected_retries
    assert report.fallback_injection_count == expected_fallbacks
    assert report.stage_dispatch_count == identity_count * len(StageName) + expected_retries
    assert report.store_reopen_count == 1
    assert 0 < report.reopened_after_stage_dispatches < report.stage_dispatch_count
    assert report.completed_items_at_reopen < identity_count
    assert 0 < report.max_stage_claims_in_flight <= claim_limit
    assert 0 < report.max_publication_claims_in_flight <= claim_limit
    assert report.workers_observed == worker_count
    assert report.elapsed_seconds > 0
    assert report.stage_dispatches_per_second > 0
    assert report.performance_target_seconds == 30.0
    assert report.performance_target_met is (
        report.elapsed_seconds <= report.performance_target_seconds
    )
    assert report.optimization_hypothesis
    assert report.next_discriminating_optimization_target
    assert report.database_file_size_bytes > 0
    assert report.database_wal_size_bytes >= 0
    assert report.database_shm_size_bytes >= 0
    assert report.database_total_storage_bytes == (
        report.database_file_size_bytes
        + report.database_wal_size_bytes
        + report.database_shm_size_bytes
    )
    assert report.database_page_count > 0
    assert report.database_page_size_bytes > 0
    assert report.database_allocated_bytes >= report.database_file_size_bytes
    assert report.event_count > report.stage_count
    assert report.terminal_exactly_once is True
    json.dumps(report.to_json(), allow_nan=False)

    reopened = WorkflowStore(database)
    assert reopened.count_batches() == expected_batches
    with closing(sqlite3.connect(database)) as connection:
        counts = {
            "batches": connection.execute(
                "SELECT COUNT(*) FROM batches WHERE status = 'completed'"
            ).fetchone()[0],
            "items": connection.execute(
                "SELECT COUNT(*) FROM items WHERE status = 'completed'"
            ).fetchone()[0],
            "stages": connection.execute(
                "SELECT COUNT(*) FROM stages WHERE status = 'completed'"
            ).fetchone()[0],
            "exact_item_graphs": connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT item_id
                    FROM stages
                    GROUP BY item_id
                    HAVING COUNT(*) = ?
                       AND COUNT(DISTINCT name) = ?
                )
                """,
                (len(StageName), len(StageName)),
            ).fetchone()[0],
            "distinct_components": connection.execute(
                "SELECT COUNT(DISTINCT component_id) FROM item_component_bindings"
            ).fetchone()[0],
            "publications": connection.execute(
                """
                SELECT COUNT(*) FROM publication_operations
                WHERE state = 'completed'
                """
            ).fetchone()[0],
            "memberships": connection.execute(
                """
                SELECT COUNT(*) FROM publication_memberships
                WHERE state = 'completed'
                """
            ).fetchone()[0],
            "receipts": connection.execute(
                "SELECT COUNT(*) FROM component_publication_receipts"
            ).fetchone()[0],
            "heads": connection.execute(
                "SELECT COUNT(*) FROM component_publication_heads"
            ).fetchone()[0],
            "decisions": connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0],
            "errors": connection.execute(
                "SELECT COUNT(*) FROM stages WHERE error_json IS NOT NULL"
            ).fetchone()[0],
            "retries": connection.execute(
                """
                SELECT COUNT(*) FROM events
                WHERE kind = 'stage_retry_scheduled'
                """
            ).fetchone()[0],
            "retry_ready": connection.execute(
                """
                SELECT COUNT(*) FROM events
                WHERE kind = 'stage_retry_ready'
                """
            ).fetchone()[0],
            "fallbacks": connection.execute(
                """
                SELECT COUNT(*) FROM stages
                WHERE name = 'cad_acquisition'
                  AND result_json LIKE '%"fallback_used":true%'
                """
            ).fetchone()[0],
            "synthetic_receipts": connection.execute(
                """
                SELECT COUNT(*) FROM component_publication_receipts
                WHERE payload_json LIKE '%synthetic_only_no_git_or_catalog_mutation%'
                  AND payload_json LIKE '%"production_asset_proof":false%'
                """
            ).fetchone()[0],
            "synthetic_operations": connection.execute(
                """
                SELECT COUNT(*) FROM publication_operations
                WHERE git_commit_oid LIKE 'synthetic-not-a-git-commit-%'
                  AND catalog_revision LIKE 'synthetic_catalog_revision_%'
                """
            ).fetchone()[0],
            "one_identity_event_per_item": connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT item_id FROM events
                    WHERE kind = 'identity_resolved'
                    GROUP BY item_id
                    HAVING COUNT(*) = 1
                )
                """
            ).fetchone()[0],
            "one_publication_event_per_item": connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT item_id FROM events
                    WHERE kind = 'publication_completed'
                    GROUP BY item_id
                    HAVING COUNT(*) = 1
                )
                """
            ).fetchone()[0],
        }

    assert counts == {
        "batches": expected_batches,
        "items": identity_count,
        "stages": identity_count * len(StageName),
        "exact_item_graphs": identity_count,
        "distinct_components": identity_count,
        "publications": identity_count,
        "memberships": identity_count,
        "receipts": identity_count,
        "heads": identity_count,
        "decisions": 0,
        "errors": 0,
        "retries": expected_retries,
        "retry_ready": expected_retries,
        "fallbacks": expected_fallbacks,
        "synthetic_receipts": identity_count,
        "synthetic_operations": identity_count,
        "one_identity_event_per_item": identity_count,
        "one_publication_event_per_item": identity_count,
    }
    assert all(path.is_file() for path in run_root.iterdir())
    assert {path.name for path in run_root.iterdir()} <= {
        f"Scale Simulation {identity_count}.sqlite",
        f"Scale Simulation {identity_count}.sqlite-shm",
        f"Scale Simulation {identity_count}.sqlite-wal",
    }
    harness.close()
    shutil.rmtree(run_root)
    assert not run_root.exists()
