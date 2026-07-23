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
import { useAltiumRegenerate, useAltiumStatus } from "../api/queries";
import { useToast } from "../lib/toast";
import { AltiumDbLibModal } from "./AltiumDbLibModal";
import { Button, Card, Eyebrow } from "./primitives";
import { RefreshIcon, LibraryIcon } from "./icons";

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
              Install it into Altium once as an Installed library, not in the project folder. Reading
              the data needs the 64-bit Access Database Engine on Windows.
            </p>
          </div>
        ) : null}

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
