/**
 * UI preferences that must outlive a restart (theme, rail and Design Studio panels).
 *
 * WHY NOT localStorage. The host serves the SPA from `http://127.0.0.1:<ephemeral port>`, so the
 * page ORIGIN is different on every launch, and localStorage is origin-scoped. Measured on real
 * Windows across two controlled restarts: the collapsed rail came back expanded (`1` -> `0`) and a
 * light theme came back dark. Every preference silently reset on every launch, and no test could
 * see it because tests all run against one origin.
 *
 * So the machine config is the source of truth. The host reads it and writes the values into the
 * page SYNCHRONOUSLY at boot (`window.__STOCKROOM_UI__`), ahead of the SPA's first byte, because an
 * async fetch would paint the default theme first and then flip it.
 *
 * localStorage is kept as a MIRROR, not as the store: it is the only thing available when the
 * frontend is served by the dev server with no host to inject anything.
 */
import { api } from "../api/client";

/**
 * Every member is a SCALAR, and `uiPrefs.test.ts` holds it that way.
 *
 * The mirror is a string store, and `writePref` writes it with a bare `String(value)`. An
 * object-valued preference added here would mirror as the literal "[object Object]", read back as
 * undefined on the next launch, and silently lose whatever it held - so the type is the gate. A
 * preference that genuinely needs structure has to bring its own encode/decode pair with it, rather
 * than inherit one that only the type made reachable.
 */
export interface UiPrefs {
  theme?: "dark" | "light";
  rail_collapsed?: boolean;
  design_studio_left_collapsed?: boolean;
  design_studio_right_collapsed?: boolean;
  design_studio_left_width?: number;
  design_studio_right_width?: number;
}

declare global {
  interface Window {
    __STOCKROOM_UI__?: UiPrefs;
  }
}

/** The host-injected preferences, or an empty object when served without a host. */
export function injectedPrefs(): UiPrefs {
  try {
    return window.__STOCKROOM_UI__ ?? {};
  } catch {
    return {};
  }
}

/** Read one preference: host injection first, then the localStorage mirror, then `fallback`. */
export function readPref<T>(
  key: keyof UiPrefs,
  mirrorKey: string,
  parse: (raw: string) => T | undefined,
  fallback: T,
): T {
  const injected = injectedPrefs()[key];
  if (injected !== undefined) return injected as T;
  try {
    const raw = localStorage.getItem(mirrorKey);
    if (raw !== null) {
      const parsed = parse(raw);
      if (parsed !== undefined) return parsed;
    }
  } catch {
    /* localStorage may be unavailable; fall through to the default */
  }
  return fallback;
}

/**
 * Persist one preference. Writes the mirror first (synchronous, so a reload inside the same launch
 * is already correct) and then the machine config, which is what actually survives a restart.
 *
 * PATCHes a single key: the endpoint MERGES `ui`, so saving the theme cannot clobber a rail state
 * written a moment earlier by a different control.
 */
export function writePref(key: keyof UiPrefs, value: unknown, mirrorKey: string): void {
  // NO-OP when the value already matches. Both call sites persist from a `useEffect` that also runs
  // on mount, so without this every window open would PATCH the settings endpoint with the value it
  // had just been given - a pointless write on every launch, and enough to make an unrelated
  // "does not double-save" test see phantom calls.
  if (injectedPrefs()[key] === value) return;
  try {
    // The bare string form, which is what both preferences already have persisted on every machine
    // this has ever run on. Nothing here encodes structure: `UiPrefs` is scalars only (see the note
    // on the interface), so an encoder for objects would be a branch no call site could take.
    localStorage.setItem(mirrorKey, String(value));
  } catch {
    /* the mirror is best-effort */
  }
  // Keep the injected copy current so a same-launch reload does not resurrect the old value.
  try {
    window.__STOCKROOM_UI__ = { ...injectedPrefs(), [key]: value };
  } catch {
    /* non-fatal */
  }
  // A preference that fails to persist must never break the interaction that set it. The try/catch
  // is NOT redundant with .catch(): that only handles a rejected promise, while a client that
  // throws synchronously would propagate straight out of the useEffect calling this and take the
  // component down with it.
  try {
    void api
      .updateSettings({ ui: { [key]: value } } as never)
      .catch(() => {
        /* offline, 401, or a backend that predates the `ui` field: the mirror still holds */
      });
  } catch {
    /* nothing to do; the value is already mirrored locally */
  }
}
