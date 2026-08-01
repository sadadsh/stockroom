"""Recover the DigiKey models id from the person's OWN browser history, and nothing else.

WHY THIS EXISTS
The deep link in `capture/digikey_models.py` skips the keyword search for a part the person has
already opened once. It learned the opaque id from `UserCaptureResult.final_url` - the page a
Playwright-driven capture ended on. Person-driven capture has since been de-automated
(`capture/handoff.py` hands the URL to the operating system's default browser and walks away), so
Stockroom no longer observes where the person went. It cannot learn a single new id, and the
shortcut is dead for every new part.

The owner approved reading their own local browser history to recover it. That approval is narrow,
and these tests are what hold it narrow:

  * it does not run at all unless explicitly enabled;
  * it reads a COPY, never the live database, and never writes to either;
  * the SQL itself is the filter, so a row that is not a DigiKey models page is never read,
    returned, counted, traced or stored;
  * an id binds to a part only when the title's MPN identifies EXACTLY ONE library part, because
    the store keys on manufacturer AND MPN and history supplies no manufacturer;
  * every failure - absent, locked, corrupt, schema-shifted - degrades to today's behaviour.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from stockroom.capture import models_history
from stockroom.capture import trace as capture_trace
from stockroom.capture.digikey_models import DigiKeyModelsIds
from stockroom.capture.identity import same_mpn

# -- fixtures and helpers ---------------------------------------------------------------------


@dataclass(frozen=True)
class _Part:
    manufacturer: str
    mpn: str


_TI = _Part(manufacturer="Texas Instruments", mpn="TPS2121RUXR")
_ABRACON = _Part(manufacturer="Abracon LLC", mpn="ABM13W-32.0000MHZ-5-DH7G-T5")

_MODELS_TITLE = "{mpn} EDA | CAD 3D Model Download | Digikey"

# A row that is none of Stockroom's business. It is inserted into every synthetic history used
# here, so any test that reads too much fails on THIS value rather than on a missing assertion.
_PRIVATE_URL = "https://members.example-bank.invalid/accounts/statement-2026-07"
_PRIVATE_TITLE = "Sensitive Personal Banking Statement"


def _chromium_history(path: Path, rows: list[tuple[str, str, int]]) -> Path:
    """A synthetic Chromium `History` database: the real `urls` table shape, nothing more."""

    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE urls(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url LONGVARCHAR,
                title LONGVARCHAR,
                visit_count INTEGER DEFAULT 0 NOT NULL,
                typed_count INTEGER DEFAULT 0 NOT NULL,
                last_visit_time INTEGER NOT NULL,
                hidden INTEGER DEFAULT 0 NOT NULL
            )
            """
        )
        connection.executemany(
            "INSERT INTO urls(url, title, last_visit_time) VALUES(?, ?, ?)",
            [*rows, (_PRIVATE_URL, _PRIVATE_TITLE, 13_300_000_000_000_000)],
        )
        connection.commit()
    finally:
        connection.close()
    return path


@pytest.fixture
def local_app_data(tmp_path, monkeypatch) -> Path:
    """A private `%LOCALAPPDATA%` with no browser installed until a test installs one."""

    root = tmp_path / "LocalAppData"
    root.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(root))
    return root


@pytest.fixture
def enabled(monkeypatch) -> None:
    monkeypatch.setenv(models_history.MODELS_HISTORY_OPT_IN, "1")


@pytest.fixture
def trace_file(tmp_path, monkeypatch):
    path = tmp_path / "capture.log"
    monkeypatch.setenv("STOCKROOM_CAPTURE_LOG", str(path))
    monkeypatch.setenv("STOCKROOM_CAPTURE_LOG_LEVEL", "DEBUG")
    capture_trace.reset_for_tests()
    try:
        yield path
    finally:
        capture_trace.reset_for_tests()


def _log_text(path: Path) -> str:
    for handler in logging.getLogger(capture_trace.LOGGER_NAME).handlers:
        handler.flush()
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _vivaldi(root: Path, rows: list[tuple[str, str, int]], profile: str = "Default") -> Path:
    return _chromium_history(root / "Vivaldi" / "User Data" / profile / "History", rows)


