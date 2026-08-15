import { useEffect, useMemo, useRef, useState } from "react";
import {
  useApproveProjectReview,
  useConnectProjectRemote,
  useFinishWorkSession,
  useProjectCollaboration,
  useProjectReviewEvidence,
  useProjectReviews,
  useRequestProjectChanges,
  useResumeWorkSession,
  useShareWorkSession,
  useStartWorkSession,
  useValidateProjectReview,
} from "../../api/queries";
import type {
  ProjectCollaboration,
  ProjectReviewCandidate,
  ProjectWorkspace,
} from "../../api/types";
import { Text, useText } from "../../lib/copy";
import { useToast } from "../../lib/toast";
import { Badge, Button, ErrorState, LoadingState, Panel, SectionHeading } from "../primitives";
import { GitIcon } from "../icons";
import { ProjectInspectorFacts } from "./ProjectInspectorFacts";

export function ProjectChangesWorkbench({
  projectId,
  workspace,
}: {
  projectId: string;
  workspace: ProjectWorkspace;
}) {
  const commitLabel = useText("projects.activity.commit", "commit");
  const commitsLabel = useText("projects.activity.commits", "commits");
  const documentLabel = useText("projects.activity.changed-document", "changed document");
  const documentsLabel = useText("projects.activity.changed-documents", "changed documents");
  const collaboration = useProjectCollaboration(projectId);
  // A local-only project has no review repository to inspect. Do not start the
  // review query until collaboration has positively reported one: apart from
  // avoiding pointless native Git work, this lets the exact setup guidance render
  // immediately instead of leaving a local project behind a loading screen.
  const hasReviewRemote = !!collaboration.data?.repository?.has_remote;
  const reviews = useProjectReviews(projectId, hasReviewRemote);
  const [selectedCommit, setSelectedCommit] = useState("");
  const candidates = reviews.data?.candidates ?? [];
  // The chosen commit is only a preference: the review actually shown is resolved here, and
  // falls back to the first candidate whenever the queue no longer carries the chosen one.
  // An effect used to write that fallback into state as well, which rendered nothing new -
  // every reader below goes through `selected`.
  const selected =
    candidates.find((candidate) => candidate.commit === selectedCommit) ?? candidates[0];
  const repository = collaboration.data?.repository;

  if (collaboration.isLoading || (hasReviewRemote && reviews.isLoading)) {
    return (
      <ChangesMessage>
        <LoadingState dense id="projects.activity.loading">Loading this project's recent work...</LoadingState>
      </ChangesMessage>
    );
  }
  if (collaboration.error || (hasReviewRemote && reviews.error)) {
    return (
      <ChangesMessage>
        {/* A written sentence and one retry. The two queries' own `.message` values were shown
            verbatim, which put a Git or HTTP string in the middle of the workbench. */}
        <ErrorState
          dense
          id="projects.activity.failed"
          onRetry={() => {
            void collaboration.refetch();
            if (hasReviewRemote) void reviews.refetch();
          }}
        >
          This project's activity could not be read.
        </ErrorState>
      </ChangesMessage>
    );
  }

  return (
    <div data-dev-id="projects.activity" className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-none items-center gap-4 pb-3">
        <div>
          <SectionHeading><Text id="projects.activity.heading">Recent Work</Text></SectionHeading>
          <p className="mt-0.5 text-xs text-t3">
            <Text id="projects.activity.subtitle">Protected work and commit review</Text>
          </p>
        </div>
        <RepositoryStanding collaboration={collaboration.data} />
      </div>
      {!repository ? (
        <div className="min-h-0 flex-1 overflow-y-auto rounded-card border border-line bg-surface">
          <GitRequiredPanel />
        </div>
      ) : !repository.has_remote ? (
        <ConnectRepositoryPanel projectId={projectId} collaboration={collaboration.data!} />
      ) : selected ? (
        <div className="grid min-h-0 flex-1 grid-cols-[230px_minmax(0,1fr)] overflow-hidden rounded-card border border-line bg-surface @[60rem]:grid-cols-[minmax(320px,0.72fr)_minmax(500px,1.28fr)]">
          <section className="flex min-h-0 flex-col border-r border-line">
            <WorkSessionCard
              projectId={projectId}
              workspace={workspace}
              collaboration={collaboration.data}
            />
            <ReviewList
              candidates={candidates}
              selected={selected}
              onSelect={setSelectedCommit}
              commitLabel={commitLabel}
              commitsLabel={commitsLabel}
              documentLabel={documentLabel}
              documentsLabel={documentsLabel}
            />
          </section>
          <ReviewInspector projectId={projectId} candidate={selected} />
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-[280px_minmax(0,1fr)] overflow-hidden rounded-card border border-line bg-surface @[60rem]:grid-cols-[minmax(320px,0.82fr)_minmax(380px,1.18fr)]">
          <section className="min-h-0 overflow-y-auto border-r border-line">
            <WorkSessionCard
              projectId={projectId}
              workspace={workspace}
              collaboration={collaboration.data}
            />
          </section>
          <ReviewQueueEmpty reason={reviews.data?.blocked_reason} />
        </div>
      )}
    </div>
  );
}

