"""Phase 3 (stm-viewer workstream), 03-01: the thinnest end-to-end slice of the Qt-free STM
service - GET /api/stm/status and GET /api/stm/mcus through AppContext.stm_index, with the
not-built 409 gate. Later plans (03-02/03-03/03-04) extend this same file as the router grows."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from stockroom.stm.db import _SCHEMA, StmIndex
from tests.backend.api.conftest import _drain_job


def _seed_stm_index(app_ctx) -> StmIndex:
    """A tiny hand-built Layer A index: two MCUs in different families/packages, each with an
    mcu_spec row and a couple of mcu_peripheral rows, stamped like a real build. Assigned onto
    app_ctx.stm_index directly (StmIndex(conn)) rather than through StmIndex.load, so the test
    never touches a real CubeMX source tree."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)

    art_id = conn.execute(
        "INSERT INTO source_artifact (path, imported_at) VALUES (?,?)",
        ("/fixture/cubemx", "2026-07-23T00:00:00Z"),
    ).lastrowid

    def _insert_mcu(
        ref_name, family, line, package, pin_count, core, flash_kb, ram_kb,
        max_freq_mhz, io_count, peripherals,
    ) -> int:
        mcu_id = conn.execute(
            "INSERT INTO mcu (source_artifact_id, ref_name, family, line, package_name, "
            "pin_count, vdd_min, vdd_max, imported_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (art_id, ref_name, family, line, package, pin_count, "1.8", "3.6",
             "2026-07-23T00:00:00Z"),
        ).lastrowid
        conn.execute(
            "INSERT INTO mcu_spec (mcu_id, core, flash_kb, ram_kb, ccm_ram_kb, max_freq_mhz, "
            "io_count, vdd_min, vdd_max, temp_min_c, temp_max_c, current_run_ua, "
            "current_lowest_ua, die) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (mcu_id, core, flash_kb, ram_kb, None, max_freq_mhz, io_count, 1.8, 3.6,
             -40, 85, None, None, None),
        )
        for name, instance, version in peripherals:
            conn.execute(
                "INSERT INTO mcu_peripheral (mcu_id, peripheral_name, instance_name, version) "
                "VALUES (?,?,?,?)",
                (mcu_id, name, instance, version),
            )
        return mcu_id

    mcu1_id = _insert_mcu(
        "STM32F407V(E-G)Tx", "STM32F4", "STM32F407", "LQFP64", 64, "Cortex-M4",
        1024, 192, 168, 51,
        [("USART", "USART1", "1"), ("USART", "USART2", "1"), ("SPI", "SPI1", "1")],
    )
    _insert_mcu(
        "STM32F103C(8-B)Tx", "STM32F1", "STM32F103", "LQFP48", 48, "Cortex-M3",
        128, 20, 72, 37,
        [("USART", "USART1", "1")],
    )

    def _insert_pin(
        mcu_id, package, position, canonical, raw, pin_type, electrical_class,
        roles=(), functions=(), afs=(), lqfp_side="left",
    ) -> int:
        pin_id = conn.execute(
            "INSERT INTO mcu_package_pin (mcu_id, package_name, physical_pin_number, "
            "position_kind, bga_row, bga_col, canonical_pin_name, raw_pin_name, pin_type, "
            "electrical_class, gpio_port, gpio_pin_index, lqfp_side) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (mcu_id, package, position, "numeric", None, None, canonical, raw, pin_type,
             electrical_class, None, None, lqfp_side),
        ).lastrowid
        for role_name, role_class in roles:
            conn.execute(
                "INSERT INTO pin_role (mcu_package_pin_id, role_name, role_class) "
                "VALUES (?,?,?)",
                (pin_id, role_name, role_class),
            )
        for signal, io_modes in functions:
            conn.execute(
                "INSERT INTO pin_function (mcu_package_pin_id, function_name, signal, "
                "io_modes) VALUES (?,?,?,?)",
                (pin_id, signal, signal, io_modes),
            )
        for af_index, signal, peripheral in afs:
            conn.execute(
                "INSERT INTO pin_alternate_function (mcu_package_pin_id, af_index, signal, "
                "peripheral) VALUES (?,?,?,?)",
                (pin_id, af_index, signal, peripheral),
            )
        return pin_id

    # MCU1 (STM32F407V(E-G)Tx) pins, for the 03-04 pinout/pin/AF/signal-candidates tests:
    _insert_pin(
        mcu1_id, "LQFP64", "1", "VDD", "VDD", "Power", "power",
        roles=[("power_vdd", "power")],
    )
    _insert_pin(
        mcu1_id, "LQFP64", "12", "PA9", "PA9", "I/O", "io",
        roles=[("gpio", "io")],
        functions=[("USART1_TX", "In/Out")],
        afs=[(7, "USART1_TX", "USART1")],
    )
    _insert_pin(
        mcu1_id, "LQFP64", "13", "PA10", "PA10", "I/O", "io",
        roles=[("gpio", "io")],
        functions=[("USART1_RX", "In/Out")],
        afs=[(7, "USART1_RX", "USART1")],
    )
    # PB6 ALSO offers USART1_TX via a different AF index - a real remap alternative,
    # giving GET /signal/candidates?signal=USART1_TX two candidate positions.
    _insert_pin(
        mcu1_id, "LQFP64", "34", "PB6", "PB6", "I/O", "io",
        roles=[("gpio", "io")],
        functions=[("I2C1_SCL", "In/Out")],
        afs=[(4, "I2C1_SCL", "I2C1"), (7, "USART1_TX", "USART1")],
    )
    conn.execute(
        "INSERT INTO package_geometry (package_name, body_shape, pin_count, rows, cols, "
        "pitch_mm, body_mm, has_center_pad, depopulation, citation, notes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("LQFP64", "qfp", 64, None, None, 0.5, 10.0, 0, None, "fixture", None),
    )

    # MCU3: a ball-grid package with NO curated package_geometry row, for the
    # inferred-geometry pinout tests (defect: an uncurated BGA must never fall back
    # to a perimeter "qfp" shape the frontend cannot lay out).
    mcu3_id = _insert_mcu(
        "STM32H747X(G-I)Hx", "STM32H7", "STM32H747", "TFBGA240", 240, "Arm Cortex-M7",
        2048, 1024, 480, 168,
        [("USART", "USART1", "1")],
    )
    for position, row, col, canonical, pin_type, ec in (
        ("A1", "A", 1, "VDD", "Power", "power"),
        ("A2", "A", 2, "PA0", "I/O", "io"),
        ("C5", "C", 5, "PB3", "I/O", "io"),
    ):
        conn.execute(
            "INSERT INTO mcu_package_pin (mcu_id, package_name, physical_pin_number, "
            "position_kind, bga_row, bga_col, canonical_pin_name, raw_pin_name, pin_type, "
            "electrical_class, gpio_port, gpio_pin_index, lqfp_side) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (mcu3_id, "TFBGA240", position, "alnum", row, col, canonical, canonical,
             pin_type, ec, None, None, None),
        )

    for key, value in (
        ("classifier_rev", "1"),
        ("af_schema_rev", "1"),
        ("geometry_rev", "3"),
        ("source_sha256", "deadbeef"),
        ("source_file_count", "2"),
        ("source_path", "/fixture/cubemx"),
        ("built_at", "2026-07-23T00:00:00Z"),
        ("all_families", "true"),
        ("device_xml_count", "2"),
        ("family_count", "2"),
    ):
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, value))
    conn.commit()

    app_ctx.stm_index = StmIndex(conn)
    return app_ctx.stm_index


