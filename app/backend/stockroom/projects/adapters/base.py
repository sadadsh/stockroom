"""The contract every Projects adapter implements."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from stockroom.model.project import ProjectRecord
from stockroom.projects.project_visuals import ProjectVisualBundle

from .models import (
    DetectedProject,
    ProjectDescription,
    ProjectDocument,
    RuntimeReport,
)


class ProjectAdapter(Protocol):
    """The current production slice of the full Projects adapter contract.

    Normalized BOM mutation, semantic diff, and output recipes are added to
    this same boundary as their native qualifications land. Shared
    callers never inspect ``ProjectRecord.eda``.
    """

    key: str
    label: str

    def detect(self, candidate: Path) -> list[DetectedProject]: ...

    def describe(self, detected: DetectedProject) -> ProjectDescription: ...

    def runtime(self, project: ProjectRecord) -> RuntimeReport: ...

    def documents(self, project: ProjectRecord) -> list[ProjectDocument]: ...

    def placements(self, project: ProjectRecord) -> list[dict]: ...

    def board_geometry(self, project: ProjectRecord) -> dict: ...

    def validate(self, project: ProjectRecord) -> dict: ...

    def render(self, project: ProjectRecord) -> ProjectVisualBundle: ...