function ReviewQueueEmpty({ reason = "" }: { reason?: string }) {
  return (
    <section className="min-h-0 overflow-y-auto">
      <div className="flex h-[34px] items-center gap-2 border-b border-line bg-band px-4">
        <span className="text-xs font-semibold text-t2">
          <Text id="projects.activity.review-queue">Review Queue</Text>
        </span>
        <span className="font-mono text-2xs text-t3">0</span>
      </div>
      <div className="w-full max-w-[520px] px-5 py-5">
        <p className="text-sm font-semibold text-t1">
          <Text id="projects.activity.no-reviews-title">No shared work so far</Text>
        </p>
        <p className="mt-1.5 text-xs leading-5 text-t3">
          {reason ? (
            reason
          ) : (
            <Text id="projects.activity.no-reviews">
              A teammate's shared branch appears here with its changed files, BOM links,
              and native design checks.
            </Text>
          )}
        </p>
        <div className="mt-5 divide-y divide-line border-y border-line">
          <WorkflowStep
            number="1"
            titleId="projects.activity.workflow-claim"
            title="Claim project files"
            detailId="projects.activity.workflow-claim-detail"
            detail="Choose the files you plan to change."
          />
          <WorkflowStep
            number="2"
            titleId="projects.activity.workflow-share"
            title="Share changes"
            detailId="projects.activity.workflow-share-detail"
            detail="Commit the protected work branch when it is ready."
          />
          <WorkflowStep
            number="3"
            titleId="projects.activity.workflow-review"
            title="Review together"
            detailId="projects.activity.workflow-review-detail"
            detail="Check the PCB, BOM, and validation evidence before approval."
          />
        </div>
      </div>
    </section>
  );
}

function WorkflowStep({
  number,
  titleId,
  title,
  detailId,
  detail,
}: {
  number: string;
  titleId: string;
  title: string;
  detailId: string;
  detail: string;
}) {
  return (
    <div className="grid grid-cols-[24px_minmax(0,1fr)] gap-3 py-3">
      <span className="flex size-6 items-center justify-center rounded-full border border-line2 font-mono text-2xs text-t2">
        {number}
      </span>
      <div>
        <p className="text-xs font-medium text-t1">
          <Text id={titleId}>{title}</Text>
        </p>
        <p className="mt-0.5 text-2xs leading-4 text-t3">
          <Text id={detailId}>{detail}</Text>
        </p>
      </div>
    </div>
  );
}

function GitRequiredPanel() {
  return (
    <>
      <div className="flex h-[34px] items-center border-b border-line bg-band px-4">
        <span className="text-xs font-semibold text-t2">
          <Text id="projects.activity.local-repository">Local Git Checkout</Text>
        </span>
      </div>
      <section className="w-full max-w-[520px] px-5 py-5">
        <p className="text-sm font-semibold text-t1">
          <Text id="projects.activity.git-not-initialized">
            Git Is Not Initialized
          </Text>
        </p>
        <p className="mt-1.5 text-xs leading-5 text-t3">
          <Text id="projects.activity.git-required-detail">Initialize Git in this project folder before connecting the shared Git remote.</Text>
        </p>
      </section>
    </>
  );
}

