/**
 * Altium Database Library, a Settings section. Shows the one git-synced library Altium reads for
 * the ACTIVE profile: how many parts are place-ready, the automatically managed path, and an
 * explicit recovery rebuild. A View Library button opens the read-only mapping table. The DbLib
 * is a projection of this profile's records, so switching profiles switches what this reflects.
 *
 * Placement: Settings, the natural sibling of Procurement Rescan and Library Health, which host
 * the other library-wide maintenance surfaces in this same status + action shape.
 */
import { useState } from "react";
import {
  useAltiumEmbedCapability,
  useAltiumEmbedModels,
  useAltiumModelsPending,
  useAltiumRegenerate,
  useAltiumSetup,
  useAltiumStatus,
  useOdbcStatus,
} from "../api/queries";
import { useToast } from "../lib/toast";
import { Text } from "../lib/copy";
import { AltiumDbLibModal } from "./AltiumDbLibModal";
import { AltiumSetupModal } from "./AltiumSetupModal";
import { Button, Dot } from "./primitives";
import { RefreshIcon, LibraryIcon, DownloadIcon, ExternalIcon } from "./icons";
import { Icon } from "./Icon";

export function AltiumDbLibSection() {
  const status = useAltiumStatus();
  const regenerate = useAltiumRegenerate();
  const setup = useAltiumSetup();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);

  const data = status.data;
  const pct = data && data.total > 0 ? Math.round((data.ready / data.total) * 100) : 0;

  async function onRegenerate() {
    try {
      const r = await regenerate.mutateAsync();
      toast(
        r.emitted > 0
          ? `Regenerated the DbLib with ${r.emitted} ${r.emitted === 1 ? "part" : "parts"}.`
          : "Regenerated. No parts carry Altium assets yet, so the library is empty.",
        r.emitted > 0 ? "ok" : "neutral",
      );
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not regenerate the DbLib.", "err");
    }
  }

  async function onCopyPath() {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(data.dblib);
      toast("Copied the install path.", "ok");
    } catch {
      toast("Could not copy the path.", "err");
    }
  }

  async function onSetup() {
    try {
      const result = await setup.mutateAsync();
      toast(result.detail, ["verified", "already-verified"].includes(result.status) ? "ok" : "err");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not set up the DbLib in Altium.", "err");
    }
  }

  return (
    <>
      {status.isLoading ? (
        <p className="py-1 text-sm text-t3">
          <Text id="altiumdb.section.loading">Reading the library...</Text>
        </p>
      ) : status.isError ? (
        <p className="py-1 text-sm text-err">
          <Text id="altiumdb.section.error">Could not read the Altium library.</Text>
        </p>
      ) : data ? (
        <div className="flex flex-col gap-3">
          <div className="flex items-baseline justify-between gap-4">
            <div className="flex items-baseline gap-2">
              <span className="tnum font-mono text-title font-bold leading-none text-t1">
                {data.ready}
              </span>
              <span className="text-sm text-t3">
                <Text id="altiumdb.section.ready-of">of</Text>{" "}
                <span className="tnum font-mono text-t2">{data.total}</span>{" "}
                <Text id="altiumdb.section.ready-suffix">parts ready to place</Text>
              </span>
            </div>
            <span className="text-xs text-t3">
              <Text id="altiumdb.section.library-label">Library</Text>{" "}
              <span className="text-t2">{data.profile}</span>
            </span>
          </div>

          <div
            className="h-1.5 w-full overflow-hidden bg-raise2"
            data-dev-id="altiumdb.section-progress"
          >
            <div className="h-full bg-acc transition-[width]" style={{ width: `${pct}%` }} />
          </div>

          <div
            className="flex items-center justify-between gap-3 border-t border-line pt-2.5"
            data-dev-id="altiumdb.section-path"
          >
            <span className="min-w-0 truncate font-mono text-xs text-t3" title={data.dblib}>
              {data.dblib}
            </span>
            <Button small onClick={onCopyPath} className="flex-none">
              <Text id="altiumdb.section.copy-path">Copy Path</Text>
            </Button>
          </div>
          <p className="text-xs text-t3">
            <Text id="altiumdb.section-install-note">
              Opening Stockroom never launches Altium. Set Up In Altium performs the one-time
              install and fresh-session verification when you choose it.
            </Text>
          </p>
          {!data.datasource_present ? (
            // The data source is derived and is not shared through git, so a clone that has
            // never been opened here has none. Saying so beats letting Altium fail with an ODBC
            // error against a file nobody mentioned.
            <p className="text-xs text-warn" data-testid="altium-datasource-missing">
              <Text id="altiumdb.section.datasource-missing">
                This machine-local data source has not been built yet. Rebuild the DbLib before
                setting it up in Altium.
              </Text>
            </p>
          ) : null}
        </div>
      ) : null}

      <OdbcDriverRow />

      <div
        className="mt-3.5 flex flex-wrap items-center gap-3"
        data-dev-id="altiumdb.section-actions"
      >
        <Button
          variant="accent"
          onClick={onRegenerate}
          disabled={regenerate.isPending || !data}
          icon={<RefreshIcon className="h-3.5 w-3.5" />}
        >
          {regenerate.isPending ? "Rebuilding..." : "Rebuild DbLib"}
        </Button>
        <Button
          onClick={onSetup}
          disabled={setup.isPending || !data?.datasource_present}
          title={
            data?.datasource_present
              ? "This action opens Altium to install and verify the active DbLib."
              : "Rebuild the DbLib first."
          }
          icon={<ExternalIcon className="h-3.5 w-3.5" />}
        >
          {setup.isPending ? "Setting Up..." : "Set Up In Altium"}
        </Button>
        <EmbedAllModelsButton />
        <Button
          onClick={() => setOpen(true)}
          disabled={!data}
          icon={<LibraryIcon className="h-3.5 w-3.5" />}
        >
          <Text id="altiumdb.section.view-library">View Library</Text>
        </Button>
        <Button onClick={() => setSetupOpen(true)} icon={<LibraryIcon className="h-3.5 w-3.5" />}>
          <Text id="altiumdb.section-setup">Setup Guide</Text>
        </Button>
      </div>

      <AltiumDbLibModal open={open} onClose={() => setOpen(false)} />
      <AltiumSetupModal open={setupOpen} onClose={() => setSetupOpen(false)} />
    </>
  );
}

