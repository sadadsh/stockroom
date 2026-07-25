/**
 * Library Sync: what the LIBRARY repository shares with a peer, and how.
 *
 * Two library-repo facts that belong together because they are the same question asked twice:
 *
 * 1. **Binary storage (git-lfs, Batch 2 item 4).** Without it every captured part adds a permanent,
 *    un-GC-able copy of its `.PcbLib` / `.SchLib` / `.step` to history for everyone who will ever
 *    clone the library, so clone size only grows. Adoption writes the rules AND wires the filter,
 *    because attributes naming `filter=lfs` with no filter configured are inert.
 * 2. **Sync hygiene for the library repo.** The backend for this shipped in Batch 2 item 1 with NO
 *    caller at all: `GET`/`POST /api/library/hygiene` existed and nothing in the app reached them,
 *    so the union-of-all-tools rules the library actually needs were never applied by anyone. The
 *    project-level equivalent on the Health tab covers ONE project, not the library.
 *
 * PRIOR ART: nothing here is new infrastructure. `Button` / `Badge` / `Dot` from
 * `components/primitives`, the toast from `lib/toast`, TanStack Query hooks from `api/queries`, and
 * the file-listing card shape is taken from the Health tab's Sync Hygiene section so the two read
 * the same. REJECTED: extracting a shared "list of files with an action" component across the two,
 * because the project version is embedded in a 5500-line page and pulling it apart is a Batch 4
 * refactor, not a change to smuggle into a peer-sync slice.
 *
 * Two honesty rules this surface keeps:
 * - It never claims adoption shrinks existing history. It does not: only NEW commits become
 *   pointers, and converting the past needs a rewrite plus a force-push, which this project
 *   forbids. `legacy_blobs` is shown rather than hidden.
 * - It never offers an action it cannot perform. No git-lfs on the machine means the reason is
 *   displayed and the button is gone, not disabled with a shrug.
 */
import { ApiError } from "../api/client";
import {
  useAdoptLibraryLfs,
  useLibraryHygiene,
  useLibraryLfs,
  useSyncLibraryHygiene,
} from "../api/queries";
import { useToast } from "../lib/toast";
import { Badge, Button, Dot, Eyebrow } from "./primitives";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function BinaryStorage() {
  const q = useLibraryLfs();
  const adopt = useAdoptLibraryLfs();
  const { toast } = useToast();
  const data = q.data;

  function onAdopt() {
    adopt.mutate(undefined, {
      onSuccess: (r) =>
        toast(
          r.committed
            ? `Binary payloads now go to Git LFS. ${r.tracked_patterns.length} pattern(s) tracked.`
            : "Already storing binaries in Git LFS; nothing changed.",
          r.committed ? "ok" : "neutral",
        ),
      onError: (e) => toast(errMsg(e, "Could not adopt Git LFS."), "err"),
    });
  }

  return (
    <div data-testid="lfs-block" data-dev-id="settings.library-lfs">
      <Eyebrow className="mb-2">Binary Storage</Eyebrow>
      {q.isLoading ? (
        <p className="text-sm text-t3">Checking how binaries are stored...</p>
      ) : q.isError ? (
        <p className="text-sm text-err">{errMsg(q.error, "Could not check binary storage.")}</p>
      ) : !data ? null : (
        <div className="rounded-card border border-line2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2">
            <Dot tone={data.adopted ? "ok" : data.installed ? "warn" : "neutral"} />
            <span className="text-sm font-medium text-t1" data-testid="lfs-state">
              {!data.installed
                ? "Git LFS Not Installed"
                : data.adopted
                  ? "Stored In Git LFS"
                  : "Stored In Git History"}
            </span>
            {data.adopted ? (
              <Badge tone="neutral" size="sm">
                {data.objects} file{data.objects === 1 ? "" : "s"}
              </Badge>
            ) : null}
            {data.installed && !data.adopted ? (
              <Button small onClick={onAdopt} disabled={adopt.isPending} className="ml-auto"
                      data-testid="lfs-adopt" data-dev-id="settings.library-lfs.adopt">
                {adopt.isPending ? "Adopting..." : "Store Binaries In Git LFS"}
              </Button>
            ) : null}
          </div>

          <p className="border-t border-line2 px-3 py-2 text-2xs text-t2">
            {!data.installed ? (
              <span data-testid="lfs-reason">
                {data.reason || "Git LFS is not available on this machine."} Install it to keep
                clone size flat as the library grows.
              </span>
            ) : data.adopted ? (
              "New captures store their symbol, footprint and 3D payloads outside git history, so a clone stays small however far the library grows."
            ) : (
              "Every captured part adds a permanent copy of its library and model files to history, for everyone who ever clones this library."
            )}
          </p>

          {data.installed && !data.adopted ? (
            <div className="border-t border-line2 px-3 py-2" data-testid="lfs-covers">
              {/* Labelled, because an unlabelled row of globs reads as debug output rather than
                  as the concrete answer to "what would this actually move". */}
              <div className="mb-1 text-2xs uppercase tracking-[0.07em] text-t3">
                Would Move To Git LFS
              </div>
              {data.covers.map((pattern) => (
                <span key={pattern} className="mr-2 font-mono text-2xs text-t2">
                  {pattern}
                </span>
              ))}
            </div>
          ) : null}

          {data.legacy_blobs > 0 ? (
            // Never implied away: adoption does not rewrite the past, and saying otherwise would
            // be a claim the tool cannot back up.
            <p className="border-t border-line2 px-3 py-2 text-2xs text-t3" data-testid="lfs-legacy">
              {data.legacy_blobs} file{data.legacy_blobs === 1 ? " was" : "s were"} committed before
              this and stay in history as they are. Moving them would rewrite every commit that
              touched them, which is not something this app will do to a shared repository.
            </p>
          ) : null}
        </div>
      )}
    </div>
  );
}