function ConnectRepositoryPanel({
  projectId,
  collaboration,
}: {
  projectId: string;
  collaboration: ProjectCollaboration;
}) {
  const connect = useConnectProjectRemote(projectId);
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const { toast } = useToast();
  const repository = collaboration.repository!;
  const connectedLabel = useText(
    "projects.activity.toast-repository-connected",
    "Git remote connected",
  );
  const connectFailed = useText(
    "projects.activity.toast-repository-connect-failed",
    "Could not connect the Git remote",
  );
  const requirement = useText(
    "projects.activity.remote-url-requirement",
    "Use a secure HTTPS or SSH Git remote URL.",
  );
  const branchLabel = useText("projects.activity.branch", "Branch");
  const remotePlaceholder = useText(
    "projects.activity.remote-url-placeholder",
    "https://github.com/team/project.git",
  );
  const stateLabel = useText("projects.activity.state", "State");
  const latestCommitLabel = useText(
    "projects.activity.commit-label",
    "Commit",
  );

  function submit() {
    const remote = url.trim();
    if (!remote) {
      setError(requirement);
      inputRef.current?.focus();
      return;
    }
    setError("");
    connect.mutate(remote, {
      onSuccess: (result) => {
        if (["offline", "denied", "diverged"].includes(result.sync.state)) {
          toast(result.sync.detail || connectedLabel, "neutral");
        } else {
          toast(connectedLabel, "ok");
        }
      },
      onError: (cause) => {
        const detail = cause instanceof Error ? cause.message : connectFailed;
        setError(detail);
        toast(detail, "err");
        inputRef.current?.focus();
      },
    });
  }

  return (
    <div className="@container/repository flex min-h-0 flex-1 flex-col overflow-y-auto rounded-card border border-line bg-surface">
      <div className="flex h-[34px] items-center border-b border-line bg-band px-4">
        <span className="text-xs font-semibold text-t2">
          <Text id="projects.activity.shared-repository">Shared Git Remote</Text>
        </span>
      </div>
      <div className="grid min-h-0 flex-1 content-start @[46rem]/repository:grid-cols-[minmax(220px,0.78fr)_minmax(340px,1.22fr)]">
        <section className="border-b border-line px-5 py-5 @[46rem]/repository:border-b-0 @[46rem]/repository:border-r">
          <h2 className="text-sm font-semibold text-t1">
            <Text id="projects.activity.local-project">Local Project</Text>
          </h2>
          <p className="mt-1.5 max-w-[34rem] text-xs leading-5 text-t3">
            <Text id="projects.activity.local-project-detail">This project has local Git commits and is prepared to connect.</Text>
          </p>
          <ProjectInspectorFacts
            className="mt-4"
            items={[
              { label: branchLabel, value: repository.branch, mono: true },
              {
                label: stateLabel,
                value: repository.clean ? (
                  <Text id="projects.activity.clean">Clean</Text>
                ) : (
                  `${repository.dirty_paths.length} changed`
                ),
              },
              {
                label: latestCommitLabel,
                value: repository.commit
                  ? repository.commit.slice(0, 12)
                  : <Text id="projects.activity.no-commits">No commits</Text>,
                mono: !!repository.commit,
              },
            ]}
          />
        </section>
        <section className="px-5 py-5">
          <h2 className="text-sm font-semibold text-t1">
            <Text id="projects.activity.connect-repository">Git Remote</Text>
          </h2>
          <p className="mt-1.5 max-w-[38rem] text-xs leading-5 text-t3">
            <Text id="projects.activity.connect-repository-detail">Connect the Git remote both engineers use for protected work and review.</Text>
          </p>
          <form
            className="mt-5"
            onSubmit={(event) => {
              event.preventDefault();
              submit();
            }}
          >
            <label htmlFor="project-remote-url" className="text-xs font-semibold text-t2">
              <Text id="projects.activity.repository-url">Git Remote URL</Text>
            </label>
            <input
              ref={inputRef}
              id="project-remote-url"
              value={url}
              onChange={(event) => {
                setUrl(event.target.value);
                if (error) setError("");
              }}
              className={`${INPUT} mt-2`}
              placeholder={remotePlaceholder}
              aria-describedby="project-remote-guidance"
              aria-invalid={!!error}
            />
            <p
              id="project-remote-guidance"
              className={`mt-2 text-xs leading-5 ${error ? "text-err-text" : "text-t3"}`}
            >
              {error || (
                <Text id="projects.activity.repository-url-detail">
                  Use a secure HTTPS or SSH URL, including git@host:path. Keep passwords and tokens out of it.
                </Text>
              )}
            </p>
            <Button
              type="submit"
              variant="accent"
              className="mt-4"
              disabled={!url.trim() || connect.isPending}
            >
              {connect.isPending
                ? <Text id="projects.activity.connecting">Connecting...</Text>
                : <Text id="projects.activity.connect">Connect Git Remote</Text>}
            </Button>
          </form>
        </section>
      </div>
    </div>
  );
}

