import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from stockroom.vcs.locks import DocumentLock, GitLfsLockService, LockError


class _Repo:
    root = Path("/repo")

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def _rel(self, path):
        p = Path(path)
        return p.as_posix().removeprefix("/repo/")

    def _run(self, *args, check=False):
        self.calls.append(args)
        return self.responses.pop(0)


def _result(*, code=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


@pytest.mark.parametrize("shape", ["wrapped", "plain", "list"])
def test_acquire_reads_the_exact_server_lock(shape):
    row = {
        "id": "42",
        "path": "board/main.kicad_pcb",
        "locked_at": "2026-07-28T12:00:00Z",
        "owner": {"name": "Sadad"},
    }
    payload = {"wrapped": {"lock": row}, "plain": row, "list": [row]}[shape]
    repo = _Repo([_result(stdout=json.dumps(payload))])
    service = GitLfsLockService(repo)

    lock = service.acquire("/repo/board/main.kicad_pcb")

    assert lock == DocumentLock(
        id="42",
        path="board/main.kicad_pcb",
        owner="Sadad",
        locked_at="2026-07-28T12:00:00Z",
    )
    assert repo.calls == [("lfs", "lock", "--json", "board/main.kicad_pcb")]


@pytest.mark.parametrize("wrapped", [True, False])
def test_list_and_owns_require_the_same_id_and_path(wrapped):
    rows = [
        {"id": "42", "path": "main.PcbDoc", "owner": {"name": "Alex"}},
        {"id": "99", "path": "power.SchDoc", "owner": {"name": "Sadad"}},
    ]
    payload = {"locks": rows} if wrapped else rows
    repo = _Repo([_result(stdout=json.dumps(payload))])
    service = GitLfsLockService(repo)

    assert service.owns(DocumentLock(id="99", path="power.SchDoc", owner="Sadad"))


def test_incomplete_or_invalid_lock_responses_fail_closed():
    service = GitLfsLockService(_Repo([_result(stdout='{"lock": {"id": "42"}}')]))
    with pytest.raises(LockError, match="wrong document"):
        service.acquire("main.PcbDoc")

    service = GitLfsLockService(_Repo([_result(stdout="not json")]))
    with pytest.raises(LockError, match="invalid JSON"):
        service.list()


def test_release_uses_the_opaque_server_id_and_never_forces_by_default():
    repo = _Repo([_result()])
    service = GitLfsLockService(repo)
    service.release(DocumentLock(id="42", path="main.PcbDoc", owner="Sadad"))
    assert repo.calls == [("lfs", "unlock", "--id", "42")]


def test_forced_release_is_an_explicit_distinct_operation():
    repo = _Repo([_result()])
    service = GitLfsLockService(repo)
    service.release(
        DocumentLock(id="42", path="main.PcbDoc", owner="Sadad"),
        force=True,
    )
    assert repo.calls == [("lfs", "unlock", "--id", "42", "--force")]
