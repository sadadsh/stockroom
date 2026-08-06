"""Which provider's CAD this component prefers, and what changing that would replace.

The CAD column always stated a preferred source and never had a control for it, because the
statement was inferred: it read the three installed assets and said "Ultra Librarian" when they
agreed and "Mixed" when they did not. That is a description of the past, not a decision, and it
left the one column-level fact on the screen as the only fact nobody could set.

This module makes it a decision, under the rule the product already enforces on the bytes:

    ONE PROVIDER SUPPLIES THE WHOLE SET. `cad_variants.same_cad_evidence_set` accepts a dual-EDA
    release only when both tool bundles are indexed from the SAME evidence manifest, which fixes
    the provider, the adapter, the operation and the source closure. Nothing here relaxes that
    gate by a single field. A per-asset preference is offered because a person legitimately
    needs to pin one artifact explicitly - but a pin that would leave two providers in force
    across the three assets is REFUSED here, before anything is written, rather than stored and
    rejected later by the gate. A preference the gate will not honour is worse than no control:
    it reads as a promise the product cannot keep.

Two more rules follow from the same place:

    * a provider must actually OFFER the asset it is being preferred for. Coverage already
      answers that per artifact, in the five-state vocabulary `provider_coverage` publishes, so
      the question is asked there rather than answered a second way here. `unknown` is refused
      as well as `not_available`: preferring a provider nothing has said anything about would
      state a source for a file that may not exist.
    * every change is PLANNED before it is applied. `plan` names the assets that would move and
      what they would move to, and the writers refuse by planning first - so the confirmation a
      reader sees and the decision the record makes are computed by one function and cannot
      describe different outcomes.

Nothing here touches the filesystem or git. The caller holds the transaction, exactly like
`dossier.decisions`, so validation and mutation are testable without a repository and a refusal
costs no write.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from stockroom.dossier.cad import representation
from stockroom.model.asset import ASSET_KINDS
from stockroom.provider_coverage import SUPPLIED_STATUSES, registry_key
from stockroom.providers import provider_label

# Where an asset's in-force provider came from. A closed set, because "the person chose this"
# and "this is simply what was downloaded" are different sentences and the reader is owed the
# difference before replacing either.
SOURCE_ORIGINS: tuple[str, ...] = ("asset_preference", "set_preference", "installed", "")

# What each asset kind is CALLED. Asset types, never EDA applications and never file formats.
ASSET_LABELS: dict[str, str] = {
    "symbol": "Symbol",
    "footprint": "Footprint",
    "model": "3D Model",
}


# Why a plan was refused. A closed set, and the reason the API layer maps a refusal to a status
# code from THIS rather than from the wording: a message is written for a person to read, and
# dispatching on its text would make rewording it a behaviour change.
REFUSALS: tuple[str, ...] = ("", "unknown_provider", "unsupplied", "mixed")


class UnknownCadAsset(LookupError):
    """An asset kind the CAD set does not have. Refused rather than written."""


class UnofferedCadSource(ValueError):
    """A provider that does not offer the artifact it was asked to be preferred for."""


class MixedCadSourceRefused(ValueError):
    """A change that would leave two providers in force across the three assets."""


def asset_label(kind: str) -> str:
    return ASSET_LABELS.get(kind, kind)


def canonical_asset(kind: object) -> str:
    """The asset kind a request names, or a refusal.

    Loud rather than silent: a typo that fell through as a no-op would leave a person believing
    they had pinned an artifact they had not.
    """
    text = str(kind or "").strip().casefold()
    if text not in ASSET_KINDS:
        raise UnknownCadAsset(
            f"no CAD asset is named {str(kind or '')!r}; this component has "
            f"{', '.join(ASSET_KINDS)}"
        )
    return text


def installed_provider(record, kind: str) -> str:
    """The provider that supplied the file actually attached for one asset kind.

    Read through `representation`, which already decides WHICH of the per-tool views is the
    selected one, so the answer here and the answer the CAD module shows cannot disagree.
    """
    view = representation(record, kind)
    selected = next(
        (tool for tool in view["tools"] if tool["tool"] == view["selectedTool"]),
        next((tool for tool in view["tools"] if tool["present"]), None),
    )
    return registry_key((selected or {}).get("sourceId", ""))


def installed_providers(record) -> dict[str, str]:
    """Every asset kind's installed provider, computed once.

    Held as a map because the comparison screen plans one change per provider per asset, and
    re-reading the record's assets for each of those would re-project the same three
    representations dozens of times to reach the same three answers.
    """
    return {kind: installed_provider(record, kind) for kind in ASSET_KINDS}


def _named(provider: str, origin: str) -> dict[str, str]:
    return {
        "provider": provider,
        "label": provider_label(provider) if provider else "",
        "origin": origin if provider else "",
    }


def in_force(record, kind: str, installed: Mapping[str, str] | None = None) -> tuple[str, str]:
    """(provider key, origin) actually governing one asset kind right now.

    A pin on the asset outranks the whole-set pin, which outranks the file on disk. The origin
    travels with the answer because a preference and a download are different claims: replacing
    a download changes which files a person should fetch, and replacing a preference overrides
    a decision somebody already made.
    """
    preference = record.cad_preference
    pinned = registry_key(preference.assets.get(kind, ""))
    if pinned:
        return pinned, "asset_preference"
    whole = registry_key(preference.provider)
    if whole:
        return whole, "set_preference"
    attached = (
        installed.get(kind, "") if installed is not None else installed_provider(record, kind)
    )
    return (attached, "installed") if attached else ("", "")


def current_sources(
    record, installed: Mapping[str, str] | None = None
) -> dict[str, dict[str, str]]:
    """Every asset kind's in-force provider, named. The `before` half of any plan."""
    return {kind: _named(*in_force(record, kind, installed)) for kind in ASSET_KINDS}