function ReviewList({
  candidates,
  selected,
  onSelect,
  commitLabel,
  commitsLabel,
  documentLabel,
  documentsLabel,
}: {
  candidates: ProjectReviewCandidate[];
  selected: ProjectReviewCandidate;
  onSelect: (commit: string) => void;
  commitLabel: string;
  commitsLabel: string;
  documentLabel: string;
  documentsLabel: string;
}) {
  return (
    <>
      <div className="flex h-[34px] flex-none items-center gap-2 border-y border-line bg-band px-3.5">
        <span className="text-xs font-semibold text-t2">
          <Text id="projects.activity.reviews">Reviews</Text>
        </span>
        <span className="text-2xs text-t3">{candidates.length}</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {candidates.map((candidate) => (
          <button
            type="button"
            key={`${candidate.branch}:${candidate.commit}`}
            onClick={() => onSelect(candidate.commit)}
            className={
              "relative w-full border-b border-line px-4 py-3 text-left transition-colors " +
              "focus-visible:z-10 focus-visible:outline focus-visible:outline-2 " +
              "focus-visible:-outline-offset-2 focus-visible:outline-focus " +
              (selected.commit === candidate.commit ? "bg-raise2" : "hover:bg-raise")
            }
          >
            <span
              aria-hidden
              className={
                "absolute inset-y-2 left-0 w-0.5 rounded-full " +
                (selected.commit === candidate.commit
                  ? "bg-acc"
                  : "bg-transparent")
              }
            />
            <span className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate text-sm font-semibold text-t1">
                {candidate.branch}
              </span>
              <Badge size="sm" tone={candidate.ready ? "ok" : "warn"}>
                {candidate.ready
                  ? <Text id="projects.activity.ready">Prepared</Text>
                  : <Text id="projects.activity.blocked">Blocked</Text>}
              </Badge>
            </span>
            <span className="mt-1.5 block font-mono text-2xs text-t3">
              {candidate.commit.slice(0, 8)} · {candidate.commit_count}{" "}
              {candidate.commit_count === 1 ? commitLabel : commitsLabel}
            </span>
            <span className="mt-1 block text-xs text-t2">
              {candidate.changed_paths.length}{" "}
              {candidate.changed_paths.length === 1
                ? documentLabel
                : documentsLabel}
            </span>
          </button>
        ))}
      </div>
    </>
  );
}

function RepositoryStanding({
  collaboration,
}: {
  collaboration:
    | ReturnType<typeof useProjectCollaboration>["data"]
    | undefined;
}) {
  const aheadLabel = useText("projects.git.ahead", "Ahead");
  const behindLabel = useText("projects.git.behind", "Behind");
  const repo = collaboration?.repository;
  if (!repo) {
    return (
      <Badge className="ml-auto" tone="warn">
        <Text id="projects.activity.git-required">Git Required</Text>
      </Badge>
    );
  }
  if (!repo.has_remote) {
    return (
      <Badge className="ml-auto" tone="warn">
        <Text id="projects.activity.local-only">Local, Not Shared</Text>
      </Badge>
    );
  }
  const synced = repo.clean && repo.ahead === 0 && repo.behind === 0;
  return (
    <div className="ml-auto flex items-center gap-2 text-xs text-t2">
      <GitIcon />
      <span className="font-mono">{repo.branch}</span>
      <Badge
        data-dev-id={repo.ahead > 0 && repo.behind > 0 ? "projects.repository-diverged" : undefined}
        tone={synced ? "ok" : "warn"}
      >
        {synced
          ? <Text id="projects.activity.synced">Aligned</Text>
          : !repo.clean
            ? <Text id="projects.activity.local-changes">Local Changes</Text>
            : `${repo.ahead} ${aheadLabel} · ${repo.behind} ${behindLabel}`}
      </Badge>
    </div>
  );
}

