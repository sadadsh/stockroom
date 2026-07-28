"""The progress page must not turn unequal implementation ticks into product readiness."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "stockroom_progress_tool", ROOT / "scripts" / "progress.py"
)
assert SPEC and SPEC.loader
progress = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(progress)


def _plan() -> dict:
    return {
        "title": "Stockroom",
        "progress_schema": 2,
        "product_scope": "Windows-only dual-EDA library.",
        "active_work": {
            "last_updated": progress._utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "objective": "Land the fail-closed workflow foundation.",
            "refresh_policy": (
                "Manually refreshed at meaningful checkpoints; "
                "this is not real-time telemetry."
            ),
            "workstreams": [
                {
                    "id": "kernel",
                    "name": "Workflow Kernel",
                    "status": "active",
                    "owner": "development tool · kernel",
                    "evidence": "The durable store exists in isolation.",
                    "blocker": "",
                    "next_action": "Finish the migration fence.",
                },
                {
                    "id": "host",
                    "name": "Host Bakeoff",
                    "status": "verification",
                    "owner": "development tool · host",
                    "evidence": "One bounded challenger proof exists.",
                    "blocker": "The full bakeoff remains.",
                    "next_action": "Run the remaining comparisons.",
                },
                {
                    "id": "aggregate",
                    "name": "Aggregate Gate",
                    "status": "pending",
                    "owner": "development tool · verification",
                    "evidence": "Parallel changes have not settled.",
                    "blocker": "The candidate is still moving.",
                    "next_action": "Run after convergence.",
                },
            ],
        },
        "owner_requirements": [],
        "outcome_gates": [
            {
                "id": "assets",
                "name": "Assets",
                "status": "not_met",
                "measure": "0/1",
                "acceptance": "Both EDA tools place the part.",
                "evidence": ["Measured on the clean profile."],
                "blockers": ["Acquire and verify the assets."],
            }
        ],
        "projects": [
            {
                "id": "stockroom",
                "name": "Stockroom",
                "why": "",
                "waves": [
                    {
                        "id": "build",
                        "name": "Build",
                        "why": "",
                        "items": [
                            {
                                "id": "pipeline",
                                "name": "Pipeline",
                                "why": "",
                                "steps": [
                                    {
                                        "t": "Delivered",
                                        "done": True,
                                        "status": "done",
                                        "evidence": "On main.",
                                    },
                                    {
                                        "t": "Experiment",
                                        "done": False,
                                        "status": "done_off_main",
                                        "evidence": "Preserved on a branch.",
                                    },
                                    {
                                        "t": "Wrong claim",
                                        "done": False,
                                        "status": "invalidated",
                                        "evidence": "Composition test disproved it.",
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }


def test_only_delivered_current_line_steps_count() -> None:
    item = _plan()["projects"][0]["waves"][0]["items"][0]
    assert progress.item_progress(item) == (1, 3)
    assert progress.derive_state(item) == "doing"


def test_old_done_boolean_remains_readable_but_explicit_lifecycle_wins() -> None:
    assert progress.step_status({"done": True}) == "done"
    assert progress.step_status({"done": False}) == "todo"
    assert progress.step_status({"done": True, "status": "invalidated"}) == "invalidated"


def test_render_refuses_to_present_the_raw_counter_as_product_readiness(monkeypatch) -> None:
    monkeypatch.setattr(progress, "activity", lambda: [])
    rendered = progress.render_html(_plan())
    assert "Product readiness has no aggregate percentage" in rendered
    assert "development tool Active Work" in rendered
    assert "Manual checkpoint snapshot" in rendered
    assert "Manually refreshed at meaningful checkpoints" in rendered
    assert "Workflow Kernel" in rendered
    assert "development tool · kernel" in rendered
    assert ">Active<" in rendered
    assert ">Verification<" in rendered
    assert ">Pending<" in rendered
    assert "Current evidence" in rendered
    assert "Next action" in rendered
    assert "Owner Outcome Gates" in rendered
    assert "Independent gates; never averaged" in rendered
    assert "Engineering Checklist History" in rendered
    assert "not product readiness" in rendered
    assert "Off Main" in rendered
    assert "Invalidated" in rendered


def test_check_validates_outcomes_and_explicit_step_state(capsys) -> None:
    plan = _plan()
    assert progress.cmd_check(plan) == 0
    assert "1 independent outcome gates" in capsys.readouterr().out

    plan["outcome_gates"][0]["evidence"] = []
    plan["projects"][0]["waves"][0]["items"][0]["steps"][1]["done"] = True
    assert progress.cmd_check(plan) == 1
    out = capsys.readouterr().out
    assert "evidence must be non-empty strings" in out
    assert "disagrees with explicit status='done_off_main'" in out


def test_check_rejects_unknown_active_work_status(capsys) -> None:
    plan = _plan()
    plan["active_work"]["workstreams"][0]["status"] = "doing"

    assert progress.cmd_check(plan) == 1
    assert "unknown active-work status 'doing'" in capsys.readouterr().out


def test_check_rejects_stale_active_work_snapshot(capsys) -> None:
    plan = _plan()
    plan["active_work"]["last_updated"] = "2000-01-01T00:00:00Z"

    assert progress.cmd_check(plan) == 1
    assert "active_work.last_updated is stale" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("missing", "message"),
    [
        ("active_work", "active_work must be an object"),
        ("objective", "active_work.objective must be a non-empty string"),
        ("workstreams", "active_work.workstreams must contain 3 to 6 workstreams"),
    ],
)
def test_check_rejects_missing_active_work_shape(
    missing: str, message: str, capsys
) -> None:
    plan = _plan()
    if missing == "active_work":
        del plan["active_work"]
    else:
        del plan["active_work"][missing]

    assert progress.cmd_check(plan) == 1
    assert message in capsys.readouterr().out
