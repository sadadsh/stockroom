"""Format-neutral project adapters for the rebuilt Projects workspace."""

from .models import (
    DetectedProject,
    ProjectDescription,
    ProjectDocument,
    RuntimeReport,
)
from .registry import adapters, detect_project, discover_projects, get_adapter

__all__ = [
    "DetectedProject",
    "ProjectDescription",
    "ProjectDocument",
    "RuntimeReport",
    "adapters",
    "detect_project",
    "discover_projects",
    "get_adapter",
]
