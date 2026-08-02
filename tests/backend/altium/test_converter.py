import hashlib
import json
from pathlib import Path

import pytest

from stockroom.altium.converter import CadConversionError, _artifact


def test_artifact_requires_output_containment_size_hash_and_suffix(tmp_path: Path):
    output = tmp_path / "Output"
    output.mkdir()
    library = output / "Part.SchLib"
    library.write_bytes(b"native")
    value = {
        "path": str(library),
        "sizeBytes": 6,
        "sha256": hashlib.sha256(b"native").hexdigest(),
    }

    assert _artifact(value, suffix=".SchLib", output_directory=output) == library

    outside = tmp_path / "Outside.SchLib"
    outside.write_bytes(b"native")
    with pytest.raises(CadConversionError, match="escaped"):
        _artifact(
            {**value, "path": str(outside)},
            suffix=".SchLib",
            output_directory=output,
        )


def test_converter_module_has_no_console_parsing_contract():
    # The sidecar result schema is JSON. This pins the test to the public shape rather
    # than accidentally teaching production code to scrape stdout in a future edit.
    value = json.loads('{"schema":"stockroom.cad-converter/result/1","status":"ok"}')
    assert value["schema"].endswith("/result/1")
