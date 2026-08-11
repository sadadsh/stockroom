import hashlib
import threading
from pathlib import Path

import pytest

from stockroom.design_studio.personal import (
    MAX_PERSONAL_DESIGN_BYTES,
    PERSONAL_DESIGN_FILENAME,
    PersonalDesignConflict,
    PersonalDesignValidationError,
    load_personal_design,
    save_personal_design,
)


def test_personal_design_save_is_atomic_and_revisioned(tmp_path):
    first = save_personal_design({"schemaVersion": 1, "base": {}}, None, tmp_path)

    second = save_personal_design(
        {"schemaVersion": 1, "base": {"copy": {}}}, first.revision, tmp_path
    )

    assert second.revision != first.revision
    assert load_personal_design(tmp_path) == second
    assert not list(tmp_path.glob(f".{PERSONAL_DESIGN_FILENAME}.*.tmp"))


def test_personal_design_rejects_stale_revision_without_changing_saved_document(tmp_path):
    saved = save_personal_design({"schemaVersion": 1, "base": {}}, None, tmp_path)

    with pytest.raises(PersonalDesignConflict):
        save_personal_design({"schemaVersion": 1, "base": {}}, "stale", tmp_path)

    assert load_personal_design(tmp_path) == saved


@pytest.mark.parametrize(
    "document",
    [
        [],
        {},
        {"schemaVersion": 0},
        {"schemaVersion": True},
        {"schemaVersion": "1"},
        {"base": {}},
    ],
)
def test_personal_design_rejects_invalid_document(document, tmp_path):
    with pytest.raises(PersonalDesignValidationError):
        save_personal_design(document, None, tmp_path)  # type: ignore[arg-type]

    assert load_personal_design(tmp_path) is None


def test_personal_design_rejects_oversize_document_without_creating_a_file(tmp_path):
    document = {
        "schemaVersion": 1,
        "base": {"copy": {"large": "x" * MAX_PERSONAL_DESIGN_BYTES}},
    }

    with pytest.raises(PersonalDesignValidationError, match="too large"):
        save_personal_design(document, None, tmp_path)

    assert load_personal_design(tmp_path) is None


def test_personal_design_load_rejects_malformed_json(tmp_path):
    path = tmp_path / PERSONAL_DESIGN_FILENAME
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(PersonalDesignValidationError, match="valid JSON"):
        load_personal_design(tmp_path)


def test_personal_design_delete_requires_the_current_revision(tmp_path):
    saved = save_personal_design({"schemaVersion": 1}, None, tmp_path)

    from stockroom.design_studio.personal import delete_personal_design

    with pytest.raises(PersonalDesignConflict):
        delete_personal_design("stale", tmp_path)

    assert load_personal_design(tmp_path) == saved

    delete_personal_design(saved.revision, tmp_path)

    assert load_personal_design(tmp_path) is None


def test_personal_design_preserves_existing_bytes_when_replace_fails(tmp_path, monkeypatch):
    saved = save_personal_design({"schemaVersion": 1, "base": {}}, None, tmp_path)
    path = tmp_path / PERSONAL_DESIGN_FILENAME
    before = path.read_bytes()

    import stockroom.design_studio.personal as personal

    def fail_replace(_source, _destination):
        raise OSError("injected replace failure")

    monkeypatch.setattr(personal.os, "replace", fail_replace)

    with pytest.raises(OSError, match="injected replace failure"):
        save_personal_design({"schemaVersion": 1, "base": {"copy": {}}}, saved.revision, tmp_path)

    assert path.read_bytes() == before
    assert hashlib.sha256(before).hexdigest() == saved.revision
    assert not list(tmp_path.glob(f".{PERSONAL_DESIGN_FILENAME}.*.tmp"))