def _store(tmp_path: Path) -> DigiKeyModelsIds:
    return DigiKeyModelsIds(tmp_path / "DigiKey Models.json")


# -- opt-in: it does not run unless the owner says so -------------------------------------------


def test_a_the_reader_is_inert_until_it_is_explicitly_enabled(tmp_path, local_app_data):
    """Default OFF. An unset environment reads no history file at all."""

    _vivaldi(
        local_app_data,
        [("https://www.digikey.com/en/models/6695662", _MODELS_TITLE.format(mpn=_TI.mpn), 1)],
    )
    store = _store(tmp_path)

    outcome = models_history.learn_models_ids_from_history([_TI], store=store)

    assert outcome.enabled is False
    assert outcome.signal == "not-enabled"
    assert outcome.databases == 0
    assert outcome.candidates == 0
    assert outcome.learned == 0
    assert store.get(manufacturer=_TI.manufacturer, mpn=_TI.mpn) == ""


def test_b_an_explicit_environment_opt_in_enables_it(monkeypatch):
    monkeypatch.delenv(models_history.MODELS_HISTORY_OPT_IN, raising=False)
    assert models_history.history_learning_decision(environ={}).enabled is False

    for value in ("1", "true", "yes", "on", "ON", " True "):
        decision = models_history.history_learning_decision(
            environ={models_history.MODELS_HISTORY_OPT_IN: value}
        )
        assert decision.enabled is True, value
        assert decision.signal == "environment-opt-in"

    for value in ("", "0", "false", "no", "off", "maybe"):
        assert (
            models_history.history_learning_decision(
                environ={models_history.MODELS_HISTORY_OPT_IN: value}
            ).enabled
            is False
        ), value


def test_c_a_per_machine_flag_enables_it_the_way_access_policy_does():
    """Same shape as `access_policy`: an explicit `True` on the machine config, never a truthy."""

    class _Config:
        pass

    config = _Config()
    assert models_history.history_learning_decision(config=config, environ={}).enabled is False

    setattr(config, models_history.MODELS_HISTORY_CONFIG_FLAG, "yes")
    assert models_history.history_learning_decision(config=config, environ={}).enabled is False

    setattr(config, models_history.MODELS_HISTORY_CONFIG_FLAG, True)
    decision = models_history.history_learning_decision(config=config, environ={})
    assert decision.enabled is True
    assert decision.signal == "machine-config-flag"


# -- the happy path ------------------------------------------------------------------------------


def test_d_a_history_models_page_teaches_the_id_for_a_matching_part(
    tmp_path, local_app_data, enabled
):
    _vivaldi(
        local_app_data,
        [
            (
                "https://www.digikey.com/en/models/6695662?tab=ultralibrarian",
                _MODELS_TITLE.format(mpn=_TI.mpn),
                13_390_000_000_000_000,
            )
        ],
    )
    store = _store(tmp_path)

    outcome = models_history.learn_models_ids_from_history([_TI], store=store)

    assert outcome.enabled is True
    assert outcome.databases == 1
    assert outcome.candidates == 1
    assert outcome.resolved == 1
    assert outcome.learned == 1
    assert store.get(manufacturer=_TI.manufacturer, mpn=_TI.mpn) == "6695662"


def test_e_the_learned_id_survives_a_reload_of_the_existing_store(
    tmp_path, local_app_data, enabled
):
    """It feeds the EXISTING store, so a later process reads it back with no new machinery."""

    _vivaldi(
        local_app_data,
        [("https://www.digikey.com/en/models/6695662", _MODELS_TITLE.format(mpn=_TI.mpn), 7)],
    )
    path = tmp_path / "Models.json"
    models_history.learn_models_ids_from_history([_TI], store=DigiKeyModelsIds(path))

    assert DigiKeyModelsIds(path).get(manufacturer=_TI.manufacturer, mpn=_TI.mpn) == "6695662"


