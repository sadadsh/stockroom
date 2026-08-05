"""The reviewed decisions a person can record about one specification, and what they cost.

Everywhere else in this package is a projection: it reads a record and decides nothing that is
not already true. This module is the one that WRITES, so it carries the rules that make a manual
decision safe to be at the top of the precedence order:

    * a decision names a field the registry defines, or it is refused. Accepting a key nothing
      in `dossier.fields` claims would let the store accumulate keys the projection can never
      render, and a value nobody can read is worse than a value nobody entered;
    * a decision never deletes evidence. Every source candidate survives an override untouched;
      the override is added on top and the disagreement becomes `resolved`, not invisible;
    * a decision records what it displaced, so the reader is told what the field will fall back
      to and clearing it is genuinely reversible rather than merely permitted;
    * a preferred source must be one of THAT field's own candidates. Pinning a source that never
      answered for the field would promise a value nothing can supply.

Nothing here touches the filesystem or git. The caller holds the transaction, so validation and
mutation are testable without a repository, and a refusal costs no write.
"""

from __future__ import annotations

from typing import Any

from stockroom.dossier.categories import resolve_schema
from stockroom.dossier.fields import field_for
from stockroom.dossier.specifications import build_specifications, source_label
from stockroom.model.part import FieldOverride


class UnknownSpecification(LookupError):
    """A key no canonical field claims. Refused rather than written."""


class UnpinnableSource(ValueError):
    """A source that offered nothing for the field it was asked to be preferred for."""


def canonical_key(key: object) -> str:
    """The canonical field key a request names.

    Spellings are folded the same way every raw distributor key is folded, so
    `Voltage - Supply`, `voltage_supply` and `supply_voltage` all name one field and the store
    can only ever grow keys the specification sheet knows how to show.
    """
    definition = field_for(key)
    if definition is None:
        raise UnknownSpecification(
            f"no canonical specification is named {str(key or '')!r}"
        )
    return definition.key


def specification_row(record, key: str) -> dict[str, Any] | None:
    """The projected specification for one canonical key, as the reader sees it today."""
    schema = resolve_schema(record)
    for item in build_specifications(record, schema).records:
        if item["key"] == key:
            return item
    return None


def sourced_candidates(record, key: str) -> list[dict[str, Any]]:
    """Every candidate for this field that a SOURCE offered, in precedence order.

    A manual decision is excluded on purpose: it is not something to prefer over the sources, it
    is the thing being decided, and offering it as a pinnable source would let a person pin a
    field to their own earlier answer and call that provenance.
    """
    row = specification_row(record, key)
    if row is None:
        return []
    return [
        candidate
        for candidate in row["sourceCandidates"]
        if candidate["tier"] != "manual_override" and candidate["sourceId"]
    ]


def _displaced(record, key: str) -> tuple[object, str]:
    """The sourced answer in force right now: what a new decision on this field replaces."""
    candidates = sourced_candidates(record, key)
    if not candidates:
        return None, ""
    return candidates[0]["value"], candidates[0]["sourceId"]


def _entry(record, key: str) -> FieldOverride:
    """This field's existing decision, or a fresh one that decides nothing yet.

    A fresh entry starts with NO value. `FieldOverride` defaults to holding one, because every
    override written before source pins existed was a value override and a record on disk must
    keep meaning what it meant; a decision being built here has not claimed a value until the
    caller gives it one.
    """
    return record.overrides.get(key) or FieldOverride(has_value=False)


def _store(record, key: str, entry: FieldOverride) -> None:
    """Keep an entry that decides something; drop one that decides nothing."""
    if entry.is_empty():
        record.overrides.pop(key, None)
        return
    record.overrides[key] = entry