def test_personal_design_allows_only_one_concurrent_save_for_a_revision(tmp_path, monkeypatch):
    saved = save_personal_design({"schemaVersion": 1}, None, tmp_path)

    import stockroom.design_studio.personal as personal

    actual_replace = personal.os.replace
    first_replace_started = threading.Event()
    release_first_replace = threading.Event()
    replace_count = 0
    replace_count_lock = threading.Lock()

    def block_first_replace(source, destination):
        nonlocal replace_count
        with replace_count_lock:
            replace_count += 1
            is_first = replace_count == 1
        if is_first:
            first_replace_started.set()
            assert release_first_replace.wait(timeout=2)
        actual_replace(source, destination)

    monkeypatch.setattr(personal.os, "replace", block_first_replace)
    first_result: list[object] = []
    second_result: list[object] = []
    second_finished = threading.Event()

    def save_first() -> None:
        try:
            first_result.append(
                save_personal_design({"schemaVersion": 1, "base": {"copy": {}}}, saved.revision, tmp_path)
            )
        except Exception as exc:  # pragma: no cover - assertion checks the captured result
            first_result.append(exc)

    def save_second() -> None:
        try:
            second_result.append(
                save_personal_design({"schemaVersion": 1, "base": {"layout": {}}}, saved.revision, tmp_path)
            )
        except Exception as exc:
            second_result.append(exc)
        finally:
            second_finished.set()

    first = threading.Thread(target=save_first)
    second = threading.Thread(target=save_second)
    first.start()
    assert first_replace_started.wait(timeout=2)
    second.start()
    assert not second_finished.wait(timeout=0.1)
    release_first_replace.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert not isinstance(first_result[0], Exception)
    assert isinstance(second_result[0], PersonalDesignConflict)


def test_personal_design_delete_cannot_remove_a_concurrently_saved_document(tmp_path, monkeypatch):
    saved = save_personal_design({"schemaVersion": 1}, None, tmp_path)

    import stockroom.design_studio.personal as personal

    actual_unlink = Path.unlink
    unlink_started = threading.Event()
    release_unlink = threading.Event()

    def block_unlink(path, *args, **kwargs):
        unlink_started.set()
        assert release_unlink.wait(timeout=2)
        return actual_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", block_unlink)
    delete_result: list[object] = []
    save_result: list[object] = []
    save_finished = threading.Event()

    def delete_current() -> None:
        try:
            from stockroom.design_studio.personal import delete_personal_design

            delete_result.append(delete_personal_design(saved.revision, tmp_path))
        except Exception as exc:  # pragma: no cover - assertion checks the captured result
            delete_result.append(exc)

    def save_again() -> None:
        try:
            save_result.append(
                save_personal_design({"schemaVersion": 1, "base": {}}, saved.revision, tmp_path)
            )
        except Exception as exc:
            save_result.append(exc)
        finally:
            save_finished.set()

    delete_thread = threading.Thread(target=delete_current)
    save_thread = threading.Thread(target=save_again)
    delete_thread.start()
    assert unlink_started.wait(timeout=2)
    save_thread.start()
    assert not save_finished.wait(timeout=0.1)
    release_unlink.set()
    delete_thread.join(timeout=2)
    save_thread.join(timeout=2)

    assert not delete_thread.is_alive()
    assert not save_thread.is_alive()
    assert delete_result == [None]
    assert isinstance(save_result[0], PersonalDesignConflict)
    assert load_personal_design(tmp_path) is None


def test_personal_design_recovers_after_a_stale_lock_artifact(tmp_path, monkeypatch):
    import stockroom.design_studio.personal as personal

    (tmp_path / ".design-studio.json.lock").touch()
    monkeypatch.setattr(personal, "_LOCK_TIMEOUT_SECONDS", 0.01)

    saved = save_personal_design({"schemaVersion": 1}, None, tmp_path)

    assert load_personal_design(tmp_path) == saved


def test_personal_design_load_treats_a_concurrent_delete_as_missing(tmp_path, monkeypatch):
    saved = save_personal_design({"schemaVersion": 1}, None, tmp_path)
    path = tmp_path / PERSONAL_DESIGN_FILENAME
    actual_read_bytes = Path.read_bytes
    read_started = threading.Event()
    release_read = threading.Event()
    result: list[object] = []

    def block_design_read(candidate):
        if candidate == path:
            read_started.set()
            assert release_read.wait(timeout=2)
        return actual_read_bytes(candidate)

    monkeypatch.setattr(Path, "read_bytes", block_design_read)

    def load() -> None:
        try:
            result.append(load_personal_design(tmp_path))
        except Exception as exc:  # pragma: no cover - assertion checks the captured result
            result.append(exc)

    reader = threading.Thread(target=load)
    reader.start()
    assert read_started.wait(timeout=2)
    path.unlink()
    release_read.set()
    reader.join(timeout=2)

    assert not reader.is_alive()
    assert result == [None]
    assert saved.revision
