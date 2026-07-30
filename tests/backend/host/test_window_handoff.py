from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from stockroom.host.window_geometry import (
    MonitorGeometry,
    PhysicalRect,
    WindowGeometry,
    WindowShowState,
)
from stockroom.host.window_handoff import (
    ManagedWindowHandoff,
    WindowCandidate,
    WindowContinuity,
    WindowHandoffError,
    WindowHandoffState,
    WindowProof,
)

_SESSION = "1" * 64
_SELECTION = "2" * 64
_HANDOFF_ID = "2ed594a5-e46d-4fc0-aecb-17ca94aab32f"


def _geometry() -> WindowGeometry:
    return WindowGeometry(
        normal_bounds=PhysicalRect(80, 60, 1480, 960),
        show_state=WindowShowState.NORMAL,
        monitor=MonitorGeometry(
            device_name=r"\\.\DISPLAY1",
            work_area=PhysicalRect(0, 0, 1920, 1040),
            dpi=96,
        ),
    )


def _continuity() -> WindowContinuity:
    return WindowContinuity(
        session_digest=_SESSION,
        geometry=_geometry(),
        theme="dark",
        route="components",
        selected_ids_digest=_SELECTION,
        workflow_batch="batch-42",
        event_sequence=917,
    )


def _candidate() -> WindowCandidate:
    return WindowCandidate(
        release_id="release-v2",
        process_id=1200,
        window_handle=4500,
        profile_id="webview-release-v2-1200",
    )


def _proof(*, visible: bool, event_sequence: int = 917) -> WindowProof:
    return WindowProof(
        release_id="release-v2",
        process_id=1200,
        window_handle=4500,
        session_digest=_SESSION,
        geometry=_geometry(),
        theme="dark",
        route="components",
        selected_ids_digest=_SELECTION,
        workflow_batch="batch-42",
        event_sequence=event_sequence,
        hidden=not visible,
        visible=visible,
        api_healthy=True,
        event_stream_healthy=True,
    )


@dataclass
class _Ports:
    fail_at: str | None = None
    operations: list[str] = field(default_factory=list)
    old_usable: bool = True

    def _step(self, name: str) -> None:
        self.operations.append(name)
        if self.fail_at == name:
            raise RuntimeError(name)

    def capture_continuity(self):
        self._step("capture")
        return _continuity()

    def spawn_hidden(self, handoff_id, target_release_id, continuity):
        assert handoff_id == _HANDOFF_ID
        assert target_release_id == "release-v2"
        assert continuity == _continuity()
        self._step("spawn")
        return _candidate()

    def wait_hidden_ready(self, candidate, continuity):
        assert candidate == _candidate()
        assert continuity == _continuity()
        self._step("hidden-ready")
        return _proof(visible=False)

    def show_candidate(self, candidate):
        assert candidate == _candidate()
        self._step("show-candidate")

    def verify_visible(self, candidate, continuity):
        self._step("visible-proof")
        return _proof(visible=True)

    def hide_old(self):
        self._step("hide-old")

    def verify_post_cutover(self, candidate, continuity):
        self._step("post-cutover")
        return _proof(visible=True)

    def commit_candidate(self, candidate):
        self._step("commit")

    def retire_old(self):
        self._step("retire-old")

    def rollback_candidate(self, candidate):
        self._step("rollback-candidate")

    def show_old(self):
        self._step("show-old")

    def verify_old_usable(self, continuity):
        self._step("verify-old")
        if not self.old_usable:
            raise RuntimeError("old unusable")

    def stop_candidate(self, candidate):
        self._step("stop-candidate")


def _handoff(ports: _Ports) -> ManagedWindowHandoff:
    ticks = iter(float(value) for value in range(20))
    return ManagedWindowHandoff(
        ports,
        clock=lambda: next(ticks),
        id_factory=lambda: _HANDOFF_ID,
    )


def test_handoff_proves_hidden_and_visible_continuity_before_commit_and_retirement() -> None:
    ports = _Ports()
    handoff = _handoff(ports)

    adoption = handoff.begin("release-v2")

    assert handoff.state is WindowHandoffState.VISIBLE_TRIAL
    assert adoption.release_id == "release-v2"
    assert [event.phase for event in adoption.events] == [
        "starting",
        "durable-session",
        "candidate-started",
        "hidden-ready",
        "candidate-show-requested",
        "candidate-visible",
        "old-hidden",
        "post-cutover-healthy",
    ]
    assert ports.operations == [
        "capture",
        "spawn",
        "hidden-ready",
        "show-candidate",
        "visible-proof",
        "hide-old",
        "post-cutover",
    ]

    receipt = handoff.commit(adoption)

    assert handoff.state is WindowHandoffState.ACTIVE
    assert receipt.state is WindowHandoffState.ACTIVE
    assert not receipt.retirement_pending
    assert receipt.session_digest == _SESSION
    assert receipt.event_sequence == 917
    assert [event.phase for event in receipt.events] == [
        "starting",
        "durable-session",
        "candidate-started",
        "hidden-ready",
        "candidate-show-requested",
        "candidate-visible",
        "old-hidden",
        "post-cutover-healthy",
        "pointer-committed",
        "old-retired",
    ]
    assert ports.operations == [
        "capture",
        "spawn",
        "hidden-ready",
        "show-candidate",
        "visible-proof",
        "hide-old",
        "post-cutover",
        "commit",
        "retire-old",
    ]


