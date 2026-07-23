"""The SQLite3 ODBC driver probe (stockroom.altium.odbc). Altium's DbLib reads the committed
SQLite data source through this 64-bit driver, so the app reports whether it is registered and
offers the official installer. The Windows registry read is factored behind an injectable opener
so both the present/absent branches are unit-testable off Windows."""
from __future__ import annotations

import contextlib
import os

import pytest


def test_constants_name_the_driver_and_official_64bit_installer():
    from stockroom.altium import odbc

    # The driver name must match the one the DbLib connection string binds to, verbatim.
    assert odbc.SQLITE3_ODBC_DRIVER == "SQLite3 ODBC Driver"
    # The download points at the ch-werner 64-bit installer the app runs in a WebView2.
    assert odbc.ODBC_DOWNLOAD_URL.endswith("sqliteodbc_w64.exe")
    assert odbc.ODBC_DOWNLOAD_URL.startswith("http")


@pytest.mark.skipif(os.name == "nt", reason="off-Windows path: no ODBC registry to read")
def test_driver_installed_is_none_off_windows():
    # Honest: on any non-Windows host the driver cannot be checked, so the answer is null,
    # never a fabricated True/False.
    from stockroom.altium.odbc import driver_installed

    assert driver_installed() is None


def test_registry_probe_is_true_when_the_key_opens():
    # The injected opener stands in for winreg.OpenKey: a driver that IS registered returns a
    # handle (here a no-op context manager), so the probe reports present.
    from stockroom.altium.odbc import _registry_has_driver

    assert _registry_has_driver(lambda: contextlib.nullcontext()) is True


def test_registry_probe_is_false_when_the_key_is_missing():
    # winreg.OpenKey raises OSError (FileNotFoundError is one) when the key is absent; the probe
    # must translate that to a plain False, not let it escape.
    from stockroom.altium.odbc import _registry_has_driver

    def _missing():
        raise FileNotFoundError("no such registry key")

    assert _registry_has_driver(_missing) is False
