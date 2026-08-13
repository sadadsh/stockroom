/**
 * The integrated datasheet viewer.
 *
 * A datasheet is the document an engineer actually reads, and `window.open()` sent them out of the
 * application to read it - losing the selected component, the three columns' scroll positions and
 * every filter they had set. This keeps all of that: the viewer opens ON TOP of the workspace, and
 * closing it puts focus back on the control that opened it.
 *
 * It has to hold every real shape at once, and it does: a PDF stored on this machine, a PDF that
 * exists only as a URL, both at once, several revisions of one document, an HTML product page that
 * is not a PDF at all, a stored file that is no longer on disk, and a load that simply fails. The
 * last three are the ones that used to produce an empty grey pane. They do not any more - a failure
 * NAMES what failed, keeps the viewer open, and offers Retry and the source page beside it, because
 * "the manufacturer's own URL still works" is exactly the thing a person needs when our copy does
 * not.
 *
 * The worker assignment lives in this module deliberately. pdf.js resolves its worker once, at the
 * moment the first document is parsed, so setting it anywhere the components are not guaranteed to
 * have imported produces a viewer that works in development and silently falls back to the main
 * thread in a build.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Document, Outline, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { api, ApiError } from "../../api/client";
import type { DocumentView } from "../../api/dossierTypes";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { openExternalUrl } from "../../lib/externalNavigation";
import { Button, ModalShell, StatusText } from "../primitives";
import { ExternalIcon } from "../icons";
import { openKindFor, type DatasheetTarget } from "./datasheetWorkflow";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

/**
 * Where pdf.js finds the 14 standard fonts, copied into the bundle by `viteStaticCopy`.
 *
 * Relative, because the app is served both from the API mount and from `file://` and an absolute
 * path resolves to the wrong root in one of the two.
 */
const PDF_OPTIONS = { standardFontDataUrl: "standard_fonts/" } as const;

const ZOOM_STEPS: readonly number[] = [0.5, 0.75, 1, 1.25, 1.5, 2, 3];
/**
 * Where the viewer opens: 100%, found by name in the ladder above rather than written as an index.
 *
 * Resolved ONCE, here, because it is a property of a module constant and cannot change. Passed
 * straight to `useState` it was recomputed on every render of the viewer and the answer thrown away,
 * since React keeps only the first initial value it is given.
 */
const ZOOM_DEFAULT_AT = ZOOM_STEPS.indexOf(1);

/** What the viewer is doing. A failure is a STATE the viewer holds, never a toast it fires. */
type ViewerState =
  | { phase: "loading" }
  | { phase: "ready" }
  | { phase: "failed"; reason: string };

export interface DatasheetViewerProps {
  open: boolean;
  componentId: string;
  target: DatasheetTarget | null;
  onClose: () => void;
}

export function DatasheetViewer({ open, componentId, target, onClose }: DatasheetViewerProps) {
  const title = useText("component-browser.datasheet-viewer", "Datasheet");
  const document = target?.document ?? null;
  return (
    <ModalShell
      open={open && document !== null}
      title={document ? document.title || title : title}
      onClose={onClose}
      size="sheet"
      devId="component-browser.datasheet-viewer"
      closeDevId="component-browser.datasheet-viewer-close"
    >
      {open && target && document ? (
        <DatasheetBody componentId={componentId} target={target} document={document} />
      ) : null}
    </ModalShell>
  );
}

function DatasheetBody({
  componentId,
  target,
  document,
}: {
  componentId: string;
  target: DatasheetTarget;
  document: DocumentView;
}) {
  const kind = openKindFor(document);
  // An HTML resource is not a document and must never be shown in a PDF pane. It is labelled for
  // what it is and opened where it lives.
  if (kind === "page") return <DatasheetPageResource document={document} />;
  if (kind === "none") return <DatasheetUnavailable document={document} reason="" />;
  return <DatasheetPdf componentId={componentId} target={target} document={document} />;
}

/**
 * An HTML datasheet page. Labelled `Datasheet Page`, with the external icon, so nobody expects a
 * PDF that does not exist.
 */