@pytest.mark.parametrize(
    "failure",
    [
        "spawn",
        "hidden-ready",
        "show-candidate",
        "visible-proof",
        "hide-old",
        "post-cutover",
    ],
)
def test_every_precommit_failure_rolls_back_without_retiring_the_old_window(
    failure: str,
) -> None:
    ports = _Ports(fail_at=failure)
    handoff = _handoff(ports)

    with pytest.raises(WindowHandoffError) as error:
        handoff.begin("release-v2")

    assert error.value.phase
    assert handoff.state is WindowHandoffState.ROLLED_BACK
    assert "retire-old" not in ports.operations
    if failure != "spawn":
        assert ports.operations[-3:] == [
            "rollback-candidate",
            "verify-old",
            "stop-candidate",
        ] or ports.operations[-4:] == [
            "rollback-candidate",
            "show-old",
            "verify-old",
            "stop-candidate",
        ]


@pytest.mark.parametrize("failure", ["post-cutover"])
def test_failure_after_old_is_hidden_shows_and_verifies_it_before_candidate_stop(
    failure: str,
) -> None:
    ports = _Ports(fail_at=failure)

    with pytest.raises(WindowHandoffError):
        _handoff(ports).begin("release-v2")

    assert ports.operations[-4:] == [
        "rollback-candidate",
        "show-old",
        "verify-old",
        "stop-candidate",
    ]


def test_mismatched_event_sequence_cannot_hide_the_old_window() -> None:
    class _Mismatch(_Ports):
        def verify_visible(self, candidate, continuity):
            self._step("visible-proof")
            return _proof(visible=True, event_sequence=916)

    ports = _Mismatch()

    with pytest.raises(WindowHandoffError, match="visible-proof") as error:
        _handoff(ports).begin("release-v2")

    assert isinstance(error.value.cause, ValueError)
    assert "hide-old" not in ports.operations
    assert ports.operations[-3:] == [
        "rollback-candidate",
        "verify-old",
        "stop-candidate",
    ]


def test_rollback_failure_is_explicit_and_never_reported_as_old_window_recovery() -> None:
    ports = _Ports(fail_at="post-cutover", old_usable=False)
    handoff = _handoff(ports)

    with pytest.raises(WindowHandoffError) as error:
        handoff.begin("release-v2")

    assert handoff.state is WindowHandoffState.FAILED
    assert error.value.rollback_errors == ("old health: RuntimeError",)


def test_retirement_failure_keeps_the_committed_candidate_active_for_cleanup_retry() -> None:
    ports = _Ports(fail_at="retire-old")
    handoff = _handoff(ports)

    receipt = handoff.commit(handoff.begin("release-v2"))

    assert handoff.state is WindowHandoffState.ACTIVE_RETIREMENT_PENDING
    assert receipt.state is WindowHandoffState.ACTIVE_RETIREMENT_PENDING
    assert receipt.retirement_pending
    assert receipt.events[-1].phase == "old-retirement-pending"
    assert "rollback-candidate" not in ports.operations
    assert "show-old" not in ports.operations


def test_invalid_hidden_visibility_proof_fails_before_candidate_show() -> None:
    class _WrongVisibility(_Ports):
        def wait_hidden_ready(self, candidate, continuity):
            self._step("hidden-ready")
            return _proof(visible=True)

    ports = _WrongVisibility()

    with pytest.raises(WindowHandoffError) as error:
        _handoff(ports).begin("release-v2")

    assert isinstance(error.value.cause, ValueError)
    assert "show-candidate" not in ports.operations


def test_concurrent_activation_is_refused() -> None:
    handoff = _handoff(_Ports())
    handoff._state = WindowHandoffState.PREPARING

    with pytest.raises(RuntimeError, match="already active"):
        handoff.begin("release-v2")


def test_release_pointer_owner_can_rollback_a_healthy_visible_trial() -> None:
    ports = _Ports()
    handoff = _handoff(ports)
    adoption = handoff.begin("release-v2")

    handoff.rollback(adoption)

    assert handoff.state is WindowHandoffState.ROLLED_BACK
    assert ports.operations[-4:] == [
        "rollback-candidate",
        "show-old",
        "verify-old",
        "stop-candidate",
    ]
    assert "commit" not in ports.operations
    assert "retire-old" not in ports.operations


def test_candidate_commit_failure_restores_old_window_for_pointer_rollback() -> None:
    ports = _Ports(fail_at="commit")
    handoff = _handoff(ports)
    adoption = handoff.begin("release-v2")

    with pytest.raises(WindowHandoffError, match="commit-candidate") as error:
        handoff.commit(adoption)

    assert handoff.state is WindowHandoffState.VISIBLE_TRIAL
    assert error.value.rollback_errors == ()
    assert ports.operations[-1] == "commit"
    assert "retire-old" not in ports.operations

    handoff.rollback(adoption)

    assert handoff.state is WindowHandoffState.ROLLED_BACK
    assert ports.operations[-5:] == [
        "commit",
        "rollback-candidate",
        "show-old",
        "verify-old",
        "stop-candidate",
    ]


def test_stale_adoption_cannot_commit_or_rollback_another_handoff() -> None:
    ports = _Ports()
    handoff = _handoff(ports)
    adoption = handoff.begin("release-v2")
    handoff.rollback(adoption)

    with pytest.raises(RuntimeError, match="stale"):
        handoff.commit(adoption)
    with pytest.raises(RuntimeError, match="stale"):
        handoff.rollback(adoption)