// Embed every pending 3D model in one action, so a whole library does not cost one click per part
// (owner's deadline ask: "no work on my end"). It states the number it will work on, because an
// action that promises a count it cannot honour is worse than one that promises none, and it hides
// itself entirely when nothing is pending rather than offering a no-op.
//
// Disabled with the REASON when Altium cannot run here: not installed, or a windowed Altium holding
// the single On-Demand license seat. Both come from the capability probe, which re-checks on window
// focus, so closing Altium and coming back enables the button with no manual refresh.
function EmbedAllModelsButton() {
  const pending = useAltiumModelsPending();
  const capability = useAltiumEmbedCapability();
  const embed = useAltiumEmbedModels();
  const { toast } = useToast();

  const count = pending.data?.count ?? 0;
  if (count === 0) return null;

  const cap = capability.data;
  const blocked =
    cap && !cap.available
      ? cap.busy
        ? `Close Altium first: ${cap.busy} is holding the license seat.`
        : cap.reason || "Altium is not installed on this machine."
      : "";
  const running = embed.status === "running";

  async function onEmbed() {
    try {
      await embed.start();
      const r = embed.result;
      if (!r) return;
      // A partial run is reported as a FAILURE tone, not a success with a footnote: the owner
      // walked away from this, so the one line they read has to say that something needs them.
      if (r.failed > 0) {
        const first = r.results.find((x) => x.status === "failed");
        toast(
          `Embedded ${r.embedded} of ${r.attempted}. ${r.failed} failed` +
            (first?.detail ? `, starting with ${first.part_id}: ${first.detail}` : "."),
          "err",
        );
        return;
      }
      toast(`Embedded ${r.embedded} 3D ${r.embedded === 1 ? "model" : "models"}.`, "ok");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not embed the 3D models.", "err");
    }
  }

  return (
    <Button
      onClick={onEmbed}
      disabled={running || Boolean(blocked)}
      title={blocked || undefined}
      data-dev-id="altiumdb.embed-all"
      icon={<Icon id="layer.model" className="h-3.5 w-3.5" />}
    >
      {running ? embed.progress?.message || "Embedding..." : `Embed 3D Models (${count})`}
    </Button>
  );
}

// The machine-level SQLite3 ODBC driver Altium needs to read the DbLib: an honest status (Installed
// / Not Installed / not verifiable off Windows) and, when it is absent, a Download that opens the
// official 64-bit installer. Independent of the profile status above (it reflects this Windows
// machine, not the library), so it renders even while the profile status is loading.
function OdbcDriverRow() {
  const odbc = useOdbcStatus();
  const installed = odbc.data?.installed ?? null;

  // status label + tone by state. null is the honest off-Windows answer (winreg cannot be read);
  // it never appears on the owner's Windows machine, where the probe returns a real boolean.
  let tone: "ok" | "warn" | "neutral" = "neutral";
  let label = <Text id="altiumdb.odbc.checking">Checking the driver...</Text>;
  if (odbc.isError) {
    tone = "warn";
    label = <Text id="altiumdb.odbc.error">Could not check the driver.</Text>;
  } else if (installed === true) {
    tone = "ok";
    label = <Text id="altiumdb.odbc.installed">Installed</Text>;
  } else if (installed === false) {
    tone = "warn";
    label = <Text id="altiumdb.odbc.missing">Not Installed</Text>;
  } else if (!odbc.isLoading) {
    tone = "neutral";
    label = <Text id="altiumdb.odbc.unknown">Cannot be verified on this platform</Text>;
  }
  const toneText = tone === "ok" ? "text-ok" : tone === "warn" ? "text-warn" : "text-t3";

  return (
    <div
      className="mt-3.5 flex items-center justify-between gap-3 border-t border-line pt-2.5"
      data-dev-id="altiumdb.section-odbc"
    >
      <div className="min-w-0">
        <div className="text-xs font-medium text-t2">
          <Text id="altiumdb.odbc.label">SQLite3 ODBC Driver</Text>
        </div>
        <div className="mt-1 flex items-center gap-1.5">
          <Dot tone={tone} />
          <span className={`text-xs ${toneText}`}>{label}</span>
        </div>
      </div>
      {installed === false ? (
        <a
          href={odbc.data?.download_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex h-[27px] flex-none items-center gap-1.5 whitespace-nowrap rounded-control border border-line bg-raise px-2.5 text-xs font-medium text-t2 transition hover:bg-raise2 hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
        >
          <DownloadIcon className="h-3.5 w-3.5" />
          <Text id="altiumdb.odbc.download">Download Driver</Text>
        </a>
      ) : null}
    </div>
  );
}