function DatasheetPageResource({ document }: { document: DocumentView }) {
  const openLabel = useCopyFormatter("component-browser.datasheet-open-page", "Open {host}");
  return (
    <div
      data-dev-id="component-browser.datasheet-page-resource"
      className="flex flex-col gap-2 p-3"
    >
      <p className="ui-row-primary">
        <Text id="component-browser.datasheet-page-title">Datasheet Page</Text>
      </p>
      <p className="ui-component-description">
        <Text id="component-browser.datasheet-page-body">
          This reference is a web page rather than a PDF, so there is no document to show here.
        </Text>
      </p>
      {document.remoteUrl ? (
        <span>
          <Button
            small
            data-dev-id="component-browser.datasheet-open-page"
            icon={<ExternalIcon className="h-3.5 w-3.5" />}
            onClick={() => openExternalUrl(document.remoteUrl)}
          >
            {openLabel({ host: document.host || document.sourceLabel })}
          </Button>
        </span>
      ) : null}
    </div>
  );
}

/** Nothing can be opened at all. A real answer, stated, rather than a disabled control. */
function DatasheetUnavailable({
  document,
  reason,
}: {
  document: DocumentView;
  reason: string;
}) {
  const openSource = useText("component-browser.datasheet-open-source", "Open Source Page");
  return (
    <div data-dev-id="component-browser.datasheet-unavailable" className="flex flex-col gap-2 p-3">
      <p className="ui-row-primary">
        <Text id="component-browser.datasheet-unavailable">This document could not be opened</Text>
      </p>
      {reason ? (
        <p data-dev-id="component-browser.datasheet-failure-reason" className="ui-component-description text-err-text">
          {reason}
        </p>
      ) : null}
      {document.remoteUrl ? (
        <span>
          <Button
            small
            data-dev-id="component-browser.datasheet-open-source"
            icon={<ExternalIcon className="h-3.5 w-3.5" />}
            onClick={() => openExternalUrl(document.remoteUrl)}
          >
            {openSource}
          </Button>
        </span>
      ) : null}
    </div>
  );
}

/**
 * The PDF itself, with the controls an engineer reads a datasheet with.
 *
 * `<Outline>` is the document's own table of contents, so page navigation is by SECTION rather
 * than by guessing a page number; the page stepper, the zoom and the rotation are the rest.
 */