function WorkSessionCard({
  projectId,
  workspace,
  collaboration,
}: {
  projectId: string;
  workspace: ProjectWorkspace;
  collaboration: ReturnType<typeof useProjectCollaboration>["data"];
}) {
  const start = useStartWorkSession(projectId);
  const share = useShareWorkSession(projectId);
  const resume = useResumeWorkSession(projectId);
  const finish = useFinishWorkSession(projectId);
  const [owner, setOwner] = useState("");
  const [message, setMessage] = useState("");
  const [documents, setDocuments] = useState<string[]>([]);
  const { toast } = useToast();
  const commitPlaceholder = useText("projects.activity.commit-placeholder", "Commit message");
  const ownerPlaceholder = useText("projects.activity.owner-placeholder", "Your name");
  const resumedLabel = useText("projects.activity.toast-resumed", "Protected work resumed");
  const resumeFailed = useText("projects.activity.toast-resume-failed", "Could not resume work");
  const sharedLabel = useText("projects.activity.toast-shared", "Changes shared");
  const shareFailed = useText("projects.activity.toast-share-failed", "Could not share changes");
  const finishedLabel = useText("projects.activity.toast-finished", "Work finished");
  const finishFailed = useText("projects.activity.toast-finish-failed", "Could not finish work");
  const startedLabel = useText("projects.activity.toast-started", "Protected work started");
  const startFailed = useText(
    "projects.activity.toast-start-failed",
    "Could not start protected work",
  );
  const session = collaboration?.session;
  const recovery = collaboration?.recovery;

  // The files a claim can cover, read once per document set. Both the seeding below and the
  // claim list itself need exactly these, so the project's documents are walked once here
  // rather than filtered and mapped again at each use.
  const claimable = useMemo(
    () => workspace.documents.filter((document) => document.lock_required),
    [workspace.documents],
  );

  // Seed the claim list ONCE per lock-required document set. `documents.length` must not be
  // the guard (nor a dependency): unchecking the last file re-fired this effect and re-checked
  // every document, so a deliberate zero selection could not be reached at all. The signature
  // still re-seeds when the project itself offers a different set of documents.
  const seededDocumentsRef = useRef<string | null>(null);
  useEffect(() => {
    const lockRequired = claimable.map((document) => document.path);
    const signature = JSON.stringify(lockRequired);
    if (!lockRequired.length || seededDocumentsRef.current === signature) return;
    seededDocumentsRef.current = signature;
    setDocuments(lockRequired);
  }, [claimable]);

  if (session) {
    const needsResume = recovery && recovery.state !== "healthy";
    return (
      <div className="p-4">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-t1">
            <Text id="projects.activity.active-work">Active Work</Text>
          </span>
          <Badge size="sm" tone={needsResume ? "warn" : "ok"}>
            {needsResume
              ? <Text id="projects.activity.resume-needed">Resume Needed</Text>
              : <Text id="projects.activity.active">Active</Text>}
          </Badge>
        </div>
        <p className="mt-1 truncate font-mono text-2xs text-t3">{session.branch}</p>
        <div className="mt-3 flex flex-wrap gap-1">
          {session.documents.map((path) => (
            <Badge key={path} size="sm" tone="neutral">
              {fileName(path)}
            </Badge>
          ))}
        </div>
        {recovery?.detail ? (
          <p className="mt-3 text-xs leading-5 text-t3">{recovery.detail}</p>
        ) : null}
        {needsResume ? (
          <Button
            variant="accent"
            className="mt-3"
            disabled={!recovery?.safe_to_resume || resume.isPending}
            onClick={() =>
              resume.mutate(session.id, {
                onSuccess: () => toast(resumedLabel, "ok"),
                onError: (error) =>
                  toast(error instanceof Error ? error.message : resumeFailed, "err"),
              })
            }
          >
            {resume.isPending
              ? <Text id="projects.activity.resuming">Resuming...</Text>
              : <Text id="projects.activity.resume-work">Resume Work</Text>}
          </Button>
        ) : (
          <>
            <input
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              className={`${INPUT} mt-3`}
              placeholder={commitPlaceholder}
            />
            <div className="mt-2 flex gap-2">
              <Button
                variant="accent"
                disabled={!message.trim() || share.isPending}
                onClick={() =>
                  share.mutate(
                    { sessionId: session.id, message: message.trim() },
                    {
                      onSuccess: () => {
                        setMessage("");
                        toast(sharedLabel, "ok");
                      },
                      onError: (error) =>
                        toast(
                          error instanceof Error ? error.message : shareFailed,
                          "err",
                        ),
                    },
                  )
                }
              >
                {share.isPending
                  ? <Text id="projects.activity.sharing">Sharing...</Text>
                  : <Text id="projects.activity.share-changes">Share Changes</Text>}
              </Button>
              {session.shared_commit ? (
                <Button
                  disabled={finish.isPending}
                  onClick={() =>
                    finish.mutate(session.id, {
                      onSuccess: () => toast(finishedLabel, "ok"),
                      onError: (error) =>
                        toast(
                          error instanceof Error ? error.message : finishFailed,
                          "err",
                        ),
                    })
                  }
                >
                  <Text id="projects.activity.finish-work">Finish Work</Text>
                </Button>
              ) : null}
            </div>
          </>
        )}
      </div>
    );
  }

  const branch = owner.trim()
    ? `work/${slug(owner)}/${slug(workspace.project.name)}`
    : "";
  // One membership set for the whole list rather than a scan of the claim array per row.
  const claimed = new Set(documents);
  return (
    <div className="p-4">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold text-t1">
          <Text id="projects.activity.start-work-heading">Work Session</Text>
        </span>
        <Badge size="sm" tone="neutral">
          {workspace.eda_label}
        </Badge>
      </div>
      <p className="mt-1.5 text-xs leading-5 text-t3">
        <Text id="projects.activity.start-work-detail">Claim the project files to be edited before opening the native editor.</Text>
      </p>
      <label className="mt-4 block">
        <span className="mb-1.5 block text-xs font-medium text-t2">
          <Text id="projects.activity.owner-label">Name</Text>
        </span>
        <input
          aria-label={ownerPlaceholder}
          value={owner}
          onChange={(event) => setOwner(event.target.value)}
          className={INPUT}
          placeholder={ownerPlaceholder}
        />
      </label>
      {branch ? <p className="mt-1.5 truncate font-mono text-2xs text-t3">{branch}</p> : null}
      <div className="mb-1.5 mt-4 flex items-center">
        <span className="text-xs font-medium text-t2">
          <Text id="projects.activity.project-files">Project Files</Text>
        </span>
        <Badge className="ml-auto" size="sm" tone="neutral">
          {documents.length}
        </Badge>
      </div>
      <div className="border-y border-line">
        {claimable.map((document) => (
          <label
            key={document.document_id}
            className="flex items-center gap-2 border-b border-line px-1 py-2.5 text-xs text-t2 transition-colors last:border-b-0 hover:bg-raise"
          >
            <input
              type="checkbox"
              checked={claimed.has(document.path)}
              onChange={(event) =>
                setDocuments((current) =>
                  event.target.checked
                    ? [...current, document.path]
                    : current.filter((path) => path !== document.path),
                )
              }
              className="accent-[var(--c-acc)]"
            />
            <span className="truncate">{document.label}</span>
          </label>
        ))}
      </div>
      <Button
        variant="accent"
        className="mt-4 w-full"
        disabled={!owner.trim() || !documents.length || start.isPending}
        onClick={() =>
          start.mutate(
            { owner: owner.trim(), branch, documents },
            {
              onSuccess: () => toast(startedLabel, "ok"),
              onError: (error) =>
                toast(
                  error instanceof Error ? error.message : startFailed,
                  "err",
                ),
            },
          )
        }
      >
        {start.isPending
          ? <Text id="projects.activity.starting">Starting...</Text>
          : <Text id="projects.activity.start-work">Start Work</Text>}
      </Button>
    </div>
  );
}

