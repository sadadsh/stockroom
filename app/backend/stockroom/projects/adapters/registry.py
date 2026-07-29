"""Registry and ambiguity-safe detection for project adapters."""

from __future__ import annotations

from pathlib import Path

from .altium import AltiumProjectAdapter
from .base import ProjectAdapter
from .kicad import KiCadProjectAdapter
from .models import DetectedProject, ProjectDescription

_ADAPTERS: tuple[ProjectAdapter, ...] = (
    KiCadProjectAdapter(),
    AltiumProjectAdapter(),
)
_BY_KEY = {adapter.key: adapter for adapter in _ADAPTERS}


def adapters() -> tuple[ProjectAdapter, ...]:
    return _ADAPTERS


def get_adapter(key: str) -> ProjectAdapter:
    try:
        return _BY_KEY[key]
    except KeyError as exc:
        raise ValueError(f"unknown EDA: {key!r}") from exc


def _detections(candidate: Path, requested: str | None) -> list[DetectedProject]:
    selected = (get_adapter(requested),) if requested else _ADAPTERS
    return [detection for adapter in selected for detection in adapter.detect(Path(candidate))]


def discover_projects(candidate: Path, requested: str | None = None) -> list[ProjectDescription]:
    """All linkable project descriptors at one selected file or directory."""

    candidate = Path(candidate)
    if not candidate.exists():
        raise ValueError(f"not a file or directory: {candidate.as_posix()}")
    return [
        get_adapter(detection.adapter_key).describe(detection)
        for detection in _detections(candidate, requested)
    ]


def detect_project(candidate: Path, requested: str | None = None) -> ProjectDescription:
    """Describe exactly one selected project or explain why selection is ambiguous."""

    detections = _detections(Path(candidate), requested)
    if not detections:
        if requested:
            raise ValueError(
                f"no {get_adapter(requested).label} project files found in {candidate}"
            )
        raise ValueError(f"no supported PCB project files found in {candidate}")
    if len(detections) > 1:
        tools = {detection.adapter_key for detection in detections}
        if len(tools) > 1:
            raise ValueError(
                f"{candidate} holds both KiCad and Altium project files; "
                "choose which project to link"
            )
        names = ", ".join(detection.name for detection in detections)
        raise ValueError(f"{candidate} holds multiple {requested or 'PCB'} projects: {names}")
    detected = detections[0]
    return get_adapter(detected.adapter_key).describe(detected)
