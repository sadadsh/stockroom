import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ApiError } from "../api/client";
import {
  useCompleteOnboarding,
  useConnectGuidedTool,
  useOnboardingGitHubLogin,
  useOnboardingGitHubRepositories,
  useSetGuidedRepository,
  useUpdateSettings,
} from "../api/queries";
import type { GuidedSetupStep, OnboardingStatus } from "../api/types";
import { useScenarioUiState } from "../design-studio/scenarioState";
import { openExternalUrl } from "../lib/externalNavigation";
import { Text, useText } from "../lib/copy";
import { Button, Card, Eyebrow } from "./primitives";

type RepositoryMode = "create" | "connect";

const INPUT =
  "h-8 w-full rounded-control border border-line2 bg-field px-3 text-sm text-t1 " +
  "outline-none focus:border-focus disabled:text-t5";

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : error instanceof Error ? error.message : fallback;
}

function StepName({ step }: { step: GuidedSetupStep }) {
  switch (step) {
    case "choose_cad_tool":
      return <Text id="onboarding.step.cad">Choose CAD Tool</Text>;
    case "catalog_repository":
      return <Text id="onboarding.step.catalog">Catalog Repository</Text>;
    case "connect_the_tool":
      return <Text id="onboarding.step.connect">Connect The Tool</Text>;
    case "ready":
      return <Text id="onboarding.step.prepared">Ready</Text>;
  }
}

function SetupProgress({ status }: { status: OnboardingStatus }) {
  const activeIndex = status.guided_setup.steps.indexOf(status.guided_setup.step);
  const label = useText("onboarding.progress", "Setup Progress");
  return (
    <ol
      aria-label={label}
      className="grid gap-1 border-b border-line pb-4"
      style={{ gridTemplateColumns: `repeat(${status.guided_setup.steps.length}, minmax(0, 1fr))` }}
    >
      {status.guided_setup.steps.map((step, index) => (
        <li
          key={step}
          aria-current={step === status.guided_setup.step ? "step" : undefined}
          className={
            "min-w-0 border-t-2 pt-2 text-xs " +
            (index <= activeIndex ? "border-acc text-t1" : "border-line2 text-t3")
          }
        >
          <span className="mr-1 text-t3">{index + 1}.</span>
          <StepName step={step} />
        </li>
      ))}
    </ol>
  );
}

export function OnboardingGate({ status }: { status: OnboardingStatus }) {
  return (
    <main
      data-dev-id="onboarding.gate"
      className="flex min-h-screen items-center justify-center bg-app px-4 py-8"
    >
      <Card className="w-full max-w-3xl border border-line p-6">
        <SetupProgress status={status} />
        <div className="pt-5">
          <SetupStep status={status} />
        </div>
      </Card>
    </main>
  );
}

function SetupStep({ status }: { status: OnboardingStatus }) {
  switch (status.guided_setup.step) {
    case "choose_cad_tool":
      return <ChooseCadTool status={status} />;
    case "catalog_repository":
      return <CatalogRepository status={status} />;
    case "connect_the_tool":
      return <ConnectTool status={status} />;
    case "ready":
      return <Prepared status={status} />;
  }
}

function StepIntro({ eyebrow, title, children }: { eyebrow: ReactNode; title: ReactNode; children: ReactNode }) {
  return (
    <>
      <Eyebrow>{eyebrow}</Eyebrow>
      <h1 className="mt-1 text-xl font-semibold text-t1">{title}</h1>
      <p className="mt-2 max-w-2xl text-sm text-t2">{children}</p>
    </>
  );
}

function OwnerKindName({ kind }: { kind: "personal" | "organization" }) {
  return kind === "organization" ? (
    <Text id="onboarding.catalog.organization">Organization</Text>
  ) : (
    <Text id="onboarding.catalog.personal">Personal Account</Text>
  );
}

function InlineError({ children }: { children: string }) {
  return (
    <p role="alert" className="mt-4 rounded-control border border-err/50 bg-err-bg px-3 py-2 text-sm text-err-text">
      {children}
    </p>
  );
}