def coherent_provider(sources: Mapping[str, Mapping[str, str]]) -> tuple[str, bool]:
    """(the one provider in force, whether the three disagree).

    A kind with no provider at all does not make a set mixed - it makes it incomplete, which is
    a different fact and is already stated by the asset's own status.
    """
    named = [
        str(entry.get("provider") or "") for entry in sources.values() if entry.get("provider")
    ]
    if not named:
        return "", False
    unique = sorted(set(named))
    return unique[0], len(unique) > 1


# ------------------------------------------------------------------ coverage questions


def _rows(coverage: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    rows = (coverage or {}).get("rows") or []
    return {str(row.get("id", "")): row for row in rows if isinstance(row, Mapping)}


def offers(coverage: Mapping[str, Any] | None, provider: str, kind: str) -> bool:
    """Whether coverage says this provider supplies this artifact for this component.

    The five-state vocabulary is read, never restated: `available`, `downloaded` and `validated`
    are the statuses `provider_coverage.SUPPLIED_STATUSES` already defines as "this provider
    supplies it", and `unknown` / `not_available` are not.
    """
    row = _rows(coverage).get(provider)
    if row is None:
        return False
    cell = row.get(kind)
    return isinstance(cell, Mapping) and str(cell.get("status", "")) in SUPPLIED_STATUSES


def _unsupplied(coverage: Mapping[str, Any] | None, provider: str, kinds) -> list[str]:
    return [kind for kind in kinds if not offers(coverage, provider, kind)]


# ------------------------------------------------------------------ the plan


def _change(kind: str, before: Mapping[str, str], provider: str) -> dict[str, str]:
    return {
        "asset": kind,
        "assetLabel": asset_label(kind),
        "fromProvider": str(before.get("provider") or ""),
        "fromLabel": str(before.get("label") or ""),
        "fromOrigin": str(before.get("origin") or ""),
        "toProvider": provider,
        "toLabel": provider_label(provider) if provider else "",
    }


def plan(
    record,
    coverage: Mapping[str, Any] | None,
    *,
    provider: object,
    asset: object = None,
    clear: bool = False,
    installed: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """What one preferred-source change would do, decided BEFORE anything is written.

    Returns `allowed`, a `refusal` code and a `reason` when it is not, the `changes` it would
    make - each naming the asset, what supplies it now and what would supply it instead - and
    the `resulting` provider per asset. The writers below refuse by consulting this, and the reader's confirmation shows
    the same document, so what a person is asked to approve is exactly what would happen.

    `asset=None` addresses the whole coherent set; an asset kind addresses that one artifact.
    `clear` withdraws the pin instead of moving it, which can never break coherence and so is
    always allowed - it returns the asset to the file that is actually attached.

    `installed` is the once-computed installed-provider map from `installed_providers`; passing
    it lets the comparison screen plan every provider's change without re-projecting the same
    three representations for each one.
    """
    attached = installed_providers(record) if installed is None else dict(installed)
    before = current_sources(record, attached)
    kind = None if asset is None else canonical_asset(asset)
    wanted = registry_key(provider) if not clear else ""
    raw = str(provider or "").strip()

    if clear:
        after = _cleared(record, kind, attached)
    else:
        if not wanted:
            return {
                "allowed": False,
                "refusal": "unknown_provider",
                "reason": (
                    f"{raw!r} is not a provider Stockroom knows" if raw else "no provider was named"
                ),
                "changes": [],
                "before": before,
                "resulting": before,
                "mixed": coherent_provider(before)[1],
            }
        after = _pinned(record, kind, wanted, before)

    changes = [
        _change(item, before[item], str(after[item]["provider"]))
        for item in ASSET_KINDS
        if after[item]["provider"] != before[item]["provider"]
    ]
    _resulting, mixed = coherent_provider(after)

    reason = ""
    refusal = ""
    if not clear:
        missing = _unsupplied(coverage, wanted, ASSET_KINDS if kind is None else (kind,))
        if missing:
            named = ", ".join(asset_label(item) for item in missing)
            refusal = "unsupplied"
            # Two different sentences, because they are two different corrections. A whole-set
            # choice failed because the provider cannot cover the set; a single-asset choice
            # failed because the provider has nothing for that artifact, and telling a person
            # to "pick a provider that supplies all three" when they picked one artifact
            # answers a question they did not ask.
            reason = (
                f"{provider_label(wanted)} does not supply the {named} for this component. "
                + (
                    "Stockroom takes a component's CAD from one provider's set, so the "
                    "preferred source must be a provider that can supply all three."
                    if kind is None
                    else "Choose a provider that has it, or record that it is available first."
                )
            )
        elif mixed:
            refusal = "mixed"
            others = sorted(
                {
                    str(after[item]["label"] or after[item]["provider"])
                    for item in ASSET_KINDS
                    if after[item]["provider"] and after[item]["provider"] != wanted
                }
            )
            reason = (
                f"Preferring {provider_label(wanted)} for the {asset_label(kind or '')} would "
                f"leave {', '.join(others)} in force for the other assets. Stockroom never "
                "combines files from two providers, so choose one provider for the whole set "
                "instead."
            )

    return {
        "allowed": refusal == "",
        "refusal": refusal,
        "reason": reason,
        "changes": changes,
        "before": before,
        "resulting": after,
        "mixed": mixed,
    }


def _pinned(
    record,
    kind: str | None,
    provider: str,
    before: Mapping[str, Mapping[str, str]],
) -> dict[str, dict[str, str]]:
    """The in-force map this record WOULD have with one pin applied. Nothing is written.

    A WHOLE-SET pin governs all three outright, per-asset exceptions included: the sentence a
    person writes by choosing a set source is "everything comes from here", and leaving a
    standing exception would contradict it silently and only on one of the three modules. The
    write below clears the exceptions for exactly that reason, so this previews the same thing.
    """
    out: dict[str, dict[str, str]] = {}
    for item in ASSET_KINDS:
        if kind is None:
            out[item] = _named(provider, "set_preference")
        elif item == kind:
            out[item] = _named(provider, "asset_preference")
        else:
            out[item] = dict(before[item])
    return out


def _cleared(record, kind: str | None, installed: Mapping[str, str]) -> dict[str, dict[str, str]]:
    """The in-force map this record WOULD have with one pin withdrawn. Nothing is written.

    Clearing the whole-set preference clears the per-asset exceptions with it, mirroring the
    write: an exception to a preference that no longer exists is not an exception to anything.
    """
    out: dict[str, dict[str, str]] = {}
    preference = record.cad_preference
    whole = "" if kind is None else registry_key(preference.provider)
    for item in ASSET_KINDS:
        pinned = "" if kind is None else registry_key(preference.assets.get(item, ""))
        if kind is not None and item == kind:
            pinned = ""
        if pinned:
            out[item] = _named(pinned, "asset_preference")
        elif whole:
            out[item] = _named(whole, "set_preference")
        else:
            out[item] = _named(installed.get(item, ""), "installed")
    return out


# ------------------------------------------------------------------ the writes


def _apply(record, decided: Mapping[str, Any]) -> None:
    """Turn a refused plan into the exception that names WHY, or return and let the write run."""
    if decided["allowed"]:
        return
    reason = str(decided["reason"])
    if str(decided["refusal"]) == "mixed":
        raise MixedCadSourceRefused(reason)
    raise UnofferedCadSource(reason)


def set_preferred_source(
    record,
    coverage: Mapping[str, Any] | None,
    provider: object,
    *,
    reviewed_by: str = "",
    reviewed_at: str = "",
) -> dict[str, Any]:
    """Prefer one provider for the WHOLE set. Returns the plan that was carried out.

    Per-asset pins are cleared by the same write, because a whole-set choice is the person
    saying "everything comes from here" and leaving an exception standing would contradict the
    sentence they just wrote - silently, and only visibly on one of three modules.
    """
    decided = plan(record, coverage, provider=provider)
    _apply(record, decided)
    preference = record.cad_preference
    preference.provider = registry_key(provider)
    preference.assets = {}
    preference.reviewed_by = reviewed_by
    preference.reviewed_at = reviewed_at
    return decided


def clear_preferred_source(record) -> dict[str, Any]:
    """Withdraw the whole-set preference, returning every asset to the files on disk.

    Idempotent: asking for a state that already holds is a success, like clearing a
    specification override, because a caller that cannot know the current state before asking
    must still be able to use the action.
    """
    decided = plan(record, None, provider="", clear=True)
    preference = record.cad_preference
    preference.provider = ""
    preference.assets = {}
    if preference.is_empty():
        preference.reviewed_by = ""
        preference.reviewed_at = ""
    return decided


def set_asset_preferred_source(
    record,
    coverage: Mapping[str, Any] | None,
    asset: object,
    provider: object,
    *,
    reviewed_by: str = "",
    reviewed_at: str = "",
) -> dict[str, Any]:
    """Prefer one provider for ONE asset, when that leaves the set coherent.

    Refused when it would not. The refusal is the product rule, not a limitation of the store:
    a mixed set cannot be indexed from one evidence manifest, so writing the pin would only
    move the failure to the moment the files are resolved.
    """
    kind = canonical_asset(asset)
    decided = plan(record, coverage, provider=provider, asset=kind)
    _apply(record, decided)
    preference = record.cad_preference
    preference.assets[kind] = registry_key(provider)
    preference.reviewed_by = reviewed_by
    preference.reviewed_at = reviewed_at
    return decided


def clear_asset_preferred_source(record, asset: object) -> dict[str, Any]:
    """Withdraw one asset's own pin, leaving the whole-set preference standing. Idempotent."""
    kind = canonical_asset(asset)
    decided = plan(record, None, provider="", asset=kind, clear=True)
    preference = record.cad_preference
    preference.assets.pop(kind, None)
    if preference.is_empty():
        preference.reviewed_by = ""
        preference.reviewed_at = ""
    return decided


# ------------------------------------------------------------------ the projection


def _scope(decided: Mapping[str, Any], current: bool) -> dict[str, Any]:
    return {
        "allowed": bool(decided["allowed"]),
        "refusal": str(decided["refusal"]),
        "reason": str(decided["reason"]),
        "changes": list(decided["changes"]),
        # Already in force. Kept apart from `allowed`, because "you may choose this" and "this
        # is what you already chose" are different answers and a control that conflates them
        # either offers a no-op as a change or hides the state a person is looking for.
        "current": current,
    }


def build_cad_preference(record, coverage: Mapping[str, Any] | None) -> dict[str, Any]:
    """The preferred CAD source, and what choosing each provider would replace.

    The whole comparison is precomputed here rather than derived by the reader, because the rule
    it enforces is the product's coherence rule and a second implementation of it - in another
    language, against a projection rather than the record - is a second answer waiting to
    disagree with the gate. The screen renders this; it decides nothing.
    """
    attached = installed_providers(record)
    sources = current_sources(record, attached)
    resolved, mixed = coherent_provider(sources)
    preference = record.cad_preference

    options: list[dict[str, Any]] = []
    for row in (coverage or {}).get("rows") or []:
        if not isinstance(row, Mapping):
            continue
        provider = str(row.get("id", ""))
        if not provider:
            continue
        whole = plan(record, coverage, provider=provider, installed=attached)
        options.append(
            {
                "provider": provider,
                "label": str(row.get("label", "")) or provider_label(provider),
                "coverage": {
                    kind: str((row.get(kind) or {}).get("status", "unknown"))
                    for kind in ASSET_KINDS
                },
                "set": _scope(whole, registry_key(preference.provider) == provider),
                "assets": {
                    kind: _scope(
                        plan(
                            record,
                            coverage,
                            provider=provider,
                            asset=kind,
                            installed=attached,
                        ),
                        registry_key(preference.assets.get(kind, "")) == provider,
                    )
                    for kind in ASSET_KINDS
                },
            }
        )

    return {
        "provider": "" if mixed else resolved,
        "label": "" if mixed or not resolved else provider_label(resolved),
        "mixed": mixed,
        # Whether a person DECIDED this, as opposed to it merely being what got downloaded.
        "pinned": bool(registry_key(preference.provider)),
        "reviewedAt": preference.reviewed_at,
        "assets": sources,
        "assetLabels": {kind: asset_label(kind) for kind in ASSET_KINDS},
        "options": options,
    }


__all__ = [
    "ASSET_LABELS",
    "REFUSALS",
    "SOURCE_ORIGINS",
    "MixedCadSourceRefused",
    "UnknownCadAsset",
    "UnofferedCadSource",
    "asset_label",
    "build_cad_preference",
    "canonical_asset",
    "clear_asset_preferred_source",
    "clear_preferred_source",
    "coherent_provider",
    "current_sources",
    "in_force",
    "installed_provider",
    "installed_providers",
    "offers",
    "plan",
    "set_asset_preferred_source",
    "set_preferred_source",
]