def test_f_every_supported_chromium_browser_is_discovered_and_missing_ones_are_skipped(
    local_app_data,
):
    layouts = {
        "vivaldi": local_app_data / "Vivaldi" / "User Data" / "Default" / "History",
        "chrome": local_app_data / "Google" / "Chrome" / "User Data" / "Default" / "History",
        "edge": local_app_data / "Microsoft" / "Edge" / "User Data" / "Default" / "History",
        "brave": (
            local_app_data
            / "BraveSoftware"
            / "Brave-Browser"
            / "User Data"
            / "Default"
            / "History"
        ),
    }
    assert models_history.chromium_history_databases() == ()

    for path in layouts.values():
        _chromium_history(path, [])
    # A second profile in one browser is found too; a profile with no History file is not.
    second = local_app_data / "Vivaldi" / "User Data" / "Profile 3" / "History"
    _chromium_history(second, [])
    (local_app_data / "Vivaldi" / "User Data" / "Profile 9").mkdir(parents=True)

    found = models_history.chromium_history_databases()
    assert {entry.path for entry in found} == {*layouts.values(), second}
    assert {entry.browser for entry in found} == {"vivaldi", "chrome", "edge", "brave"}


# -- reading only what is needed ------------------------------------------------------------------


def test_g_a_url_that_is_not_a_digikey_models_page_is_never_a_candidate(
    tmp_path, local_app_data, enabled
):
    _vivaldi(
        local_app_data,
        [
            # DigiKey, but a search and a product page - neither is a models page.
            (
                "https://www.digikey.com/en/products/result?keywords=TPS2121RUXR",
                _MODELS_TITLE.format(mpn=_TI.mpn),
                9,
            ),
            (
                "https://www.digikey.com/en/products/detail/texas-instruments/TPS2121RUXR/1",
                _MODELS_TITLE.format(mpn=_TI.mpn),
                9,
            ),
            # A look-alike host, a traversal, and a non-numeric id all fail closed.
            ("https://www.digikey.com.evil.invalid/en/models/1", "x EDA | Digikey", 9),
            ("https://www.digikey.com/en/models/../../etc", "x EDA | Digikey", 9),
            ("https://www.digikey.com/en/models/abc", "x EDA | Digikey", 9),
            ("https://www.digikey.com/en/models/0", "x EDA | Digikey", 9),
        ],
    )
    store = _store(tmp_path)

    outcome = models_history.learn_models_ids_from_history([_TI], store=store)

    assert outcome.candidates == 0
    assert outcome.learned == 0
    assert store.get(manufacturer=_TI.manufacturer, mpn=_TI.mpn) == ""


def test_h_no_non_digikey_history_row_is_ever_surfaced(tmp_path, local_app_data, enabled):
    """Not returned, not counted, not traced. The SQL is the filter, so it is never even read."""

    _vivaldi(
        local_app_data,
        [
            ("https://www.digikey.com/en/models/6695662", _MODELS_TITLE.format(mpn=_TI.mpn), 9),
            ("https://mail.example.invalid/inbox/17", "Private Mail", 9),
        ],
    )

    visits = models_history.read_models_page_visits(
        models_history.chromium_history_databases()[0].path
    )

    assert [visit.models_id for visit in visits] == ["6695662"]
    rendered = repr(visits)
    for secret in ("example-bank", "example.invalid", _PRIVATE_TITLE, "Private Mail"):
        assert secret not in rendered


def test_i_the_trace_names_counts_and_never_a_foreign_url_or_title(
    tmp_path, local_app_data, enabled, trace_file
):
    _vivaldi(
        local_app_data,
        [
            ("https://www.digikey.com/en/models/6695662", _MODELS_TITLE.format(mpn=_TI.mpn), 9),
            ("https://intranet.example.invalid/hr/salary-review", "Salary Review 2026", 9),
        ],
    )
    models_history.learn_models_ids_from_history([_TI], store=_store(tmp_path))

    text = _log_text(trace_file)
    assert "models-history" in text
    assert "candidates=1" in text
    assert "learned=1" in text
    for secret in (
        _PRIVATE_URL,
        _PRIVATE_TITLE,
        "example-bank",
        "intranet",
        "Salary",
        "salary-review",
    ):
        assert secret not in text


# -- the live database is never opened ------------------------------------------------------------