function ChooseCadTool({ status }: { status: OnboardingStatus }) {
  const update = useUpdateSettings();
  const initial = status.primary_eda ?? status.recommended_primary_eda ?? "";
  const [selection, setSelection] = useState(initial);
  const [error, setError] = useState("");
  const failed = useText("onboarding.cad.failed", "Stockroom could not record the CAD tool. Rerun this step.");

  async function submit() {
    if (!selection) return;
    setError("");
    try {
      await update.mutateAsync({ primary_eda: selection });
    } catch (cause) {
      setError(errorText(cause, failed));
    }
  }

  return (
    <>
      <StepIntro
        eyebrow={<Text id="onboarding.cad.eyebrow">Step One</Text>}
        title={<Text id="onboarding.cad.title">Choose CAD Tool</Text>}
      >
        <Text id="onboarding.cad.lede">
          Stockroom configures one CAD tool for normal use on this PC. A later switch retains assets for the other tool.
        </Text>
      </StepIntro>
      <div className="mt-5 grid gap-2 sm:grid-cols-2">
        {status.eda_tools.map((tool) => (
          <button
            key={tool.key}
            type="button"
            aria-pressed={selection === tool.key}
            onClick={() => setSelection(tool.key)}
            className={
              "rounded-control border p-4 text-left outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus " +
              (selection === tool.key ? "border-acc bg-raise2" : "border-line bg-raise hover:bg-raise2")
            }
          >
            <span className="block text-sm font-semibold text-t1">{tool.label}</span>
            <span className="mt-1 block text-xs text-t3">
              {tool.detected ? (
                <Text id="onboarding.cad.detected">Detected On This PC</Text>
              ) : (
                <Text id="onboarding.cad.not-detected">Not Detected On This PC</Text>
              )}
              {tool.key === status.recommended_primary_eda ? (
                <> · <Text id="onboarding.cad.recommended">Recommended</Text></>
              ) : null}
            </span>
          </button>
        ))}
      </div>
      {error ? <InlineError>{error}</InlineError> : null}
      <div className="mt-5 flex justify-end">
        <Button variant="accent" disabled={!selection || update.isPending} onClick={submit}>
          {update.isPending ? (
            <Text id="onboarding.cad.saving">Recording...</Text>
          ) : (
            <Text id="onboarding.cad.continue">Continue</Text>
          )}
        </Button>
      </div>
    </>
  );
}

