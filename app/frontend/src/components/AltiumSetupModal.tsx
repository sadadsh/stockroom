/**
 * Live Altium integration guide. Stockroom never launches a licensed editor merely because the
 * app opened; installation and fresh-session verification begin from the explicit Settings action.
 */
import { useAltiumStatus, useOdbcStatus } from "../api/queries";
import { useModalDismiss } from "../lib/useModalDismiss";
import { useToast } from "../lib/toast";
import { Button, Dot, ModalHeader } from "./primitives";
import { DownloadIcon, DuplicateIcon } from "./icons";
import { Text, useText } from "../lib/copy";

export function AltiumSetupModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const status = useAltiumStatus();
  const odbc = useOdbcStatus();
  const { toast } = useToast();
  const { ref: dialogRef, zIndex: modalZ } = useModalDismiss(open, onClose);
  const dialogLabel = useText("altiumdb.setup.aria", "Altium Setup");
  // Glyph carries the verb; the label carries the object. The complete action lives here, where
  // the tooltip and the accessible name both read it.
  const copyPathAction = useText(
    "altiumdb.setup.step2-copy.action",
    "Place The Diagnostic Path On The Clipboard",
  );
  // A toast takes a resolved string, so both outcomes are resolved here rather than at the call.
  const clipboardOk = useText("altiumdb.setup.step2-copy.ok", "Copied the install path.");
  const clipboardFailed = useText(
    "altiumdb.setup.step2-copy.err",
    "Could not place the path on the clipboard.",
  );

  const installed = odbc.data?.installed ?? null;
  const data = status.data;

  async function onCopyPath() {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(data.dblib);
      toast(clipboardOk, "ok");
    } catch {
      toast(clipboardFailed, "err");
    }
  }

  if (!open) return null;

  return (
    <div
      style={{ zIndex: modalZ }}
      className="fixed inset-0 flex items-start justify-center bg-scrim p-4 pt-[7vh]"
      // role="presentation", matching the shared modal frame in components/modalParts: the scrim
      // is a surface, not a control. The press-to-dismiss below is a POINTER convenience whose
      // keyboard equivalent is Escape on the top layer, which useModalDismiss already answers, so
      // the scrim must not enter the accessibility tree as a second way to close the window.
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={dialogLabel}
        data-dev-id="altiumdb.setup-modal"
        className="flex max-h-[82vh] w-full max-w-[560px] flex-col overflow-hidden rounded-card border border-line2 bg-popover shadow-pop"
      >
        <ModalHeader
          title={<Text id="altiumdb.setup.title">Altium Setup</Text>}
          onClose={onClose}
        />

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <p className="mb-4 text-xs leading-relaxed text-t3">
            <Text id="altiumdb.setup.subtitle">Stockroom prepares the active DbLib without opening Altium until the setup action is chosen.</Text>
          </p>
          <ol className="flex flex-col gap-4">
            <Step
              n={1}
              titleId="altiumdb.setup.step1-title"
              title="Install the SQLite3 ODBC Driver"
            >
              <p className="text-xs leading-relaxed text-t3">
                <Text id="altiumdb.setup.step1-body">
                  Altium reads the catalog through this 64-bit driver, one small install per
                  machine.
                </Text>
              </p>
              <div className="mt-1.5 flex items-center justify-between gap-3">
                <span className="flex items-center gap-1.5">
                  <Dot
                    tone={installed === true ? "ok" : installed === false ? "warn" : "neutral"}
                  />
                  <span
                    className={
                      "text-xs " +
                      (installed === true
                        ? "text-ok-text"
                        : installed === false
                          ? "text-warn"
                          : "text-t3")
                    }
                  >
                    {installed === true ? (
                      <Text id="altiumdb.setup.step1-done">
                        Installed on this machine. Nothing to do.
                      </Text>
                    ) : installed === false ? (
                      <Text id="altiumdb.setup.step1-missing">
                        Not installed. Run it with all defaults, approve the prompt, then return
                        here.
                      </Text>
                    ) : (
                      <Text id="altiumdb.setup.step1-unknown">
                        Cannot be validated on this platform.
                      </Text>
                    )}
                  </span>
                </span>
                {installed === false ? (
                  <a
                    href={odbc.data?.download_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex h-[27px] flex-none items-center gap-1.5 whitespace-nowrap rounded-control border border-line bg-raise px-2.5 text-xs font-medium text-t2 transition hover:bg-raise2 hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
                  >
                    <DownloadIcon className="h-3.5 w-3.5" />
                    <Text id="altiumdb.setup.step1-download">Download Driver</Text>
                  </a>
                ) : null}
              </div>
            </Step>

            <Step n={2} titleId="altiumdb.setup.step2-title" title="Prepared Catalog Target">
              <p className="text-xs leading-relaxed text-t3">
                <Text id="altiumdb.setup.step2-body">Stockroom builds the machine-local data source at this path and keeps it aligned with the active catalog. Place it on the clipboard just when diagnosing an integration problem.</Text>
              </p>
              <div className="mt-1.5 flex items-center justify-between gap-3">
                <span
                  className="min-w-0 truncate font-mono text-xs text-t3"
                  title={data?.dblib ?? ""}
                >
                  {data?.dblib ?? ""}
                </span>
                <Button
                  small
                  onClick={onCopyPath}
                  disabled={!data}
                  className="flex-none"
                  title={copyPathAction}
                  aria-label={copyPathAction}
                  icon={<DuplicateIcon className="h-3.5 w-3.5" />}
                >
                  <Text id="altiumdb.setup.step2-copy">Diagnostic Path</Text>
                </Button>
              </div>
            </Step>

            <Step
              n={3}
              titleId="altiumdb.setup.step3-title"
              title="Explicit Install And Verification"
            >
              <p className="text-xs leading-relaxed text-t3">
                <Text id="altiumdb.setup.step3-body">Stockroom installs the active DbLib as an Altium Installed catalog, closes Altium without force, then proves a real component resolves in a fresh session - and does all of that just after Set Up In Altium is pressed. Opening Stockroom, switching catalogs, and rebuilding the DbLib never launch Altium.</Text>
              </p>
            </Step>

            <Step n={4} titleId="altiumdb.setup.step4-title" title="Verified Component Flow">
              <p className="text-xs leading-relaxed text-t3">
                <Text id="altiumdb.setup.step4-body">A part can be placed just when its KiCad and native Altium pair came from one validated download. Their shared STEP remains linked in KiCad and embedded in the Altium footprint. Catalog Build remains an explicit action in Assets; missing CAD sources return there for review.</Text>
              </p>
              {data ? (
                <p className="mt-1.5 text-xs text-t3">
                  <span className="tnum font-mono text-t2">{data.ready}</span>{" "}
                  <Text id="altiumdb.setup.step4-ready">of</Text>{" "}
                  <span className="tnum font-mono text-t2">{data.total}</span>{" "}
                  <Text id="altiumdb.setup.step4-ready-tail">parts can be placed right now.</Text>
                </p>
              ) : null}
            </Step>
          </ol>
        </div>
      </div>
    </div>
  );
}

// One numbered step: the index chip, a Title Case heading, and the step's body.
function Step({
  n,
  title,
  titleId,
  children,
}: {
  n: number;
  title: string;
  titleId: string;
  children: React.ReactNode;
}) {
  return (
    <li className="flex gap-3">
      <span className="tnum mt-0.5 grid h-6 w-6 flex-none place-items-center rounded-control bg-raise2 font-mono text-xs font-semibold text-t2">
        {n}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold text-t1">
          <Text id={titleId}>{title}</Text>
        </div>
        <div className="mt-1">{children}</div>
      </div>
    </li>
  );
}
