"""Pure publication-state rules shared by the workflow store and its tests."""

from __future__ import annotations

from .model import PublicationState

ACTIVE_PUBLICATION_STATES = frozenset(
    {
        PublicationState.PREPARING,
        PublicationState.COMMIT_FENCED,
        PublicationState.GIT_COMMITTED,
        PublicationState.CATALOG_ACTIVATED,
    }
)

POST_FENCE_PUBLICATION_STATES = frozenset(
    {
        PublicationState.COMMIT_FENCED,
        PublicationState.GIT_COMMITTED,
        PublicationState.CATALOG_ACTIVATED,
    }
)

RECONCILABLE_PUBLICATION_STATES = frozenset(
    {
        PublicationState.PREPARING,
        *POST_FENCE_PUBLICATION_STATES,
    }
)


def is_post_commit_fence(state: PublicationState | str) -> bool:
    return PublicationState(state) in POST_FENCE_PUBLICATION_STATES
