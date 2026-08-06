import { useState } from "react";
import {
  useOpenProjectDocument,
  useProjectPlacementGeometry,
} from "../../api/queries";
import type {
  ProjectCollaboration,
  ProjectDocument,
  ProjectPlacement,
  ProjectWorkspace,
} from "../../api/types";
import { Text, useText } from "../../lib/copy";
import { useToast } from "../../lib/toast";
import { Badge, Button, Dot } from "../primitives";
import { BoardIcon, GitIcon } from "../icons";
import { ProjectPlacementStage } from "./ProjectPlacementStage";
import { ProjectInspectorFacts } from "./ProjectInspectorFacts";
import { AdaptiveChoice } from "../AdaptiveChoice";

export function ProjectDesignWorkbench({
  workspace,
  collaboration,
}: {
  workspace: ProjectWorkspace;
  collaboration: ProjectCollaboration | undefined;
}) {
  const geometry = useProjectPlacementGeometry(workspace.project.id);
  // The opening choice is read once, on mount: React discards every later result, so an
  // eager call here only re-scanned the document list on every render.
  const [chosenDocumentId, setChosenDocumentId] = useState(
    () =>
      workspace.documents.find((document) => document.kind === "pcb")?.document_id ??
      workspace.documents[0]?.document_id ??
      "",
  );
  const [selectedReference, setSelectedReference] = useState("");
  const documentListLabel = useText("projects.overview.documents-aria", "Project documents");
  const inspectorLabel = useText("projects.overview.inspector-aria", "Project selection");
  const compactDocumentLabel = useText(
    "projects.overview.compact-document",
    "Project File",
  );
  const claimLabel = useText("projects.overview.file-claim", "Claim Needed");
  const missingLabel = useText("projects.overview.file-missing", "Missing");

  // A chosen file that the project no longer offers falls back to the first one DURING
  // render. Writing the fallback back into state took an extra render to settle, which
  // showed the empty inspector for a frame; the settled choice is the same either way.
  const selectedDocumentId =
    chosenDocumentId &&
    !workspace.documents.some((document) => document.document_id === chosenDocumentId)
      ? workspace.documents[0]?.document_id ?? ""
      : chosenDocumentId;

  const selectedDocument =
    workspace.documents.find((document) => document.document_id === selectedDocumentId) ?? null;
  const selectedPlacement =
    geometry.data?.placements.find(
      (placement) =>
        placement.reference === selectedReference &&
        selectedDocument?.kind === "pcb" &&
        sameDocumentPath(placement.board, selectedDocument.path),
    ) ?? null;
  const selectDocument = (documentId: string) => {
    setChosenDocumentId(documentId);
    setSelectedReference("");
  };
  return (
    <div
      data-dev-id="projects.overview"
      className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_228px] overflow-hidden bg-surface max-[1180px]:grid-cols-[minmax(0,1fr)_205px] @[60rem]:grid-cols-[192px_minmax(420px,1fr)_236px]"
    >
      <section
        className="hidden min-h-0 min-w-0 flex-col border-r border-line @[60rem]:flex"
        aria-label={documentListLabel}
      >
        <header className="flex h-[40px] flex-none items-center border-b border-line bg-band px-3">
          <h2 className="text-xs font-semibold text-t1">
            <Text id="projects.overview.documents">Project Files</Text>
          </h2>
          <Badge size="sm" tone="neutral" className="ml-auto">
            {workspace.documents.length}
          </Badge>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {workspace.documents.map((document) => {
            const selected = document.document_id === selectedDocumentId && !selectedPlacement;
            const context = documentContext(document);
            return (
              <button
                key={document.document_id}
                type="button"
                onClick={() => selectDocument(document.document_id)}
                className={
                  "relative flex w-full items-center gap-2.5 border-b border-line px-2.5 py-2.5 text-left " +
                  "transition-colors focus-visible:z-10 focus-visible:outline focus-visible:outline-2 " +
                  "focus-visible:-outline-offset-2 focus-visible:outline-acc " +
                  (selected ? "bg-raise2" : "hover:bg-raise")
                }
              >
                <span
                  aria-hidden
                  className={
                    "absolute inset-y-2 left-0 w-0.5 rounded-full " +
                    (selected ? "bg-acc" : "bg-transparent")
                  }
                />
                <span className="flex h-7 w-7 flex-none items-center justify-center rounded-control bg-field text-t3">
                  <DocumentGlyph kind={document.kind} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-t1">
                    {document.label}
                  </span>
                  {context ? (
                    <span className="mt-0.5 block truncate font-mono text-2xs text-t3">
                      {context}
                    </span>
                  ) : null}
                </span>
                {!document.exists ? (
                  <span className="flex-none text-2xs font-medium text-err-text">
                    {missingLabel}
                  </span>
                ) : document.lock_required ? (
                  <span className="flex-none text-2xs font-medium text-warn">
                    {claimLabel}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
        <div className="flex-none border-t border-line bg-band p-3">
          <RepositorySummary collaboration={collaboration} />
        </div>
      </section>

      <div className="min-h-0 min-w-0 border-r border-line">
        <ProjectPlacementStage
          projectId={workspace.project.id}
          geometry={geometry.data}
          unavailable={!!geometry.error}
          selectedReferences={selectedReference ? [selectedReference] : []}
          activeReference={selectedReference}
          onRetry={() => geometry.refetch()}
          onBoardChange={(board) => {
            setSelectedReference("");
            const boardDocument = workspace.documents.find(
              (document) =>
                document.kind === "pcb" && sameDocumentPath(document.path, board),
            );
            if (boardDocument) setChosenDocumentId(boardDocument.document_id);
          }}
          onSideChange={() => setSelectedReference("")}
          onSelectReference={(reference, board) => {
            setSelectedReference(reference);
            const boardDocument = workspace.documents.find(
              (document) =>
                document.kind === "pcb" && sameDocumentPath(document.path, board),
            );
            if (boardDocument) setChosenDocumentId(boardDocument.document_id);
          }}
          className="h-full !rounded-none !border-0"
        />
      </div>

      <aside
        className="min-h-0 overflow-y-auto px-3.5 pb-4 pt-3"
        aria-label={inspectorLabel}
      >
        <label className="mb-3 block @[60rem]:hidden">
          <span className="mb-1.5 block text-xs font-medium text-t2">
            {compactDocumentLabel}
          </span>
          <AdaptiveChoice
            devId="projects.document-control"
            label={compactDocumentLabel}
            value={selectedDocumentId}
            onChange={selectDocument}
            className="h-9 w-full"
            options={workspace.documents.map((document) => ({ value: document.document_id, label: document.label }))}
          />
        </label>
        {selectedPlacement ? (
          <PlacementInspector
            placement={selectedPlacement}
            editorName={workspace.eda_label}
          />
        ) : selectedDocument ? (
          <DocumentInspector document={selectedDocument} workspace={workspace} />
        ) : (
          <p className="text-sm text-t3">
            <Text id="projects.overview.select">
              Select a document or placement to inspect it.
            </Text>
          </p>
        )}
      </aside>
    </div>
  );
}

function PlacementInspector({
  placement,
  editorName,
}: {
  placement: ProjectPlacement;
  editorName: string;
}) {
  const boardLabel = useText("projects.overview.field.board", "Board");
  const sideLabel = useText("projects.overview.field.side", "Side");
  const topLabel = useText("projects.side.top", "Top");
  const bottomLabel = useText("projects.side.bottom", "Bottom");
  const xLabel = useText("projects.overview.field.x", "X");
  const yLabel = useText("projects.overview.field.y", "Y");
  const rotationLabel = useText("projects.overview.field.rotation", "Rotation");
  const editPlacementLabel = useText(
    "projects.overview.native-edit",
    "Edit placement or routing in",
  );
  return (
    <>
      <p className="text-xs font-semibold text-t3">
        <Text id="projects.overview.selected-placement">Selected Placement</Text>
      </p>
      <h3 className="mt-1 font-mono text-2xl font-semibold text-t1">
        {placement.reference}
      </h3>
      <p className="mt-1 truncate font-mono text-xs text-t3">{placement.footprint}</p>
      <ProjectInspectorFacts
        items={[
          { label: boardLabel, value: placement.board },
          {
            label: sideLabel,
            value: placement.side === "top" ? topLabel : bottomLabel,
          },
          { label: xLabel, value: `${formatNumber(placement.x_mm)} mm`, mono: true },
          { label: yLabel, value: `${formatNumber(placement.y_mm)} mm`, mono: true },
          {
            label: rotationLabel,
            value: `${formatNumber(placement.rotation_deg)}°`,
            mono: true,
          },
        ]}
      />
      <p className="mt-4 text-xs leading-5 text-t3">
        {editPlacementLabel} {editorName}.
      </p>
    </>
  );
}

function DocumentInspector({
  document,
  workspace,
}: {
  document: ProjectDocument;
  workspace: ProjectWorkspace;
}) {
  const openDocument = useOpenProjectDocument(workspace.project.id);
  const { toast } = useToast();
  const typeLabel = useText("projects.overview.field.type", "Kind");
  const pathLabel = useText("projects.overview.field.path", "Path");
  const editorLabel = useText("projects.overview.field.editor", "Editor");
  const runtimeLabel = useText("projects.overview.field.runtime", "Runtime");
  const pcbType = useText("projects.document-type.pcb", "PCB");
  const schematicType = useText("projects.document-type.schematic", "Schematic");
  const projectType = useText("projects.document-type.project", "Project");
  const readyLabel = useText("projects.runtime.ready", "Free");
  const busyLabel = useText("projects.runtime.busy", "In Use");
  const notInstalledLabel = useText("projects.runtime.not-installed", "Not Installed");
  const blockedLabel = useText("projects.runtime.blocked", "Blocked");
  const notDetectedLabel = useText("projects.runtime.not-detected", "Not Detected");
  const openedLabel = useText("projects.overview.toast-opened", "Opened in");
  const openFailed = useText(
    "projects.overview.toast-open-failed",
    "Could not open document",
  );
  const editorName = workspace.eda_label;
  const openLabel = `Open In ${editorName}`;
  const runtimeValue =
    workspace.runtime.version ||
    (workspace.runtime.status === "ready"
      ? readyLabel
      : workspace.runtime.status === "busy"
        ? busyLabel
        : workspace.runtime.status === "unavailable" ||
            workspace.runtime.status === "not-installed"
          ? notInstalledLabel
          : workspace.runtime.status === "blocked"
            ? blockedLabel
            : notDetectedLabel);
  return (
    <>
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 flex-none items-center justify-center rounded-control border border-line bg-field text-t3">
          <DocumentGlyph kind={document.kind} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-t3">
            <Text id="projects.overview.selected-document">Selected Document</Text>
          </p>
          <h3 className="mt-1 break-words text-lg font-semibold text-t1">
            {document.label}
          </h3>
          <Badge
            size="sm"
            tone={document.exists ? (document.lock_required ? "warn" : "ok") : "err"}
            className="mt-2"
          >
            {document.exists
              ? document.lock_required
                ? <Text id="projects.overview.claim-to-edit">Claim Required</Text>
                : <Text id="projects.overview.shared-state">Shared</Text>
              : <Text id="projects.overview.missing">Missing</Text>}
          </Badge>
        </div>
      </div>
      <ProjectInspectorFacts
        items={[
          {
            label: typeLabel,
            value:
            document.kind === "pcb"
              ? pcbType
              : document.kind === "schematic"
                ? schematicType
                : projectType,
          },
          { label: pathLabel, value: document.path, mono: true },
          { label: editorLabel, value: workspace.eda_label },
          { label: runtimeLabel, value: runtimeValue, mono: true },
        ]}
      />
      <Button
        variant="accent"
        className="mt-4 w-full justify-center"
        disabled={!document.exists || openDocument.isPending}
        onClick={() =>
          openDocument.mutate(document.document_id, {
            onSuccess: () => toast(`${openedLabel} ${editorName}`, "ok"),
            onError: (error) =>
              toast(
                error instanceof Error ? error.message : openFailed,
                "err",
              ),
          })
        }
      >
        {openDocument.isPending ? (
          <Text id="projects.overview.opening">Opening...</Text>
        ) : (
          openLabel
        )}
      </Button>
      <p className="mt-4 text-xs leading-5 text-t3">
        {document.lock_required ? (
          <Text id="projects.overview.claim">Claim this file in Recent Work before editing.</Text>
        ) : (
          <Text id="projects.overview.shared">
            This file is available to open without a claim.
          </Text>
        )}
      </p>
    </>
  );
}

function RepositorySummary({
  collaboration,
}: {
  collaboration: ProjectCollaboration | undefined;
}) {
  const syncedLabel = useText("projects.git.synced", "Aligned");
  const localChangesLabel = useText("projects.git.local-changes", "Local Changes");
  const behindLabel = useText("projects.git.behind", "Behind");
  const aheadLabel = useText("projects.git.ahead", "Ahead");
  const noCommitLabel = useText("projects.git.no-commit", "No commit");
  const sharedLabel = useText("projects.git.shared", "Shared");
  const localOnlyLabel = useText("projects.git.local-only", "Local, not shared");
  const repo = collaboration?.repository;
  if (!repo) {
    return (
      <div className="flex gap-2.5">
        <Dot tone="warn" />
        <div>
          <p className="text-xs font-medium text-t1">
            <Text id="projects.overview.git-required">Git Required</Text>
          </p>
          <p className="mt-1 text-2xs leading-4 text-t3">
            <Text id="projects.overview.git-required-detail">
              Initialize Git for this project, then add a remote for protected work.
            </Text>
          </p>
        </div>
      </div>
    );
  }
  return (
    <div>
      <div className="flex items-center gap-2 text-xs font-medium text-t1">
        <GitIcon />
        <span className="min-w-0 truncate">{repo.branch}</span>
        <Badge
          size="sm"
          tone={repo.clean && repo.ahead === 0 && repo.behind === 0 ? "ok" : "warn"}
          className="ml-auto"
        >
          {repo.clean
            ? repo.behind
              ? `${repo.behind} ${behindLabel}`
              : repo.ahead
                ? `${repo.ahead} ${aheadLabel}`
                : syncedLabel
            : localChangesLabel}
        </Badge>
      </div>
      <p className="mt-2 truncate font-mono text-2xs text-t3">
        {shortCommit(repo.commit, noCommitLabel)} ·{" "}
        {repo.has_remote ? sharedLabel : localOnlyLabel}
      </p>
    </div>
  );
}

function DocumentGlyph({ kind }: { kind: "project" | "schematic" | "pcb" }) {
  return kind === "pcb" ? (
    <BoardIcon />
  ) : (
    <span className="font-mono text-2xs font-semibold">
      {kind === "schematic" ? "SCH" : "PRJ"}
    </span>
  );
}

function formatNumber(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function shortCommit(commit: string, fallback: string) {
  return commit ? commit.slice(0, 8) : fallback;
}

function sameDocumentPath(left: string, right: string) {
  const normalize = (value: string) => value.replaceAll("\\", "/").toLocaleLowerCase();
  return normalize(left) === normalize(right);
}

function documentContext(document: ProjectDocument) {
  const normalizedPath = document.path.replaceAll("\\", "/");
  const normalizedLabel = document.label.replaceAll("\\", "/");
  if (normalizedPath.toLocaleLowerCase() === normalizedLabel.toLocaleLowerCase()) {
    return "";
  }
  const parts = normalizedPath.split("/");
  const fileName = parts.pop() ?? "";
  if (fileName.toLocaleLowerCase() === normalizedLabel.toLocaleLowerCase()) {
    return parts.join("/");
  }
  return normalizedPath;
}
