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
import { Text, useCopyFormatter, useText } from "../lib/copy";
import { Badge, Button, Dot, ErrorState, Eyebrow, LoadingState } from "./primitives";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function BinaryStorage() {
  const q = useLibraryLfs();
  const adopt = useAdoptLibraryLfs();
  const { toast } = useToast();
  // A toast takes a resolved string, so both outcomes are resolved during render and the pattern
  // count is substituted when the mutation comes back.
  const adopted = useCopyFormatter(
    "library.sync.lfs-adopted",
    "Binaries now go to Git LFS. {count} pattern(s) tracked.",
  );
  const adoptedInForce = useText(
    "library.sync.lfs-adopted-in-force",
    "Binaries are stored in Git LFS; nothing changed.",
  );
  // What adoption cannot undo, one id per number agreement: three clauses agree with the count.
  const legacyOne = useCopyFormatter(
    "library.sync.lfs-legacy-one",
    "{count} file was committed before this and remains in the git commits as it is. Moving it would rewrite each commit that touched it, which is not something this app will do to a shared git remote.",
  );
  const legacyMany = useCopyFormatter(
    "library.sync.lfs-legacy-many",
    "{count} files were committed before this and remain in the git commits as those are. Moving them would rewrite each commit that touched them, which is not something this app will do to a shared git remote.",
  );
  const data = q.data;

  function onAdopt() {
    adopt.mutate(undefined, {
      onSuccess: (r) =>
        toast(
          r.committed ? adopted({ count: r.tracked_patterns.length }) : adoptedInForce,
          r.committed ? "ok" : "neutral",
        ),
      onError: (e) => toast(errMsg(e, "Could not adopt Git LFS."), "err"),
    });
  }

  return (
    <div data-testid="lfs-block" data-dev-id="settings.library-lfs">
      <Eyebrow className="mb-2">
        <Text id="library.sync.binary-storage-heading">Large File Storage</Text>
      </Eyebrow>
      {q.isLoading ? (
        <LoadingState dense id="library.sync.binary-storage-loading">
          Checking how binaries are stored...
        </LoadingState>
      ) : q.isError ? (
        <ErrorState dense id="library.sync.binary-storage-failed" onRetry={() => q.refetch()}>
          {errMsg(q.error, "Could not check binary storage.")}
        </ErrorState>
      ) : !data ? null : (
        <div className="rounded-card border border-line2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2">
            <Dot tone={data.adopted ? "ok" : data.installed ? "warn" : "neutral"} />
            <span className="text-sm font-medium text-t1" data-testid="lfs-state">
              {!data.installed ? (
                <Text id="library.sync.lfs-not-installed">Git LFS Not Installed</Text>
              ) : data.adopted ? (
                <Text id="library.sync.lfs-state-adopted">Stored In Git LFS</Text>
              ) : (
                <Text id="library.sync.lfs-state-in-git">Stored In Git Commits</Text>
              )}
            </span>
            {data.adopted ? (
              <Badge tone="neutral" size="sm">
                {data.objects} file{data.objects === 1 ? "" : "s"}
              </Badge>
            ) : null}
            {data.installed && !data.adopted ? (
              <Button small onClick={onAdopt} disabled={adopt.isPending} className="ml-auto"
                      data-testid="lfs-adopt" data-dev-id="settings.library-lfs.adopt">
                {adopt.isPending ? (
                  <Text id="library.sync.lfs-adopting">Adopting...</Text>
                ) : (
                  <Text id="library.sync.lfs-adopt">Store Binaries In Git LFS</Text>
                )}
              </Button>
            ) : null}
          </div>

          <p className="border-t border-line2 px-3 py-2 text-2xs text-t2">
            {!data.installed ? (
              <span data-testid="lfs-reason">
                {data.reason || "Git LFS is not available on this machine."}{" "}
                <Text id="library.sync.lfs-install-note">
                  Install it to keep clone size flat as the catalog grows.
                </Text>
              </span>
            ) : data.adopted ? (
              <Text id="library.sync.lfs-adopted-note">New captures store their symbol, footprint and 3D files outside the git commits, so a clone remains small however far the catalog grows.</Text>
            ) : (
              <Text id="library.sync.lfs-unadopted-note">Each captured part adds a permanent duplicate of its catalog and model files to the git commits, for all who ever clone this catalog.</Text>
            )}
          </p>

          {data.installed && !data.adopted ? (
            <div className="border-t border-line2 px-3 py-2" data-testid="lfs-covers">
              {/* Labelled, because an unlabelled row of globs reads as debug output rather than
                  as the concrete answer to "what would this actually move". */}
              <div className="mb-1 ui-property-label">
                <Text id="library.sync.lfs-covers-heading">Would Move To Git LFS</Text>
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
              {(data.legacy_blobs === 1 ? legacyOne : legacyMany)({ count: data.legacy_blobs })}
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
  // Resolved during render because a toast takes a plain string; the file count arrives later.
  const aligned = useCopyFormatter(
    "library.sync.hygiene-aligned",
    "Aligned. {count} file(s) are no longer shared through git.",
  );
  const alignedInForce = useText(
    "library.sync.hygiene-aligned-in-force",
    "The catalog is aligned; nothing changed.",
  );
  const data = q.data;
  const pending = (data?.untracked.length ?? 0) + (data?.writes.length ?? 0);

  function onSync() {
    sync.mutate(undefined, {
      onSuccess: (r) =>
        toast(
          r.committed ? aligned({ count: r.untracked.length }) : alignedInForce,
          r.committed ? "ok" : "neutral",
        ),
      onError: (e) => toast(errMsg(e, "Could not sync the library's workspace hygiene."), "err"),
    });
  }

  return (
    <div className="mt-5" data-testid="library-hygiene-block" data-dev-id="settings.library-hygiene">
      <Eyebrow className="mb-2">
        <Text id="library.sync.shared-files-heading">Shared Files</Text>
      </Eyebrow>
      {q.isLoading ? (
        <LoadingState dense id="library.sync.hygiene-loading">
          Checking what the catalog shares...
        </LoadingState>
      ) : q.isError ? (
        <ErrorState dense id="library.sync.hygiene-failed" onRetry={() => q.refetch()}>
          {errMsg(q.error, "Could not check the library.")}
        </ErrorState>
      ) : !data ? null : pending === 0 ? (
        <p className="text-xs text-ok-text" data-testid="library-hygiene-clean">
          <Text id="library.sync.hygiene-clean">
            Nothing per-user or regenerated is being shared from this catalog.
          </Text>
        </p>
      ) : (
        <div className="rounded-card border border-line2" data-testid="library-hygiene-pending">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2">
            <span className="text-sm text-t2">
              {data.untracked.length > 0 ? (
                data.untracked.length === 1 ? (
                  <Text
                    id="library.sync.hygiene-shared-one"
                    values={{ count: data.untracked.length }}
                  >{"{count} file is shared that should not be."}</Text>
                ) : (
                  <Text
                    id="library.sync.hygiene-shared-many"
                    values={{ count: data.untracked.length }}
                  >{"{count} files are shared that should not be."}</Text>
                )
              ) : (
                <Text id="library.sync.hygiene-stale-ignores">
                  The ignore rules are out of date.
                </Text>
              )}
            </span>
            <Button small onClick={onSync} disabled={sync.isPending} className="ml-auto"
                    data-testid="library-hygiene-sync"
                    data-dev-id="settings.library-hygiene.sync">
              {sync.isPending ? (
                <Text id="library.sync.hygiene-aligning">Aligning...</Text>
              ) : data.untracked.length > 0 ? (
                <Text id="library.sync.hygiene-stop-sharing">Stop Sharing These</Text>
              ) : (
                <Text id="library.sync.hygiene-update-ignores">Update Ignore Rules</Text>
              )}
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
            <Text id="library.sync.hygiene-note">These remain on the local disk. Git alone stops transporting them to whoever else clones this catalog.</Text>
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
