"""Durable, origin-independent UI continuity for the desktop renderer.

The WebView origin changes whenever the loopback server is restarted, so browser
storage cannot be the authority for in-progress UI state.  This module owns two
small, machine-local documents beside ``MachineConfig``:

* one replace-in-place UI snapshot (route, selections, filters and anchors);
* immutable, revisioned Add-a-Part review drafts referenced by that snapshot.

Both formats are deliberately narrow.  They reject unknown fields, bound every
collection and string, never accept native paths/handles or credential-shaped
fields, and are written with a same-directory ``os.replace``.  A draft revision
is staged before the snapshot points at it, so a failed snapshot replace leaves
the previous snapshot and its previous immutable draft revision valid.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import threading
import uuid
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit, urlunsplit

from stockroom.store.machine_config import MachineConfig, config_dir

SESSION_SCHEMA = "stockroom.ui-session"
# v2 adds the opened-component workspace: which components are open as tabs, which one is
# active, and each one's own view state. A stored v1 document upgrades on read (see
# `_migrated`), so an existing install keeps its route, filters, and picker anchor.
SESSION_VERSION = 3
DRAFT_SCHEMA = "stockroom.intake-draft"
DRAFT_VERSION = 1

SESSION_FILE_NAME = "ui-session.json"
DRAFT_DIRECTORY_NAME = "ui-session-drafts"
MAX_SESSION_BYTES = 64 * 1024
MAX_DRAFT_BYTES = 256 * 1024

_MAX_TEXT = 2_000
_MAX_SHORT_TEXT = 256
_MAX_ID = 192
_MAX_FILTERS = 48
_MAX_FILTER_VALUES = 64
_MAX_LIST = 128
_MAX_SAFE_JSON_DEPTH = 6
_MAX_SAFE_JSON_NODES = 2_048
_MAX_SCROLL_OFFSET = 10_000_000
_MAX_EVENT_SEQUENCE = (1 << 63) - 1

# One workspace tab per open component. Bounded so a long session cannot grow the durable
# document without limit; the frontend evicts the least-recently-active tab at the same bound.
_MAX_OPEN_COMPONENTS = 12
_INFO_TABS = {"overview", "specifications", "sourcing", "sources"}
_CAD_VIEWS = {"models", "manage-models"}
# Both are MEMBERSHIP vocabularies: the layout is validated against a set and the tool map is
# addressed by key, so neither sequence reaches a screen. The CAD column stacks 3D Model, Footprint,
# Symbol, and the layout set is written in that order so reading this file does not suggest otherwise.
# `_REPRESENTATION_KINDS` keeps the storage order it shares with `model.asset.ASSET_KINDS`, because it
# builds the key order of the durable `representation_tool` object.
_REPRESENTATION_LAYOUTS = {"all", "model", "footprint", "symbol"}
_REPRESENTATION_KINDS = ("symbol", "footprint", "model")

_ROUTES = {"components", "projects", "stm", "settings"}
_DETAIL_TABS = {"specs", "sourcing", "enrich", "history", "handoff"}
_SETTINGS_GROUPS = {"general", "library", "eda", "sources", "maintenance"}
_OPEN_SURFACES = {None, "search", "add_part", "complete_part"}
_STM_TABS = {"explorer", "compatibility"}
_PIN_VIEWS = {"map", "table"}
_SORT_DIRECTIONS = {"asc", "desc"}
_SIMPLE_SORT_KINDS = {"name", "stock", "unit"}
_NETWORK_INPUT_KINDS = {"mpn", "product_url"}

_SENSITIVE_KEY = re.compile(
    r"(?:^|[_\W])(?:password|passwd|secret|token|authorization|cookie|credential|"
    r"private[_-]?key|access[_-]?key)(?:$|[_\W])",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(?:"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}|"
    r"\bgithub_pat_[A-Za-z0-9_]{12,}|"
    r"\bgh[pousr]_[A-Za-z0-9]{12,}|"
    r"\b(?:api[_ -]?key|password|client[_ -]?secret|access[_ -]?token)\s*[:=]"
    r")",
    re.IGNORECASE,
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MPN = re.compile(r"^[\w .+\-/#():]{1,256}$", re.UNICODE)

_LOCK = threading.RLock()


class UiSessionConflict(ValueError):
    """A draft update was based on a stale immutable revision."""


def _invalid(field: str) -> ValueError:
    # Never include a submitted value in an error.  API errors can be reflected
    # into the renderer and logs, so hostile/secret input remains non-reflective.
    return ValueError(f"{field} is invalid")


def _expect_object(value: object, field: str) -> dict:
    if type(value) is not dict:
        raise _invalid(field)
    return value


def _expect_exact(
    value: object,
    *,
    field: str,
    required: set[str],
    optional: set[str] | None = None,
) -> dict:
    obj = _expect_object(value, field)
    optional = optional or set()
    keys = set(obj)
    if not all(type(key) is str for key in obj):
        raise _invalid(field)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        raise _invalid(field)
    return obj


def _text(
    value: object,
    field: str,
    *,
    maximum: int = _MAX_TEXT,
    allow_empty: bool = True,
) -> str:
    if type(value) is not str:
        raise _invalid(field)
    out = value.strip()
    if (not out and not allow_empty) or len(out) > maximum or _CONTROL.search(out):
        raise _invalid(field)
    if _SENSITIVE_VALUE.search(out):
        raise _invalid(field)
    return out


def _nullable_text(
    value: object,
    field: str,
    *,
    maximum: int = _MAX_ID,
) -> str | None:
    if value is None:
        return None
    return _text(value, field, maximum=maximum, allow_empty=False)


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise _invalid(field)
    return value


def _integer(
    value: object,
    field: str,
    *,
    minimum: int = 0,
    maximum: int = _MAX_EVENT_SEQUENCE,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _invalid(field)
    return value


def _number(value: object, field: str) -> int | float:
    if type(value) not in {int, float}:
        raise _invalid(field)
    number = cast(int | float, value)
    if not math.isfinite(number) or abs(number) > 1e100:
        raise _invalid(field)
    return number


def _enum(value: object, allowed: set, field: str):
    if value is not None and type(value) is not str:
        raise _invalid(field)
    if value not in allowed:
        raise _invalid(field)
    return value


def _text_list(
    value: object,
    field: str,
    *,
    maximum_items: int = _MAX_LIST,
    item_maximum: int = _MAX_SHORT_TEXT,
) -> list[str]:
    if type(value) is not list or len(value) > maximum_items:
        raise _invalid(field)
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        cleaned = _text(item, field, maximum=item_maximum, allow_empty=False)
        if cleaned in seen:
            raise _invalid(field)
        seen.add(cleaned)
        out.append(cleaned)
    return out


def default_snapshot() -> dict:
    """Return a fresh canonical snapshot at the current version."""

    return {
        "schema": SESSION_SCHEMA,
        "version": SESSION_VERSION,
        "route": "components",
        "open_components": [],
        "active_component": None,
        "component_views": {},
        "selected_ids": {
            "component": None,
            "project": None,
            "stm_part": None,
            "stm_pin": None,
            "workflow_batch": None,
            "workflow_item": None,
        },
        "component_filters": {
            "query": "",
            "category": None,
            "complete_only": False,
            "duplicates_only": False,
        },
        "component_list_anchor": {"part_id": None, "offset_px": 0},
        "search_filters": {
            "query": "",
            "category": None,
            "in_stock": False,
            "options": [],
            "ranges": [],
        },
        "search_sort": {"kind": "name", "direction": "asc"},
        "search_results": {
            "active_part_id": None,
            "anchor_part_id": None,
            "offset_px": 0,
        },
        "detail_tab": "specs",
        "stm": {
            "tab": "explorer",
            "families": [],
            "lines": [],
            "pin_view": "map",
        },
        "settings_group": "general",
        "open_surface": None,
        "intake_draft_ref": None,
        "event_sequence": 0,
    }


def _selected_ids(value: object) -> dict:
    obj = _expect_exact(
        value,
        field="selected_ids",
        required={
            "component",
            "project",
            "stm_part",
            "stm_pin",
            "workflow_batch",
            "workflow_item",
        },
    )
    return {
        key: _nullable_text(obj[key], f"selected_ids.{key}")
        for key in (
            "component",
            "project",
            "stm_part",
            "stm_pin",
            "workflow_batch",
            "workflow_item",
        )
    }


def _component_filters(value: object) -> dict:
    obj = _expect_exact(
        value,
        field="component_filters",
        required={"query", "category", "complete_only", "duplicates_only"},
    )
    return {
        "query": _text(obj["query"], "component_filters.query", maximum=512),
        "category": _nullable_text(
            obj["category"], "component_filters.category", maximum=_MAX_SHORT_TEXT
        ),
        "complete_only": _boolean(
            obj["complete_only"], "component_filters.complete_only"
        ),
        "duplicates_only": _boolean(
            obj["duplicates_only"], "component_filters.duplicates_only"
        ),
    }


def _anchor(value: object, field: str, *, id_key: str) -> dict:
    obj = _expect_exact(
        value,
        field=field,
        required={id_key, "offset_px"},
    )
    return {
        id_key: _nullable_text(obj[id_key], f"{field}.{id_key}"),
        "offset_px": _integer(
            obj["offset_px"],
            f"{field}.offset_px",
            maximum=_MAX_SCROLL_OFFSET,
        ),
    }


def _search_filters(value: object) -> dict:
    obj = _expect_exact(
        value,
        field="search_filters",
        required={"query", "category", "in_stock", "options", "ranges"},
    )
    raw_options = obj["options"]
    if type(raw_options) is not list or len(raw_options) > _MAX_FILTERS:
        raise _invalid("search_filters.options")
    options: list[dict] = []
    option_keys: set[str] = set()
    for item in raw_options:
        entry = _expect_exact(
            item,
            field="search_filters.options",
            required={"key", "values"},
        )
        key = _text(
            entry["key"],
            "search_filters.options.key",
            maximum=_MAX_SHORT_TEXT,
            allow_empty=False,
        )
        if key in option_keys:
            raise _invalid("search_filters.options")
        option_keys.add(key)
        options.append(
            {
                "key": key,
                "values": _text_list(
                    entry["values"],
                    "search_filters.options.values",
                    maximum_items=_MAX_FILTER_VALUES,
                ),
            }
        )

    raw_ranges = obj["ranges"]
    if type(raw_ranges) is not list or len(raw_ranges) > _MAX_FILTERS:
        raise _invalid("search_filters.ranges")
    ranges: list[dict] = []
    range_keys: set[str] = set()
    for item in raw_ranges:
        entry = _expect_exact(
            item,
            field="search_filters.ranges",
            required={"key", "min", "max"},
        )
        key = _text(
            entry["key"],
            "search_filters.ranges.key",
            maximum=_MAX_SHORT_TEXT,
            allow_empty=False,
        )
        if key in range_keys:
            raise _invalid("search_filters.ranges")
        range_keys.add(key)
        minimum = (
            None
            if entry["min"] is None
            else _number(entry["min"], "search_filters.ranges.min")
        )
        maximum = (
            None
            if entry["max"] is None
            else _number(entry["max"], "search_filters.ranges.max")
        )
        if minimum is not None and maximum is not None and minimum > maximum:
            raise _invalid("search_filters.ranges")
        ranges.append({"key": key, "min": minimum, "max": maximum})

    return {
        "query": _text(obj["query"], "search_filters.query", maximum=512),
        "category": _nullable_text(
            obj["category"], "search_filters.category", maximum=_MAX_SHORT_TEXT
        ),
        "in_stock": _boolean(obj["in_stock"], "search_filters.in_stock"),
        "options": options,
        "ranges": ranges,
    }


def _search_sort(value: object) -> dict:
    obj = _expect_object(value, "search_sort")
    kind = obj.get("kind")
    if kind in _SIMPLE_SORT_KINDS:
        obj = _expect_exact(
            obj,
            field="search_sort",
            required={"kind", "direction"},
        )
        return {
            "kind": kind,
            "direction": _enum(
                obj["direction"], _SORT_DIRECTIONS, "search_sort.direction"
            ),
        }
    if kind == "spec":
        obj = _expect_exact(
            obj,
            field="search_sort",
            required={"kind", "key", "numeric", "direction"},
        )
        return {
            "kind": "spec",
            "key": _text(
                obj["key"],
                "search_sort.key",
                maximum=_MAX_SHORT_TEXT,
                allow_empty=False,
            ),
            "numeric": _boolean(obj["numeric"], "search_sort.numeric"),
            "direction": _enum(
                obj["direction"], _SORT_DIRECTIONS, "search_sort.direction"
            ),
        }
    raise _invalid("search_sort")


def _search_results(value: object) -> dict:
    obj = _expect_exact(
        value,
        field="search_results",
        required={"active_part_id", "anchor_part_id", "offset_px"},
    )
    return {
        "active_part_id": _nullable_text(
            obj["active_part_id"], "search_results.active_part_id"
        ),
        "anchor_part_id": _nullable_text(
            obj["anchor_part_id"], "search_results.anchor_part_id"
        ),
        "offset_px": _integer(
            obj["offset_px"],
            "search_results.offset_px",
            maximum=_MAX_SCROLL_OFFSET,
        ),
    }


def _stm(value: object) -> dict:
    obj = _expect_exact(
        value,
        field="stm",
        required={"tab", "families", "lines", "pin_view"},
    )
    return {
        "tab": _enum(obj["tab"], _STM_TABS, "stm.tab"),
        "families": _text_list(
            obj["families"], "stm.families", maximum_items=32
        ),
        "lines": _text_list(obj["lines"], "stm.lines", maximum_items=64),
        "pin_view": _enum(obj["pin_view"], _PIN_VIEWS, "stm.pin_view"),
    }


def _draft_ref(value: object) -> dict | None:
    if value is None:
        return None
    obj = _expect_exact(
        value,
        field="intake_draft_ref",
        required={"draft_id", "revision"},
    )
    try:
        draft_id = str(uuid.UUID(_text(obj["draft_id"], "intake_draft_ref.draft_id")))
    except (ValueError, AttributeError):
        raise _invalid("intake_draft_ref.draft_id") from None
    return {
        "draft_id": draft_id,
        "revision": _integer(
            obj["revision"], "intake_draft_ref.revision", minimum=1
        ),
    }


def _component_view(value: object, field: str) -> dict:
    obj = _expect_exact(
        value,
        field=field,
        required={"info_tab", "cad_view", "representation_layout", "representation_tool"},
    )
    tools = _expect_exact(
        obj["representation_tool"],
        field=f"{field}.representation_tool",
        required=set(_REPRESENTATION_KINDS),
    )
    return {
        "info_tab": _enum(obj["info_tab"], _INFO_TABS, f"{field}.info_tab"),
        "cad_view": _enum(obj["cad_view"], _CAD_VIEWS, f"{field}.cad_view"),
        "representation_layout": _enum(
            obj["representation_layout"],
            _REPRESENTATION_LAYOUTS,
            f"{field}.representation_layout",
        ),
        "representation_tool": {
            kind: _text(
                tools[kind],
                f"{field}.representation_tool.{kind}",
                maximum=_MAX_SHORT_TEXT,
            )
            for kind in _REPRESENTATION_KINDS
        },
    }


def _component_views(value: object, open_components: list[str]) -> dict:
    """Per-component view state, kept only for components that are actually open.

    Pruning rather than rejecting: a view entry for a closed tab is stale bookkeeping, and
    throwing away the whole durable session over it would cost the person their route,
    filters, and picker position for no benefit.
    """
    if type(value) is not dict or len(value) > _MAX_OPEN_COMPONENTS:
        raise _invalid("component_views")
    open_set = set(open_components)
    out: dict[str, dict] = {}
    for key, entry in value.items():
        component_id = _text(key, "component_views", maximum=_MAX_ID, allow_empty=False)
        if component_id not in open_set:
            continue
        out[component_id] = _component_view(entry, f"component_views.{component_id}")
    return out


def _migrated(value: object) -> object:
    """Upgrade an older stored snapshot in place of rejecting it.

    Only the exact previous version is upgraded, and only when it is otherwise the shape this
    module wrote. Anything else falls through to validation, which fails closed to defaults -
    a document from a NEWER build must never be silently downgraded and re-saved as ours.
    """
    if type(value) is not dict:
        return value
    if value.get("schema") != SESSION_SCHEMA or value.get("version") not in {1, 2}:
        return value
    upgraded = dict(value)
    if upgraded["version"] == 1:
        selected = upgraded.get("selected_ids")
        component = selected.get("component") if type(selected) is dict else None
        upgraded["version"] = 2
        upgraded["open_components"] = [component] if type(component) is str and component else []
        upgraded["active_component"] = component if type(component) is str and component else None
        upgraded["component_views"] = {}
    if upgraded["version"] == 2:
        views = upgraded.get("component_views")
        if type(views) is dict:
            upgraded["component_views"] = {
                key: {**entry, "cad_view": "models"} if type(entry) is dict else entry
                for key, entry in views.items()
            }
        upgraded["version"] = SESSION_VERSION
    return upgraded


def normalize_snapshot(value: object) -> dict:
    """Validate and return the canonical snapshot without unknown fields."""

    obj = _expect_exact(
        _migrated(value),
        field="ui_session",
        required={
            "schema",
            "version",
            "open_components",
            "active_component",
            "component_views",
            "route",
            "selected_ids",
            "component_filters",
            "component_list_anchor",
            "search_filters",
            "search_sort",
            "search_results",
            "detail_tab",
            "stm",
            "settings_group",
            "open_surface",
            "intake_draft_ref",
            "event_sequence",
        },
    )
    if obj["schema"] != SESSION_SCHEMA or obj["version"] != SESSION_VERSION:
        raise _invalid("ui_session.schema")
    selected = _selected_ids(obj["selected_ids"])
    open_surface = _enum(obj["open_surface"], _OPEN_SURFACES, "open_surface")
    if open_surface == "complete_part" and selected["component"] is None:
        raise _invalid("open_surface")
    open_components = _text_list(
        obj["open_components"],
        "open_components",
        maximum_items=_MAX_OPEN_COMPONENTS,
        item_maximum=_MAX_ID,
    )
    active_component = _nullable_text(obj["active_component"], "active_component")
    # The active tab must be one of the open ones. Coerced rather than rejected for the same
    # reason stale view entries are pruned: the inconsistency is bookkeeping, and failing the
    # whole document closed would discard everything else the person had restored.
    if active_component not in open_components:
        active_component = None
    snapshot = {
        "schema": SESSION_SCHEMA,
        "version": SESSION_VERSION,
        "route": _enum(obj["route"], _ROUTES, "route"),
        "open_components": open_components,
        "active_component": active_component,
        "component_views": _component_views(obj["component_views"], open_components),
        "selected_ids": selected,
        "component_filters": _component_filters(obj["component_filters"]),
        "component_list_anchor": _anchor(
            obj["component_list_anchor"],
            "component_list_anchor",
            id_key="part_id",
        ),
        "search_filters": _search_filters(obj["search_filters"]),
        "search_sort": _search_sort(obj["search_sort"]),
        "search_results": _search_results(obj["search_results"]),
        "detail_tab": _enum(obj["detail_tab"], _DETAIL_TABS, "detail_tab"),
        "stm": _stm(obj["stm"]),
        "settings_group": _enum(
            obj["settings_group"], _SETTINGS_GROUPS, "settings_group"
        ),
        "open_surface": open_surface,
        "intake_draft_ref": _draft_ref(obj["intake_draft_ref"]),
        "event_sequence": _integer(obj["event_sequence"], "event_sequence"),
    }
    _encoded(snapshot, MAX_SESSION_BYTES, "ui_session")
    return snapshot


def _safe_url(value: object, field: str, *, allow_empty: bool = True) -> str:
    raw = _text(value, field, maximum=_MAX_TEXT, allow_empty=allow_empty)
    if not raw:
        return ""
    parts = urlsplit(raw)
    if (
        parts.scheme.casefold() not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
    ):
        raise _invalid(field)
    # Tracking/query values can contain account or session material and are not
    # needed to identify a distributor product page in a resumable draft.
    return urlunsplit(
        (
            parts.scheme.casefold(),
            parts.netloc,
            parts.path or "/",
            "",
            "",
        )
    )


def _network_input(value: object, field: str) -> dict:
    obj = _expect_exact(
        value,
        field=field,
        required={"kind", "value"},
    )
    kind = _enum(obj["kind"], _NETWORK_INPUT_KINDS, f"{field}.kind")
    if kind == "product_url":
        cleaned = _safe_url(obj["value"], f"{field}.value", allow_empty=False)
    else:
        cleaned = _text(
            obj["value"],
            f"{field}.value",
            maximum=_MAX_SHORT_TEXT,
            allow_empty=False,
        )
        if not _MPN.fullmatch(cleaned):
            raise _invalid(f"{field}.value")
    return {"kind": kind, "value": cleaned}


def _safe_json(
    value: object,
    field: str,
    *,
    depth: int = 0,
    budget: list[int] | None = None,
):
    """Bound a JSON value used only inside explicitly allowlisted review fields."""

    if budget is None:
        budget = [_MAX_SAFE_JSON_NODES]
    budget[0] -= 1
    if budget[0] < 0 or depth > _MAX_SAFE_JSON_DEPTH:
        raise _invalid(field)
    if value is None or type(value) is bool:
        return value
    if type(value) in {int, float}:
        return _number(value, field)
    if type(value) is str:
        if value.strip().casefold().startswith(("http://", "https://")):
            return _safe_url(value, field)
        return _text(value, field)
    if type(value) is list:
        if len(value) > _MAX_LIST:
            raise _invalid(field)
        return [
            _safe_json(item, field, depth=depth + 1, budget=budget)
            for item in value
        ]
    if type(value) is dict:
        if len(value) > _MAX_LIST:
            raise _invalid(field)
        out: dict[str, object] = {}
        for key, item in value.items():
            clean_key = _text(
                key,
                field,
                maximum=_MAX_SHORT_TEXT,
                allow_empty=False,
            )
            if _SENSITIVE_KEY.search(clean_key):
                raise _invalid(field)
            out[clean_key] = _safe_json(
                item, field, depth=depth + 1, budget=budget
            )
        return out
    raise _invalid(field)


def _sourced(value: object, field: str) -> dict:
    obj = _expect_exact(
        value,
        field=field,
        required={"value", "source", "confidence"},
    )
    return {
        "value": _safe_json(obj["value"], f"{field}.value"),
        "source": _text(
            obj["source"], f"{field}.source", maximum=_MAX_SHORT_TEXT
        ),
        "confidence": _text(
            obj["confidence"], f"{field}.confidence", maximum=64
        ),
    }


def _enrichment_result(value: object) -> dict | None:
    if value is None:
        return None
    required = {
        "category",
        "mpn",
        "manufacturer",
        "description",
        "datasheet_url",
        "stock",
        "package",
        "price_breaks",
        "specs",
        "schema_version",
    }
    optional = {
        "lifecycle",
        "lead_time",
        "product_url",
        "dist_pns",
        "dist_price_breaks",
        "dist_stock",
        "dist_urls",
        "spec_conflicts",
        "field_conflicts",
        "add_plan",
        "catalog",
        "source_states",
        "identity_suggestions",
    }
    obj = _expect_exact(
        value,
        field="review.enrichment_result",
        required=required,
        optional=optional,
    )
    # The enrichment DTO itself is already versioned and allowlisted above.  Its
    # dynamic distributor/spec maps are bounded recursively and reject secret-
    # shaped keys/values; no fetched HTML or response bytes are accepted.
    return _safe_json(obj, "review.enrichment_result")


def _purchase(value: object) -> dict:
    obj = _expect_exact(
        value,
        field="review.candidates.purchase",
        required={
            "vendor",
            "url",
            "part_number",
            "price_breaks",
            "stock",
            "currency",
            "fetched_at",
        },
    )
    stock = obj["stock"]
    if stock is not None:
        stock = _integer(
            stock,
            "review.candidates.purchase.stock",
            maximum=1_000_000_000_000,
        )
    price_breaks = obj["price_breaks"]
    if type(price_breaks) is not list or len(price_breaks) > 128:
        raise _invalid("review.candidates.purchase.price_breaks")
    clean_breaks: list[dict] = []
    for item in price_breaks:
        entry = _expect_exact(
            item,
            field="review.candidates.purchase.price_breaks",
            required={"qty", "price", "currency"},
        )
        clean_breaks.append(
            {
                "qty": _integer(
                    entry["qty"],
                    "review.candidates.purchase.price_breaks.qty",
                    minimum=0,
                    maximum=1_000_000_000_000,
                ),
                "price": _number(
                    entry["price"],
                    "review.candidates.purchase.price_breaks.price",
                ),
                "currency": _text(
                    entry["currency"],
                    "review.candidates.purchase.price_breaks.currency",
                    maximum=16,
                ),
            }
        )
    return {
        "vendor": _text(
            obj["vendor"],
            "review.candidates.purchase.vendor",
            maximum=_MAX_SHORT_TEXT,
        ),
        "url": _safe_url(obj["url"], "review.candidates.purchase.url"),
        "part_number": _text(
            obj["part_number"],
            "review.candidates.purchase.part_number",
            maximum=_MAX_SHORT_TEXT,
        ),
        "price_breaks": clean_breaks,
        "stock": stock,
        "currency": _text(
            obj["currency"],
            "review.candidates.purchase.currency",
            maximum=16,
        ),
        "fetched_at": _text(
            obj["fetched_at"],
            "review.candidates.purchase.fetched_at",
            maximum=64,
        ),
    }


def _keyed_values(value: object, field: str, *, confidence: bool) -> list[dict]:
    if type(value) is not list or len(value) > _MAX_FILTERS:
        raise _invalid(field)
    out: list[dict] = []
    keys: set[str] = set()
    for item in value:
        entry = _expect_exact(
            item,
            field=field,
            required={"key", "values"},
        )
        key = _text(
            entry["key"], f"{field}.key", maximum=_MAX_SHORT_TEXT, allow_empty=False
        )
        if key in keys:
            raise _invalid(field)
        keys.add(key)
        raw_values = entry["values"]
        if type(raw_values) is not list or len(raw_values) > _MAX_FILTER_VALUES:
            raise _invalid(field)
        clean_values: list[dict] = []
        for raw in raw_values:
            required = {"value", "source", "confidence"} if confidence else {
                "value",
                "source",
            }
            sourced = _expect_exact(raw, field=f"{field}.values", required=required)
            clean = {
                "value": _safe_json(sourced["value"], f"{field}.values.value"),
                "source": _text(
                    sourced["source"],
                    f"{field}.values.source",
                    maximum=_MAX_SHORT_TEXT,
                ),
            }
            if confidence:
                clean["confidence"] = _text(
                    sourced["confidence"],
                    f"{field}.values.confidence",
                    maximum=64,
                )
            clean_values.append(clean)
        out.append({"key": key, "values": clean_values})
    return out


def _candidate(value: object) -> dict:
    obj = _expect_exact(
        value,
        field="review.candidates",
        required={
            "client_id",
            "vendor",
            "display_name",
            "entry_name",
            "category",
            "mpn",
            "manufacturer",
            "description",
            "tags",
            "purchase",
            "gaps",
            "specs",
            "alternates",
            "enrichment",
            "datasheet_url",
            "conflicts",
        },
    )
    purchases = obj["purchase"]
    if type(purchases) is not list or len(purchases) > 32:
        raise _invalid("review.candidates.purchase")
    specs = obj["specs"]
    if type(specs) is not list or len(specs) > _MAX_LIST:
        raise _invalid("review.candidates.specs")
    clean_specs: list[dict] = []
    spec_keys: set[str] = set()
    for item in specs:
        entry = _expect_exact(
            item,
            field="review.candidates.specs",
            required={"key", "value"},
        )
        key = _text(
            entry["key"],
            "review.candidates.specs.key",
            maximum=_MAX_SHORT_TEXT,
            allow_empty=False,
        )
        if key in spec_keys or _SENSITIVE_KEY.search(key):
            raise _invalid("review.candidates.specs")
        spec_keys.add(key)
        clean_specs.append(
            {
                "key": key,
                "value": _safe_json(
                    entry["value"], "review.candidates.specs.value"
                ),
            }
        )
    enrichment = obj["enrichment"]
    if type(enrichment) is not list or len(enrichment) > _MAX_LIST:
        raise _invalid("review.candidates.enrichment")
    clean_enrichment: list[dict] = []
    enrichment_keys: set[str] = set()
    for item in enrichment:
        entry = _expect_exact(
            item,
            field="review.candidates.enrichment",
            required={"key", "source", "confidence"},
        )
        key = _text(
            entry["key"],
            "review.candidates.enrichment.key",
            maximum=_MAX_SHORT_TEXT,
            allow_empty=False,
        )
        if key in enrichment_keys or _SENSITIVE_KEY.search(key):
            raise _invalid("review.candidates.enrichment")
        enrichment_keys.add(key)
        clean_enrichment.append(
            {
                "key": key,
                "source": _text(
                    entry["source"],
                    "review.candidates.enrichment.source",
                    maximum=_MAX_SHORT_TEXT,
                ),
                "confidence": _text(
                    entry["confidence"],
                    "review.candidates.enrichment.confidence",
                    maximum=64,
                ),
            }
        )
    return {
        "client_id": _text(
            obj["client_id"],
            "review.candidates.client_id",
            maximum=_MAX_ID,
            allow_empty=False,
        ),
        "vendor": _text(
            obj["vendor"], "review.candidates.vendor", maximum=_MAX_SHORT_TEXT
        ),
        "display_name": _text(
            obj["display_name"], "review.candidates.display_name"
        ),
        "entry_name": _text(
            obj["entry_name"],
            "review.candidates.entry_name",
            maximum=_MAX_SHORT_TEXT,
        ),
        "category": _text(
            obj["category"],
            "review.candidates.category",
            maximum=_MAX_SHORT_TEXT,
        ),
        "mpn": _text(
            obj["mpn"], "review.candidates.mpn", maximum=_MAX_SHORT_TEXT
        ),
        "manufacturer": _text(
            obj["manufacturer"],
            "review.candidates.manufacturer",
            maximum=_MAX_SHORT_TEXT,
        ),
        "description": _text(
            obj["description"], "review.candidates.description"
        ),
        "tags": _text_list(obj["tags"], "review.candidates.tags"),
        "purchase": [_purchase(item) for item in purchases],
        "gaps": _text_list(obj["gaps"], "review.candidates.gaps"),
        "specs": clean_specs,
        "alternates": _keyed_values(
            obj["alternates"],
            "review.candidates.alternates",
            confidence=True,
        ),
        "enrichment": clean_enrichment,
        "datasheet_url": _safe_url(
            obj["datasheet_url"], "review.candidates.datasheet_url"
        ),
        "conflicts": _keyed_values(
            obj["conflicts"],
            "review.candidates.conflicts",
            confidence=False,
        ),
    }


def normalize_review(value: object) -> dict:
    obj = _expect_exact(
        value,
        field="review",
        required={"lookup_input", "enrichment_result", "candidates"},
    )
    lookup = (
        None
        if obj["lookup_input"] is None
        else _network_input(obj["lookup_input"], "review.lookup_input")
    )
    candidates = obj["candidates"]
    if type(candidates) is not list or len(candidates) > 16:
        raise _invalid("review.candidates")
    return {
        "lookup_input": lookup,
        "enrichment_result": _enrichment_result(obj["enrichment_result"]),
        "candidates": [_candidate(item) for item in candidates],
    }


def _draft_document(
    draft_id: str,
    revision: int,
    network_input: object,
    review: object,
) -> dict:
    try:
        clean_id = str(uuid.UUID(draft_id))
    except (ValueError, AttributeError):
        raise _invalid("draft_id") from None
    document = {
        "schema": DRAFT_SCHEMA,
        "version": DRAFT_VERSION,
        "draft_id": clean_id,
        "revision": _integer(revision, "revision", minimum=1),
        "network_input": _network_input(network_input, "network_input"),
        "review": normalize_review(review),
    }
    _encoded(document, MAX_DRAFT_BYTES, "intake_draft")
    return document


def normalize_draft(value: object) -> dict:
    obj = _expect_exact(
        value,
        field="intake_draft",
        required={
            "schema",
            "version",
            "draft_id",
            "revision",
            "network_input",
            "review",
        },
    )
    if obj["schema"] != DRAFT_SCHEMA or obj["version"] != DRAFT_VERSION:
        raise _invalid("intake_draft.schema")
    return _draft_document(
        obj["draft_id"],
        obj["revision"],
        obj["network_input"],
        obj["review"],
    )


def normalize_draft_create(value: object) -> dict:
    obj = _expect_exact(
        value,
        field="intake_draft",
        required={"network_input", "review"},
    )
    return {
        "network_input": _network_input(obj["network_input"], "network_input"),
        "review": normalize_review(obj["review"]),
    }


def normalize_draft_update(value: object) -> dict:
    obj = _expect_exact(
        value,
        field="intake_draft",
        required={"revision", "network_input", "review"},
    )
    return {
        "revision": _integer(obj["revision"], "revision", minimum=1),
        "network_input": _network_input(obj["network_input"], "network_input"),
        "review": normalize_review(obj["review"]),
    }


def _config_root(config: MachineConfig | None = None) -> Path:
    source = getattr(config, "source_path", None) if config is not None else None
    return Path(source).parent if source is not None else config_dir()


def snapshot_path(config: MachineConfig | None = None) -> Path:
    return _config_root(config) / SESSION_FILE_NAME


def draft_directory(config: MachineConfig | None = None) -> Path:
    return _config_root(config) / DRAFT_DIRECTORY_NAME


def _draft_path(
    draft_id: str,
    revision: int,
    config: MachineConfig | None = None,
) -> Path:
    try:
        clean_id = str(uuid.UUID(draft_id))
    except (ValueError, AttributeError):
        raise _invalid("draft_id") from None
    clean_revision = _integer(revision, "revision", minimum=1)
    return draft_directory(config) / f"{clean_id}.{clean_revision}.json"


def _encoded(document: object, maximum: int, field: str) -> bytes:
    try:
        payload = json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise _invalid(field) from None
    if len(payload) > maximum:
        raise _invalid(field)
    return payload + b"\n"


def _reject_constant(_value: str):
    raise ValueError("non-finite JSON number")


def _pairs_object(pairs: list[tuple[str, object]]) -> dict:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON key")
        out[key] = value
    return out


def decode_json(payload: bytes, *, maximum: int, field: str) -> object:
    if len(payload) > maximum:
        raise _invalid(field)
    try:
        text = payload.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=_pairs_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise _invalid(field) from None


def _read(path: Path, maximum: int, field: str) -> object:
    try:
        if path.stat().st_size > maximum:
            raise _invalid(field)
        payload = path.read_bytes()
    except FileNotFoundError:
        raise
    return decode_json(payload, maximum=maximum, field=field)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def load_snapshot(
    config: MachineConfig | None = None,
    *,
    verify_draft: bool = True,
) -> dict:
    path = snapshot_path(config)
    try:
        value = _read(path, MAX_SESSION_BYTES, "ui_session")
    except FileNotFoundError:
        return default_snapshot()
    document = normalize_snapshot(value)
    ref = document["intake_draft_ref"]
    if verify_draft and ref is not None:
        load_draft(ref["draft_id"], ref["revision"], config)
    return document


def _latest_revision(
    draft_id: str,
    config: MachineConfig | None = None,
) -> int | None:
    directory = draft_directory(config)
    if not directory.exists():
        return None
    try:
        clean_id = str(uuid.UUID(draft_id))
    except (ValueError, AttributeError):
        raise _invalid("draft_id") from None
    latest: int | None = None
    for path in directory.glob(f"{clean_id}.*.json"):
        try:
            revision = int(path.name.removeprefix(f"{clean_id}.").removesuffix(".json"))
        except ValueError:
            continue
        if revision >= 1 and (latest is None or revision > latest):
            latest = revision
    return latest


def load_draft(
    draft_id: str,
    revision: int | None = None,
    config: MachineConfig | None = None,
) -> dict:
    if revision is None:
        revision = _latest_revision(draft_id, config)
        if revision is None:
            raise FileNotFoundError("intake draft does not exist")
    path = _draft_path(draft_id, revision, config)
    value = _read(path, MAX_DRAFT_BYTES, "intake_draft")
    document = normalize_draft(value)
    if document["draft_id"] != str(uuid.UUID(draft_id)) or document["revision"] != revision:
        raise _invalid("intake_draft")
    return document


def create_draft(
    value: object,
    config: MachineConfig | None = None,
) -> dict:
    clean = normalize_draft_create(value)
    with _LOCK:
        document = _draft_document(
            str(uuid.uuid4()),
            1,
            clean["network_input"],
            clean["review"],
        )
        _atomic_write(
            _draft_path(document["draft_id"], 1, config),
            _encoded(document, MAX_DRAFT_BYTES, "intake_draft"),
        )
        return document


def update_draft(
    draft_id: str,
    value: object,
    config: MachineConfig | None = None,
) -> dict:
    clean = normalize_draft_update(value)
    with _LOCK:
        latest = _latest_revision(draft_id, config)
        if latest is None:
            raise FileNotFoundError("intake draft does not exist")
        if latest != clean["revision"]:
            raise UiSessionConflict("intake draft revision is stale")
        document = _draft_document(
            str(uuid.UUID(draft_id)),
            latest + 1,
            clean["network_input"],
            clean["review"],
        )
        _atomic_write(
            _draft_path(document["draft_id"], document["revision"], config),
            _encoded(document, MAX_DRAFT_BYTES, "intake_draft"),
        )
        return document


def delete_draft(
    draft_id: str,
    config: MachineConfig | None = None,
) -> None:
    # Every target is reconstructed from a parsed UUID inside the dedicated
    # config subdirectory; no caller-supplied path segment reaches unlink().
    try:
        clean_id = str(uuid.UUID(draft_id))
    except (ValueError, AttributeError):
        raise _invalid("draft_id") from None
    with _LOCK:
        directory = draft_directory(config)
        found = False
        if directory.exists():
            for path in directory.glob(f"{clean_id}.*.json"):
                path.unlink()
                found = True
        if not found:
            raise FileNotFoundError("intake draft does not exist")


def save_snapshot(
    value: object,
    config: MachineConfig | None = None,
    *,
    verify_draft: bool = True,
) -> dict:
    document = normalize_snapshot(value)
    with _LOCK:
        ref = document["intake_draft_ref"]
        if verify_draft and ref is not None:
            load_draft(ref["draft_id"], ref["revision"], config)
        _atomic_write(
            snapshot_path(config),
            _encoded(document, MAX_SESSION_BYTES, "ui_session"),
        )
    return document


def stage_exported_draft(
    value: object,
    config: MachineConfig | None = None,
) -> dict:
    obj = _expect_exact(
        value,
        field="intake_draft",
        required={"draft_id", "revision", "network_input", "review"},
    )
    draft_id = obj["draft_id"]
    revision = obj["revision"]
    if draft_id is None:
        if revision != 0:
            raise _invalid("intake_draft.revision")
        return create_draft(
            {"network_input": obj["network_input"], "review": obj["review"]},
            config,
        )
    return update_draft(
        _text(draft_id, "intake_draft.draft_id", allow_empty=False),
        {
            "revision": revision,
            "network_input": obj["network_input"],
            "review": obj["review"],
        },
        config,
    )


def persist_export_envelope(
    value: object,
    config: MachineConfig | None = None,
) -> dict:
    """Persist a synchronous renderer export before navigation.

    The optional full intake draft is written first.  Its returned immutable
    reference replaces whatever reference the renderer supplied, then the
    snapshot is atomically replaced.  An invalid hook result writes nothing.
    """

    envelope = _expect_exact(
        value,
        field="ui_session_export",
        required={"snapshot"},
        optional={"intake_draft"},
    )
    # Validate the snapshot before staging a draft so an invalid envelope cannot
    # manufacture orphan revisions.  A supplied draft is allowed to replace the
    # snapshot's reference only after it is itself valid and durably staged.
    snapshot = normalize_snapshot(envelope["snapshot"])
    draft_value = envelope.get("intake_draft")
    if draft_value is not None:
        draft = stage_exported_draft(draft_value, config)
        snapshot = {
            **snapshot,
            "intake_draft_ref": {
                "draft_id": draft["draft_id"],
                "revision": draft["revision"],
            },
        }
    return save_snapshot(snapshot, config)


def bootstrap_script(snapshot: object) -> str:
    """Return a script-safe synchronous bootstrap assignment."""

    document = normalize_snapshot(snapshot)
    payload = json.dumps(
        document,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    return f"window.__STOCKROOM_SESSION__ = {payload};\n"
