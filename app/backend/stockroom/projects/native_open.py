"""Open one adapter-reported project document with its Windows file association."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from pathlib import Path

from stockroom.projects.adapters import ProjectDocument

DocumentOpener = Callable[[str, str], object]


def open_project_document(
    project_root: Path,
    document_id: str,
    documents: Iterable[ProjectDocument],
    *,
    opener: DocumentOpener | None = None,
) -> ProjectDocument:
    """Resolve one linked document below the project root and ask Windows to open it."""

    document = next(
        (candidate for candidate in documents if candidate.document_id == document_id),
        None,
    )
    if document is None:
        raise FileNotFoundError(f"no such linked project document: {document_id}")

    root = project_root.resolve(strict=True)
    path = (root / document.path).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("the linked document must be a file inside the project")

    launch = opener or getattr(os, "startfile", None)
    if launch is None:
        raise RuntimeError("native document opening requires Windows")
    try:
        launch(str(path), "open")
    except OSError as exc:
        raise RuntimeError(f"Windows could not open {document.label}") from exc
    return document