function ReviewInspector({
  projectId,
  candidate,
}: {
  projectId: string;
  candidate: ProjectReviewCandidate | undefined;
}) {
  const evidence = useProjectReviewEvidence(projectId, candidate);
  const validate = useValidateProjectReview(projectId);
  const approve = useApproveProjectReview(projectId);
  const requestChanges = useRequestProjectChanges(projectId);
  const [reviewer, setReviewer] = useState("");
  const [message, setMessage] = useState("");
  const { toast } = useToast();
  const reviewAria = useText("projects.activity.review-evidence-aria", "Review evidence");
  const reviewerPlaceholder = useText("projects.activity.reviewer-placeholder", "Reviewer name");
  const requestPlaceholder = useText("projects.activity.request-placeholder", "What should change?");
  const reviewerLabel = useText("projects.activity.reviewer-label", "Reviewer Name");
  const reviewNoteLabel = useText("projects.activity.review-note-label", "Review Note");
  const decisionLabel = useText("projects.activity.decision", "Decision");
  const selectReview = useText("projects.activity.select-review", "Select a review.");
  const checkingCommit = useText("projects.activity.checking-commit", "Checking commit...");
  const changedFilesLabel = useText("projects.activity.changed-files", "Changed Files");
  const reviewChecksLabel = useText("projects.activity.review-checks", "Review Checks");
  const filesLabel = useText("projects.activity.files", "Files");
  const bomLinkedLabel = useText("projects.activity.bom-linked", "BOM Linked");
  const designChecksLabel = useText("projects.activity.design-checks", "Design Checks");
  const errorsLabel = useText("projects.activity.errors", "errors");
  const sourceLabel = useText("projects.activity.source", "Source");
  const nativeChecksLabel = useText("projects.activity.native-checks", "Native Checks");
  const visualDiffLabel = useText("projects.activity.visual-diff", "Visual Diff");
  const validationFinished = useText(
    "projects.activity.toast-validation-finished",
    "Native validation finished",
  );
  const validationFailed = useText(
    "projects.activity.toast-validation-failed",
    "Could not run native checks",
  );
  const changesRequested = useText(
    "projects.activity.toast-changes-requested",
    "Changes requested",
  );
  const requestFailed = useText(
    "projects.activity.toast-request-failed",
    "Could not request changes",
  );
  const approvedLabel = useText(
    "projects.activity.toast-approved",
    "Review approved and merged",
  );
  const approvalFailed = useText(
    "projects.activity.toast-approval-failed",
    "Could not approve review",
  );
  const approvesCommitLabel = useText(
    "projects.activity.approves-commit",
    "Approves commit",
  );

  if (!candidate) {
    return <ChangesMessage>{selectReview}</ChangesMessage>;
  }
  const result = evidence.data;
  const validation = result?.native_validation;
  const canApprove =
    candidate.ready &&
    !!result?.reviewable &&
    validation?.status === "passed" &&
    !approve.isPending;

  return (
    <aside
      data-dev-id="projects.shared-review"
      className="min-h-0 overflow-y-auto p-5"
      aria-label={reviewAria}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-t3">
            <Text id="projects.activity.review">Review</Text>
          </p>
          <h3 className="mt-1 truncate text-lg font-semibold text-t1">{candidate.branch}</h3>
          <p className="mt-1 font-mono text-xs text-t3">
            {candidate.commit.slice(0, 12)} onto {candidate.base_branch}
          </p>
        </div>
        <Badge tone={candidate.ready ? "ok" : "warn"}>
          {candidate.ready
            ? <Text id="projects.activity.review-ready">Prepared</Text>
            : <Text id="projects.activity.review-blocked-state">Blocked</Text>}
        </Badge>
      </div>

      {!candidate.ready ? (
        <Panel inset className="mt-4">
          <p className="text-sm font-medium text-warn">
            <Text id="projects.activity.review-blocked">Review Blocked</Text>
          </p>
          <p className="mt-1 text-xs leading-5 text-t3">{candidate.blocked_reason}</p>
        </Panel>
      ) : evidence.isLoading ? (
        <ChangesMessage>{checkingCommit}</ChangesMessage>
      ) : evidence.error ? (
        <ChangesMessage>
          <ErrorState dense id="projects.activity.evidence-failed" onRetry={() => evidence.refetch()}>
            The evidence for this commit could not be read.
          </ErrorState>
        </ChangesMessage>
      ) : result ? (
        <>
          <ProjectInspectorFacts
            items={[
              {
                label: filesLabel,
                value: <span className="font-mono">{result.documents.length}</span>,
              },
              {
                label: bomLinkedLabel,
                value: (
                  <span
                    className={`font-mono ${
                      result.bom.lines.every((line) => line.identity_ready)
                        ? "text-ok-text"
                        : "text-warn"
                    }`}
                  >
                    {result.bom.lines.filter((line) => line.identity_ready).length}/
                    {result.bom.line_count}
                  </span>
                ),
              },
              {
                label: designChecksLabel,
                value: (
                  <span
                    className={`font-mono ${
                      result.semantic_audit.counts.by_severity.error === 0
                        ? "text-ok-text"
                        : "text-err-text"
                    }`}
                  >
                    {result.semantic_audit.counts.by_severity.error} {errorsLabel}
                  </span>
                ),
              },
            ]}
          />

          <ReviewSection
            title={changedFilesLabel}
            count={candidate.changed_paths.length}
          >
            <div className="divide-y divide-line border-y border-line">
              {candidate.changed_paths.map((path) => (
                <div key={path} className="flex items-center gap-3 py-2.5">
                  <span className="min-w-0 flex-1 truncate font-mono text-xs text-t2">
                    {path}
                  </span>
                  <Badge size="sm" tone="neutral">
                    <Text id="projects.activity.changed">Changed</Text>
                  </Badge>
                </div>
              ))}
            </div>
          </ReviewSection>

          <ReviewSection title={reviewChecksLabel}>
            <div className="border-y border-line">
              <GateRow
                label={sourceLabel}
                status={result.reviewable ? "passed" : "failed"}
              />
              <GateRow
                label={nativeChecksLabel}
                status={validation?.status ?? "pending"}
                detail={validation?.detail}
              />
              <GateRow
                label={visualDiffLabel}
                status={result.visual_diff.status}
                detail={result.visual_diff.detail}
              />
            </div>
            {validation?.status !== "passed" ? (
              <Button
                className="mt-3"
                disabled={validate.isPending}
                onClick={() =>
                  validate.mutate(candidate, {
                    onSuccess: () => toast(validationFinished, "ok"),
                    onError: (error) =>
                      toast(
                        error instanceof Error ? error.message : validationFailed,
                        "err",
                      ),
                  })
                }
              >
                {validate.isPending
                  ? <Text id="projects.activity.checking">Checking...</Text>
                  : <Text id="projects.activity.run-native-checks">Run Native Checks</Text>}
              </Button>
            ) : null}
          </ReviewSection>

          <section className="mt-5 border-t border-line pt-4">
            <h4 className="text-xs font-semibold text-t2">{decisionLabel}</h4>
            <div className="mt-3 grid gap-4 @xl:grid-cols-2">
              <div>
                <label className="block">
                  <span className="mb-1.5 block text-xs font-medium text-t2">
                    {reviewerLabel}
                  </span>
                  <input
                    aria-label={reviewerLabel}
                    value={reviewer}
                    onChange={(event) => setReviewer(event.target.value)}
                    className={INPUT}
                    placeholder={reviewerPlaceholder}
                  />
                </label>
                <label className="mt-3 block">
                  <span className="mb-1.5 block text-xs font-medium text-t2">
                    {reviewNoteLabel}
                  </span>
                  <input
                    aria-label={reviewNoteLabel}
                    value={message}
                    onChange={(event) => setMessage(event.target.value)}
                    className={INPUT}
                    placeholder={requestPlaceholder}
                  />
                </label>
                <Button
                  variant="ghost-danger"
                  className="mt-2"
                  disabled={!reviewer.trim() || !message.trim() || requestChanges.isPending}
                  onClick={() =>
                    requestChanges.mutate(
                      {
                        ...candidate,
                        reviewer: reviewer.trim(),
                        message: message.trim(),
                      },
                      {
                        onSuccess: () => {
                          setMessage("");
                          toast(changesRequested, "ok");
                        },
                        onError: (error) =>
                          toast(
                            error instanceof Error
                              ? error.message
                              : requestFailed,
                            "err",
                          ),
                      },
                    )
                  }
                >
                  <Text id="projects.activity.request-changes">Request Changes</Text>
                </Button>
              </div>
              <div className="flex flex-col items-end justify-end">
                <p className="mb-2 text-right text-xs leading-5 text-t3">
                  {approvesCommitLabel} {candidate.commit.slice(0, 12)}.
                </p>
                <Button
                  variant="accent"
                  disabled={!canApprove}
                  onClick={() =>
                    approve.mutate(candidate, {
                      onSuccess: () => toast(approvedLabel, "ok"),
                      onError: (error) =>
                        toast(
                          error instanceof Error ? error.message : approvalFailed,
                          "err",
                        ),
                    })
                  }
                >
                  {approve.isPending
                    ? <Text id="projects.activity.approving">Approving...</Text>
                    : <Text id="projects.activity.approve-merge">Approve And Merge</Text>}
                </Button>
              </div>
            </div>
          </section>
        </>
      ) : null}
    </aside>
  );
}

