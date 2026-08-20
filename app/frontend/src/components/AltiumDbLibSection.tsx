/**
 * Altium Database Library, a Settings section. Shows the one git-synced library Altium reads for
 * the ACTIVE profile: how many parts are place-ready, the automatically managed path, and an
 * a pointer to Assets for explicit Catalog Build. A View Library button opens the read-only mapping table. The DbLib
 * is a projection of this profile's records, so switching profiles switches what this reflects.
 *
 * Placement: Settings, the natural sibling of Procurement Rescan and Library Health, which host
 * the other library-wide maintenance surfaces in this same status + action shape.
 */
import { useEffect, useState } from "react";
import {
  useAltiumSetup,
  useAltiumStatus,
  useOdbcStatus,
} from "../api/queries";
import { useToast } from "../lib/toast";
import { Text, useText } from "../lib/copy";
import { AltiumDbLibModal } from "./AltiumDbLibModal";
import { AltiumSetupModal } from "./AltiumSetupModal";
import { Button, Dot, ErrorState, LoadingState } from "./primitives";
import { LibraryIcon, DownloadIcon, ExternalIcon, DuplicateIcon } from "./icons";
import { useScenarioUiState } from "../design-studio/scenarioState";

export function AltiumDbLibSection() {
  const scenarioDialog = useScenarioUiState().settings?.altiumDialog;
  const status = useAltiumStatus();
  const setup = useAltiumSetup();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);
  const [dismissedScenarioDialog, setDismissedScenarioDialog] = useState<string | null>(null);

  useEffect(() => {
    setDismissedScenarioDialog(null);
  }, [scenarioDialog]);
  // The glyph carries the verb, so the label carries the object alone. The full action still has
  // to be readable and announceable, which is what this string is for.
  const copyPathAction = useText(
    "altiumdb.section.copy-path.action",
    "Place The Install Path On The Clipboard",
  );
  const pathPlaced = useText("altiumdb.section.toast-path-placed", "Copied the install path.");
  const pathNotPlaced = useText(
    "altiumdb.section.toast-path-failed",
    "Could not place the path on the clipboard.",
  );
  const setupFailed = useText(
    "altiumdb.section.toast-setup-failed",
    "Could not set up the DbLib in Altium.",
  );
  const setupBusyLabel = useText("altiumdb.section.setup-busy", "Setting Up...");
  const setupLabel = useText("altiumdb.section.setup-action", "Set Up In Altium");
  const setupTip = useText(
    "altiumdb.section.setup-tip",
    "This action opens Altium to install and validate the active DbLib.",
  );
  const setupBlockedTip = useText("altiumdb.section.setup-blocked-tip", "Rebuild the DbLib first.");

  const data = status.data;
  const pct = data && data.total > 0 ? Math.round((data.ready / data.total) * 100) : 0;

  async function onCopyPath() {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(data.dblib);
      toast(pathPlaced, "ok");
    } catch {
      toast(pathNotPlaced, "err");
    }
  }

  async function onSetup() {
    try {
      const result = await setup.mutateAsync();
      toast(result.detail, ["verified", "already-verified"].includes(result.status) ? "ok" : "err");
    } catch (err) {
      toast(err instanceof Error ? err.message : setupFailed, "err");
    }
  }

  return (
    <>
      {status.isLoading ? (
        <LoadingState dense id="altiumdb.section.loading">Reading the catalog...</LoadingState>
      ) : status.isError ? (
        <ErrorState dense id="altiumdb.section.error" onRetry={() => status.refetch()}>
          Could not read the Altium catalog.
        </ErrorState>
      ) : data ? (
        <div className="flex flex-col gap-3">
          <div className="flex items-baseline justify-between gap-4">
            <div className="flex items-baseline gap-2">
              <span className="tnum font-mono text-title font-semibold leading-none text-t1">
                {data.ready}
              </span>
              <span className="text-sm text-t3">
                <Text id="altiumdb.section.ready-of">of</Text>{" "}
                <span className="tnum font-mono text-t2">{data.total}</span>{" "}
                <Text id="altiumdb.section.ready-suffix">parts prepared to place</Text>
              </span>
            </div>
            <span className="text-xs text-t3">
              <Text id="altiumdb.section.library-label">Catalog</Text>{" "}
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
            <Button
              small
              onClick={onCopyPath}
              className="flex-none"
              title={copyPathAction}
              aria-label={copyPathAction}
              icon={<DuplicateIcon className="h-3.5 w-3.5" />}
            >
              <Text id="altiumdb.section.copy-path">Path</Text>
            </Button>
          </div>
          <p className="text-xs text-t3">
            <Text id="altiumdb.section-install-note">Opening Stockroom never launches Altium. Set Up In Altium performs the one-time install and fresh-session validation at the moment it is chosen.</Text>
          </p>
          {!data.datasource_present ? (
            // The data source is derived and is not shared through git, so a clone that has
            // never been opened here has none. Saying so beats letting Altium fail with an ODBC
            // error against a file nobody mentioned.
            <p className="text-xs text-warn" data-testid="altium-datasource-missing">
              <Text id="altiumdb.section.datasource-missing">This machine-local data source has not been built. Open Assets and choose Build Now before setting it up in Altium.</Text>
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
          onClick={onSetup}
          disabled={setup.isPending || !data?.datasource_present}
          title={data?.datasource_present ? setupTip : setupBlockedTip}
          icon={<ExternalIcon className="h-3.5 w-3.5" />}
        >
          {setup.isPending ? setupBusyLabel : setupLabel}
        </Button>
        <Button
          onClick={() => setOpen(true)}
          disabled={!data}
          icon={<LibraryIcon className="h-3.5 w-3.5" />}
        >
          <Text id="altiumdb.section.view-library">View Catalog</Text>
        </Button>
        <Button onClick={() => setSetupOpen(true)} icon={<LibraryIcon className="h-3.5 w-3.5" />}>
          <Text id="altiumdb.section-setup">Setup Guide</Text>
        </Button>
      </div>

      <AltiumDbLibModal
        open={open || (scenarioDialog === "dblib" && dismissedScenarioDialog !== "dblib")}
        onClose={() => {
          setOpen(false);
          if (scenarioDialog === "dblib") setDismissedScenarioDialog("dblib");
        }}
      />
      <AltiumSetupModal
        open={setupOpen || (scenarioDialog === "setup" && dismissedScenarioDialog !== "setup")}
        onClose={() => {
          setSetupOpen(false);
          if (scenarioDialog === "setup") setDismissedScenarioDialog("setup");
        }}
      />
    </>
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
    label = <Text id="altiumdb.odbc.unknown">Cannot be validated on this platform</Text>;
  }
  const toneText = tone === "ok" ? "text-ok-text" : tone === "warn" ? "text-warn" : "text-t3";

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
          className="inline-flex h-[27px] flex-none items-center gap-1.5 whitespace-nowrap rounded-control border border-line bg-raise px-2.5 text-xs font-medium text-t2 transition hover:bg-raise2 hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        >
          <DownloadIcon className="h-3.5 w-3.5" />
          <Text id="altiumdb.odbc.download">Download Driver</Text>
        </a>
      ) : null}
    </div>
  );
}