def test_j_the_live_database_is_copied_and_never_opened_in_place(
    tmp_path, local_app_data, enabled, monkeypatch
):
    """The file is locked while the browser runs, and it is the person's data either way."""

    live = _vivaldi(
        local_app_data,
        [("https://www.digikey.com/en/models/6695662", _MODELS_TITLE.format(mpn=_TI.mpn), 9)],
    )
    before = live.read_bytes()
    opened: list[str] = []
    real_connect = sqlite3.connect

    def spy(database, *args, **kwargs):
        opened.append(str(database))
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(models_history.sqlite3, "connect", spy)

    outcome = models_history.learn_models_ids_from_history([_TI], store=_store(tmp_path))

    assert outcome.learned == 1
    assert opened, "the reader never opened anything at all"
    for target in opened:
        # The live path is never handed to sqlite in any form - bare, URI, or resolved.
        assert str(live) not in target
        assert live.as_posix() not in target
        assert Path(target.split("?")[0].removeprefix("file:")).resolve() != live.resolve()
        # Read-only, so even the copy cannot be written through.
        assert "mode=ro" in target
    # Untouched, byte for byte, and no stray sidecar left beside it.
    assert live.read_bytes() == before
    assert sorted(entry.name for entry in live.parent.iterdir()) == ["History"]


def test_k_the_temporary_copy_does_not_outlive_the_read(
    tmp_path, local_app_data, enabled, monkeypatch
):
    """The copy is the person's browsing history. It is deleted whether the read worked or not."""

    import shutil
    import tempfile

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    copies: list[Path] = []
    real_copyfile = shutil.copyfile

    def spy(source, destination, *args, **kwargs):
        copies.append(Path(destination))
        return real_copyfile(source, destination, *args, **kwargs)

    monkeypatch.setattr(models_history.shutil, "copyfile", spy)
    _vivaldi(
        local_app_data,
        [("https://www.digikey.com/en/models/6695662", _MODELS_TITLE.format(mpn=_TI.mpn), 9)],
    )

    outcome = models_history.learn_models_ids_from_history([_TI], store=_store(tmp_path))

    assert outcome.learned == 1
    # The copy really was made, really was under the scratch root, and really is gone.
    assert len(copies) == 1
    assert scratch in copies[0].parents
    assert not copies[0].exists()
    assert list(scratch.iterdir()) == []


# -- binding an id to exactly one part ------------------------------------------------------------


def test_l_the_mpn_comes_from_the_page_title_not_the_url(tmp_path, local_app_data, enabled):
    """The models URL carries an opaque id and no part number, so the title is the only source."""

    assert models_history.mpn_from_models_title(_MODELS_TITLE.format(mpn=_TI.mpn)) == _TI.mpn
    assert (
        models_history.mpn_from_models_title(
            "ABM13W-32.0000MHZ-5-DH7G-T5 EDA | CAD 3D Model Download | Digikey"
        )
        == "ABM13W-32.0000MHZ-5-DH7G-T5"
    )
    # Whitespace, the trailing marker words, and a missing separator.
    assert models_history.mpn_from_models_title("  TPS2121RUXR  EDA | Digikey ") == "TPS2121RUXR"
    assert models_history.mpn_from_models_title("TPS2121RUXR EDA & CAD Models | DigiKey") == (
        "TPS2121RUXR"
    )
    assert models_history.mpn_from_models_title("TPS2121RUXR") == "TPS2121RUXR"
    # Nothing identifiable.
    assert models_history.mpn_from_models_title("") == ""
    assert models_history.mpn_from_models_title("| CAD 3D Model Download | Digikey") == ""
    assert models_history.mpn_from_models_title("EDA | Digikey") == ""
    assert models_history.mpn_from_models_title(None) == ""
    assert models_history.mpn_from_models_title("Z" * 400) == ""