function CatalogRepository({ status }: { status: OnboardingStatus }) {
  const scenario = useScenarioUiState().onboarding;
  const scenarioMode: RepositoryMode = scenario?.mode === "create" ? "create" : "connect";
  const [mode, setMode] = useState<RepositoryMode>(scenarioMode);
  const priorScenarioMode = useRef<RepositoryMode | null>(null);
  const [owner, setOwner] = useState(status.guided_setup.github.viewer?.login ?? "");
  const [name, setName] = useState("stockroom-catalog");
  const [visibility, setVisibility] = useState<"public" | "private">("private");
  const [error, setError] = useState(scenario?.setupError ?? "");
  const openedCode = useRef<string | null>(null);
  const login = useOnboardingGitHubLogin();
  const repository = useSetGuidedRepository();
  const repositories = useOnboardingGitHubRepositories(
    owner,
    status.guided_setup.github.authenticated && mode === "connect",
  );
  const ownerLabel = useText("onboarding.catalog.owner", "GitHub Owner");
  const nameLabel = useText("onboarding.catalog.name", "Git Checkout Name");
  const modeLabel = useText("onboarding.catalog.mode", "Catalog Setup Mode");
  const catalogLabel = useText("onboarding.catalog.title", "Catalog Repository");
  const failed = useText("onboarding.catalog.failed", "Stockroom could not prepare the Catalog Git checkout. Rerun this step.");

  useEffect(() => {
    setError(scenario?.setupError ?? "");
  }, [scenario?.setupError]);

  useEffect(() => {
    const next = status.guided_setup.github.viewer?.login ?? status.guided_setup.github.owners[0]?.login ?? "";
    if (!owner && next) setOwner(next);
  }, [owner, status.guided_setup.github.owners, status.guided_setup.github.viewer]);

  useEffect(() => {
    if (scenario?.mode === undefined) {
      if (priorScenarioMode.current !== null) setMode(priorScenarioMode.current);
      priorScenarioMode.current = null;
      return;
    }
    const next = scenario.mode === "create" ? "create" : "connect";
    if (priorScenarioMode.current === null) priorScenarioMode.current = mode;
    setMode(next);
  }, [mode, scenario?.mode]);

  const writableRepositories = useMemo(
    () => repositories.data?.repositories.filter((item) => item.writable) ?? [],
    [repositories.data],
  );

  const selectedName = mode === "connect" && !writableRepositories.some((item) => item.name === name)
    ? writableRepositories.find((item) => /catalog|components|library/i.test(item.name))?.name
      ?? writableRepositories[0]?.name
      ?? ""
    : name;

  useEffect(() => {
    const code = login.progress?.user_code;
    if (!code || openedCode.current === code) return;
    openedCode.current = code;
    openExternalUrl(login.progress?.verification_uri ?? "https://github.com/login/device");
  }, [login.progress?.user_code, login.progress?.verification_uri]);

  async function signIn() {
    setError("");
    try {
      const terminal = await login.start();
      if (terminal.status === "error") setError(terminal.error ?? failed);
    } catch (cause) {
      setError(errorText(cause, failed));
    }
  }

  async function submit() {
    if (!owner || !selectedName.trim()) return;
    setError("");
    try {
      await repository.mutateAsync({
        mode,
        owner,
        name: selectedName.trim(),
        visibility: mode === "create" ? visibility : undefined,
        path: status.default_dir,
      });
    } catch (cause) {
      setError(errorText(cause, failed));
    }
  }

  const github = status.guided_setup.github;
  if (!github.online && github.error) {
    return (
      <>
        <StepIntro
          eyebrow={<Text id="onboarding.catalog.eyebrow">Step Two</Text>}
          title={<Text id="onboarding.catalog.title">Catalog Repository</Text>}
        >
          <Text id="onboarding.catalog.reconnecting-lede">
            Stockroom needs GitHub to prepare and confirm the Catalog Git checkout. Stockroom reconnects in the background.
          </Text>
        </StepIntro>
        <InlineError>{github.error}</InlineError>
        <p role="status" className="mt-4 text-sm text-t2">
          <Text id="onboarding.catalog.reconnecting">Waiting For GitHub...</Text>
        </p>
      </>
    );
  }
  if (!github.authenticated) {
    return (
      <>
        <StepIntro
          eyebrow={<Text id="onboarding.catalog.eyebrow">Step Two</Text>}
          title={<Text id="onboarding.catalog.title">Catalog Repository</Text>}
        >
          <Text id="onboarding.catalog.login-lede">
            Sign in through the GitHub browser flow. Stockroom does not request or store a GitHub token.
          </Text>
        </StepIntro>
        {error || login.error || github.error ? <InlineError>{error || login.error || github.error || failed}</InlineError> : null}
        {login.progress?.user_code ? (
          <section className="mt-5 rounded-control border border-acc bg-field p-4 text-center">
            <p className="text-xs text-t3"><Text id="onboarding.catalog.device-code-label">GitHub Device Code</Text></p>
            <p className="mt-2 font-mono text-2xl font-semibold tracking-[0.18em] text-t1">{login.progress.user_code}</p>
            <p className="mt-2 text-xs text-t2"><Text id="onboarding.catalog.device-code-help">Paste this code into the GitHub page that just opened.</Text></p>
          </section>
        ) : null}
        <div className="mt-5 flex justify-end">
          <Button variant="accent" disabled={login.status === "running" || !github.available} onClick={signIn}>
            {login.status === "running" ? (
              <Text id="onboarding.catalog.signing-in">Getting Code...</Text>
            ) : (
              <Text id="onboarding.catalog.sign-in">Sign In With GitHub</Text>
            )}
          </Button>
        </div>
      </>
    );
  }

  const canSubmit = Boolean(owner && selectedName.trim()) && !repository.isPending;
  return (
    <>
      <StepIntro
        eyebrow={<Text id="onboarding.catalog.eyebrow">Step Two</Text>}
        title={<Text id="onboarding.catalog.title">Catalog Repository</Text>}
      >
        <Text id="onboarding.catalog.lede">
          Select a Catalog Repository. Stockroom handles its local folder.
        </Text>
      </StepIntro>
      <p className="mt-3 text-xs text-t3">
        <Text id="onboarding.catalog.account">GitHub Account:</Text>{" "}
        <span className="text-t2">{github.viewer?.login}</span>
      </p>
      <div className="mt-4 grid grid-cols-2 gap-2" role="group" aria-label={modeLabel}>
        <Button variant={mode === "create" ? "soft" : "default"} aria-pressed={mode === "create"} onClick={() => setMode("create")}>
          <Text id="onboarding.catalog.create">Create New</Text>
        </Button>
        <Button variant={mode === "connect" ? "soft" : "default"} aria-pressed={mode === "connect"} onClick={() => setMode("connect")}>
          <Text id="onboarding.catalog.connect-existing">Connect Existing</Text>
        </Button>
      </div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-xs text-t3">{ownerLabel}</span>
          <select className={INPUT} aria-label={ownerLabel} value={owner} onChange={(event) => setOwner(event.target.value)}>
            {github.owners.map((item) => (
              <option key={item.login} value={item.login}>
                {item.login} (<OwnerKindName kind={item.kind} />)
              </option>
            ))}
          </select>
        </label>
        {mode === "create" ? (
          <label className="block">
            <span className="mb-1 block text-xs text-t3">{nameLabel}</span>
            <input className={INPUT} aria-label={nameLabel} value={name} onChange={(event) => setName(event.target.value)} spellCheck={false} />
            <span className="mt-1 block text-xs text-t3">
              <Text id="onboarding.catalog.suggested">Suggested Name: Stockroom Catalog</Text>
            </span>
          </label>
        ) : repositories.isLoading ? (
          <p className="self-end pb-2 text-xs text-t3"><Text id="onboarding.catalog.loading">Loading Catalogs...</Text></p>
        ) : writableRepositories.length === 0 ? (
          <p className="self-end pb-2 text-xs text-t3"><Text id="onboarding.catalog.none">No Writable Catalogs Found</Text></p>
        ) : (
          <label className="block">
            <span className="mb-1 block text-xs text-t3">
              <Text id="onboarding.catalog.available">Available Catalogs</Text>
            </span>
            <select
              className={INPUT}
              aria-label={catalogLabel}
              value={selectedName}
              onChange={(event) => setName(event.target.value)}
            >
              {writableRepositories.map((item) => (
                <option key={`${item.owner}/${item.name}`} value={item.name}>
                  {item.owner}/{item.name} · {item.visibility}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {mode === "create" ? (
        <fieldset className="mt-4">
          <legend className="mb-1 text-xs text-t3"><Text id="onboarding.catalog.access">GitHub Access</Text></legend>
          <div className="flex gap-2">
            <Button aria-pressed={visibility === "public"} variant={visibility === "public" ? "soft" : "default"} onClick={() => setVisibility("public")}>
              <Text id="onboarding.catalog.public">Public</Text>
            </Button>
            <Button aria-pressed={visibility === "private"} variant={visibility === "private" ? "soft" : "default"} onClick={() => setVisibility("private")}>
              <Text id="onboarding.catalog.private">Private</Text>
            </Button>
          </div>
        </fieldset>
      ) : null}
      {repositories.error && !error ? <InlineError>{errorText(repositories.error, failed)}</InlineError> : null}
      {error ? <InlineError>{error}</InlineError> : null}
      <div className="mt-5 flex justify-end">
        <Button variant="accent" disabled={!canSubmit} onClick={submit}>
          {repository.isPending ? (
            <Text id="onboarding.catalog.preparing" values={{ catalog: selectedName }}>{"Downloading {catalog}..."}</Text>
          ) : mode === "create" ? (
            <Text id="onboarding.catalog.create-action">Create Catalog</Text>
          ) : (
            <Text id="onboarding.catalog.connect-action" values={{ catalog: selectedName }}>{"Connect {catalog}"}</Text>
          )}
        </Button>
      </div>
    </>
  );
}

function ConnectTool({ status }: { status: OnboardingStatus }) {
  const job = useConnectGuidedTool();
  const primary = status.eda_tools.find((tool) => tool.key === status.primary_eda);
  const isAltium = status.primary_eda === "altium";
  const failed = useText("onboarding.tool.failed", "Stockroom could not connect the CAD tool. Rerun this step.");

  return (
    <>
      <StepIntro
        eyebrow={<Text id="onboarding.tool.eyebrow">Step Three</Text>}
        title={<Text id="onboarding.tool.title">Connect The Tool</Text>}
      >
        {isAltium ? (
          <Text id="onboarding.tool.altium-lede">
            Stockroom locates Altium Designer and ODBC, prepares the local DbLib, and completes the one-time catalog setup.
          </Text>
        ) : (
          <Text id="onboarding.tool.kicad-lede">
            Stockroom locates KiCad and its config, then connects the Component Catalog. The result states if KiCad needs a restart.
          </Text>
        )}
      </StepIntro>
      {isAltium ? (
        <p className="mt-4 rounded-control border border-warn/50 bg-warn-bg px-3 py-2 text-sm text-warn-text">
          <Text id="onboarding.tool.altium-disclosure">
            Altium Designer can open during this explicit setup if its one-time connection requires interaction. Stockroom does not open it from component adds.
          </Text>
        </p>
      ) : null}
      <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
        <dt className="text-t3"><Text id="onboarding.tool.selected">Selected Tool</Text></dt>
        <dd className="text-t1">{primary?.label ?? status.primary_eda}</dd>
        <dt className="text-t3"><Text id="onboarding.tool.installation">Installation</Text></dt>
        <dd className="text-t1">{status.guided_setup.tool_connection.installed ? <Text id="onboarding.tool.detected-state">Detected</Text> : <Text id="onboarding.tool.not-detected-state">Not Detected</Text>}</dd>
      </dl>
      {job.error ? <InlineError>{job.error || failed}</InlineError> : null}
      {job.progress?.message ? <p role="status" className="mt-4 text-sm text-t2">{job.progress.message}</p> : null}
      <div className="mt-5 flex justify-end">
        <Button variant="accent" disabled={job.status === "running"} onClick={() => void job.start()}>
          {job.status === "running" ? (
            <Text id="onboarding.tool.connecting">Connecting...</Text>
          ) : (
            <Text id="onboarding.tool.connect-action" values={{ tool: primary?.label ?? "CAD Tool" }}>{"Connect {tool}"}</Text>
          )}
        </Button>
      </div>
    </>
  );
}

function Prepared({ status }: { status: OnboardingStatus }) {
  const complete = useCompleteOnboarding();
  const [error, setError] = useState("");
  const attempted = useRef(false);
  const failed = useText("onboarding.prepared.failed", "Stockroom could not finish setup. Rerun this step.");
  const repository = status.guided_setup.repository;
  const primary = status.eda_tools.find((tool) => tool.key === status.primary_eda);

  useEffect(() => {
    if (attempted.current) return;
    attempted.current = true;
    void complete.mutateAsync().catch((cause) => setError(errorText(cause, failed)));
  }, [complete, failed]); // Legacy ready state: finish once without another confirmation screen.

  return (
    <>
      <StepIntro
        eyebrow={<Text id="onboarding.prepared.eyebrow">Finishing Setup</Text>}
        title={<Text id="onboarding.prepared.title">Ready</Text>}
      >
        <Text id="onboarding.prepared.lede">
          The Component Catalog and selected CAD tool passed the required setup checks. Open Components to add the first part.
        </Text>
      </StepIntro>
      <dl className="mt-5 grid grid-cols-[auto_1fr] gap-x-5 gap-y-3 rounded-control border border-line bg-field p-4 text-sm">
        <dt className="text-t3"><Text id="onboarding.prepared.catalog">Catalog Repository</Text></dt>
        <dd className="text-t1">{repository ? `${repository.owner}/${repository.name}` : ""}</dd>
        <dt className="text-t3"><Text id="onboarding.prepared.tool">Selected CAD Tool</Text></dt>
        <dd className="text-t1">{primary?.label ?? status.primary_eda}</dd>
        <dt className="text-t3"><Text id="onboarding.prepared.connection">Tool Connection</Text></dt>
        <dd className="text-t1">{status.guided_setup.tool_connection.detail}</dd>
        {status.guided_setup.tool_connection.restart_required ? (
          <>
            <dt className="text-t3"><Text id="onboarding.prepared.restart">CAD Restart</Text></dt>
            <dd className="text-t1"><Text id="onboarding.prepared.restart-required">Required</Text></dd>
          </>
        ) : null}
        <dt className="text-t3"><Text id="onboarding.prepared.mouser">Mouser</Text></dt>
        <dd className="text-t1">
          {status.guided_setup.source_data.skipped ? <Text id="onboarding.prepared.sources-skipped">Skipped</Text> : status.guided_setup.source_data.mouser_connected ? <Text id="onboarding.prepared.source-connected">Connected</Text> : <Text id="onboarding.prepared.source-not-connected">Not Connected</Text>}
        </dd>
        <dt className="text-t3"><Text id="onboarding.prepared.digikey">DigiKey</Text></dt>
        <dd className="text-t1">
          {status.guided_setup.source_data.skipped ? <Text id="onboarding.prepared.sources-skipped">Skipped</Text> : status.guided_setup.source_data.digikey_connected ? <Text id="onboarding.prepared.source-connected">Connected</Text> : <Text id="onboarding.prepared.source-not-connected">Not Connected</Text>}
        </dd>
        <dt className="text-t3"><Text id="onboarding.prepared.first-action">First Action</Text></dt>
        <dd className="text-t1"><Text id="onboarding.prepared.add">Add A Component</Text></dd>
      </dl>
      {error ? <InlineError>{error}</InlineError> : null}
      <p role="status" className="mt-5 text-sm text-t2"><Text id="onboarding.prepared.opening">Opening...</Text></p>
    </>
  );
}