def test_status_reports_unbuilt_when_index_absent(client, app_ctx):
    assert app_ctx.stm_index is None
    r = client.get("/api/stm/status")
    assert r.status_code == 200
    body = r.json()
    assert body["built"] is False
    assert body["building"] is False
    assert body["mcu_count"] == 0
    assert body["source_path"] != ""  # non-empty: configured/default source discovery


def test_status_reports_built_and_echoes_stamp(client, app_ctx):
    _seed_stm_index(app_ctx)
    r = client.get("/api/stm/status")
    assert r.status_code == 200
    body = r.json()
    assert body["built"] is True
    assert body["mcu_count"] == 3
    assert body["classifier_rev"] == 1
    assert body["af_schema_rev"] == 1
    assert body["geometry_rev"] == 3
    assert body["source_sha256"] == "deadbeef"
    assert body["built_at"] == "2026-07-23T00:00:00Z"
    assert body["all_families"] is True
    assert body["device_xml_count"] == 2
    assert body["family_count"] == 2
    assert set(body["families"]) == {"STM32F4", "STM32F1", "STM32H7"}


def test_mcus_returns_409_when_index_absent(client, app_ctx):
    assert app_ctx.stm_index is None
    r = client.get("/api/stm/mcus")
    assert r.status_code == 409
    assert "not built" in r.json()["detail"].lower()


