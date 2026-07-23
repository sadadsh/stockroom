/**
 * The pure file->part matcher behind the Altium DbLib modal's bulk attach (FIX-07). At 88 rows a
 * per-part file picker is untenable; a single picker returns a whole folder of .IntLib / .SchLib /
 * .PcbLib files, and this maps those files to the selected parts BY MPN so a select-all "Attach
 * Selected" can attach each match through the existing per-part endpoint.
 *
 * Strict + honest: a part matches only when the picked files carry a complete asset set for its
 * MPN, either a single `<MPN>.IntLib` OR both `<MPN>.SchLib` and `<MPN>.PcbLib`. A lone half of the
 * Sch/Pcb pair is reported unmatched, never half-attached; extra unrelated files are ignored; a row
 * with no MPN can never match. Pure + deterministic.
 */
import type { AltiumStatusRow } from "../api/types";

export interface AltiumFileMatch {
  row: AltiumStatusRow;
  /** the file paths to send to this part's attach (a single .IntLib, or the .SchLib + .PcbLib pair) */
  paths: string[];
}

export interface AltiumBulkPlan {
  matched: AltiumFileMatch[];
  unmatched: AltiumStatusRow[];
}

type AltiumExt = ".intlib" | ".schlib" | ".pcblib";
const _EXTS: AltiumExt[] = [".intlib", ".schlib", ".pcblib"];

// The filename (after the last / or \) split into its stem + a recognized Altium extension, or null
// for any other file. The extension is matched as a suffix so an MPN that itself contains dots
// still yields the correct stem.
function _parse(path: string): { stem: string; ext: AltiumExt } | null {
  const base = path.split(/[\\/]/).pop() ?? "";
  const lower = base.toLowerCase();
  for (const ext of _EXTS) {
    if (lower.endsWith(ext)) return { stem: base.slice(0, base.length - ext.length), ext };
  }
  return null;
}

interface StemAssets {
  intlib?: string;
  schlib?: string;
  pcblib?: string;
}

/** Map picked file `paths` to the given needs-files `rows` by MPN filename stem. Returns each
 * matched part with the exact file paths to attach, plus the rows that had no complete match. */
export function matchAltiumFilesToParts(
  rows: AltiumStatusRow[],
  paths: string[],
): AltiumBulkPlan {
  // group every recognized picked file by its (lowercased) stem
  const byStem = new Map<string, StemAssets>();
  for (const p of paths) {
    const parsed = _parse(p);
    if (!parsed) continue; // an unrelated file: ignored
    const key = parsed.stem.toLowerCase();
    const assets = byStem.get(key) ?? {};
    if (parsed.ext === ".intlib") assets.intlib = p;
    else if (parsed.ext === ".schlib") assets.schlib = p;
    else assets.pcblib = p;
    byStem.set(key, assets);
  }

  const matched: AltiumFileMatch[] = [];
  const unmatched: AltiumStatusRow[] = [];
  for (const row of rows) {
    const mpn = (row.mpn || "").trim();
    const assets = mpn ? byStem.get(mpn.toLowerCase()) : undefined;
    let filePaths: string[] | null = null;
    if (assets) {
      if (assets.intlib) filePaths = [assets.intlib]; // a single integrated library wins
      else if (assets.schlib && assets.pcblib) filePaths = [assets.schlib, assets.pcblib];
    }
    if (filePaths) matched.push({ row, paths: filePaths });
    else unmatched.push(row); // no MPN, no files, or only half the Sch/Pcb pair
  }
  return { matched, unmatched };
}