def test_m_an_mpn_matching_two_library_parts_is_skipped_and_said_so(
    tmp_path, local_app_data, enabled, trace_file
):
    """History gives no manufacturer, and the store keys on one. Ambiguity must fail closed."""

    alpha = _Part(manufacturer="Alpha Components", mpn="SHARED-1234")
    beta = _Part(manufacturer="Beta Devices", mpn="SHARED-1234")
    _vivaldi(
        local_app_data,
        [("https://www.digikey.com/en/models/4242424", _MODELS_TITLE.format(mpn="SHARED-1234"), 9)],
    )
    store = _store(tmp_path)

    outcome = models_history.learn_models_ids_from_history([alpha, beta], store=store)

    assert outcome.candidates == 1
    assert outcome.resolved == 0
    assert outcome.learned == 0
    assert outcome.skipped_ambiguous_mpn == 1
    assert store.get(manufacturer=alpha.manufacturer, mpn=alpha.mpn) == ""
    assert store.get(manufacturer=beta.manufacturer, mpn=beta.mpn) == ""
    text = _log_text(trace_file)
    assert "skipped_ambiguous_mpn=1" in text
    assert "SHARED-1234" in text


def test_n_two_records_of_the_same_part_are_not_ambiguous(tmp_path, local_app_data, enabled):
    """Same manufacturer AND same MPN is ONE identity, whatever the record count."""

    _vivaldi(
        local_app_data,
        [("https://www.digikey.com/en/models/6695662", _MODELS_TITLE.format(mpn=_TI.mpn), 9)],
    )
    store = _store(tmp_path)

    outcome = models_history.learn_models_ids_from_history([_TI, _TI], store=store)

    assert outcome.learned == 1
    assert store.get(manufacturer=_TI.manufacturer, mpn=_TI.mpn) == "6695662"


def test_o_an_mpn_in_no_library_part_is_counted_but_never_named(
    tmp_path, local_app_data, enabled, trace_file
):
    """A models page for a part the owner does not own is still their private browsing."""

    _vivaldi(
        local_app_data,
        [
            (
                "https://www.digikey.com/en/models/9999999",
                _MODELS_TITLE.format(mpn="NOT-IN-LIBRARY-9"),
                9,
            )
        ],
    )

    outcome = models_history.learn_models_ids_from_history([_TI], store=_store(tmp_path))

    assert outcome.candidates == 1
    assert outcome.resolved == 0
    assert outcome.skipped_unknown_mpn == 1
    text = _log_text(trace_file)
    assert "skipped_unknown_mpn=1" in text
    assert "NOT-IN-LIBRARY-9" not in text


def test_p_the_shared_mpn_comparison_tolerates_the_separators_a_slug_destroyed(
    tmp_path, local_app_data, enabled
):
    """`identity.same_mpn` is the ONE comparison; a title's lost separator must not lose a part."""

    assert same_mpn("ABM13W-32-0000MHZ-5-DH7G-T5", _ABRACON.mpn) is True
    assert same_mpn("ABC-1", "ABC1") is False
    assert same_mpn("ABC-1", "ABC-2") is False

    _vivaldi(
        local_app_data,
        [
            (
                "https://www.digikey.com/en/models/1234567",
                _MODELS_TITLE.format(mpn="ABM13W-32-0000MHZ-5-DH7G-T5"),
                9,
            )
        ],
    )
    store = _store(tmp_path)

    outcome = models_history.learn_models_ids_from_history([_ABRACON], store=store)

    assert outcome.learned == 1
    # Stored under the LIBRARY's own spelling, which is what every reader looks it up by.
    assert store.get(manufacturer=_ABRACON.manufacturer, mpn=_ABRACON.mpn) == "1234567"


def test_q_a_title_that_yields_no_mpn_is_skipped(tmp_path, local_app_data, enabled):
    _vivaldi(
        local_app_data,
        [("https://www.digikey.com/en/models/6695662", "", 9)],
    )
    store = _store(tmp_path)

    outcome = models_history.learn_models_ids_from_history([_TI], store=store)

    assert outcome.candidates == 1
    assert outcome.skipped_no_mpn == 1
    assert outcome.learned == 0


# -- newest wins ---------------------------------------------------------------------------------