def test_mcus_returns_spec_matrix_rows_and_facets(client, app_ctx):
    _seed_stm_index(app_ctx)
    r = client.get("/api/stm/mcus")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    assert len(body["mcus"]) == 3

    row = next(m for m in body["mcus"] if m["part"] == "STM32F407V(E-G)Tx")
    assert row["series"] == "STM32F4"
    assert row["line"] == "STM32F407"
    assert row["core"] == "Cortex-M4"
    assert row["package"] == "LQFP64"
    assert row["pin_count"] == 64
    assert row["io_count"] == 51
    assert row["flash_kb"] == 1024
    assert row["ram_kb"] == 192
    assert row["max_freq_mhz"] == 168
    assert row["peripherals"]["USART"] == 2
    assert row["peripherals"]["SPI"] == 1
    assert row["mpn_example"]  # a non-empty display expansion of the ref name

    facets = body["facets"]
    assert set(facets["family"]) == {"STM32F4", "STM32F1", "STM32H7"}
    assert set(facets["core"]) == {"Cortex-M4", "Cortex-M3", "Arm Cortex-M7"}
    assert set(facets["package"]) == {"LQFP64", "LQFP48", "TFBGA240"}
    assert set(facets["series"]) == {"STM32F4", "STM32F1", "STM32H7"}