function ReviewSection({
  title,
  count,
  children,
}: {
  title: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-5">
      <div className="mb-2 flex items-center gap-2">
        <h4 className="text-xs font-semibold text-t2">{title}</h4>
        {count === undefined ? null : (
          <span className="font-mono text-2xs text-t3">{count}</span>
        )}
      </div>
      {children}
    </section>
  );
}

function GateRow({
  label,
  status,
  detail,
}: {
  label: string;
  status: "pending" | "passed" | "failed" | "blocked";
  detail?: string;
}) {
  const passedLabel = useText("projects.activity.passed", "Passed");
  const failedLabel = useText("projects.activity.failed", "Failed");
  const blockedLabel = useText("projects.activity.gate-blocked", "Blocked");
  const pendingLabel = useText("projects.activity.pending", "Pending");
  const tone = status === "passed" ? "ok" : status === "failed" ? "err" : "warn";
  return (
    <div className="border-b border-line py-2 last:border-b-0">
      <div className="flex items-center gap-2">
        <span className="text-sm text-t2">{label}</span>
        <Badge size="sm" tone={tone} className="ml-auto">
          {status === "passed"
            ? passedLabel
            : status === "failed"
              ? failedLabel
              : status === "blocked"
                ? blockedLabel
                : pendingLabel}
        </Badge>
      </div>
      {detail ? <p className="mt-1 text-xs leading-5 text-t3">{detail}</p> : null}
    </div>
  );
}

/** The centring frame a state block sits in. The state decides its own tone. */
function ChangesMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-[240px] flex-1 items-center justify-center p-6 text-center text-sm text-t3">
      {children}
    </div>
  );
}

const INPUT =
  "h-9 w-full rounded-control border border-line bg-field px-3 text-sm text-t1 outline-none " +
  "placeholder:text-t3 focus:border-focus focus-visible:outline focus-visible:outline-2 " +
  "focus-visible:outline-offset-1 focus-visible:outline-focus";

function slug(value: string) {
  return value
    .trim()
    .toLocaleLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function fileName(path: string) {
  return path.replaceAll("\\", "/").split("/").pop() || path;
}
