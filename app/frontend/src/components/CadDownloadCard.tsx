/**
 * Get CAD Files From DigiKey (Phase-2 asset download, spec section 5): the part-detail
 * action that resolves a part's DigiKey product page from its MPN, opens it in the
 * host's dedicated CAD-download window, and auto-attaches whatever symbol/footprint/3D
 * the captured ZIP yields - so a part that landed identity-only (no CAD assets at all
 * yet) picks up its files with one click instead of a manual ZIP hunt.
 *
 * Shown ONLY when the part is missing every asset (no symbol, footprint, or 3D model -
 * the `assetsMissing` gate the caller computes) AND a DigiKey CAD source actually
 * resolves for its MPN. That second check is its OWN query (useCadSourceQuery), kept
 * deliberately separate from useCadDownload's own cad-source GET (re-fired fresh right
 * before opening the remote page): this one only decides whether the card renders at
 * all, so a stale cached "yes" here can never be the thing that opens a dead page - a
 * genuine mid-flight "unavailable" (the MPN or DigiKey creds changed between mount and
 * click) is still surfaced honestly by the hook's own state, in place, rather than the
 * whole card vanishing out from under an in-progress attempt.
 *
 * Kept as its own file (rather than growing DetailPanel's body): DetailPanel is a
 * large, actively-shared file, so this owns its full state machine here and
 * DetailPanel only imports and mounts it.
 */
import { useCadSourceQuery } from "../api/queries";
import { useCadDownload, type CadDownloadStatus } from "../lib/useCadDownload";
import { Button, Card, Dot } from "./primitives";
import { DownloadIcon } from "./icons";

// The native ZIP picker (mirrors IngestPage's browseForZip): a host bridge exposes real
// filesystem paths straight into the same inspect -> commit pipeline the captured
// download uses. A plain browser (no pywebview) has no picker either, so this is a
// no-op there - the caller degrades to whatever manual path it already offers.
function pickIngestFiles(): Promise<string[]> | null {
  const hostApi = (
    window as unknown as {
      pywebview?: { api?: { pick_ingest_files?: () => Promise<string[]> } };
    }
  ).pywebview?.api;
  return hostApi?.pick_ingest_files ? hostApi.pick_ingest_files() : null;
}

function buttonLabel(status: CadDownloadStatus): string {
  switch (status) {
    case "waiting":
      return "Waiting for the Download...";
    case "inspecting":
      return "Inspecting...";
    case "committing":
      return "Attaching...";
    case "unavailable":
    case "error":
      return "Try Again";
    default:
      return "Get CAD Files From DigiKey";
  }
}

export function CadDownloadCard({
  partId,
  assetsMissing,
}: {
  partId: string;
  assetsMissing: boolean;
}) {
  const cadSource = useCadSourceQuery(partId, assetsMissing);
  const download = useCadDownload(partId);

  // Hidden while the part still carries an asset, while the gate is still loading or
  // errored, and when no DigiKey source resolved at all - no dead affordance on a part
  // that will never have one.
  if (!assetsMissing || !cadSource.data?.url) return null;

  const busy =
    download.status === "waiting" ||
    download.status === "inspecting" ||
    download.status === "committing";

  async function browse() {
    const picked = pickIngestFiles();
    if (!picked) return;
    const paths = await picked;
    if (paths && paths.length > 0) void download.submitPaths(paths);
  }

  if (download.status === "done") {
    return (
      <Card data-testid="cad-download-card" className="flex items-center gap-2.5 px-4 py-3">
        <Dot tone="ok" />
        <span className="text-sm text-t1" data-testid="cad-download-message">
          {download.message}
        </span>
      </Card>
    );
  }

  const dotTone =
    download.status === "error" ? "err" : download.status === "unavailable" ? "warn" : "neutral";

  return (
    <Card data-testid="cad-download-card" className="flex flex-col gap-2.5 px-4 py-3.5">
      <div className="flex items-center gap-2">
        <Dot tone={dotTone} />
        <span className="text-sm font-medium text-t1">DigiKey CAD Files</span>
      </div>
      <p
        className={"text-xs " + (download.status === "error" ? "text-err" : "text-t3")}
        data-testid="cad-download-message"
      >
        {download.message ?? "Pull the symbol, footprint, and 3D model straight from DigiKey."}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="accent"
          small
          icon={<DownloadIcon className="h-3.5 w-3.5" />}
          disabled={busy}
          onClick={() => void download.start()}
        >
          {buttonLabel(download.status)}
        </Button>
        {download.status === "waiting" ? (
          <Button small onClick={() => void browse()}>
            Browse for ZIP
          </Button>
        ) : null}
      </div>
    </Card>
  );
}