function LibraryHygiene() {
  const q = useLibraryHygiene();
  const sync = useSyncLibraryHygiene();
  const { toast } = useToast();
  const data = q.data;
  const pending = (data?.untracked.length ?? 0) + (data?.writes.length ?? 0);

  function onSync() {
    sync.mutate(undefined, {
      onSuccess: (r) =>
        toast(
          r.committed
            ? `Synced. ${r.untracked.length} file(s) are no longer shared through git.`
            : "Already in sync; nothing changed.",
          r.committed ? "ok" : "neutral",
        ),
      onError: (e) => toast(errMsg(e, "Could not sync the library's workspace hygiene."), "err"),
    });
  }

  return (
    <div className="mt-5" data-testid="library-hygiene-block" data-dev-id="settings.library-hygiene">
      <Eyebrow className="mb-2">Shared Files</Eyebrow>
      {q.isLoading ? (
        <p className="text-sm text-t3">Checking what the library shares...</p>
      ) : q.isError ? (
        <p className="text-sm text-err">{errMsg(q.error, "Could not check the library.")}</p>
      ) : !data ? null : pending === 0 ? (
        <p className="text-xs text-ok" data-testid="library-hygiene-clean">
          Nothing per-user or regenerated is being shared from this library.
        </p>
      ) : (
        <div className="rounded-card border border-line2" data-testid="library-hygiene-pending">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2">
            <span className="text-sm text-t2">
              {data.untracked.length > 0
                ? `${data.untracked.length} ${data.untracked.length === 1 ? "file is" : "files are"} shared that should not be.`
                : "The ignore rules are out of date."}
            </span>
            <Button small onClick={onSync} disabled={sync.isPending} className="ml-auto"
                    data-testid="library-hygiene-sync"
                    data-dev-id="settings.library-hygiene.sync">
              {sync.isPending
                ? "Syncing..."
                : data.untracked.length > 0
                  ? "Stop Sharing These"
                  : "Update Ignore Rules"}
            </Button>
          </div>
          {data.untracked.length > 0 ? (
            <div className="border-t border-line2 px-3 py-2" data-testid="library-hygiene-files">
              {data.untracked.map((path) => (
                <div key={path} className="truncate font-mono text-2xs text-t2" title={path}>
                  {path}
                </div>
              ))}
            </div>
          ) : null}
          <p className="border-t border-line2 px-3 py-2 text-2xs text-t3">
            These stay on your disk. Only git stops carrying them to whoever else clones this
            library.
          </p>
        </div>
      )}
    </div>
  );
}

export function LibrarySyncSection() {
  return (
    <div data-testid="library-sync-section">
      <BinaryStorage />
      <LibraryHygiene />
    </div>
  );
}
