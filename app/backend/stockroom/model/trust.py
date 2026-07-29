"""Trust: STORE THE EVIDENCE, DERIVE THE VERDICT.

DECIDED in `docs/specs/2026-07-27-owner-spec-complete-trusted-library.md` section 6 (D2). An
asset records FACTS - what checks ran, what each measured, against what authority. PASS / FAIL
/ UNKNOWN is computed from those facts on read and is NEVER stored.

Two properties follow, and they are the reason for the split:

  - **Tightening a check re-judges the whole library with no re-audit.** The judgement lives in
    code; only the measurements live on disk.
  - **A verdict can never silently disagree with its own evidence**, because there is no second
    copy of it to go stale.

REJECTED (recorded so it is not re-proposed): a STORED verdict - it goes stale the moment a
check changes and can contradict the very numbers printed beside it; and compute-everything-live
- unusable at 10,000 parts, and it keeps no history of what was checked, when, or against which
datasheet revision.

**UNKNOWN is mandatory, not a convenience.** A check that could not run must never claim either
outcome. The cost of getting this wrong is measured and on the record: on 2026-07-27 a
package-vs-pad-count check reported 16 mismatches on the owner's library and ALL 16 were false
positives (it read "SOT-23" as 23 pins). A false-positive machine is worse than no check.

PRIOR ART (checked before writing): this is the shape of a test-result model - pytest's
passed/failed/skipped, TAP's ok/not ok/SKIP, JUnit's failure/skipped - and the three-valued
outcome is taken from them deliberately, because every one of those formats learned the same
lesson: a run that did not happen is not a run that succeeded. No library is adopted, because
what is stored here is a MEASUREMENT (measured, expected, authority, tolerance), not a test
report, and the verdict has to be recomputable from those numbers by anyone reading the record.

**TRUST IS NOT PRESENCE.** Whether a part HAS a footprint is answered by `missing_assets`; this
module only judges assets that exist. Conflating the two is what made a coverage matrix read
like a quality claim.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import TypeGuard


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


# Worst first. A FAIL outranks everything (something is measurably wrong), and an UNKNOWN
# outranks a PASS (evidence is missing, so the PASS does not cover the whole asset).
_WORST_FIRST: tuple[Verdict, ...] = (Verdict.FAIL, Verdict.UNKNOWN, Verdict.PASS)


@dataclass
class AssetCheck:
    """ONE measurement taken against an asset. Facts only - no verdict is stored here.

    The owner selected these four checks (spec section 3), and the shape carries all of them
    without naming any: symbol pins vs datasheet pinout, footprint pads vs package dimensions,
    3D bounding box vs footprint courtyard size, category vs description.

    `measured is None` means the check COULD NOT MEASURE, and `expected is None` means there
    was no authority to compare against. Either one is UNKNOWN, and neither is a failure. Note
    that `0` is a real measurement and must never be confused with "missing" - a confirmed
    zero-pad footprint is a genuine result.
    """

    # The check's stable id, e.g. "pins_vs_datasheet". Free-form here on purpose: the checks
    # themselves are built and PROVEN one at a time against parts the owner has confirmed are
    # broken (spec section 3), and a closed enum would gate that work on a schema change.
    check: str = ""
    # What the asset actually has.
    measured: object = None
    # What the authority says it should have.
    expected: object = None
    # The authority itself: "datasheet rev C", "JEDEC MO-220", "Mouser package field". Without
    # it a stale PASS is indistinguishable from a current one.
    against: str = ""
    checked_at: str = ""
    # Absolute tolerance for a numeric comparison, e.g. a courtyard measured in mm. A FACT
    # about how the check was run, not a judgement, so it belongs with the evidence. None
    # means exact equality is required.
    tolerance: float | None = None
    note: str = ""
    # Keys a newer build wrote here, kept verbatim and re-emitted.
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        # Unknown keys first so a known one can never be shadowed by a stale preserved copy.
        return {
            **self.extra,
            "check": self.check,
            "measured": self.measured,
            "expected": self.expected,
            "against": self.against,
            "checked_at": self.checked_at,
            "tolerance": self.tolerance,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AssetCheck":
        known = {"check", "measured", "expected", "against", "checked_at", "tolerance", "note"}
        return cls(
            check=d.get("check", ""),
            measured=d.get("measured"),
            expected=d.get("expected"),
            against=d.get("against", ""),
            checked_at=d.get("checked_at", ""),
            tolerance=d.get("tolerance"),
            note=d.get("note", ""),
            extra={k: v for k, v in d.items() if k not in known},
        )


def _is_number(v: object) -> TypeGuard[int | float]:
    # bool is a subclass of int; treating True as 1 would make a boolean check compare
    # numerically with a tolerance, which is nonsense.
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_verdict(check: AssetCheck) -> Verdict:
    """PASS / FAIL / UNKNOWN for one measurement.

    UNKNOWN whenever the check could not measure OR had nothing to measure against. Numbers
    compare within the declared tolerance (exact when none is declared); everything else
    compares for equality exactly, because a near-match on a package name is how "SOT-23"
    became a 23-pin part.
    """
    measured, expected = check.measured, check.expected
    if measured is None or expected is None:
        return Verdict.UNKNOWN
    if _is_number(measured) and _is_number(expected):
        measured_number = float(measured)
        expected_number = float(expected)
        if not math.isfinite(measured_number) or not math.isfinite(expected_number):
            return Verdict.UNKNOWN
        if check.tolerance is None:
            tol = 0.0
        elif _is_number(check.tolerance) and math.isfinite(float(check.tolerance)):
            tol = abs(float(check.tolerance))
        else:
            # JSON is an external evidence boundary. A malformed tolerance is not proof of a
            # mismatch, and it must not crash every list-row readiness calculation either.
            return Verdict.UNKNOWN
        ok = math.isclose(measured_number, expected_number, rel_tol=0.0, abs_tol=tol)
        return Verdict.PASS if ok else Verdict.FAIL
    return Verdict.PASS if measured == expected else Verdict.FAIL


def combine(verdicts) -> Verdict:
    """The worst verdict in `verdicts`; UNKNOWN when there are none.

    No evidence is never a PASS. "Trust is not presence" applies to evidence too: an asset
    nobody has checked is not a trusted asset.
    """
    seen = set(verdicts)
    if not seen:
        return Verdict.UNKNOWN
    for v in _WORST_FIRST:
        if v in seen:
            return v
    return Verdict.UNKNOWN


def verdict_for(checks) -> Verdict:
    """The verdict implied by a list of checks."""
    return combine(check_verdict(c) for c in (checks or ()))


def asset_verdict(asset) -> Verdict:
    """The verdict for one asset, from its own checks. UNKNOWN for a missing asset, because
    absence is a PRESENCE question and `PartRecord.missing_assets` is what answers it."""
    if asset is None:
        return Verdict.UNKNOWN
    return verdict_for(getattr(asset, "checks", ()))


def present_assets(record, tool_key: str) -> list:
    """The assets `tool_key` actually HOLDS on this record, in registry kind order.

    Absent assets are skipped everywhere below rather than counted as failures or as unknowns:
    not having a footprint yet is incompleteness, not untrustworthiness, and mixing the two is
    what made a presence matrix read like a quality claim.
    """
    from stockroom.eda.registry import get_tool

    bundle = record.assets_for(tool_key)
    out = []
    for kind in get_tool(tool_key).asset_kinds:
        asset = bundle.get(kind)
        if asset is not None:
            out.append(asset)
    return out


def tool_verdict(record, tool_key: str) -> Verdict:
    """The worst verdict across the assets `tool_key` actually holds. UNKNOWN when it holds
    none, because there is no evidence either way."""
    return combine(asset_verdict(a) for a in present_assets(record, tool_key))


def record_verdict(record, tool_key: str | None = None) -> Verdict:
    """The part's trust verdict: one tool's, or the worst across every asset it holds for any
    registered tool.

    A tool the part carries nothing for contributes NOTHING here - not an UNKNOWN. Folding
    tool verdicts together instead would make a part with a fully checked KiCad set and no
    Altium set read as UNKNOWN, which is a presence answer dressed up as a trust answer.
    """
    if tool_key is not None:
        return tool_verdict(record, tool_key)
    # Imported here rather than at module scope so this module stays importable by the record
    # model itself without a cycle.
    from stockroom.eda.registry import all_tools

    return combine(
        asset_verdict(a) for t in all_tools() for a in present_assets(record, t.key)
    )
