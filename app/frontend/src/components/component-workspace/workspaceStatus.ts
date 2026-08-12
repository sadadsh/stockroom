/**
 * The words a REPRESENTATION's readiness can be said in.
 *
 * Five, closed, and every one of them producible: the set is exactly the range of
 * `REPRESENTATION_STATUS_LABEL`, which is the only thing in this codebase that turns a record into
 * one of these words. The point of closing it is that "Ready", "Complete", "OK" and "Done" stop
 * being four names for one condition on one screen.
 *
 * It used to carry four more - `Validated`, `Downloaded`, `Available`, `Unknown` - on the claim
 * that this was the ONE vocabulary the whole opened component speaks. It never was. Those four are
 * spoken on that screen, but by two other closed sets with two other subjects and two other tone
 * functions: a CAD asset's own state is `CadAssetStatus` below, toned by `cadStatusTone`, and a
 * provider's coverage of one artifact is `CoverageStatus` from the dossier, labelled in the
 * Manage Models provider list. Naming their words here as well gave this type members no
 * value of it could ever hold, and gave `statusTone` entries no caller could ever reach. A word
 * that only a vocabulary list can produce is not a vocabulary - it is a list.
 */
import type { RepresentationStatus, RepresentationView } from "../../api/dossierTypes";
import type { BadgeTone } from "../primitives";

export type WorkspaceStatus =
  | "Ready"
  | "Needs Review"
  | "Missing"
  | "Failed"
  | "Not Required";

/** A representation's own readiness, in the vocabulary. */
export const REPRESENTATION_STATUS_LABEL: Record<RepresentationStatus, WorkspaceStatus> = {
  ready: "Ready",
  review: "Needs Review",
  missing: "Missing",
  failed: "Failed",
  not_required: "Not Required",
};

const TONES: Record<WorkspaceStatus, BadgeTone> = {
  Ready: "ok",
  // "Not Required" is a fact, not a verdict, so it is not coloured as one.
  "Not Required": "neutral",
  "Needs Review": "warn",
  Missing: "warn",
  Failed: "err",
};

export function statusTone(status: WorkspaceStatus): BadgeTone {
  return TONES[status];
}

/**
 * The state a CAD asset module states about itself, in the words the owner fixed.
 *
 * "Ready" is deliberately NOT in this set. It is the vaguest word available for the most important
 * distinction on the column: a file that merely EXISTS and a file a recorded check has passed are
 * not the same claim, and calling both of them ready is how a component with an unvalidated
 * footprint gets sent to a fabricator. `Validated` says a check passed, `Available` says a file is
 * attached and nothing has verified it, and the remaining four say what is wrong.
 */
export type CadAssetStatus =
  | "Available"
  | "Validated"
  | "Needs Review"
  | "Missing"
  | "Failed"
  | "Not Required"
  | "Package Matched"
  | "Pin Match Failed"
  | "Incomplete";

/**
 * What the drawing itself measured, when the preview has it.
 *
 * The three extra states can only be said with this: a terminal count that disagrees with the
 * component's own pin count is `Pin Match Failed`, and a file whose terminals are unnumbered or
 * numbered twice is `Incomplete` - which is a different fault from missing and from failed, and
 * was previously reported as `Available` because nothing had been recorded against it.
 *
 * `terminals`/`expected` are null when there is nothing to compare; a comparison with one side
 * missing is not a comparison and must never be reported as a pass.
 */
export interface CadMeasured {
  terminals: number | null;
  expected: number | null;
  duplicates: number;
  unnumbered: number;
}

/** A recorded check whose id names the thing it checked, so the state can say which one failed. */
function namedCheck(view: RepresentationView, word: string) {
  return view.tools
    .flatMap((tool) => tool.checks)
    .find((check) => check.check.toLowerCase().includes(word));
}

export function cadAssetStatus(
  view: RepresentationView,
  measured?: CadMeasured | null,
): CadAssetStatus {
  if (view.status === "failed") {
    // A failure that named the pins says so, because "Failed" alone sends a person looking
    // through a file for a fault the record already located.
    return namedCheck(view, "pin") ? "Pin Match Failed" : "Failed";
  }
  if (view.status === "missing") return "Missing";
  if (view.status === "review") return "Needs Review";
  if (view.status === "not_required") return "Not Required";
  const present = view.tools.filter((tool) => tool.present);
  if (present.length === 0) return "Missing";
  if (measured) {
    if (
      measured.terminals !== null &&
      measured.expected !== null &&
      measured.terminals !== measured.expected
    ) {
      return "Pin Match Failed";
    }
    if (measured.duplicates > 0 || measured.unnumbered > 0) return "Incomplete";
  }
  const checks = present.flatMap((tool) => tool.checks);
  if (checks.length === 0) return "Available";
  // A check that PASSED on the package is the strongest thing a land pattern can say about
  // itself, so it is said rather than folded into the general word.
  const packageCheck = namedCheck(view, "package");
  if (packageCheck && packageCheck.measured !== null && packageCheck.measured === packageCheck.expected) {
    return "Package Matched";
  }
  return "Validated";
}

const CAD_TONES: Record<CadAssetStatus, BadgeTone> = {
  Validated: "ok",
  "Package Matched": "ok",
  Available: "neutral",
  "Not Required": "neutral",
  "Needs Review": "warn",
  Incomplete: "warn",
  Missing: "warn",
  Failed: "err",
  "Pin Match Failed": "err",
};

export function cadStatusTone(status: CadAssetStatus): BadgeTone {
  return CAD_TONES[status];
}

// What happened to one SOURCE is a different question from a representation's readiness, and its
// vocabulary lives in `provenanceText.tsx` with the rest of the provenance translation. It used to
// live here and say "Answered", which is a word about a request rather than about the part.
