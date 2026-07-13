"""Unpack ingestion inputs (zips, folders, bare files, any mix) into isolated
sandbox roots so the rest of the pipeline works against a plain directory tree,
never the caller's originals (spec section 5, stage 1). Zip extraction is
zip-slip guarded (spec section 11)."""

from __future__ import annotations

import hashlib
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

from stockroom.ingest.errors import IngestError


@dataclass
class Unpacked:
    root: Path
    origin: Path
    is_zip: bool
    sha256: str


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_extract(zf: zipfile.ZipFile, dst: Path) -> None:
    dst_resolved = dst.resolve()
    for member in zf.namelist():
        target = (dst / member).resolve()
        if dst_resolved != target and dst_resolved not in target.parents:
            raise IngestError(f"unsafe zip entry escapes sandbox: {member!r}")
    zf.extractall(dst)


def unpack_inputs(inputs: list[Path], workdir: Path) -> list[Unpacked]:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    out: list[Unpacked] = []
    for n, raw in enumerate(inputs):
        origin = Path(raw)
        if not origin.exists():
            raise IngestError(f"input does not exist: {origin}")
        root = workdir / str(n)
        root.mkdir(parents=True, exist_ok=True)
        if origin.is_dir():
            shutil.copytree(origin, root, dirs_exist_ok=True)
            out.append(Unpacked(root=root, origin=origin, is_zip=False, sha256=""))
        elif zipfile.is_zipfile(origin):
            with zipfile.ZipFile(origin) as zf:
                _safe_extract(zf, root)
            out.append(Unpacked(root=root, origin=origin, is_zip=True, sha256=sha256_of(origin)))
        else:
            shutil.copyfile(origin, root / origin.name)
            out.append(Unpacked(root=root, origin=origin, is_zip=False, sha256=sha256_of(origin)))
    return out
