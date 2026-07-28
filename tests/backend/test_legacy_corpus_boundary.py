from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_HARNESS = REPOSITORY_ROOT / "scripts" / "s8_cold_rebuild.py"


def test_historical_corpus_cannot_become_an_implicit_intake_source() -> None:
    source = HISTORICAL_HARNESS.read_text(encoding="utf-8")

    assert "stockroom-winverify" not in source
    assert "DEFAULT_CORPUS" not in source

    result = subprocess.run(
        [sys.executable, str(HISTORICAL_HARNESS), "--sample", "1"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "--corpus" in result.stderr
    assert "required" in result.stderr.casefold()
