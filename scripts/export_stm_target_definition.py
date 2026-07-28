"""Compile a generic STM target-definition request to deterministic JSON.

The browser can download the same artifact through ``/api/stm/target-definition``.
This command is the non-interactive adapter for downstream build systems:

    .venv/Scripts/python.exe scripts/export_stm_target_definition.py \
        request.json --out target-definition.json

The request is JSON with ``format: stm-target-request/1``, a ``selection``
(``parts`` or ``package`` + ``families``), and a caller-owned ``policy``.
No downstream project conventions are embedded here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "app" / "backend"))

from stockroom.stm.db import StmIndex  # noqa: E402
from stockroom.stm.seed import restore_baked_index  # noqa: E402
from stockroom.stm.source import default_index_path  # noqa: E402
from stockroom.stm.target_definition import (  # noqa: E402
    compile_target_definition,
    resolve_target_refs,
)

REQUEST_FORMAT = "stm-target-request/1"


def _read_request(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read target-definition request {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("target-definition request must be a JSON object")
    if value.get("format") != REQUEST_FORMAT:
        raise ValueError(f"target-definition request format must be {REQUEST_FORMAT}")
    if not isinstance(value.get("selection"), dict):
        raise ValueError("target-definition request needs a selection object")
    if not isinstance(value.get("policy"), dict):
        raise ValueError("target-definition request needs a policy object")
    return value


def _write_atomic(path: Path, artifact: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-target-definition")
    try:
        temp.write_text(
            json.dumps(artifact, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compile a generic STM target-definition request."
    )
    parser.add_argument("request", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--index", type=Path)
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="return nonzero after writing when the compiled definition is blocked",
    )
    args = parser.parse_args(argv)

    scratch: tempfile.TemporaryDirectory[str] | None = None
    index_path = args.index or default_index_path()
    index = StmIndex.load(index_path)
    if index is None and args.index is None:
        scratch = tempfile.TemporaryDirectory(prefix="stockroom-stm-target-")
        restored = Path(scratch.name) / "index.sqlite"
        if restore_baked_index(restored):
            index = StmIndex.load(restored)
            index_path = restored
    if index is None:
        if scratch is not None:
            scratch.cleanup()
        print(f"FAIL: no stamp-valid STM index at {index_path}", file=sys.stderr)
        return 2

    try:
        request = _read_request(args.request)
        refs = resolve_target_refs(index.conn, request["selection"])
        artifact = compile_target_definition(
            index.conn,
            refs=refs,
            policy=request["policy"],
            source_meta=index.meta(),
        )
        _write_atomic(args.out, artifact)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    finally:
        index.close()
        if scratch is not None:
            scratch.cleanup()

    status = artifact["readiness"]["status"]
    print(
        f"wrote {args.out} - {artifact['scope']['target_count']} targets, "
        f"{artifact['scope']['package']}, {status}, "
        f"digest {artifact['artifact_digest'][:12]}"
    )
    if args.require_ready and status != "ready":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
