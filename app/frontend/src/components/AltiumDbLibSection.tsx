/**
 * Altium Database Library, a Settings section. Shows the one git-synced library Altium reads for
 * the ACTIVE profile: how many parts are place-ready, the install path, and a Regenerate action;
 * a View Library button opens the full data table with per-part attach. The DbLib is a projection
 * of this profile's records, so switching profiles switches what this reflects.
 *
 * Placement: Settings, the natural sibling of Procurement Rescan and Library Health, which host
 * the other library-wide maintenance surfaces in this same status + action shape.
 */
import { useState } from "react";
import { useAltiumRegenerate, useAltiumStatus, useOdbcStatus } from "../api/queries";
import { useToast } from "../lib/toast";
import { Text } from "../lib/copy";
import { AltiumDbLibModal } from "./AltiumDbLibModal";
import { Button, Card, Dot, Eyebrow } from "./primitives";
import { RefreshIcon, LibraryIcon, DownloadIcon } from "./icons";

export function AltiumDbLibSection() {
  const status = useAltiumStatus();
  const regenerate = useAltiumRegenerate();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);

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

  return (
    <section className="mb-7" data-dev-id="altiumdb.section">
      <Eyebrow className="mb-2">Altium Database Library</Eyebrow>
      <p className="mb-2.5 text-xs text-t3">
        One git-synced library Altium reads, regenerated from this profile&rsquo;s records. Install
        it into Altium once, then it fills as you attach each part&rsquo;s Altium assets.
      </p>
      <Card className="px-4 py-3.5">
        {status.isLoading ? (
          <p className="py-1 text-sm text-t3">Reading the library...</p>
        ) : status.isError ? (
          <p className="py-1 text-sm text-err">Could not read the Altium library.</p>
        ) : data ? (
          <div className="flex flex-col gap-3">
            <div className="flex items-baseline justify-between gap-4">
              <div className="flex items-baseline gap-2">
                <span className="tnum font-mono text-title font-bold leading-none text-t1">
                  {data.ready}
                </span>
                <span className="text-sm text-t3">
                  of <span className="tnum font-mono text-t2">{data.total}</span> parts ready to
                  place
                </span>
              </div>
              <span className="text-xs text-t3">
                Profile <span className="text-t2">{data.profile}</span>
              </span>
            </div>

            <div className="h-1.5 w-full overflow-hidden bg-raise2" data-dev-id="altiumdb.section-progress">
              <div
                className="h-full bg-acc transition-[width]"
                style={{ width: `${pct}%` }}
              />
            </div>

            <div className="flex items-center justify-between gap-3 border-t border-line pt-2.5" data-dev-id="altiumdb.section-path">
              <span className="min-w-0 truncate font-mono text-xs text-t3" title={data.dblib}>
                {data.dblib}
              </span>
              <Button small onClick={onCopyPath} className="flex-none">
                Copy Path
              </Button>
            </div>
            <p className="text-xs text-t3">
              <Text id="altiumdb.section-install-note">
                Install it into Altium once as an Installed library, not in the project folder.
              </Text>
            </p>
          </div>
        ) : null}

        <OdbcDriverRow />

        <div className="mt-3.5 flex flex-wrap items-center gap-3" data-dev-id="altiumdb.section-actions">
          <Button
            variant="accent"
            onClick={onRegenerate}
            disabled={regenerate.isPending || !data}
            icon={<RefreshIcon className="h-3.5 w-3.5" />}
          >
            {regenerate.isPending ? "Regenerating..." : "Regenerate DbLib"}
          </Button>
          <Button
            onClick={() => setOpen(true)}
            disabled={!data}
            icon={<LibraryIcon className="h-3.5 w-3.5" />}
          >
            View Library
          </Button>
        </div>
      </Card>

      <AltiumDbLibModal open={open} onClose={() => setOpen(false)} />

    </section>
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
