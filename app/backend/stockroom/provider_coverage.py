"""Per-component provider coverage: which provider can supply everything for one part.

Stockroom does not mix CAD across providers - a symbol, a footprint and a 3D model must come
from one provider's download set, and every gate that enforces that is untouched by this
module. What was missing is the question that makes the rule usable: *which* provider can
supply the whole set for THIS part, and how do I get to it. That is what this answers, per
component, for every provider in `stockroom.providers` - no provider is hidden, and the ones
with nothing recorded say so instead of disappearing.

Five columns per provider: `symbol`, `footprint`, `model`, and one count out of three per
registered EDA tool (`kicad`, `altium`). The status vocabulary is closed, and every status
names the evidence that produced it:

    unknown        nobody said anything. The default, and the only honest answer to silence.
    not_available  an official catalogue probe, or a person, said the artifact is not there.
    available      official catalogue/API evidence named THIS provider AND this artifact, or
                   a person did. A provider page merely existing proves nothing.
    downloaded     a matching native download for that provider has been captured.
    validated      Stockroom inspected the artifact and the inspection passed.

Absence of evidence is never `not_available`: a probe that could not run leaves `None` behind
(`enrich/digikey_api.py` keeps it honestly `None`), and `None` reads as `unknown`. There are no
confidence percentages, and nothing here crawls a provider page to find out - a number between
0 and 1 would only be an opinion wearing a measurement's clothes.

Everything is a pure function of what it is given. The evidence store and the retained-candidate
list arrive as ARGUMENTS: nothing here opens a path on its own, so the same projection serves a
caller that has an evidence store and a caller that has only the record.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from stockroom.cad_variants import list_cad_variants
from stockroom.eda.registry import all_tools
from stockroom.model.cad_variant import CAD_VARIANT_ROLE_MAP
from stockroom.model.part import ProviderAssertion
from stockroom.model.trust import Verdict, asset_verdict
from stockroom.providers import ProviderRecord, all_providers, provider_for_media, search_url

# The artifacts a person needs to place a part. Deliberately the three the whole product already
# speaks in (`model.asset.ASSET_KINDS`), so a coverage row and a representation row agree.
COVERAGE_ARTIFACTS: tuple[str, ...] = ("symbol", "footprint", "model")

COVERAGE_STATUSES: tuple[str, ...] = (
    "unknown",
    "available",
    "not_available",
    "downloaded",
    "validated",
)

# What PROVED a status. Recorded so a reader can always ask "who says so", and deliberately a
# closed set of evidence kinds rather than a score: "official_api" and "user" are different
# sentences, not different amounts of the same thing.
COVERAGE_ORIGINS: tuple[str, ...] = ("official_api", "user", "native_download", "validator")

# The only two things a person is allowed to assert. Neither "downloaded" nor "validated" is
# here: those are claims about bytes on disk, and a person cannot make them true by saying so.
USER_STATUSES: frozenset[str] = frozenset({"available", "not_available"})

# Statuses that count towards "this provider supplies it".
SUPPLIED_STATUSES: frozenset[str] = frozenset({"available", "downloaded", "validated"})

# Proven by bytes Stockroom holds. A correction corrects a CLAIM; it can never un-download or
# un-validate a file that is on disk, so these two are never overwritten by an assertion.
PROVEN_STATUSES: frozenset[str] = frozenset({"downloaded", "validated"})

# Stronger evidence wins, so the order the evidence arrives in cannot change the answer.
# `not_available` outranks `unknown` because it is a real claim, and is outranked by everything
# above it because a file we hold settles the question a claim was only guessing at.
_STATUS_RANK: dict[str, int] = {
    "unknown": 0,
    "not_available": 1,
    "available": 2,
    "downloaded": 3,
    "validated": 4,
}

# The whole-part scope: "this provider has a symbol for this part", independent of which EDA
# tool consumes it. Per-tool scopes are the registered tool keys.
_ANY_TOOL = ""

# Which registry flag says a provider offers an artifact at all. A provider that does not author
# symbols cannot have one for this part, so catalogue evidence is never spread onto it.
_OFFERS_ATTRIBUTE: dict[str, str] = {
    "symbol": "symbols",
    "footprint": "footprints",
    "model": "models",
}

# Retained-candidate `detected_format` -> the EDA tool the file is native to. A STEP/VRML model
# is deliberately absent: KiCad references it and Altium embeds it, so it belongs to no single
# tool and only raises the whole-part column.
_CANDIDATE_TOOLS: dict[str, str] = {
    "kicad_symbol_library": "kicad",
    "kicad_legacy_symbol_library": "kicad",
    "kicad_footprint": "kicad",
    "altium_schlib": "altium",
    "altium_pcblib": "altium",
    "altium_intlib": "altium",
}

# Retained-candidate `artifact_kind` -> the coverage columns it fills. A `library` container
# holds both a symbol and a footprint (an .IntLib, a multi-entry .kicad_sym).
_CANDIDATE_KINDS: dict[str, tuple[str, ...]] = {
    "symbol": ("symbol",),
    "footprint": ("footprint",),
    "model": ("model",),
    "library": ("symbol", "footprint"),
}

# `ingest.candidates.ValidationOutcome` values that mean Stockroom read the file and it proved
# to be this part's artifact. Held as the wire strings that enum declares rather than importing
# it, so this projection does not pull the whole ingest package in; `tests/backend/
# test_provider_coverage.py` fails if the enum and these ever disagree.
_VALIDATED_OUTCOMES: frozenset[str] = frozenset({"Ready To Import", "Imported"})

_REGISTRY: dict[str, ProviderRecord] = {item.key: item for item in all_providers()}


def _role_targets() -> dict[str, tuple[tuple[str, str], ...]]:
    """Evidence role -> every (tool, artifact) it satisfies, from the coherence registry.

    Read from `CAD_VARIANT_ROLE_MAP` rather than restated, so a tool whose roles change here
    cannot end up reported under a role nothing produces. Altium has no independent `model`
    role by design (its 3D body is embedded in the footprint), so an Altium download never
    claims a downloaded 3D model - that column can still be answered by catalogue evidence or
    by a person, which is the honest difference.
    """
    out: dict[str, list[tuple[str, str]]] = {}
    for tool, roles in CAD_VARIANT_ROLE_MAP.items():
        for artifact, role in roles.items():
            out.setdefault(role, []).append((tool, artifact))
    return {role: tuple(items) for role, items in out.items()}


_ROLE_TARGETS: dict[str, tuple[tuple[str, str], ...]] = _role_targets()


# ------------------------------------------------------------------ registry mapping


def registry_key(value: object) -> str:
    """The registry key a stored provider name refers to, or "" when the registry has none.

    Three spellings reach this. A registry key ("ultralibrarian") is itself. An evidence
    provider key carries the acquisition surface as a prefix ("digikey-ultralibrarian" is an
    Ultra Librarian bundle downloaded through DigiKey's page) - the same family convention the
    evidence store's own ranking uses. A catalogue payload names a provider the way a person
    reads it ("Ultra Librarian"), which is exactly what `providers.provider_for_media` decides.

    A name the registry cannot place returns "" and is dropped rather than inventing a row: a
    coverage table with a provider nobody can open is not coverage.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    folded = text.casefold()
    if folded in _REGISTRY:
        return folded
    for key in _REGISTRY:
        if folded.endswith(f"-{key}"):
            return key
    matched = provider_for_media(text, "")
    return matched.key if matched is not None else ""


def _provider_tools(provider: ProviderRecord) -> tuple[str, ...]:
    """The registered EDA tools this provider exports for.

    `ProviderRecord` carries one boolean per tool named for the tool's registry key, so this
    stays a lookup instead of a branch and a third tool needs no edit here.
    """
    return tuple(tool.key for tool in all_tools() if getattr(provider, tool.key, False))


# ------------------------------------------------------------------ the status grid


class _Grid:
    """(provider, scope, artifact) -> (status, origin), under construction."""

    def __init__(self) -> None:
        self._cells: dict[tuple[str, str, str], tuple[str, str]] = {}

    def raise_to(
        self,
        provider: str,
        artifact: str,
        status: str,
        origin: str,
        *,
        scopes: Sequence[str],
    ) -> None:
        """Record evidence, keeping the strongest claim already made for each scope."""
        if not provider or artifact not in COVERAGE_ARTIFACTS:
            return
        for scope in scopes:
            key = (provider, scope, artifact)
            current = self._cells.get(key)
            if current is not None and _STATUS_RANK[current[0]] >= _STATUS_RANK[status]:
                continue
            self._cells[key] = (status, origin)

    def assert_user(self, provider: str, artifact: str, status: str, scopes: Sequence[str]) -> bool:
        """Apply a person's correction wherever it is not overruled by bytes on disk.

        Returns whether it took effect on the whole-part column, which is the cell the person
        was looking at. A correction that could not downgrade `downloaded` or `validated` is
        still kept and still reported - it is a disagreement worth seeing, not an error.
        """
        applied = self.cell(provider, _ANY_TOOL, artifact)[0] not in PROVEN_STATUSES
        for scope in scopes:
            if self.cell(provider, scope, artifact)[0] in PROVEN_STATUSES:
                continue
            self._cells[(provider, scope, artifact)] = (status, "user")
        return applied

    def cell(self, provider: str, scope: str, artifact: str) -> tuple[str, str]:
        return self._cells.get((provider, scope, artifact), ("unknown", ""))


# ------------------------------------------------------------------ evidence sources


def _catalog_payloads(record) -> list[tuple[str, Mapping[str, Any]]]:
    return [
        (str(key), payload)
        for key, payload in (getattr(record, "catalog", None) or {}).items()
        if isinstance(payload, Mapping)
    ]


def _apply_catalog(grid: _Grid, record) -> None:
    """Official catalogue availability -> `available` / `not_available`.

    `PartRecord.catalog[<surface>]["availability"]` is the distributor's own answer, shaped
    `{cad_model, three_d_model, providers}`. It is the ONLY thing in Stockroom that may set
    `available`, and it does so only where it names a provider AND an artifact together:

      * `cad_model` is the ECAD probe, so it answers the symbol and footprint columns;
      * `three_d_model` answers the model column;
      * `providers` names the model libraries the surface links to. On its own that is a page
        existing, which proves nothing - it only becomes evidence paired with a probe that came
        back True for the artifact in question.

    `False` is a real answer and marks the SURFACE that ran the probe `not_available`; it is
    never spread onto a linked library, which never ran a probe. `None` means the probe did not
    answer and is left alone, because `unknown` and `not_available` are different sentences.
    """
    for surface_key, payload in _catalog_payloads(record):
        availability = payload.get("availability")
        if not isinstance(availability, Mapping):
            continue
        surface = registry_key(surface_key)
        named = [
            key
            for key in (registry_key(item) for item in availability.get("providers") or [])
            if key
        ]
        for probe, artifacts in (
            ("cad_model", ("symbol", "footprint")),
            ("three_d_model", ("model",)),
        ):
            answer = availability.get(probe)
            if answer is True:
                for provider_key in ([surface] if surface else []) + named:
                    _claim(grid, provider_key, artifacts, "available", "official_api")
            elif answer is False and surface:
                _claim(grid, surface, artifacts, "not_available", "official_api")


def _claim(
    grid: _Grid,
    provider_key: str,
    artifacts: Sequence[str],
    status: str,
    origin: str,
) -> None:
    """Record a catalogue-level claim on the whole-part column and every tool it can reach."""
    provider = _REGISTRY.get(provider_key)
    if provider is None:
        return
    scopes = (_ANY_TOOL, *_provider_tools(provider))
    for artifact in artifacts:
        if not getattr(provider, _OFFERS_ATTRIBUTE[artifact], False):
            continue
        grid.raise_to(provider_key, artifact, status, origin, scopes=scopes)


def _apply_assets(grid: _Grid, record) -> None:
    """Installed assets -> `downloaded`, and `validated` once their checks pass.

    `AssetOrigin.vendor` is what says which provider supplied the file. A present asset is a
    download that happened; it becomes validated only on a PASS verdict, so an asset carrying a
    failed check reports `downloaded` and never keeps a `validated` it did not earn.
    """
    for tool in all_tools():
        bundle = record.assets_for(tool.key)
        for artifact in COVERAGE_ARTIFACTS:
            asset = bundle.get(artifact)
            if asset is None or not asset.is_present():
                continue
            origin = getattr(asset, "origin", None)
            provider_key = registry_key(getattr(origin, "vendor", "") if origin else "")
            if not provider_key:
                continue
            if asset_verdict(asset) is Verdict.PASS:
                status, evidence = "validated", "validator"
            else:
                status, evidence = "downloaded", "native_download"
            grid.raise_to(
                provider_key, artifact, status, evidence, scopes=(_ANY_TOOL, tool.key)
            )


def _apply_evidence_store(grid: _Grid, store, identity) -> None:
    """Retained evidence -> `downloaded`, and `validated` for a complete tool bundle.

    Both reads reverify: `list_role_variants` re-reads each indexed manifest and its bytes, and
    `list_cad_variants` additionally proves one coherent whole-tool bundle. A single retained
    role is a native download Stockroom holds; a complete bundle is one whose role validation
    report proved out, which is what "Stockroom inspected the artifact" means here. Neither
    check is relaxed - a tampered object still raises out of this function.
    """
    for role, targets in _ROLE_TARGETS.items():
        for variant in store.list_role_variants(identity=identity, role=role):
            provider_key = registry_key(variant.provider_key)
            for tool, artifact in targets:
                grid.raise_to(
                    provider_key,
                    artifact,
                    "downloaded",
                    "native_download",
                    scopes=(_ANY_TOOL, tool),
                )
    for tool in CAD_VARIANT_ROLE_MAP:
        for descriptor in list_cad_variants(store, identity=identity, tool=tool):
            provider_key = registry_key(descriptor.provider)
            for artifact in descriptor.artifacts:
                grid.raise_to(
                    provider_key,
                    artifact.asset_kind,
                    "validated",
                    "validator",
                    scopes=(_ANY_TOOL, tool),
                )


def _apply_candidates(grid: _Grid, record, candidates: Sequence[Any]) -> None:
    """Retained ingest candidates -> `downloaded`, and `validated` once inspection succeeded.

    A rejected candidate contributes nothing: an unreadable file is not a download of this
    part's artifact. A candidate still awaiting a person's judgement stays `downloaded`, because
    "we have the bytes" is true and "we checked them" is not yet.
    """
    for candidate in candidates:
        if getattr(candidate, "component_id", "") != record.id:
            continue
        if getattr(candidate, "rejected", False):
            continue
        provider_key = registry_key(getattr(candidate, "provider_id", ""))
        if not provider_key:
            continue
        artifacts = _CANDIDATE_KINDS.get(str(getattr(candidate, "artifact_kind", "")), ())
        if not artifacts:
            continue
        tool = _CANDIDATE_TOOLS.get(str(getattr(candidate, "detected_format", "")), "")
        validated = str(
            getattr(candidate, "validation_result", "")
        ) in _VALIDATED_OUTCOMES and not getattr(candidate, "manual_review_required", False)
        status, evidence = (
            ("validated", "validator") if validated else ("downloaded", "native_download")
        )
        scopes = (_ANY_TOOL,) if not tool else (_ANY_TOOL, tool)
        for artifact in artifacts:
            grid.raise_to(provider_key, artifact, status, evidence, scopes=scopes)


def _apply_user_assertions(grid: _Grid, record) -> dict[str, dict[str, dict[str, Any]]]:
    """A person's corrections, applied last and attributed to them.

    Last because a correction is meant to overrule a catalogue that got it wrong; never over
    `downloaded` or `validated`, because those are statements about files Stockroom is holding.
    """
    notes: dict[str, dict[str, dict[str, Any]]] = {}
    for stored_key, slots in (getattr(record, "provider_assertions", None) or {}).items():
        provider_key = registry_key(stored_key)
        provider = _REGISTRY.get(provider_key)
        if provider is None:
            continue
        scopes = (_ANY_TOOL, *_provider_tools(provider))
        for artifact, assertion in slots.items():
            status = str(getattr(assertion, "status", ""))
            if artifact not in COVERAGE_ARTIFACTS or status not in USER_STATUSES:
                continue
            applied = grid.assert_user(provider_key, artifact, status, scopes)
            notes.setdefault(provider_key, {})[artifact] = {
                "status": status,
                "origin": "user",
                "notedAt": str(getattr(assertion, "noted_at", "")),
                "note": str(getattr(assertion, "note", "")),
                "applied": applied,
            }
    return notes


# ------------------------------------------------------------------ provider access


def _provider_urls(record) -> dict[str, str]:
    """The exact page catalogue evidence supplies for each provider, where it supplies one.

    Order is deliberate. A distributor's own product URL and a stored purchase link are that
    distributor's part page. A catalogue media link is matched by the provider tokens in the
    registry, so it attaches to the library that AUTHORED the model rather than to whoever
    happened to host the link.
    """
    urls: dict[str, str] = {}
    for surface_key, payload in _catalog_payloads(record):
        key = registry_key(surface_key)
        url = str(payload.get("product_url") or "")
        if key and url.startswith("https://"):
            urls.setdefault(key, url)
    for entry in getattr(record, "purchase", None) or []:
        key = registry_key(getattr(entry, "vendor", ""))
        url = str(getattr(entry, "url", "") or "")
        if key and url.startswith("https://"):
            urls.setdefault(key, url)
    for _surface_key, payload in _catalog_payloads(record):
        for item in payload.get("media") or []:
            if not isinstance(item, Mapping):
                continue
            url = str(item.get("url") or "")
            if not url.startswith("https://"):
                continue
            matched = provider_for_media(str(item.get("title") or ""), url)
            if matched is not None:
                urls.setdefault(matched.key, url)
    return urls


def _access(provider: ProviderRecord, record, urls: Mapping[str, str]) -> tuple[str, str]:
    """(url, kind) for reaching this provider: an exact page, an MPN search, or nothing.

    Nothing is a real answer. TraceParts, CADENAS and a manufacturer site have no measured
    search surface (`providers.search_url` returns ""), so unless catalogue evidence handed us
    an exact page there is no honest link - and a fabricated one would send a person to a page
    that proves nothing about this part.
    """
    exact = urls.get(provider.key, "")
    if exact:
        return exact, "evidence"
    mpn = str(getattr(record, "mpn", "") or "").strip()
    search = search_url(provider.key, mpn) if mpn else ""
    return (search, "search") if search else ("", "")


def _evidence_identity(record):
    """The exact identity retained evidence is indexed under, or None when there can be none.

    Evidence is keyed by an already-canonical manufacturer and MPN, so a record whose identity
    is missing or not yet canonical has no evidence to find. Checking that here rather than
    letting `exact_identity` raise keeps a reference part's coverage answerable - its catalogue
    and asset evidence are still real - instead of failing the whole projection over a part that
    was never eligible.
    """
    manufacturer = str(getattr(record, "manufacturer", "") or "")
    mpn = str(getattr(record, "mpn", "") or "")
    if not manufacturer or not mpn:
        return None
    if manufacturer != manufacturer.strip() or mpn != mpn.strip():
        return None
    # Imported here so this projection does not drag the capture package into every caller that
    # only ever passes a record.
    from stockroom.capture.evidence import exact_identity

    return exact_identity(record)


# ------------------------------------------------------------------ the document


def _row(provider: ProviderRecord, record, grid: _Grid, notes, urls) -> dict[str, Any]:
    counts = dict.fromkeys(COVERAGE_STATUSES, 0)
    columns: dict[str, Any] = {}
    for artifact in COVERAGE_ARTIFACTS:
        status, origin = grid.cell(provider.key, _ANY_TOOL, artifact)
        counts[status] += 1
        columns[artifact] = {
            "status": status,
            "origin": origin,
            "userAssertion": (notes.get(provider.key) or {}).get(artifact),
        }
    url, url_kind = _access(provider, record, urls)
    total = len(COVERAGE_ARTIFACTS)
    row: dict[str, Any] = {
        "id": provider.key,
        "label": provider.label,
        "order": provider.order,
        "url": url,
        "urlKind": url_kind,
        "instruction": provider.instruction,
        "needsLogin": provider.needs_login,
        "aggregator": provider.aggregator,
        "distributor": provider.distributor,
        "statusCounts": counts,
        "complete": all(
            columns[artifact]["status"] in SUPPLIED_STATUSES for artifact in COVERAGE_ARTIFACTS
        ),
        **columns,
    }
    for tool in all_tools():
        supplied = sum(
            1
            for artifact in COVERAGE_ARTIFACTS
            if grid.cell(provider.key, tool.key, artifact)[0] in SUPPLIED_STATUSES
        )
        row[tool.key] = {
            "count": supplied,
            "total": total,
            "summary": f"{supplied}/{total}",
            "complete": supplied == total,
            # Whether the provider exports for this tool at all. A 0/3 on a provider that never
            # offered the tool is a different fact from a 0/3 on one that does.
            "supported": bool(getattr(provider, tool.key, False)),
        }
    return row


def provider_coverage(
    record,
    *,
    evidence=None,
    identity=None,
    candidates: Sequence[Any] = (),
) -> dict[str, Any]:
    """Every registered provider's coverage of one component, strongest evidence first.

    `evidence` is an `EvidenceStore` (or anything with its two listing methods) and `candidates`
    are `ingest.candidates.RetainedCandidate` values. Both are optional: with neither, coverage
    is what the record itself proves, which is exactly what a caller holding only a record can
    honestly say.

    Rows sort by what a person is actually choosing between: providers with validated artifacts
    first, then ones whose files we hold, then ones a catalogue explicitly named, and finally
    the registry's own stable order - so a table with no evidence at all is still the registry
    in its declared order rather than something reshuffled at random.
    """
    grid = _Grid()
    _apply_catalog(grid, record)
    _apply_assets(grid, record)
    if evidence is not None:
        resolved = identity if identity is not None else _evidence_identity(record)
        if resolved is not None:
            _apply_evidence_store(grid, evidence, resolved)
    _apply_candidates(grid, record, candidates)
    notes = _apply_user_assertions(grid, record)

    urls = _provider_urls(record)
    rows = [_row(provider, record, grid, notes, urls) for provider in all_providers()]
    rows.sort(
        key=lambda row: (
            -row["statusCounts"]["validated"],
            -row["statusCounts"]["downloaded"],
            -row["statusCounts"]["available"],
            row["order"],
        )
    )
    return {
        "artifacts": list(COVERAGE_ARTIFACTS),
        "statuses": list(COVERAGE_STATUSES),
        "tools": [tool.key for tool in all_tools()],
        "rows": rows,
        # The answer to "which provider can give me everything for this part", precomputed so no
        # reader has to re-derive it and get it subtly different.
        "completeProviders": [row["id"] for row in rows if row["complete"]],
    }


def set_user_assertion(
    record,
    *,
    provider: str,
    artifact: str,
    status: str,
    noted_at: str = "",
    note: str = "",
) -> None:
    """Record (or clear, with an empty status) one person's claim on the record itself.

    Loud on an unknown provider, artifact or status: a typo that became a silent no-op would
    leave a person believing they had corrected something they had not.
    """
    provider_key = registry_key(provider)
    if provider_key not in _REGISTRY:
        raise KeyError(f"unknown provider: {provider!r}")
    if artifact not in COVERAGE_ARTIFACTS:
        raise ValueError(f"unknown coverage artifact: {artifact!r}")
    if status and status not in USER_STATUSES:
        raise ValueError(f"a person may only assert {sorted(USER_STATUSES)}, not {status!r}")
    slots = record.provider_assertions.setdefault(provider_key, {})
    if not status:
        slots.pop(artifact, None)
        if not slots:
            record.provider_assertions.pop(provider_key, None)
        return
    slots[artifact] = ProviderAssertion(
        status=status,
        origin="user",
        noted_at=noted_at,
        note=note,
    )


__all__ = [
    "COVERAGE_ARTIFACTS",
    "COVERAGE_ORIGINS",
    "COVERAGE_STATUSES",
    "PROVEN_STATUSES",
    "SUPPLIED_STATUSES",
    "USER_STATUSES",
    "provider_coverage",
    "registry_key",
    "set_user_assertion",
]
