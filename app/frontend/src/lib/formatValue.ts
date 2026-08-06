/**
 * The one place a number, a quantity, a range, a price or a timestamp is turned into text.
 *
 * Every rule here exists because the alternative is visible on screen. `3.3V` reads as a token and
 * breaks across lines mid-value; `1.65V - 5.5V` states the unit twice and uses a hyphen where a
 * range belongs; `-40` uses the hyphen-minus, which is narrower and lower than the digits beside
 * it and makes a column of negatives look ragged; `3.300000000001` is a float artefact and
 * `3.30` may be a real measurement. A component library is read as a table of values, so the
 * values have to be typeset, not stringified.
 *
 * All exports are pure: same input, same output, no clock and no locale lookup except the caller's
 * own `now`. Non-finite and unparseable inputs return "" rather than throwing, so a bad field in
 * one row cannot blank a screen.
 */

/** U+00A0. Binds a unit to its number so "3.3 V" can never wrap between them. */
export const NBSP = "\u00A0";
/** U+2013. A range is an en dash; a hyphen is for compound words. */
export const EN_DASH = "\u2013";
/** U+2212. The real minus: the same width and height as the digits it sits beside. */
export const MINUS = "\u2212";

/** Units that attach directly to the number, against the general space rule. */
const TIGHT_UNITS = new Set(["%", "\u2030"]);

/** Replace a leading hyphen-minus with the real minus sign. */
function withRealMinus(text: string): string {
  return text.startsWith("-") ? MINUS + text.slice(1) : text;
}

/** Drop trailing zeros in a decimal fraction, and the point if nothing survives it. */
function trimTrailingZeros(text: string): string {
  if (!text.includes(".")) return text;
  return text.replace(/\.?0+$/, "");
}

export interface NumberOptions {
  /**
   * The most decimal places a NUMERIC input may keep. Defaults to 6, which is past the point where
   * a float has anything true left to say about a component's specification and short of losing a
   * real 0.000001 F. Ignored for a string input, whose precision was authored deliberately.
   */
  maxDecimals?: number;
  /** Group thousands ("1,240"). Off by default: a part count wants it, a voltage does not. */
  grouping?: boolean;
}

/**
 * A single number as text.
 *
 * A STRING input is passed through with its precision intact, because a string is how a datasheet
 * value arrives and "3.30" said three significant figures on purpose. A NUMBER input is a computed
 * value, so it is rounded to `maxDecimals` and stripped of the trailing zeros that rounding leaves.
 * Both get the real minus sign.
 */
export function formatNumber(value: number | string, options: NumberOptions = {}): string {
  const { maxDecimals = 6, grouping = false } = options;

  let digits: string;
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (trimmed === "") return "";
    const normalized = trimmed.replace(MINUS, "-");
    if (!/^[+-]?(\d+\.?\d*|\.\d+)$/.test(normalized)) return "";
    // Authored precision is preserved exactly; only a redundant leading "+" and a bare
    // leading "." are normalised, so ".5" and "+5" do not read as typos.
    digits = normalized.replace(/^\+/, "").replace(/^(-?)\./, "$10.");
  } else {
    if (!Number.isFinite(value)) return "";
    digits = trimTrailingZeros(value.toFixed(Math.max(0, Math.min(20, maxDecimals))));
    // toFixed(0) on -0.4 yields "-0"; a negative zero is not a value anyone means.
    if (digits === "-0") digits = "0";
  }

  if (grouping) {
    const negative = digits.startsWith("-");
    const bare = negative ? digits.slice(1) : digits;
    const [whole, fraction] = bare.split(".");
    const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    digits = (negative ? "-" : "") + (fraction ? `${grouped}.${fraction}` : grouped);
  }

  return withRealMinus(digits);
}

/**
 * A number with its unit: `3.3 V`, `100 nF`, `40 %`.
 *
 * The separator is a non-breaking space, so the value never splits across a line or a column edge.
 * An empty or absent unit returns the bare number, so a caller does not have to branch.
 */
export function formatQuantity(
  value: number | string,
  unit?: string | null,
  options: NumberOptions = {},
): string {
  const number = formatNumber(value, options);
  if (number === "") return "";
  const u = unit?.trim();
  if (!u) return number;
  return TIGHT_UNITS.has(u) ? `${number}${u}` : `${number}${NBSP}${u}`;
}

/**
 * A range: `1.65${EN_DASH}5.5 V`, `${MINUS}40${EN_DASH}125 °C`.
 *
 * The unit is stated ONCE, after the range, because repeating it on both endpoints doubles the
 * width of every tolerance column for no information. The endpoints are joined by an en dash with
 * no spaces around it, which is what makes a range read as one value rather than as two values and
 * an operator. A degenerate range (both endpoints equal) collapses to the single quantity: a spec
 * that says `5${EN_DASH}5 V` is a spec that says `5 V`.
 */
