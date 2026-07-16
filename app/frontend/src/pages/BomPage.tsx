/**
 * The BOM Coverage tab: paste part numbers or a BOM CSV and see, per line, what
 * the library already has (and whether it is complete), with a second pass that
 * looks the missing lines up through enrichment. Named for its scope, distinct
 * from a project's own BOM (Projects > BOM & Procurement): this answers "does my
 * library cover this list?", not "what does this board cost?". Honest triage, not
 * an importer: nothing is added here (a part still needs a symbol to pass the
 * complete-to-add gate), and the report says exactly what remains.
 */
import { useState } from "react";
import { ApiError, api } from "../api/client";
import type { BomMatchReport, BulkReport } from "../api/types";
import { useJob } from "../lib/useJob";
import { useToast } from "../lib/toast";
import { Button, Card, Dot, Eyebrow } from "../components/primitives";

export function BomPage() {
  const [text, setText] = useState("");
  const [report, setReport] = useState<BomMatchReport | null>(null);
  const [checking, setChecking] = useState(false);
  const lookup = useJob<BulkReport>();
  const { toast } = useToast();

  const looking = lookup.status === "running";
  const missing = report ? report.items.filter((i) => !i.part_id) : [];
  const lookupByMpn = new Map(
    (lookup.result?.items ?? []).map((i) => [i.mpn, i]),
  );

  async function check() {
    const value = text.trim();
    if (!value || checking) return;
    setChecking(true);
    lookup.reset();
    try {
      // a BOM CSV carries commas (columns); a plain list is one MPN per line
      const body = value.includes(",") ? { csv: value } : { text: value };
      setReport(await api.bomMatch(body));
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not check the BOM", "err");
    } finally {
      setChecking(false);
    }
  }

  async function lookUpMissing() {
    if (looking || missing.length === 0) return;
    try {
      const { job_id } = await api.enrichBulk({
        text: missing.map((i) => i.mpn).join("\n"),
      });
      await lookup.run(job_id);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Lookup failed", "err");
    }
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-[30px] pt-[22px]">
      <div className="max-w-[880px] pb-12">
        <Eyebrow className="mb-0.5">BOM Coverage</Eyebrow>
        <p className="mb-3 text-xs text-t3">
          Paste part numbers (one per line) or a BOM CSV to see what your library
          already covers. Look Up Missing checks the web for the rest through
          enrichment; nothing is added from here.
        </p>
        <Card className="px-4 py-3.5">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={"TPS62130RGTR\nLM358DR\nSTM32F401RET6"}
            disabled={checking || looking}
            rows={5}
            data-testid="bom-input"
            className="min-h-0 w-full resize-y rounded-control border border-line2 bg-field px-3 py-2 text-sm text-t1 outline-none focus:border-acc disabled:opacity-50"
          />
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Button
              variant="accent"
              onClick={check}
              disabled={checking || looking || !text.trim()}
            >
              {checking ? "Checking..." : "Check Against Library"}
            </Button>
            {report && missing.length > 0 ? (
              <Button onClick={lookUpMissing} disabled={looking}>
                {looking ? "Looking Up..." : "Look Up Missing"}
              </Button>
            ) : null}
          </div>
        </Card>

        {lookup.status === "error" ? (
          <div className="mt-4 text-sm text-err">Lookup failed. {lookup.error}</div>
        ) : null}

        {report ? (
          <div className="mt-6">
            <div className="mb-2.5 flex items-baseline gap-2">
              <span
                data-testid="bom-coverage"
                className="text-lg font-semibold tabular-nums text-t1"
              >
                {report.in_library}
                <span className="text-t3">/{report.total}</span>
              </span>
              <span className="text-xs text-t3">in the library</span>
            </div>
            {report.items.length === 0 ? (
              <p className="text-sm text-t3">Nothing to check in what you pasted.</p>
            ) : (
              <Card className="overflow-hidden">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-line text-2xs text-t3">
                      <th className="px-4 py-2 font-medium">Part Number</th>
                      <th className="px-4 py-2 font-medium">Library Part</th>
                      <th className="px-4 py-2 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.items.map((item) => {
                      const looked = lookupByMpn.get(item.mpn);
                      return (
                        <tr
                          key={item.mpn}
                          className="border-b border-line last:border-b-0"
                          data-testid={`bom-row-${item.mpn}`}
                        >
                          <td className="px-4 py-2 align-top font-mono text-xs text-t2">
                            {item.mpn}
                          </td>
                          <td className="px-4 py-2 align-top text-t2">
                            {item.part_id ? item.display_name : ""}
                          </td>
                          <td className="px-4 py-2 align-top">
                            <span className="inline-flex items-center gap-2">
                              <Dot
                                tone={
                                  item.part_id
                                    ? item.is_complete
                                      ? "ok"
                                      : "warn"
                                    : looked?.complete
                                      ? "warn"
                                      : "err"
                                }
                              />
                              <span className="text-t2">
                                {item.part_id
                                  ? item.is_complete
                                    ? "In Library"
                                    : `In Library, missing ${item.missing.join(", ")}`
                                  : looked
                                    ? looked.error
                                      ? `Not In Library (lookup failed: ${looked.error})`
                                      : looked.complete
                                        ? "Not In Library (identity findable, needs a symbol to add)"
                                        : `Not In Library (lookup missing ${looked.missing.join(", ")})`
                                    : "Not In Library"}
                              </span>
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </Card>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
