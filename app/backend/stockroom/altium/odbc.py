"""Whether this machine can read the Altium DbLib's SQLite data source, and where to get the
driver if not. Altium reaches the committed stockroom-parts.db through the SQLite3 ODBC driver via
the OLE DB -> ODBC bridge (see dblib.py). That driver is a small one-time Windows install, so the
app probes for it and offers the official 64-bit installer.

Qt-free (imports nothing from PyQt/pywebview), so it is safe under stockroom.api. The Windows
registry read mirrors launcher.launch.webview2_installed: lazy `winreg`, the 64-bit HKLM view, an
OSError meaning "not registered". It is factored behind an injectable opener so both branches are
unit-testable off Windows, where `winreg` does not exist."""
from __future__ import annotations

import os
from typing import Callable, ContextManager

# The exact driver name the DbLib connection string binds to (dblib.py imports this, so the probe
# and the emitted string can never name two different drivers).
SQLITE3_ODBC_DRIVER = "SQLite3 ODBC Driver"

# The official 64-bit installer (Christian Werner's SQLite ODBC page). The app opens this in the
# default browser; the same file is also staged locally during winverify.
ODBC_DOWNLOAD_URL = "http://www.ch-werner.de/sqliteodbc/sqliteodbc_w64.exe"

# HKLM subkey the ODBC installer writes for a registered 64-bit driver.
_ODBCINST_KEY = rf"SOFTWARE\ODBC\ODBCINST.INI\{SQLITE3_ODBC_DRIVER}"


def _registry_has_driver(open_key: Callable[[], ContextManager]) -> bool:
    """True iff `open_key()` can open the driver's registry key. `open_key` is a zero-arg callable
    returning a context manager (winreg.OpenKey's handle is one) and raising OSError when the key is
    absent; injected so the registry read is testable without a real registry."""
    try:
        with open_key():
            return True
    except OSError:
        return False


def driver_installed() -> bool | None:
    """Whether the 64-bit SQLite3 ODBC driver is registered. True/False on Windows (reading the
    64-bit HKLM ODBCINST view); None on any non-Windows host, where the answer honestly cannot be
    determined rather than guessed."""
    if os.name != "nt":
        return None
    try:
        import winreg  # Windows-only, imported lazily
    except ImportError:  # pragma: no cover - non-Windows
        return None

    def _open() -> ContextManager:  # pragma: no cover - real Windows registry read
        return winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            _ODBCINST_KEY,
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        )

    return _registry_has_driver(_open)


def odbc_status() -> dict:
    """The full probe payload the API returns: whether the driver is installed (bool | None), its
    name, and where to download it."""
    return {
        "installed": driver_installed(),
        "driver": SQLITE3_ODBC_DRIVER,
        "download_url": ODBC_DOWNLOAD_URL,
    }