@pytest.mark.parametrize("reverse", [False, True])
def test_r_the_newest_visit_wins_when_a_part_has_several(
    tmp_path, local_app_data, enabled, reverse
):
    rows = [
        ("https://www.digikey.com/en/models/1111111", _MODELS_TITLE.format(mpn=_TI.mpn), 100),
        (
            "https://www.digikey.com/en/models/2222222",
            _MODELS_TITLE.format(mpn=_TI.mpn) + " ",
            13_390_000_000_000_000,
        ),
    ]
    _vivaldi(local_app_data, list(reversed(rows)) if reverse else rows)
    store = _store(tmp_path)

    outcome = models_history.learn_models_ids_from_history([_TI], store=store)

    assert outcome.candidates == 2
    assert outcome.learned == 1
    assert store.get(manufacturer=_TI.manufacturer, mpn=_TI.mpn) == "2222222"


def test_s_the_newest_visit_wins_across_two_browsers(tmp_path, local_app_data, enabled):
    _vivaldi(
        local_app_data,
        [("https://www.digikey.com/en/models/1111111", _MODELS_TITLE.format(mpn=_TI.mpn), 100)],
    )
    _chromium_history(
        local_app_data / "Google" / "Chrome" / "User Data" / "Default" / "History",
        [
            (
                "https://www.digikey.com/en/models/3333333",
                _MODELS_TITLE.format(mpn=_TI.mpn),
                13_390_000_000_000_000,
            )
        ],
    )
    store = _store(tmp_path)

    outcome = models_history.learn_models_ids_from_history([_TI], store=store)

    assert outcome.databases == 2
    assert store.get(manufacturer=_TI.manufacturer, mpn=_TI.mpn) == "3333333"


# -- every failure degrades to today's behaviour ------------------------------------------------


def test_t_an_absent_database_learns_nothing_and_raises_nothing(tmp_path, local_app_data, enabled):
    outcome = models_history.learn_models_ids_from_history([_TI], store=_store(tmp_path))

    assert outcome.enabled is True
    assert outcome.databases == 0
    assert outcome.candidates == 0
    assert outcome.learned == 0


def test_u_a_corrupt_database_degrades_silently(tmp_path, local_app_data, enabled):
    path = local_app_data / "Vivaldi" / "User Data" / "Default" / "History"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"this is not a sqlite database at all" * 40)

    outcome = models_history.learn_models_ids_from_history([_TI], store=_store(tmp_path))

    assert outcome.databases == 1
    assert outcome.candidates == 0
    assert outcome.learned == 0


def test_v_a_schema_shifted_database_degrades_silently(tmp_path, local_app_data, enabled):
    path = local_app_data / "Vivaldi" / "User Data" / "Default" / "History"
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE visits(id INTEGER PRIMARY KEY, place INTEGER)")
        connection.commit()
    finally:
        connection.close()

    outcome = models_history.learn_models_ids_from_history([_TI], store=_store(tmp_path))

    assert outcome.databases == 1
    assert outcome.candidates == 0
    assert outcome.learned == 0


def test_w_an_uncopyable_database_degrades_silently(tmp_path, local_app_data, enabled):
    """A directory where the file should be stands in for every copy failure, lock included."""

    (local_app_data / "Vivaldi" / "User Data" / "Default" / "History").mkdir(parents=True)

    outcome = models_history.learn_models_ids_from_history([_TI], store=_store(tmp_path))

    assert outcome.learned == 0
    assert outcome.candidates == 0


def test_x_a_store_that_cannot_be_written_never_fails_the_read(
    tmp_path, local_app_data, enabled, monkeypatch
):
    _vivaldi(
        local_app_data,
        [("https://www.digikey.com/en/models/6695662", _MODELS_TITLE.format(mpn=_TI.mpn), 9)],
    )
    store = _store(tmp_path)
    monkeypatch.setattr(
        type(store), "learn", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("full disk"))
    )

    outcome = models_history.learn_models_ids_from_history([_TI], store=store)

    assert outcome.learned == 0
    assert outcome.candidates == 1


def test_y_a_broken_part_record_never_stops_the_others(tmp_path, local_app_data, enabled):
    class _Exploding:
        @property
        def mpn(self):
            raise RuntimeError("unreadable record")

        manufacturer = "Nobody"

    _vivaldi(
        local_app_data,
        [("https://www.digikey.com/en/models/6695662", _MODELS_TITLE.format(mpn=_TI.mpn), 9)],
    )
    store = _store(tmp_path)

    outcome = models_history.learn_models_ids_from_history([_Exploding(), _TI], store=store)

    assert store.get(manufacturer=_TI.manufacturer, mpn=_TI.mpn) == "6695662"
    assert outcome.learned == 1


