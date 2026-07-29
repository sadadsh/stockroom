"""Shared project-adapter values.

These values deliberately contain no KiCad or Altium fields. Tool-specific file
formats end at the adapter boundary; selection, collaboration, API responses, and
the Projects UI consume these shapes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DetectedProject:
    """One project candidate found at a user-selected file or directory."""

    adapter_key: str
    descriptor: Path
    root: Path
    name: str


@dataclass(frozen=True, slots=True)
class ProjectDescription:
    """The durable project identity and native source documents."""

    adapter_key: str
    root: Path
    descriptor: str
    name: str
    boards: tuple[str, ...]
    schematics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProjectDocument:
    """One source document that can be opened, claimed, reviewed, and validated."""

    document_id: str
    path: str
    label: str
    kind: str
    exists: bool
    lock_required: bool = True


@dataclass(frozen=True, slots=True)
class RuntimeReport:
    """Whether this adapter's authoritative native runtime can act right now."""

    adapter_key: str
    available: bool
    status: str
    version: str = ""
    detail: str = ""
