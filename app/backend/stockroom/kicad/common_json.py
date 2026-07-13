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
    data = _load(Path(path))
    vars_ = (data.get("environment") or {}).get("vars") or {}
    return vars_.get(name)


def write_env_var(path: Path, name: str, value: str) -> bool:
    path = Path(path)
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
