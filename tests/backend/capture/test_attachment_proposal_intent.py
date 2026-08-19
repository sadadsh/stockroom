from __future__ import annotations

import pytest

from stockroom.capture.intent import PersonCaptureIntent, PersonCaptureIntentError


def _proposal() -> dict[str, object]:
    return {
        "part_id": "part-1",
        "provider": "ultralibrarian",
        "primary_tool": "kicad",
        "attachments": [
            {
                "role": "Symbol",
                "file_name": "Part.kicad_sym",
                "target": "Active KiCad Symbol",
            },
            {
                "role": "Footprint",
                "file_name": "Part.kicad_mod",
                "target": "Active KiCad Footprint",
            },
        ],
        "inactive_evidence": [],
    }


def test_attachment_proposal_is_non_activating_until_exact_apply() -> None:
    intent = PersonCaptureIntent("part-1")

    token = intent.set_attachment_proposal(_proposal())

    assert intent.take_attachment_apply(token) is False
    assert intent.attachment_proposal() == {"proposal_token": token, **_proposal()}
    with pytest.raises(PersonCaptureIntentError, match="proposal changed"):
        intent.apply_attachment_proposal("stale-token")
    intent.apply_attachment_proposal(token)
    assert intent.take_attachment_apply(token) is True
    assert intent.take_attachment_apply(token) is False


def test_clearing_one_proposal_cannot_clear_its_successor() -> None:
    intent = PersonCaptureIntent("part-1")
    old_token = intent.set_attachment_proposal(_proposal())
    current_token = intent.set_attachment_proposal(_proposal())

    intent.clear_attachment_proposal(old_token)

    assert intent.attachment_proposal() == {"proposal_token": current_token, **_proposal()}
