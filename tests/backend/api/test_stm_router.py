"""Phase 3 (stm-viewer workstream), 03-01: the thinnest end-to-end slice of the Qt-free STM
service - GET /api/stm/status and GET /api/stm/mcus through AppContext.stm_index, with the
not-built 409 gate. Later plans (03-02/03-03/03-04) extend this same file as the router grows."""

from __future__ import annotations

import sqlite3

import pytest

from stockroom.stm.db import _SCHEMA, StmIndex


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

    _insert_mcu(
        "STM32F407V(E-G)Tx", "STM32F4", "STM32F407", "LQFP64", 64, "Cortex-M4",
        1024, 192, 168, 51,
        [("USART", "USART1", "1"), ("USART", "USART2", "1"), ("SPI", "SPI1", "1")],
    )
    _insert_mcu(
        "STM32F103C(8-B)Tx", "STM32F1", "STM32F103", "LQFP48", 48, "Cortex-M3",
        128, 20, 72, 37,
        [("USART", "USART1", "1")],
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
    assert body["mcu_count"] == 2
    assert body["classifier_rev"] == 1
    assert body["af_schema_rev"] == 1
    assert body["geometry_rev"] == 3
    assert body["source_sha256"] == "deadbeef"
    assert body["built_at"] == "2026-07-23T00:00:00Z"
    assert body["all_families"] is True
    assert body["device_xml_count"] == 2
    assert body["family_count"] == 2
    assert set(body["families"]) == {"STM32F4", "STM32F1"}


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
    assert body["count"] == 2
    assert len(body["mcus"]) == 2

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
    assert set(facets["family"]) == {"STM32F4", "STM32F1"}
    assert set(facets["core"]) == {"Cortex-M4", "Cortex-M3"}
    assert set(facets["package"]) == {"LQFP64", "LQFP48"}
    assert set(facets["series"]) == {"STM32F4", "STM32F1"}


def test_mcus_filtered_by_family_keeps_full_facets(client, app_ctx):
    _seed_stm_index(app_ctx)
    r = client.get("/api/stm/mcus", params={"family": "STM32F4"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["mcus"][0]["series"] == "STM32F4"
    # facet counts reflect the FULL unfiltered set for the other facet dimensions
    assert set(body["facets"]["package"]) == {"LQFP64", "LQFP48"}
    assert set(body["facets"]["core"]) == {"Cortex-M4", "Cortex-M3"}
