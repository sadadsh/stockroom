/**
 * First-run onboarding (M9c). A frozen exe ships no library, so on the very first launch
 * the user tells Stockroom where its library lives: open an existing one, clone a git URL,
 * or create a fresh one. On success the backend repoints the running engine live (same
 * token) and the gate clears. A secondary action keeps the auto-created default library.
 *
 * Interactive labels are Title Case; prose is sentence case; no em dashes; 8/6 radii;
 * colors are tokens only (owner design contract).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Card, Eyebrow } from "./primitives";
import { useCompleteOnboarding, useSetLibrary } from "../api/queries";
import { Text, useCopyFormatter, useText } from "../lib/copy";
import { useToast } from "../lib/toast";
import { ApiError } from "../api/client";
import type { OnboardingStatus, SetLibraryBody } from "../api/types";
import { useScenarioUiState } from "../design-studio/scenarioState";

type Mode = "open" | "create" | "clone";

const MODES: { key: Mode; label: string; blurb: string }[] = [
  { key: "open", label: "Open Existing", blurb: "Point at a components folder already on this machine." },
  { key: "create", label: "Create New", blurb: "Start a fresh, empty components folder at a new location." },
  { key: "clone", label: "Clone From Git", blurb: "Copy a components repository from a git URL." },
];

const INPUT =
  "w-full rounded-control border border-line2 bg-field px-3 py-2 text-base text-t1 " +
  "outline-none focus:border-focus disabled:opacity-50";

export function OnboardingGate({ status }: { status: OnboardingStatus }) {
  const scenarioUi = useScenarioUiState();
  const scenarioMode = scenarioUi.onboarding?.mode;
  const scenarioSetupError = scenarioUi.onboarding?.setupError;
  const [mode, setMode] = useState<Mode>(() => scenarioMode ?? "open");
  const priorScenarioMode = useRef<Mode | null>(null);
  const [path, setPath] = useState("");
  const [url, setUrl] = useState("");
  const [dest, setDest] = useState("");
  const { toast } = useToast();
  const setLibrary = useSetLibrary();
  const complete = useCompleteOnboarding();
  const busy = setLibrary.isPending || complete.isPending;
  // The two examples below are sample DATA, but they are still chrome a person reads, so the
  // wording is editable. The doubled backslashes are the literal characters the field shows.
  const openPathPlaceholder = useText(
    "onboarding.open-path-placeholder",
    "C:\\\\Users\\\\name\\\\stockroom-components",
  );
  const cloneUrlPlaceholder = useText(
    "onboarding.clone-url-placeholder",
    "https://github.com/team/stockroom-components.git",
  );
  // The mutation callbacks below run outside render, so the sentences they toast are resolved here.
  // The checkout path is DATA and rides in through a placeholder rather than being concatenated;
  // an ApiError's own message is a backend diagnostic and is toasted exactly as it arrived.
  const continueFailed = useText("onboarding.toast-continue-failed", "Could not continue");
  const libraryPrepared = useCopyFormatter(
    "onboarding.toast-prepared",
    "Components prepared at {root}",
  );
  const setupFailed = useText(
    "onboarding.toast-setup-failed",
    "Could not set up the components",
  );

  useEffect(() => {
    if (scenarioMode === undefined) {
      if (priorScenarioMode.current !== null) setMode(priorScenarioMode.current);
      priorScenarioMode.current = null;
      return;
    }
    if (priorScenarioMode.current === null) priorScenarioMode.current = mode;
    setMode(scenarioMode);
  }, [scenarioMode]);

  const showSetupFailure = useCallback(
    (error: unknown) => toast(error instanceof ApiError ? error.message : setupFailed, "err"),
    [setupFailed, toast],
  );

  useEffect(() => {
    if (scenarioSetupError === undefined) return;
    return toast(scenarioSetupError, "err", undefined, null);
  }, [scenarioSetupError, toast]);

  // Each mode has its own required field: open needs a path, clone needs a URL; create
  // can fall back to the default location, so its path is optional.
  const canSubmit =
    !busy &&
    ((mode === "open" && path.trim() !== "") ||
      mode === "create" ||
      (mode === "clone" && url.trim() !== ""));

  function continueWithDefault() {
    complete.mutate(undefined, {
      onError: (e) => toast(e instanceof ApiError ? e.message : continueFailed, "err"),
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
      onSuccess: (s) => toast(libraryPrepared({ root: s.libraries_root }), "ok"),
      onError: showSetupFailure,
    });
  }

  return (
    <div data-dev-id="onboarding.gate" className="flex min-h-screen items-center justify-center bg-app px-4 py-10">
      <Card className="w-full max-w-lg p-6">
        <Eyebrow>
          <Text id="onboarding.eyebrow">Welcome</Text>
        </Eyebrow>
        <h1 className="mt-1 text-xl font-semibold text-t1">
          <Text id="onboarding.title">Set Up Your Components</Text>
        </h1>
        <p className="mt-2 text-sm text-t2">
          <Text id="onboarding.lede">The components live in a Git checkout with one JSON record per part and their shared catalog assets. Tell Stockroom where that checkout lives to get started.</Text>
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
              <span className="mb-1 block text-xs text-t3">
                <Text id="onboarding.field-components-folder">Components Folder</Text>
              </span>
              <input
                className={INPUT}
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder={openPathPlaceholder}
                spellCheck={false}
              />
            </label>
          )}
          {mode === "create" && (
            <label className="block">
              <span className="mb-1 block text-xs text-t3">
                <Text id="onboarding.field-new-components-folder">
                  New Components Folder (blank uses the default)
                </Text>
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
                <span className="mb-1 block text-xs text-t3">
                  <Text id="onboarding.field-git-url">Git URL</Text>
                </span>
                <input
                  className={INPUT}
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder={cloneUrlPlaceholder}
                  spellCheck={false}
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-t3">
                  <Text id="onboarding.field-clone-into">Clone Into (blank uses the default)</Text>
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
            <Text id="onboarding.continue-default">Continue with the Default</Text>
          </button>
          <Button variant="accent" onClick={submit} disabled={!canSubmit}>
            {busy ? (
              <Text id="onboarding.submit-busy">Working...</Text>
            ) : (
              <Text id="onboarding.submit">Set Up Components</Text>
            )}
          </Button>
        </div>

        <p className="mt-4 border-t border-line pt-3 text-xs text-t3">
          <Text id="onboarding.default-location">Default location:</Text>{" "}
          <span className="text-t2">{status.default_dir}</span>
        </p>
      </Card>
    </div>
  );
}