def test_mcus_filtered_by_family_keeps_full_facets(client, app_ctx):
    _seed_stm_index(app_ctx)
    r = client.get("/api/stm/mcus", params={"family": "STM32F4"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["mcus"][0]["series"] == "STM32F4"
    # facet counts reflect the FULL unfiltered set for the other facet dimensions
    assert set(body["facets"]["package"]) == {"LQFP64", "LQFP48", "TFBGA240"}
    assert set(body["facets"]["core"]) == {"Cortex-M4", "Cortex-M3", "Arm Cortex-M7"}


# ─────────────────────────────────────────────────────────────────────────────
# AppContext.rebuild_stm_index (03-03 task 2)
# ─────────────────────────────────────────────────────────────────────────────

_FIXTURE_CUBEMX_SOURCE = Path(__file__).resolve().parent.parent / "fixtures" / "stm"


def test_rebuild_stm_index_builds_a_queryable_index_and_forwards_progress(app_ctx):
    assert app_ctx.stm_index is None
    progress_events = []

    app_ctx.rebuild_stm_index(_FIXTURE_CUBEMX_SOURCE, progress=progress_events.append)

    assert app_ctx.stm_index is not None
    assert app_ctx.stm_index.mcu_count() > 0
    assert progress_events  # at least one progress callback fired


def test_rebuild_stm_index_closes_the_old_index_and_swaps_in_the_new_one(app_ctx):
    app_ctx.rebuild_stm_index(_FIXTURE_CUBEMX_SOURCE)
    first = app_ctx.stm_index
    first_count = first.mcu_count()

    app_ctx.rebuild_stm_index(_FIXTURE_CUBEMX_SOURCE)
    second = app_ctx.stm_index

    assert second is not first
    assert second.mcu_count() == first_count


def test_rebuild_stm_index_propagates_build_errors(app_ctx, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("synthetic build failure")

    monkeypatch.setattr(StmIndex, "build", _boom)
    with pytest.raises(RuntimeError, match="synthetic build failure"):
        app_ctx.rebuild_stm_index(_FIXTURE_CUBEMX_SOURCE)


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/stm/build (03-03 task 3)
# ─────────────────────────────────────────────────────────────────────────────


def test_build_endpoint_runs_to_completion_and_status_reports_built(client, app_ctx):
    app_ctx.config.stm_cubemx_source = str(_FIXTURE_CUBEMX_SOURCE)
    r = client.post("/api/stm/build")
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    out = _drain_job(client, job_id)
    assert out["status"] == "done", out

    status = client.get("/api/stm/status").json()
    assert status["built"] is True
    assert status["mcu_count"] > 0


def test_build_is_single_flight_while_one_is_running(client, app_ctx):
    import threading

    event = threading.Event()
    original_rebuild = app_ctx.rebuild_stm_index

    def _blocking_rebuild(source=None, progress=None):
        event.wait()  # blocks until the test releases it, keeping the job RUNNING
        return original_rebuild(source, progress=progress)

    app_ctx.config.stm_cubemx_source = str(_FIXTURE_CUBEMX_SOURCE)
    app_ctx.rebuild_stm_index = _blocking_rebuild

    r1 = client.post("/api/stm/build")
    assert r1.status_code == 200
    job_a = r1.json()["job_id"]

    # job A is now blocked mid-build on the read lane; a second POST must NOT submit a new job
    r2 = client.post("/api/stm/build")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["job_id"] == job_a
    assert body2["already_running"] is True
    assert len(app_ctx.jobs._jobs) == 1  # only job A was ever created

    event.set()  # release the blocked build so job A can complete
    out = _drain_job(client, job_a)
    assert out["status"] == "done", out


# ─────────────────────────────────────────────────────────────────────────────
# families / pinout / pin (03-04 task 1)
# ─────────────────────────────────────────────────────────────────────────────


def test_families_returns_409_when_index_absent(client, app_ctx):
    assert app_ctx.stm_index is None
    r = client.get("/api/stm/families")
    assert r.status_code == 409


def test_families_returns_family_rollup(client, app_ctx):
    _seed_stm_index(app_ctx)
    r = client.get("/api/stm/families")
    assert r.status_code == 200
    families = {f["family"]: f for f in r.json()["families"]}
    assert families["STM32F4"]["lines"] == ["STM32F407"]
    assert families["STM32F4"]["packages"] == ["LQFP64"]
    assert families["STM32F4"]["mcu_count"] == 1
    assert families["STM32F1"]["mcu_count"] == 1


def test_pinout_returns_409_when_index_absent(client, app_ctx):
    assert app_ctx.stm_index is None
    r = client.get("/api/stm/pinout", params={"part": "STM32F407V(E-G)Tx"})
    assert r.status_code == 409


def test_pinout_404_on_resolve_miss(client, app_ctx):
    _seed_stm_index(app_ctx)
    r = client.get("/api/stm/pinout", params={"part": "NONEXISTENT999"})
    assert r.status_code == 404


def test_pinout_resolves_by_ref_or_mpn_and_inlines_pin_facts(client, app_ctx):
    _seed_stm_index(app_ctx)
    by_ref = client.get("/api/stm/pinout", params={"part": "STM32F407V(E-G)Tx"})
    assert by_ref.status_code == 200
    body = by_ref.json()
    assert body["part"] == "STM32F407V(E-G)Tx"
    assert body["package"] == "LQFP64"
    assert body["geometry"]["body_shape"] == "qfp"
    assert body["geometry"]["pin_count"] == 64

    by_mpn = client.get("/api/stm/pinout", params={"part": "STM32F407VGT6"})
    assert by_mpn.status_code == 200
    assert by_mpn.json()["part"] == "STM32F407V(E-G)Tx"

    pins_by_position = {p["position"]: p for p in body["pins"]}
    assert pins_by_position["12"]["canonical_pin_name"] == "PA9"
    assert pins_by_position["12"]["category"] == "gpio"
    assert pins_by_position["12"]["alternate_functions"] == [
        {"af_index": 7, "signal": "USART1_TX", "peripheral": "USART1"}
    ]
    assert pins_by_position["1"]["electrical_class"] == "power"
    assert pins_by_position["1"]["supply"] == "VDD"

    assert "<svg" not in json.dumps(body).lower()


def test_pinout_geometry_carries_curated_source_for_a_curated_package(client, app_ctx):
    _seed_stm_index(app_ctx)
    r = client.get("/api/stm/pinout", params={"part": "STM32F407V(E-G)Tx"})
    assert r.status_code == 200
    assert r.json()["geometry"]["source"] == "curated"


def test_pinout_geometry_is_inferred_for_an_uncurated_bga_package(client, app_ctx):
    """An uncurated area-array package must resolve to an honest inferred ball-grid
    geometry (body shape from the name + ball evidence, grid span from the real ball
    maxima), never the perimeter-qfp default the map cannot lay out."""
    _seed_stm_index(app_ctx)
    r = client.get("/api/stm/pinout", params={"part": "STM32H747X(G-I)Hx"})
    assert r.status_code == 200
    geometry = r.json()["geometry"]
    assert geometry["source"] == "inferred"
    assert geometry["body_shape"] == "bga"
    assert geometry["rows"] == 3  # rows A..C observed -> row index 2 -> 3 rows
    assert geometry["cols"] == 5  # max observed ball column
    assert geometry["pin_count"] == 3
    assert geometry["pitch_mm"] is None
    assert geometry["has_center_pad"] is False


def test_pin_returns_one_pin_with_every_derived_fact(client, app_ctx):
    _seed_stm_index(app_ctx)
    r = client.get("/api/stm/pin", params={"part": "STM32F407V(E-G)Tx", "position": "12"})
    assert r.status_code == 200
    body = r.json()
    assert body["position"] == "12"
    assert body["canonical_pin_name"] == "PA9"
    assert body["five_v"]["tolerant"] is True
    assert body["roles"] == [{"role_name": "gpio", "role_class": "io"}]


def test_pin_404_when_position_absent(client, app_ctx):
    _seed_stm_index(app_ctx)
    r = client.get(
        "/api/stm/pin", params={"part": "STM32F407V(E-G)Tx", "position": "999"}
    )
    assert r.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# pin/af + signal/candidates (03-04 task 2, SWAP-01/02)
# ─────────────────────────────────────────────────────────────────────────────


def test_pin_af_returns_the_complete_af_set(client, app_ctx):
    _seed_stm_index(app_ctx)
    r = client.get(
        "/api/stm/pin/af", params={"part": "STM32F407V(E-G)Tx", "position": "34"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["position"] == "34"
    signals = {a["signal"] for a in body["alternate_functions"]}
    assert signals == {"I2C1_SCL", "USART1_TX"}


def test_pin_af_404_when_position_absent(client, app_ctx):
    _seed_stm_index(app_ctx)
    r = client.get(
        "/api/stm/pin/af", params={"part": "STM32F407V(E-G)Tx", "position": "999"}
    )
    assert r.status_code == 404


def test_signal_candidates_returns_every_candidate_pin(client, app_ctx):
    _seed_stm_index(app_ctx)
    r = client.get(
        "/api/stm/signal/candidates",
        params={"part": "STM32F407V(E-G)Tx", "signal": "USART1_TX"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["signal"] == "USART1_TX"
    positions = {c["position"] for c in body["candidates"]}
    assert positions == {"12", "34"}


def test_signal_candidates_empty_list_for_unused_signal_not_404(client, app_ctx):
    _seed_stm_index(app_ctx)
    r = client.get(
        "/api/stm/signal/candidates",
        params={"part": "STM32F407V(E-G)Tx", "signal": "NEVER_USED_SIGNAL"},
    )
    assert r.status_code == 200
    assert r.json()["candidates"] == []


# ─────────────────────────────────────────────────────────────────────────────
# compat/union, compat/suggestions, af-check (03-04 task 3)
# ─────────────────────────────────────────────────────────────────────────────


def test_compat_union_returns_shared_and_verdict(client, app_ctx):
    _seed_stm_index(app_ctx)
    r = client.post("/api/stm/compat/union", json={"family": "STM32F4", "package": "LQFP64"})
    assert r.status_code == 200
    body = r.json()
    assert body["package"] == "LQFP64"
    assert body["family"] == "STM32F4"
    assert body["grain"] == "per-part"
    assert "interchangeable" in body["verdict"]


def test_compat_union_mixed_package_scope_is_400(client, app_ctx):
    # F407 is LQFP64, F103 is LQFP48 in this seed: a cross-PACKAGE set stays a 400
    # (a socket is a physical footprint). Cross-FAMILY same-package sets are legal
    # since the 2026-07-23 owner amendment (covered at authority grain in
    # tests/backend/stm/test_authority.py).
    _seed_stm_index(app_ctx)
    r = client.post(
        "/api/stm/compat/union",
        json={"parts": ["STM32F407V(E-G)Tx", "STM32F103C(8-B)Tx"]},
    )
    assert r.status_code == 400


def test_compat_union_accepts_a_families_array_scope(client, app_ctx):
    _seed_stm_index(app_ctx)
    r = client.post(
        "/api/stm/compat/union", json={"families": ["STM32F4"], "package": "LQFP64"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["families"] == ["STM32F4"]
    assert body["family"] == "STM32F4"


def test_compat_suggestions_accepts_a_comma_separated_family_scope(client, app_ctx):
    _seed_stm_index(app_ctx)
    r = client.get(
        "/api/stm/compat/suggestions",
        params={"package": "LQFP64", "family": "STM32F4,STM32F1"},
    )
    assert r.status_code == 200
    groups = r.json()["groups"]
    assert groups and groups[0]["family"] == "STM32F1 + STM32F4"


def test_compat_suggestions_returns_groups(client, app_ctx):
    _seed_stm_index(app_ctx)
    r = client.get(
        "/api/stm/compat/suggestions",
        params={"package": "LQFP64", "family": "STM32F4", "tolerance": 0},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["groups"]) == 1
    assert body["groups"][0]["tier"] == "baseline"
    assert body["groups"][0]["refs"] == ["STM32F407V(E-G)Tx"]


def test_af_check_returns_a_known_conflict(client, app_ctx):
    _seed_stm_index(app_ctx)
    r = client.post(
        "/api/stm/af-check",
        json={
            "part": "STM32F407V(E-G)Tx",
            "assignment": {"12": {"signal": "USART1_TX", "af_index": 99}},
        },
    )
    assert r.status_code == 200
    conflicts = r.json()["conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["kind"] == "unavailable_af"


def test_af_check_conflict_free_returns_empty_list(client, app_ctx):
    _seed_stm_index(app_ctx)
    r = client.post(
        "/api/stm/af-check",
        json={
            "part": "STM32F407V(E-G)Tx",
            "assignment": {"12": {"signal": "USART1_TX", "af_index": 7}},
        },
    )
    assert r.status_code == 200
    assert r.json()["conflicts"] == []


def test_concurrent_stm_reads_share_one_connection_safely(client, app_ctx):
    """The Bench fires suggestions and the socket-union CONCURRENTLY (redesign 2026-07-23).
    Two threadpool handlers on one sqlite connection raised InterfaceError before the
    router's read lock; this drives a mixed burst in parallel and requires every response
    to succeed."""
    import concurrent.futures

    _seed_stm_index(app_ctx)

    def call(kind: str) -> int:
        if kind == "union":
            return client.post(
                "/api/stm/compat/union", json={"family": "STM32F4", "package": "LQFP64"}
            ).status_code
        if kind == "sugg":
            return client.get(
                "/api/stm/compat/suggestions",
                params={"package": "LQFP64", "family": "STM32F4"},
            ).status_code
        return client.get("/api/stm/pinout", params={"part": "STM32F407V(E-G)Tx"}).status_code

    kinds = ["union", "sugg", "pinout"] * 8
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        codes = list(pool.map(call, kinds))
    assert codes == [200] * len(kinds)
