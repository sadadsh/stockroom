/**
 * Library Version: which library commit this project was resolved against, and how that compares
 * with the library on THIS machine.
 *
 * Why it exists (Batch 2 item 2): a project and the Stockroom library are two SEPARATE git repos.
 * Two people can therefore sit on the byte-identical project commit while their libraries are at
 * different commits, so the same footprint reference resolves to different geometry, and neither
 * repo's history says a word about it. The pin is a lockfile committed into the PROJECT's repo.
 *
 * PRIOR ART: this is a view, not infrastructure. Every reusable piece it needs already exists in
 * this codebase and is REUSED rather than rebuilt: `Button` / `Badge` / `Dot` from
 * `components/primitives`, the toast from `lib/toast`, TanStack Query hooks from `api/queries`,
 * and the section shell (`mt-7 border-t border-line pt-6` + eyebrow + prose) copied from the
 * neighbouring Sync Hygiene section so the two read as one Health tab. REJECTED: a generic
 * "status card" abstraction extracted across this and Sync Hygiene, because two instances is not
 * yet a pattern and the two cards genuinely differ (one lists files, one compares two versions);
 * and any date/formatting library, because one UTC date string does not justify a dependency.
 *
 * Two things this surface deliberately does NOT do:
 *
 * - It never offers to pin when this machine's library is BEHIND the pin or missing its commit.
 *   Pinning there would move the pin backwards onto an older library, which is the exact opposite
 *   of the remedy, and it would look like the problem had been solved.
 * - It never re-derives severity or wording from the status. The backend decides both, so the two
 *   layers can never describe the same state differently (the "CAD Incomplete" class of bug).
 */
import { ApiError } from "../api/client";
import { useLibraryPin, useSetLibraryPin } from "../api/queries";
import type { LibraryPinRead, LibraryPinStatus } from "../api/types";
import { useToast } from "../lib/toast";
import { Badge, Button, Dot, Eyebrow } from "./primitives";

type Tone = "ok" | "warn" | "err" | "neutral";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

const STATUS_LABEL: Record<LibraryPinStatus, string> = {
  unpinned: "Not Pinned",
  match: "In Sync",
  library_ahead: "Library Ahead",
  library_behind: "Library Behind",
  diverged: "Diverged",
  unknown_commit: "Version Missing",
  different_library: "Different Library",
  different_profile: "Different Profile",
  library_not_git: "No Library History",
};

// Whether pinning to the library as it is RIGHT NOW is a sensible thing to offer, and what the
// action is called when it is. A status absent here has no button at all, which is the honest
// answer for "your library is older than the pin": the fix is to pull, not to lower the bar.
const PIN_ACTION: Partial<Record<LibraryPinStatus, string>> = {
  unpinned: "Pin Library Version",
  library_ahead: "Update Pin",
  diverged: "Pin To This Version",
  different_profile: "Re-pin To This Profile",
  different_library: "Re-pin To This Library",
};

function toneFor(severity: string): Tone {
  if (severity === "ok") return "ok";
  if (severity === "notice") return "warn";
  return "err";
}

