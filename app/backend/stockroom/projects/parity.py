"""The public Projects contract shared by every supported EDA.

Native adapters may use different executables and file formats, but those
differences stop at the adapter boundary. The API and frontend consume this
single contract so a tool cannot quietly gain EDA-specific controls, states, or
acceptance rules.
"""

from __future__ import annotations

from copy import deepcopy

PROJECT_PARITY_SCHEMA = "stockroom-project-parity/1"
PROJECT_EDAS = ("kicad", "altium")
PROJECT_TOOLS = ("design", "bom", "assemble", "changes", "releases")

_TOOL_CONTRACTS = (
    {
        "key": "design",
        "label": "Design",
        "status": "active",
        "behavior": "identical",
        "actions": ["inspect_documents"],
        "inputs": ["selected_document"],
        "states": ["loading", "ready", "missing_source", "runtime_blocked"],
        "results": ["document_inventory", "native_source_status"],
        "recovery": ["refresh_workspace"],
        "acceptance": ["same_document_shape", "source_bytes_unchanged"],
    },
    {
        "key": "bom",
        "label": "BOM",
        "status": "active",
        "behavior": "identical",
        "actions": [
            "inspect_live_bom",
            "set_build_quantity",
            "resolve_identity",
            "export_bom",
        ],
        "inputs": ["build_quantity", "search", "selected_line", "library_part"],
        "states": ["loading", "ready", "empty", "unresolved", "error"],
        "results": [
            "normalized_bom",
            "identity_coverage",
            "stable_digest",
            "download",
        ],
        "recovery": ["retry_read", "replace_identity_choice"],
        "acceptance": ["same_bom_shape", "grouped_assignment", "native_source_preserved"],
    },
    {
        "key": "assemble",
        "label": "Assemble",
        "status": "active",
        "behavior": "identical",
        "actions": ["start_run", "verify_part", "record_placement", "complete_run"],
        "inputs": ["operator", "board_quantity", "scanned_mpn", "placement_state"],
        "states": ["not_started", "active", "paused", "completed", "blocked"],
        "results": ["placement_queue", "progress", "event_history"],
        "recovery": ["resume_active_run", "record_rework", "record_skip"],
        "acceptance": ["same_event_shape", "exact_source_commit", "matching_part_scan"],
    },
    {
        "key": "changes",
        "label": "Changes",
        "status": "active",
        "behavior": "identical",
        "actions": [
            "inspect_repository",
            "start_work",
            "recover_work",
            "share_work",
            "review_commit",
            "run_native_checks",
            "request_changes",
            "approve_commit",
            "finish_work",
        ],
        "inputs": ["owner", "documents", "commit_message", "reviewer", "review_message"],
        "states": [
            "idle",
            "claimed",
            "shared",
            "changes_requested",
            "approved",
            "integrated",
            "recovery_required",
        ],
        "results": ["work_session", "review_evidence", "integration_receipt"],
        "recovery": ["resume_verified_session", "rollback_partial_recovery"],
        "acceptance": [
            "exact_commit",
            "source_hashes",
            "bom_digest",
            "semantic_audit",
            "native_validation",
        ],
    },
    {
        "key": "releases",
        "label": "Releases",
        "status": "planned",
        "behavior": "identical",
        "actions": [],
        "inputs": [],
        "states": ["not_available"],
        "results": [],
        "recovery": [],
        "acceptance": ["paired_implementation_required_before_activation"],
    },
)


def project_capabilities() -> list[str]:
    """Return the shared user-facing tool set, never native implementation details."""

    return list(PROJECT_TOOLS)


def parity_payload() -> dict:
    """Return a fresh JSON-safe copy so request handlers cannot mutate the contract."""

    return {
        "schema": PROJECT_PARITY_SCHEMA,
        "edas": list(PROJECT_EDAS),
        "strict": True,
        "adapter_boundary": "native_io_only",
        "tools": deepcopy(_TOOL_CONTRACTS),
    }