# -- the capture-run entry point -----------------------------------------------------------------


def _ctx(tmp_path: Path, records: list[_Part], config: object = None):
    from types import SimpleNamespace

    parts_dir = tmp_path / "parts"
    parts_dir.mkdir(exist_ok=True)
    by_id = {}
    for index, record in enumerate(records):
        part_id = f"part-{index}"
        (parts_dir / f"{part_id}.json").write_text("{}\n", encoding="utf-8")
        by_id[part_id] = record
    return SimpleNamespace(
        config=config,
        profile=SimpleNamespace(library=SimpleNamespace(parts_dir=parts_dir)),
        ops=SimpleNamespace(load_record=lambda part_id: by_id[part_id]),
    )


def test_z1_the_run_entry_point_binds_ids_over_the_library_on_disk(
    tmp_path, local_app_data, enabled
):
    _vivaldi(
        local_app_data,
        [("https://www.digikey.com/en/models/6695662", _MODELS_TITLE.format(mpn=_TI.mpn), 9)],
    )
    store = _store(tmp_path)

    outcome = models_history.learn_models_ids_for_library(
        _ctx(tmp_path, [_ABRACON, _TI]), store=store
    )

    assert outcome.learned == 1
    assert store.get(manufacturer=_TI.manufacturer, mpn=_TI.mpn) == "6695662"


def test_z2_the_run_entry_point_reads_nothing_when_the_feature_is_off(tmp_path, local_app_data):
    _vivaldi(
        local_app_data,
        [("https://www.digikey.com/en/models/6695662", _MODELS_TITLE.format(mpn=_TI.mpn), 9)],
    )
    store = _store(tmp_path)

    outcome = models_history.learn_models_ids_for_library(_ctx(tmp_path, [_TI]), store=store)

    assert outcome.enabled is False
    assert outcome.databases == 0
    assert store.get(manufacturer=_TI.manufacturer, mpn=_TI.mpn) == ""


def test_z3_the_run_entry_point_survives_an_unusable_context(tmp_path, local_app_data, enabled):
    from types import SimpleNamespace

    for broken in (None, object(), SimpleNamespace(profile=None)):
        outcome = models_history.learn_models_ids_for_library(broken, store=_store(tmp_path))
        assert outcome.learned == 0


def test_z4_a_corrupt_part_record_never_stops_the_library_pass(
    tmp_path, local_app_data, enabled
):
    from types import SimpleNamespace

    parts_dir = tmp_path / "parts"
    parts_dir.mkdir()
    for name in ("good.json", "broken.json"):
        (parts_dir / name).write_text("{}\n", encoding="utf-8")

    def load_record(part_id):
        if part_id == "broken":
            raise ValueError("unreadable record")
        return _TI

    _vivaldi(
        local_app_data,
        [("https://www.digikey.com/en/models/6695662", _MODELS_TITLE.format(mpn=_TI.mpn), 9)],
    )
    store = _store(tmp_path)
    ctx = SimpleNamespace(
        config=None,
        profile=SimpleNamespace(library=SimpleNamespace(parts_dir=parts_dir)),
        ops=SimpleNamespace(load_record=load_record),
    )

    assert models_history.learn_models_ids_for_library(ctx, store=store).learned == 1
    assert store.get(manufacturer=_TI.manufacturer, mpn=_TI.mpn) == "6695662"


def test_z_the_reader_never_raises_whatever_the_environment_does(tmp_path, monkeypatch):
    """The whole feature is an optimisation. It may never fail a capture."""

    monkeypatch.setenv(models_history.MODELS_HISTORY_OPT_IN, "1")
    monkeypatch.setattr(
        models_history,
        "chromium_history_databases",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    outcome = models_history.learn_models_ids_from_history([_TI], store=_store(tmp_path))

    assert outcome.learned == 0
    assert outcome.signal == "unreadable"