export function formatRange(
  low: number | string,
  high: number | string,
  unit?: string | null,
  options: NumberOptions = {},
): string {
  const lo = formatNumber(low, options);
  const hi = formatNumber(high, options);
  if (lo === "" && hi === "") return "";
  if (lo === "") return formatQuantity(high, unit, options);
  if (hi === "") return formatQuantity(low, unit, options);
  if (lo === hi) return formatQuantity(low, unit, options);

  const u = unit?.trim();
  const span = `${lo}${EN_DASH}${hi}`;
  if (!u) return span;
  return TIGHT_UNITS.has(u) ? `${span}${u}` : `${span}${NBSP}${u}`;
}

/**
 * One number and the unit token trailing it, or null when the text is not a quantity.
 *
 * Deliberately strict. A unit is one word with no digits and no spaces in it, so `3.3 V`,
 * `100nF` and `−40 °C` are quantities while `5 V (typ)`, `±1%` and `SOT-23-5` are not. Anything
 * this refuses is passed through untouched, because typesetting text that is not a measurement
 * is how a package code becomes a subtraction.
 */
const QUANTITY_TOKEN = /^([+\-−]?(?:\d+\.?\d*|\.\d+))\s*(\S*)$/;
const UNIT_TOKEN = /^[^\s\d]{0,8}$/u;

function splitQuantity(text: string): { number: string; unit: string } | null {
  const trimmed = text.trim();
  // A grouped figure was authored that way; re-typesetting it would either drop the separators
  // or re-apply them by our own rule, and neither is what the source wrote.
  if (trimmed === "" || trimmed.includes(",")) return null;
  const match = QUANTITY_TOKEN.exec(trimmed);
  if (!match) return null;
  const unit = match[2];
  if (!UNIT_TOKEN.test(unit)) return null;
  return { number: match[1], unit };
}

/** The separators a range is written with, in the spellings sources actually use. */
const RANGE_WORDS = /\s*(?:\bto\b|~|\.{2,3}|–|—)\s*/i;
/** A hyphen BETWEEN two figures - never a leading sign, and never inside a package code. */
const RANGE_HYPHEN = /(?<=[^\s\-−])\s*-\s*(?=[.\d])/;

function splitRange(text: string): [string, string] | null {
  for (const separator of [RANGE_WORDS, RANGE_HYPHEN]) {
    const parts = text.split(separator).filter((part) => part.trim() !== "");
    if (parts.length === 2) return [parts[0], parts[1]];
  }
  return null;
}

/**
 * A stored engineering value, typeset: `3.3 V`, `1.65–5.5 V`, `−40–125 °C`.
 *
 * The value arrives as the source's own words, which is what the record has to keep. What the
 * source does NOT get to decide is the typography: `3.3V` reads as a token and wraps mid-value,
 * `1.65V - 5.5V` states the unit twice and uses a hyphen where a range belongs, and `-40` uses a
 * hyphen-minus that sits lower and narrower than the digits beside it. Precision is the source's
 * and is never touched - `3.30` said three significant figures on purpose.
 *
 * `fallbackUnit` is the schema's unit for the field, used ONLY when the value carried none.
 *
 * Returns "" for anything that is not a quantity or a range, so the caller can fall back to the
 * source's text rather than receiving a mangled version of it.
 */
export function formatEngineeringValue(text: string, fallbackUnit?: string | null): string {
  const trimmed = text.trim();
  if (trimmed === "") return "";
  const spare = fallbackUnit?.trim() ?? "";

  const range = splitRange(trimmed);
  if (range) {
    const low = splitQuantity(range[0]);
    const high = splitQuantity(range[1]);
    if (low && high) {
      // Two different units across one range is not a range we can restate in one unit, so the
      // source's own wording stands.
      if (low.unit && high.unit && low.unit !== high.unit) return "";
      return formatRange(low.number, high.number, high.unit || low.unit || spare);
    }
    return "";
  }

  const single = splitQuantity(trimmed);
  if (!single) return "";
  return formatQuantity(single.number, single.unit || spare);
}

/**
 * Money. Two decimals is the floor because `$1.20` is a price and `$1.2` is a typo; five is the
 * ceiling because a volume price break really is quoted at `$0.00412` and rounding it to cents
 * would state a different price.
 */