def set_override(
    record,
    key: object,
    value: object,
    *,
    reviewed_by: str = "",
    reviewed_at: str = "",
    note: str = "",
    verified: bool = True,
) -> str:
    """Record a reviewed value for one specification. Returns the canonical key written.

    The displaced sourced answer is captured BEFORE the write, from the record as it stands, so
    replacing an existing override reports what the SOURCES say rather than what the previous
    override said - otherwise a second edit would record the first edit as the thing it
    overrode, and the trail back to the evidence would be lost one edit at a time.

    `note` is the reviewer's stated REASON. It is the difference between a value that disagrees
    with two distributors for no visible cause and one that says why, and it is the only part of
    a manual decision that can explain itself to the next person to read the field.

    `verified` says whether the reviewer stands behind the value as checked. False is not a
    lesser write: it records the honest case of a value entered but not confirmed, and the row
    reads `Unverified` rather than claiming the authority a reviewed override otherwise carries.
    """
    canonical = canonical_key(key)
    replaced_value, replaced_source = _displaced(record, canonical)
    entry = _entry(record, canonical)
    entry.value = value
    entry.has_value = True
    entry.note = note
    entry.verified = verified
    entry.reviewed_by = reviewed_by
    entry.reviewed_at = reviewed_at
    entry.replaced_value = replaced_value
    entry.replaced_source = replaced_source
    _store(record, canonical, entry)
    return canonical


def clear_override(record, key: object) -> tuple[str, bool]:
    """Withdraw the reviewed value for one specification, keeping any preferred source.

    Returns (canonical key, whether anything changed). Clearing what was never set is a real
    success: the desired end state - no manual value on this field - is already true, and
    reporting that as a failure would make an idempotent action unusable to any caller that
    cannot know the current state before asking.
    """
    canonical = canonical_key(key)
    entry = record.overrides.get(canonical)
    if entry is None or not entry.has_value:
        return canonical, False
    entry.has_value = False
    entry.value = ""
    # The reason and the reviewer's confidence were statements about the VALUE. Keeping them on a
    # withdrawn value would attach an explanation to a decision that no longer exists.
    entry.note = ""
    entry.verified = True
    # The displaced evidence belongs to the decision that displaced it. A pin that survives this
    # clear keeps its own, so nothing inherits a story about a value it never replaced.
    if not entry.preferred_source:
        entry.replaced_value = None
        entry.replaced_source = ""
    _store(record, canonical, entry)
    return canonical, True


def set_preferred_source(
    record, key: object, source_id: object, *, reviewed_by: str = "", reviewed_at: str = ""
) -> str:
    """Pin one specification to one source's answer. Returns the canonical key written.

    The pin FOLLOWS the source: nothing is copied, so refreshing that source moves the field
    with it. A source that is not among this field's own candidates is refused - the control
    would otherwise be able to prefer an answer that does not exist.
    """
    canonical = canonical_key(key)
    wanted = str(source_id or "").strip()
    candidates = sourced_candidates(record, canonical)
    offered = {candidate["sourceId"] for candidate in candidates}
    if wanted not in offered:
        raise UnpinnableSource(
            f"{source_label(wanted) if wanted else 'an unnamed source'} offered no value for "
            f"{canonical}"
            + (f"; {', '.join(sorted(offered))} did" if offered else "; nothing did")
        )
    entry = _entry(record, canonical)
    if entry.preferred_source == wanted:
        # Already pinned here. Recomputing what it displaced would read the pin's OWN answer as
        # the thing the pin replaced, and the field would end up recorded as overriding itself.
        return canonical
    replaced_value, replaced_source = _displaced(record, canonical)
    entry.preferred_source = wanted
    entry.reviewed_by = reviewed_by
    entry.reviewed_at = reviewed_at
    if not entry.has_value:
        entry.replaced_value = replaced_value
        entry.replaced_source = replaced_source
    _store(record, canonical, entry)
    return canonical


def clear_preferred_source(record, key: object) -> tuple[str, bool]:
    """Withdraw the pin so the field returns to computed precedence.

    Returns (canonical key, whether anything changed). Like clearing an override, asking for a
    state that already holds is a success.
    """
    canonical = canonical_key(key)
    entry = record.overrides.get(canonical)
    if entry is None or not entry.preferred_source:
        return canonical, False
    entry.preferred_source = ""
    if not entry.has_value:
        entry.replaced_value = None
        entry.replaced_source = ""
    _store(record, canonical, entry)
    return canonical, True


__all__ = [
    "UnknownSpecification",
    "UnpinnableSource",
    "canonical_key",
    "clear_override",
    "clear_preferred_source",
    "set_override",
    "set_preferred_source",
    "sourced_candidates",
    "specification_row",
]
