/**
 * Live Altium integration guide. Stockroom never launches a licensed editor merely because the
 * app opened; installation and fresh-session verification begin from the explicit Settings action.
 */
import { motion } from "motion/react";
import { useAltiumStatus, useOdbcStatus } from "../api/queries";
import { useModalDismiss } from "../lib/useModalDismiss";
import { useToast } from "../lib/toast";
import { Button, Dot } from "./primitives";
import { DownloadIcon } from "./icons";
import { Text, useText } from "../lib/copy";

export function AltiumSetupModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const status = useAltiumStatus();
  const odbc = useOdbcStatus();
  const { toast } = useToast();
  const dialogRef = useModalDismiss(open, onClose);
  const dialogLabel = useText("altiumdb.setup.aria", "Altium Setup");

  const installed = odbc.data?.installed ?? null;
  const data = status.data;

  async function onCopyPath() {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(data.dblib);
      toast("Copied the install path.", "ok");
    } catch {
      toast("Could not copy the path.", "err");
    }
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[95] flex items-start justify-center bg-black/60 p-4 pt-[7vh]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <motion.div
        ref={dialogRef}
        tabIndex={-1}
        initial={{ opacity: 0, y: 8, scale: 0.99 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ type: "spring", stiffness: 420, damping: 32 }}
        role="dialog"
        aria-modal="true"
        aria-label={dialogLabel}
        data-dev-id="altiumdb.setup-modal"
        className="flex max-h-[82vh] w-full max-w-[560px] flex-col overflow-hidden rounded-card border border-line2 bg-popover shadow-pop"
      >
        <div className="flex flex-none items-center justify-between gap-3 border-b border-line px-5 py-3.5">
          <div>
            <div className="text-base font-semibold tracking-[-0.01em] text-t1">
              <Text id="altiumdb.setup.title">Altium Setup</Text>
            </div>
            <p className="mt-0.5 text-xs text-t3">
              <Text id="altiumdb.setup.subtitle">
                Stockroom prepares the active DbLib without opening Altium until you choose the
                setup action.
              </Text>
            </p>
          </div>
          <Button small onClick={onClose}>
            <Text id="altiumdb.setup.close">Close</Text>
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <ol className="flex flex-col gap-4">
            <Step
              n={1}
              titleId="altiumdb.setup.step1-title"
              title="Install the SQLite3 ODBC Driver"
            >
              <p className="text-xs leading-relaxed text-t3">
                <Text id="altiumdb.setup.step1-body">
                  Altium reads the library through this 64-bit driver, one small install per
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
                        ? "text-ok"
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
                        Cannot be verified on this platform.
                      </Text>
                    )}
                  </span>
                </span>
                {installed === false ? (
                  <a
                    href={odbc.data?.download_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex h-[27px] flex-none items-center gap-1.5 whitespace-nowrap rounded-control border border-line bg-raise px-2.5 text-xs font-medium text-t2 transition hover:bg-raise2 hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
                  >
                    <DownloadIcon className="h-3.5 w-3.5" />
                    <Text id="altiumdb.setup.step1-download">Download Driver</Text>
                  </a>
                ) : null}
              </div>
            </Step>

            <Step n={2} titleId="altiumdb.setup.step2-title" title="Prepared Library Target">
              <p className="text-xs leading-relaxed text-t3">
                <Text id="altiumdb.setup.step2-body">
                  Stockroom builds the machine-local data source at this path and keeps it aligned
                  with the active library. Copy it only when diagnosing an integration problem.
                </Text>
              </p>
              <div className="mt-1.5 flex items-center justify-between gap-3">
                <span
                  className="min-w-0 truncate font-mono text-xs text-t3"
                  title={data?.dblib ?? ""}
                >
                  {data?.dblib ?? ""}
                </span>
                <Button small onClick={onCopyPath} disabled={!data} className="flex-none">
                  <Text id="altiumdb.setup.step2-copy">Copy Diagnostic Path</Text>
                </Button>
              </div>
            </Step>

            <Step
              n={3}
              titleId="altiumdb.setup.step3-title"
              title="Explicit Install And Verification"
            >
              <p className="text-xs leading-relaxed text-t3">
                <Text id="altiumdb.setup.step3-body">
                  Stockroom installs the active DbLib as an Altium Installed library, closes Altium
                  cleanly, then proves a real component resolves in a fresh session only after you
                  press Set Up In Altium. Opening Stockroom, switching libraries, and rebuilding the
                  DbLib never launch Altium.
                </Text>
              </p>
            </Step>

            <Step n={4} titleId="altiumdb.setup.step4-title" title="Verified Component Flow">
              <p className="text-xs leading-relaxed text-t3">
                <Text id="altiumdb.setup.step4-body">
                  Only parts with a verified same-download KiCad and native Altium pair are
                  place-ready. Their shared STEP stays linked in KiCad and embedded in the Altium
                  footprint. Rebuild DbLib is a recovery action; missing assets return to Components
                  and Collect All Sources.
                </Text>
              </p>
              {data ? (
                <p className="mt-1.5 text-xs text-t3">
                  <span className="tnum font-mono text-t2">{data.ready}</span>{" "}
                  <Text id="altiumdb.setup.step4-ready">of</Text>{" "}
                  <span className="tnum font-mono text-t2">{data.total}</span>{" "}
                  <Text id="altiumdb.setup.step4-ready-tail">
                    parts are ready to place right now.
                  </Text>
                </p>
              ) : null}
            </Step>
          </ol>
        </div>
      </motion.div>
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
      <span className="tnum mt-0.5 grid h-6 w-6 flex-none place-items-center rounded-control bg-raise2 font-mono text-xs font-bold text-t2">
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