export function formatPrice(amount: number | string, currencySymbol = "$"): string {
  const n = typeof amount === "string" ? Number(amount.replace(MINUS, "-")) : amount;
  if (!Number.isFinite(n)) return "";
  const [whole, fraction = ""] = trimTrailingZeros(Math.abs(n).toFixed(5)).split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${n < 0 ? MINUS : ""}${currencySymbol}${grouped}.${fraction.padEnd(2, "0")}`;
}

/** A whole count: stock, quantity on hand, pin count. Grouped, never fractional. */
export function formatCount(value: number | string): string {
  const n = typeof value === "string" ? Number(value.replace(MINUS, "-")) : value;
  if (!Number.isFinite(n)) return "";
  return formatNumber(Math.trunc(n), { maxDecimals: 0, grouping: true });
}

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

function toDate(value: Date | number | string): Date | null {
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/**
 * The ONE absolute timestamp format: `Aug 5, 2026, 10:42 AM`.
 *
 * Built by hand rather than through Intl on purpose. Intl's output for these options has changed
 * shape across ICU versions (the separator before AM/PM became a narrow no-break space, U+202F,
 * which is invisible in a diff and breaks every string comparison), and the whole point of having
 * one date format is that it is the same string everywhere, forever. Local time, because the user
 * is looking at their own machine's clock.
 */
export function formatDateTime(value: Date | number | string): string {
  const d = toDate(value);
  if (!d) return "";
  const hour24 = d.getHours();
  const hour = hour24 % 12 === 0 ? 12 : hour24 % 12;
  const minute = String(d.getMinutes()).padStart(2, "0");
  const meridiem = hour24 < 12 ? "AM" : "PM";
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}, ${hour}:${minute} ${meridiem}`;
}

/** The date alone, same vocabulary: `Aug 5, 2026`. */
export function formatDate(value: Date | number | string): string {
  const d = toDate(value);
  if (!d) return "";
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/**
 * A relative time: `just now`, `4 min ago`, `3 h ago`, `2 d ago`.
 *
 * Falls back to the absolute format past a week, because "37 d ago" is not something anyone can
 * turn back into a date. Never use this on its own: see `formatTimestamp`.
 */
export function formatRelativeTime(
  value: Date | number | string,
  now: Date | number = Date.now(),
): string {
  const d = toDate(value);
  if (!d) return "";
  const nowMs = now instanceof Date ? now.getTime() : now;
  const delta = nowMs - d.getTime();
  if (delta < 0) return formatDateTime(d);
  if (delta < MINUTE) return "just now";
  if (delta < HOUR) return `${Math.floor(delta / MINUTE)}${NBSP}min ago`;
  if (delta < DAY) return `${Math.floor(delta / HOUR)}${NBSP}h ago`;
  if (delta < 7 * DAY) return `${Math.floor(delta / DAY)}${NBSP}d ago`;
  return formatDateTime(d);
}

export interface Timestamp {
  /** What is rendered. */
  text: string;
  /** What the `title` attribute must carry. */
  title: string;
}

/**
 * A timestamp for display: the relative text plus the absolute time it stands for.
 *
 * The pair is returned together because the rule is a pair. "4 min ago" is only acceptable when
 * the exact time is one hover away, and a helper that returned the relative string alone would let
 * a caller drop the half that makes it honest. Spread it onto the element:
 * `<span title={ts.title}>{ts.text}</span>`.
 */
export function formatTimestamp(
  value: Date | number | string,
  now: Date | number = Date.now(),
): Timestamp {
  const absolute = formatDateTime(value);
  if (absolute === "") return { text: "", title: "" };
  return { text: formatRelativeTime(value, now), title: absolute };
}

/**
 * What kind of thing a cell holds, which is what decides its alignment.
 *
 * Figures that are COMPARED down a column (stock, prices, quantities, price breaks) are
 * right-aligned, so the digits stack on their place values and a longer number is visibly larger.
 * Everything else is left-aligned against the label beside it, including measurements and dates,
 * which are read one at a time rather than compared. Tabular figures are wider than that: any
 * value containing digits gets them, so a number never reflows as it updates.
 */
export type ValueKind =
  | "stock"
  | "price"
  | "priceBreak"
  | "quantity"
  | "measurement"
  | "date"
  | "identifier"
  | "text";

const RIGHT_ALIGNED: ReadonlySet<ValueKind> = new Set<ValueKind>([
  "stock",
  "price",
  "priceBreak",
  "quantity",
]);

const TABULAR: ReadonlySet<ValueKind> = new Set<ValueKind>([
  "stock",
  "price",
  "priceBreak",
  "quantity",
  "measurement",
  "date",
]);

export function alignmentFor(kind: ValueKind): "left" | "right" {
  return RIGHT_ALIGNED.has(kind) ? "right" : "left";
}

export function isTabular(kind: ValueKind): boolean {
  return TABULAR.has(kind);
}
