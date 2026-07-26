"""Write the SR_LIB path-substitution variable into kicad_common.json.

This is KiCad's own per-machine config (outside the repo), and KiCad rewrites it
on every run, so a whole-file JSON re-serialize is safe here (unlike the library
files, which are byte-preserved). The writer still takes a timestamped backup
before touching it and re-parses to validate after (spec section 4). Verified:
KiCad ships environment.vars as null; we materialize it to an object.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_env_var(path: Path, name: str) -> str | None:
    """None when the file is absent or unparseable: this is a status probe, and a
    KiCad that has never run simply has no vars yet."""
    try:
        data = _load(Path(path))
    except (OSError, json.JSONDecodeError):
        return None
    vars_ = (data.get("environment") or {}).get("vars") or {}
    return vars_.get(name)


def write_env_var(path: Path, name: str, value: str) -> bool:
    path = Path(path)
    if not path.exists():
        # KiCad installed but never run: materialize a minimal config holding just
        # the var (KiCad merges its own defaults on first run). Nothing existed, so
        # there is nothing to back up. An EXISTING but unparseable file still
        # raises: never clobber a KiCad-owned file we cannot parse.
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(
            {"environment": {"vars": {name: value}}},
            indent=2, sort_keys=True, ensure_ascii=False,
        ) + "\n"
        path.write_text(text, encoding="utf-8")
        json.loads(path.read_text(encoding="utf-8"))  # parse-validate the result
        return True
    data = _load(path)
    env = data.get("environment")
    if not isinstance(env, dict):
        env = {}
        data["environment"] = env
    vars_ = env.get("vars")
    if not isinstance(vars_, dict):
        vars_ = {}
        env["vars"] = vars_
    if vars_.get(name) == value:
        return False  # already correct: no backup, no write
    # timestamped backup before modifying a file Stockroom does not own
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    backup = path.with_name(f"{path.name}.{stamp}.bak")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    vars_[name] = value
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    json.loads(path.read_text(encoding="utf-8"))  # parse-validate the result
    return True
