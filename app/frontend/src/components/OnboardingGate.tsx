/**
 * First-run onboarding (M9c). A frozen exe ships no library, so on the very first launch
 * the user tells Stockroom where its library lives: open an existing one, clone a git URL,
 * or create a fresh one. On success the backend repoints the running engine live (same
 * token) and the gate clears. A secondary action keeps the auto-created default library.
 *
 * Interactive labels are Title Case; prose is sentence case; no em dashes; 8/6 radii;
 * colors are tokens only (owner design contract).
 */
import { useState } from "react";
import { Button, Card, Eyebrow } from "./primitives";
import { useCompleteOnboarding, useSetLibrary } from "../api/queries";
import { useToast } from "../lib/toast";
import { ApiError } from "../api/client";
import type { OnboardingStatus, SetLibraryBody } from "../api/types";

type Mode = "open" | "create" | "clone";

const MODES: { key: Mode; label: string; blurb: string }[] = [
  { key: "open", label: "Open Existing", blurb: "Point at a components folder already on this machine." },
  { key: "create", label: "Create New", blurb: "Start a fresh, empty components folder at a new location." },
  { key: "clone", label: "Clone From Git", blurb: "Copy a components repository from a git URL." },
];

const INPUT =
  "w-full rounded-control border border-line2 bg-field px-3 py-2 text-base text-t1 " +
  "outline-none focus:border-acc disabled:opacity-50";

export function OnboardingGate({ status }: { status: OnboardingStatus }) {
  const [mode, setMode] = useState<Mode>("open");
  const [path, setPath] = useState("");
  const [url, setUrl] = useState("");
  const [dest, setDest] = useState("");
  const { toast } = useToast();
  const setLibrary = useSetLibrary();
  const complete = useCompleteOnboarding();
  const busy = setLibrary.isPending || complete.isPending;

  // Each mode has its own required field: open needs a path, clone needs a URL; create
  // can fall back to the default location, so its path is optional.
  const canSubmit =
    !busy &&
    ((mode === "open" && path.trim() !== "") ||
      mode === "create" ||
      (mode === "clone" && url.trim() !== ""));

  function continueWithDefault() {
    complete.mutate(undefined, {
      onError: (e) =>
        toast(e instanceof ApiError ? e.message : "Could not continue", "err"),
    });
  }

  function submit() {
    if (!canSubmit) return;
    const body: SetLibraryBody =
      mode === "open"
        ? { mode, path: path.trim() }
        : mode === "create"
          ? { mode, path: path.trim() || undefined }
          : { mode, url: url.trim(), dest: dest.trim() || undefined };
    setLibrary.mutate(body, {
      onSuccess: (s) => toast(`Components ready at ${s.libraries_root}`, "ok"),
      onError: (e) =>
        toast(e instanceof ApiError ? e.message : "Could not set up your components", "err"),
    });
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-app px-4 py-10">
      <Card className="w-full max-w-lg p-6">
        <Eyebrow>Welcome</Eyebrow>
        <h1 className="mt-1 text-xl font-semibold text-t1">Set Up Your Components</h1>
        <p className="mt-2 text-sm text-t2">
          Your components live in a git repository of one JSON record per part, plus the KiCad
          projects you register. Tell Stockroom where they live to get started.
        </p>

        <div className="mt-5 grid grid-cols-3 gap-2">
          {MODES.map((m) => (
            <button
              key={m.key}
              type="button"
              onClick={() => setMode(m.key)}
              aria-pressed={mode === m.key}
              className={
                "rounded-control border px-2 py-2 text-sm font-medium transition-colors " +
                (mode === m.key
                  ? "border-transparent bg-acc text-acc-on"
                  : "border-line bg-raise text-t2 hover:bg-raise2 hover:text-t1")
              }
            >
              {m.label}
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-t3">{MODES.find((m) => m.key === mode)?.blurb}</p>

        <div className="mt-4 space-y-3">
          {mode === "open" && (
            <label className="block">
              <span className="mb-1 block text-xs text-t3">Components Folder</span>
              <input
                className={INPUT}
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder="C:\\Users\\you\\stockroom-components"
                spellCheck={false}
              />
            </label>
          )}
          {mode === "create" && (
            <label className="block">
              <span className="mb-1 block text-xs text-t3">
                New Components Folder (blank uses the default)
              </span>
              <input
                className={INPUT}
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder={status.default_dir}
                spellCheck={false}
              />
            </label>
          )}
          {mode === "clone" && (
            <>
              <label className="block">
                <span className="mb-1 block text-xs text-t3">Git URL</span>
                <input
                  className={INPUT}
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://github.com/you/stockroom-components.git"
                  spellCheck={false}
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-t3">
                  Clone Into (blank uses the default)
                </span>
                <input
                  className={INPUT}
                  value={dest}
                  onChange={(e) => setDest(e.target.value)}
                  placeholder={status.default_dir}
                  spellCheck={false}
                />
              </label>
            </>
          )}
        </div>

        <div className="mt-5 flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={continueWithDefault}
            disabled={busy}
            className="text-sm text-t3 underline-offset-2 hover:text-t1 hover:underline disabled:opacity-50"
          >
            Continue With the Default
          </button>
          <Button variant="accent" onClick={submit} disabled={!canSubmit}>
            {busy ? "Working..." : "Set Up Components"}
          </Button>
        </div>

        <p className="mt-4 border-t border-line pt-3 text-xs text-t3">
          Default location: <span className="text-t2">{status.default_dir}</span>
        </p>
      </Card>
    </div>
  );
}