// "2026-07-25T06:00:00+00:00" -> "25 Jul 2026". Deliberately not locale-formatted: the value is a
// record of WHEN a version was adopted, read next to a commit id, and it must read the same in a
// screenshot taken on any machine.
function pinnedDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${d.getUTCDate()} ${months[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

// What sits under the pinned commit id. Normally the date it was adopted, but when the pin names a
// DIFFERENT profile from the active one, that profile is the whole difference and it has to be
// visible: without it the card says "Different Profile" and never says which.
function pinnedSub(data: LibraryPinRead): string {
  if (!data.pinned) return "Never pinned";
  const date = pinnedDate(data.pinned.pinned_at);
  if (data.pinned.profile && data.pinned.profile !== data.library_profile) {
    return date ? `${date} · ${data.pinned.profile} profile` : `${data.pinned.profile} profile`;
  }
  return date;
}

// The distance between the two versions, in git's own words, as a badge beside the status. It sits
// with the status rather than between the commit ids: "4 newer" IS the headline when the library
// has moved, and a number stranded in the gap between two columns reads as decoration.
function DeltaLabel({ data }: { data: LibraryPinRead }) {
  const bits: string[] = [];
  if (data.ahead > 0) bits.push(`${data.ahead} newer`);
  if (data.behind > 0) bits.push(`${data.behind} missing`);
  if (bits.length === 0) return null;
  return (
    <Badge tone={data.behind > 0 ? "err" : "warn"} size="sm" data-testid="pin-delta">
      {bits.join(", ")}
    </Badge>
  );
}

// One side of the comparison. Sized to its CONTENT, never stretched: a 7-character commit id in a
// half-card-wide column puts 500px of nothing between the two things being compared, which is the
// opposite of a comparison.
function VersionColumn({
  label,
  sha,
  sub,
  dim,
  testId,
}: {
  label: string;
  sha: string;
  sub?: string;
  dim?: boolean;
  testId: string;
}) {
  return (
    <div className="min-w-0">
      <div className="text-2xs font-semibold uppercase tracking-[0.07em] text-t3">{label}</div>
      <div
        className={`truncate font-mono text-sm ${dim ? "text-t3" : "text-t1"}`}
        data-testid={testId}
        title={sha}
      >
        {sha ? sha.slice(0, 7) : "None"}
      </div>
      {sub ? <div className="truncate text-2xs text-t3">{sub}</div> : null}
    </div>
  );
}

export function LibraryVersionSection({ projectId }: { projectId: string }) {
  const q = useLibraryPin(projectId);
  const pin = useSetLibraryPin();
  const { toast } = useToast();
  const data = q.data;

  function onPin() {
    pin.mutate(projectId, {
      onSuccess: (r) =>
        toast(
          r.committed
            ? `Pinned to library ${r.pinned.commit.slice(0, 7)}.`
            : "Already pinned to this version; nothing changed.",
          r.committed ? "ok" : "neutral",
        ),
      onError: (e) => toast(errMsg(e, "Could not pin the library version."), "err"),
    });
  }

  return (
    <div
      className="mt-7 border-t border-line pt-6"
      data-testid="library-version-section"
      data-dev-id="projects.library-pin"
    >
      <div className="mb-3">
        <Eyebrow className="mb-0.5">Library Version</Eyebrow>
        <p className="text-xs text-t3">
          The library is a separate repository from this project, so two people can share the same
          project commit and still resolve different footprints. Pinning records which library
          version this project was built against.
        </p>
      </div>

      {q.isLoading ? (
        <p className="text-sm text-t3">Checking the library version...</p>
      ) : q.isError ? (
        <p className="text-sm text-err">
          {errMsg(q.error, "Could not check the library version.")}
        </p>
      ) : !data ? null : (
        <div className="rounded-card border border-line2" data-testid="pin-card">
          {/* One band carries the whole verdict: what state this is, how far apart the two
              versions are, and the one action available. The two commit ids sit together at
              content width so the comparison reads as a comparison. */}
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3 px-3 py-2.5">
            <div className="flex min-w-0 items-center gap-2">
              <Dot tone={toneFor(data.severity)} />
              <span className="text-sm font-medium text-t1" data-testid="pin-status">
                {STATUS_LABEL[data.status] ?? data.status}
              </span>
              <DeltaLabel data={data} />
            </div>

            <div className="flex items-center gap-3">
              <VersionColumn
                label="Pinned"
                sha={data.pinned?.commit ?? ""}
                dim={!data.pinned}
                sub={pinnedSub(data)}
                testId="pin-pinned-sha"
              />
              <span aria-hidden className="text-sm leading-none text-t3">
                &rarr;
              </span>
              <VersionColumn
                label="This Machine"
                sha={data.library_commit}
                sub={`${data.library_profile} profile`}
                testId="pin-local-sha"
              />
            </div>

            {PIN_ACTION[data.status] ? (
              <Button
                small
                onClick={onPin}
                disabled={pin.isPending || !data.under_git}
                data-testid="pin-apply"
                data-dev-id="projects.library-pin.apply"
                className="ml-auto"
              >
                {pin.isPending ? "Pinning..." : PIN_ACTION[data.status]}
              </Button>
            ) : null}
          </div>

          {/* The REMEDY leads and the explanation follows it, because the remedy is the only line
              here that tells a person what to do. The first version of this card had them the
              other way round, with the action set in the dimmest text in the card. */}
          <div className="border-t border-line2 px-3 py-2">
            <p className="text-xs text-t2" data-testid="pin-remedy">
              {data.remedy}
            </p>
            <p className="mt-0.5 text-2xs text-t3" data-testid="pin-detail">
              {data.detail}
            </p>
          </div>
          {!data.under_git ? (
            <p className="border-t border-line2 px-3 py-2 text-2xs text-t3" data-testid="pin-no-git">
              This project is not under git, so a pin could never reach anyone else. Initialize a
              git repository for it first.
            </p>
          ) : null}
          {data.path_contract.description ? (
            <p
              className="border-t border-line2 px-3 py-2 text-2xs text-t3"
              data-testid="pin-path-contract"
            >
              {data.path_contract.description}
            </p>
          ) : null}
        </div>
      )}
    </div>
  );
}