function DatasheetPdf({
  componentId,
  target,
  document,
}: {
  componentId: string;
  target: DatasheetTarget;
  document: DocumentView;
}) {
  const [state, setState] = useState<ViewerState>({ phase: "loading" });
  const [source, setSource] = useState<{ data: ArrayBuffer } | { url: string } | null>(null);
  const [pageCount, setPageCount] = useState(0);
  const [page, setPage] = useState(1);
  const [zoomAt, setZoomAt] = useState(ZOOM_DEFAULT_AT);
  const [rotation, setRotation] = useState(0);
  const [attempt, setAttempt] = useState(0);

  const kind = openKindFor(document);
  const outlineLabel = useText("component-browser.datasheet-outline", "Datasheet contents");
  const fileFailed = useCopyFormatter(
    "component-browser.datasheet-file-failed",
    "The stored file could not be read: {reason}",
  );
  const renderFailed = useText(
    "component-browser.datasheet-render-failed",
    "This PDF could not be shown.",
  );

  // Load every PDF through the authenticated document endpoint. It serves local files and safely
  // proxies public remote PDFs, so pdf.js never depends on distributor CORS policy.
  useEffect(() => {
    let live = true;
    setState({ phase: "loading" });
    setPage(1);
    setSource(null);
    api
      .documentFile(componentId, target.id)
      .then((blob) => blob.arrayBuffer())
      .then((data) => {
        if (!live) return;
        setSource({ data });
      })
      .catch((error: unknown) => {
        if (!live) return;
        // A file recorded on the record but no longer on disk is a 404 here. Saying so, and
        // offering the URL beside it, is the difference between a dead pane and a next step.
        const detail =
          error instanceof ApiError ? error.message : String((error as Error)?.message ?? error);
        setState({ phase: "failed", reason: fileFailed({ reason: detail }) });
      });
    return () => {
      live = false;
    };
    // `fileFailed` is a fresh closure every render; the identity of the document is the trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [componentId, target.id, document.remoteUrl, kind, attempt]);

  const file = useMemo(() => source, [source]);

  const onLoad = useCallback((pdf: { numPages: number }) => {
    setPageCount(pdf.numPages);
    setState({ phase: "ready" });
  }, []);

  const onLoadError = useCallback(
    (error: Error) => {
      setState({ phase: "failed", reason: error?.message || renderFailed });
    },
    [renderFailed],
  );

  if (state.phase === "failed") {
    return (
      <DatasheetFailure
        document={document}
        reason={state.reason}
        onRetry={() => setAttempt((value) => value + 1)}
      />
    );
  }

  return (
    <div data-dev-id="component-browser.datasheet-pdf" className="flex min-h-0 flex-col">
      <DatasheetToolbar
        document={document}
        page={page}
        pageCount={pageCount}
        zoom={ZOOM_STEPS[zoomAt]}
        onPage={setPage}
        onZoomIn={() => setZoomAt((at) => Math.min(at + 1, ZOOM_STEPS.length - 1))}
        onZoomOut={() => setZoomAt((at) => Math.max(at - 1, 0))}
        onRotate={() => setRotation((value) => (value + 90) % 360)}
      />
      <div className="flex min-h-0 flex-1 gap-2 overflow-hidden p-2">
        {file ? (
          <Document
            file={file}
            options={PDF_OPTIONS}
            onLoadSuccess={onLoad}
            onLoadError={onLoadError}
            loading={
              <p className="ui-component-metadata p-2">
                <Text id="component-browser.datasheet-loading">Loading the datasheet</Text>
              </p>
            }
            error={
              <p className="ui-component-metadata p-2 text-err-text">
                <Text id="component-browser.datasheet-render-failed">
                  This PDF could not be shown.
                </Text>
              </p>
            }
            className="flex min-h-0 flex-1 gap-2"
          >
            <nav
              data-dev-id="component-browser.datasheet-outline"
              aria-label={outlineLabel}
              className="ui-component-metadata min-h-0 w-[13rem] flex-none overflow-auto border border-line bg-panel p-2"
            >
              <Outline onItemClick={({ pageNumber }) => setPage(pageNumber)} />
            </nav>
            <div className="min-h-0 flex-1 overflow-auto bg-field p-2">
              <Page
                pageNumber={page}
                scale={ZOOM_STEPS[zoomAt]}
                rotate={rotation}
                renderAnnotationLayer
                renderTextLayer
              />
            </div>
          </Document>
        ) : (
          <p className="ui-component-metadata p-2">
            <Text id="component-browser.datasheet-loading">Loading the datasheet</Text>
          </p>
        )}
      </div>
    </div>
  );
}

function DatasheetToolbar({
  document,
  page,
  pageCount,
  zoom,
  onPage,
  onZoomIn,
  onZoomOut,
  onRotate,
}: {
  document: DocumentView;
  page: number;
  pageCount: number;
  zoom: number;
  onPage: (page: number) => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onRotate: () => void;
}) {
  const pageLabel = useText("component-browser.datasheet-page", "Page");
  const previousLabel = useText("component-browser.datasheet-previous", "Previous Page");
  const nextLabel = useText("component-browser.datasheet-next", "Next Page");
  const zoomInLabel = useText("component-browser.datasheet-zoom-in", "Zoom In");
  const zoomOutLabel = useText("component-browser.datasheet-zoom-out", "Zoom Out");
  const rotateLabel = useText("component-browser.datasheet-rotate", "Rotate");
  const externalLabel = useText("component-browser.datasheet-open-external", "Open in the Browser");
  const ofPages = useCopyFormatter("component-browser.datasheet-of-pages", "of {count}");

  return (
    <div
      data-dev-id="component-browser.datasheet-toolbar"
      className="flex flex-none flex-wrap items-center gap-2 border-b border-line px-2 py-1.5"
    >
      <span className="ui-component-metadata min-w-0 truncate">
        {[document.documentTypeLabel, document.revision, document.sourceLabel]
          .filter(Boolean)
          .join(" · ")}
      </span>
      <span className="ml-auto flex flex-none items-center gap-1.5">
        <Button
          small
          data-dev-id="component-browser.datasheet-previous"
          aria-label={previousLabel}
          title={previousLabel}
          disabled={page <= 1}
          onClick={() => onPage(Math.max(1, page - 1))}
        >
          <Text id="component-browser.datasheet-previous-short">Back</Text>
        </Button>
        <span className="ui-property-value ui-numeric flex items-baseline gap-1">
          <span className="ui-property-label">{pageLabel}</span>
          <span data-dev-id="component-browser.datasheet-page-number">{page}</span>
          <span className="ui-component-metadata">{ofPages({ count: pageCount || 1 })}</span>
        </span>
        <Button
          small
          data-dev-id="component-browser.datasheet-next"
          aria-label={nextLabel}
          title={nextLabel}
          disabled={pageCount > 0 && page >= pageCount}
          onClick={() => onPage(Math.min(pageCount || page + 1, page + 1))}
        >
          <Text id="component-browser.datasheet-next-short">Forward</Text>
        </Button>
        <Button
          small
          data-dev-id="component-browser.datasheet-zoom-out"
          aria-label={zoomOutLabel}
          title={zoomOutLabel}
          onClick={onZoomOut}
        >
          <Text id="component-browser.datasheet-zoom-out-short">Smaller</Text>
        </Button>
        <span
          data-dev-id="component-browser.datasheet-zoom"
          className="ui-component-metadata ui-numeric"
        >
          {`${Math.round(zoom * 100)}%`}
        </span>
        <Button
          small
          data-dev-id="component-browser.datasheet-zoom-in"
          aria-label={zoomInLabel}
          title={zoomInLabel}
          onClick={onZoomIn}
        >
          <Text id="component-browser.datasheet-zoom-in-short">Larger</Text>
        </Button>
        <Button
          small
          data-dev-id="component-browser.datasheet-rotate"
          aria-label={rotateLabel}
          title={rotateLabel}
          onClick={onRotate}
        >
          <Text id="component-browser.datasheet-rotate-short">Rotate</Text>
        </Button>
        {document.remoteUrl ? (
          <Button
            small
            data-dev-id="component-browser.datasheet-open-external"
            aria-label={externalLabel}
            title={externalLabel}
            icon={<ExternalIcon className="h-3.5 w-3.5" />}
            onClick={() => openExternalUrl(document.remoteUrl)}
          >
            <Text id="component-browser.datasheet-open-external-short">Open</Text>
          </Button>
        ) : null}
      </span>
    </div>
  );
}

/**
 * A failure, INSIDE the viewer, naming what failed and what to do next.
 *
 * The viewer stays open. Closing it and firing a toast would take away the one surface the person
 * can act on, and "Something went wrong" would not tell them whether the file is gone, the network
 * is down, or the PDF itself is broken.
 */
function DatasheetFailure({
  document,
  reason,
  onRetry,
}: {
  document: DocumentView;
  reason: string;
  onRetry: () => void;
}) {
  const retryLabel = useText("component-browser.datasheet-retry", "Rerun");
  const openSource = useText("component-browser.datasheet-open-source", "Open Source Page");
  return (
    <div
      data-dev-id="component-browser.datasheet-failed"
      role="alert"
      className="flex flex-col gap-2 p-3"
    >
      <StatusText tone="err">
        <Text id="component-browser.datasheet-failed">The datasheet could not be opened</Text>
      </StatusText>
      <p
        data-dev-id="component-browser.datasheet-failure-reason"
        className="ui-component-description"
      >
        {reason}
      </p>
      <div className="flex flex-wrap items-center gap-1.5">
        <Button small data-dev-id="component-browser.datasheet-retry" onClick={onRetry}>
          {retryLabel}
        </Button>
        {document.remoteUrl ? (
          <Button
            small
            data-dev-id="component-browser.datasheet-open-source"
            icon={<ExternalIcon className="h-3.5 w-3.5" />}
            onClick={() => openExternalUrl(document.remoteUrl)}
          >
            {openSource}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
