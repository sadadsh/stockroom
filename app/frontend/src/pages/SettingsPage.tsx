/**
 * Settings (spec sections 5.3, 9, 11, 12): the per-machine controls that live
 * outside the library. Appearance, independent library repositories, library
 * sync, EDA wiring, distributor credentials, and
 * the app self-update. Every section is honest about its state: offline/divergence
 * and a missing kicad-cli are surfaced verbatim, never faked green, and the Mouser
 * key is only ever shown as a last-4 hint.
 */
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { ApiError, api } from "../api/client";
import type { SetLibraryBody, SettingsPatch, WiringReport } from "../api/types";
import { useJob } from "../lib/useJob";
import { AltiumDbLibSection } from "../components/AltiumDbLibSection";
import { SettingsDisclosure } from "../components/SettingsDisclosure";
import { LibraryCompletionSection } from "../components/LibraryCompletionSection";
import { DerivationSection } from "../components/DerivationSection";
import { CadClearSection } from "../components/CadClearSection";
import { LibraryHealthSection } from "../components/LibraryHealthSection";
import { LibrarySyncSection } from "../components/LibrarySyncSection";
import { RescanSection } from "../components/RescanSection";
import { lastChecked } from "../components/rescanState";
import {
  useDoSync,
  useConnectLibraryRemote,
  useOnboarding,
  useSetLibrary,
  useSettings,
  useSyncStatus,
  useSystemInfo,
  useUpdateSettings,
  useLoadDevCreds,
  useOdbcStatus,
  useLibraryCoverage,
  useLibraryDerivation,
  useCadInventory,
  useDoctorScan,
  useLibraryLfs,
  useRescanState,
} from "../api/queries";
import { useTheme, type Theme } from "../lib/theme";
import { statusTone } from "../lib/statusTone";
import { useToast } from "../lib/toast";
import {
  Badge,
  Button,
  Card,
  Dot,
  ErrorState,
  Eyebrow,
  LoadingState,
  RouteHeader,
} from "../components/primitives";
import { Text, useCopyFormatter, useText } from "../lib/copy";
import { Icon } from "../components/Icon";
import {
  shortRevision,
  updateTargetRevision,
  type UpdateStanding,
} from "../lib/updateStanding";
import { useUpdateStanding } from "../lib/useUpdateStanding";
import { pickHostFolder } from "../lib/hostFolderPicker";
import { useScenarioUiState } from "../design-studio/scenarioState";

function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

function errMsg(err: unknown): string {
  return err instanceof ApiError ? err.message : "Something went wrong.";
}

const INPUT_CLS =
  "h-[29px] min-w-0 flex-1 rounded-control border border-line2 bg-field px-3 " +
  "text-sm text-t1 outline-none focus:border-acc disabled:opacity-50";

function StatusRow({
  label,
  labelId,
  value,
}: {
  label: string;
  labelId?: string;
  value: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-line py-2 last:border-b-0">
      <span className="flex-none text-xs text-t3">
        {labelId ? <Text id={labelId}>{label}</Text> : label}
      </span>
      <span className="min-w-0 truncate text-right text-sm text-t1">{value}</span>
    </div>
  );
}

// Five scopes a person can reason about. Automatic behavior is separate from library sharing;
// both EDA projections live together; destructive and repair work is isolated in Maintenance.
type GroupId = "general" | "library" | "eda" | "sources" | "maintenance";

const SETTINGS_GROUPS: {
  id: GroupId;
  label: string;
  description: string;
  icon: string;
}[] = [
  {
    id: "general",
    label: "General",
    description: "Application appearance, delivery, and the exact behavior of updates.",
    icon: "action.settings",
  },
  {
    id: "library",
    label: "Library",
    description: "Which component collection is active and how its changes reach collaborators.",
    icon: "nav.library",
  },
  {
    id: "eda",
    label: "EDA Tools",
    description: "Machine integration for KiCad and Altium, with automatic state shown first.",
    icon: "nav.board",
  },
  {
    id: "sources",
    label: "Data Sources",
    description: "Optional provider access and controlled refresh of commercial evidence.",
    icon: "action.download",
  },
  {
    id: "maintenance",
    label: "Maintenance",
    description: "Repair, rebuild, storage, and destructive recovery kept away from daily setup.",
    icon: "action.doctor",
  },
];

// One unmet setup step surfaced by Machine Readiness; clicking it jumps to the owning category.
interface SetupStep {
  id: string;
  // The imperative shown while unmet ("Wire KiCad") and the achieved state shown
  // once met ("KiCad Wired") - a met step must read as state, never as a command.
  label: string;
  labelId: string;
  metLabel: string;
  metLabelId: string;
  met: boolean;
  group: GroupId;
}

export function SettingsPage() {
  const scenarioSettings = useScenarioUiState().settings;
  // The page-level reads that feed the Machine Setup band and the nav dots. Every one is a cached
  // query a section also uses, so this adds no extra request load. Each group panel below resolves
  // the rest of what it needs from the same cached keys.
  const settingsQ = useSettings();
  const odbc = useOdbcStatus();
  const syncQ = useSyncStatus();
  const { query: updateQ, view: updateStanding } = useUpdateStanding();
  const coverageQ = useLibraryCoverage();
  const doctorQ = useDoctorScan();
  const navAria = useText("settings.nav.aria", "Settings Sections");
  // A toast takes a resolved string, so every sentence one of them says is read here. The paths and
  // credential names inside the holes are values off the machine and are not ours to reword.
  const devCredsLoaded = useCopyFormatter(
    "settings.dev-creds.toast-loaded",
    "Loaded dev creds: {names}.",
  );
  const devCredsAbsent = useCopyFormatter(
    "settings.dev-creds.toast-absent",
    "No dev-creds.json at {path}. Place it there from another machine to load credentials in one stroke.",
  );

  const [group, setGroup] = useState<GroupId>("general");
  const settingsContentRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (settingsContentRef.current) settingsContentRef.current.scrollTop = 0;
  }, [group]);

  useEffect(() => {
    if (scenarioSettings?.group) setGroup(scenarioSettings.group);
  }, [scenarioSettings?.group]);

  // Hidden dev combo (Ctrl+Alt+K): load API keys / logins from the per-machine
  // dev-creds.json so live validation is not blocked on retyping them. It lives at
  // the PAGE level deliberately - inside a section it dies whenever that section's
  // disclosure is collapsed (the grouped IA unmounts collapsed content), which
  // silently killed the hotkey (2026-07-24 report). A ref keeps the listener
  // subscribed once while always firing the latest handler.
  const loadDev = useLoadDevCreds();
  const { toast } = useToast();
  const fireDevLoad = useRef<() => void>(() => {});
  // Installed in a layout effect, not during render: render can be replayed or thrown away, and the
  // ref would then hold a closure over a tree that never committed. The listener below is registered
  // in a passive effect, which runs after every layout effect, so the hotkey can never fire before
  // the real handler is in place.
  useLayoutEffect(() => {
    fireDevLoad.current = () => {
      if (loadDev.isPending) return;
      loadDev.mutate(undefined, {
        onSuccess: (res) =>
          toast(
            res.loaded.length
              ? devCredsLoaded({ names: res.loaded.join(", ") })
              : devCredsAbsent({ path: res.config_path }),
            res.loaded.length ? "ok" : "neutral",
          ),
        onError: (e) => toast(errMsg(e), "err"),
      });
    };
  });
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.ctrlKey && e.altKey && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        fireDevLoad.current();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const s = settingsQ.data;
  const odbcInstalled = odbc.data?.installed;
  const githubAccounts = syncQ.data?.github_auth.accounts ?? [];
  // A legacy app-owned token may still exist on an upgraded machine. It remains a temporary
  // compatibility signal, but the UI creates no new tokens and GCM is the durable authority.
  const githubConnected = githubAccounts.length > 0 || Boolean(s?.github_token_set);

  function jump(step: SetupStep) {
    setGroup(step.group);
  }

  function selectGroup(g: GroupId) {
    setGroup(g);
  }

  // -- the Machine Setup verdict: is THIS machine fully set up? ---------------
  const steps: SetupStep[] = [];
  if (s) {
    steps.push({
      id: "kicad",
      label: "Wire KiCad",
      labelId: "settings.machine.step-kicad",
      metLabel: "KiCad Wired",
      metLabelId: "settings.machine.step-kicad-met",
      met: s.kicad_wired,
      group: "eda",
    });
    if (odbcInstalled !== null && odbcInstalled !== undefined) {
      steps.push({
        id: "odbc",
        label: "Install The ODBC Driver",
        labelId: "settings.machine.step-odbc",
        metLabel: "ODBC Driver Installed",
        metLabelId: "settings.machine.step-odbc-met",
        met: odbcInstalled,
        group: "eda",
      });
    }
    steps.push({
      id: "key",
      label: "Add A Distributor Credential",
      labelId: "settings.machine.step-key",
      metLabel: "Distributor Credential Saved",
      metLabelId: "settings.machine.step-key-met",
      met: s.mouser_api_key_set || s.digikey_client_secret_set,
      group: "sources",
    });
    steps.push({
      id: "github",
      label: "Connect GitHub",
      labelId: "settings.machine.step-github",
      metLabel: "GitHub Connected",
      metLabelId: "settings.machine.step-github-met",
      met: githubConnected,
      group: "library",
    });
  }
  const unmet = steps.filter((st) => !st.met);
  const headerAttention = useText("settings.machine.header-attention", "{count} need attention", {
    count: unmet.length,
  });
  const headerReady = useText("settings.machine.header-ready", "Machine prepared");

  // -- per-group attention dots (mirror the unmet steps + an available update) --
  const groupAttention: Record<GroupId, "warn" | "neutral" | null> = {
    general:
      updateStanding.standing === "available"
        ? "neutral"
        : ["retrying", "blocked", "restart_required", "unknown"].includes(
              updateStanding.standing,
            )
          ? "warn"
          : null,
    library: unmet.some((st) => st.group === "library") ? "warn" : null,
    eda: unmet.some((st) => st.group === "eda") ? "warn" : null,
    sources: unmet.some((st) => st.group === "sources") ? "warn" : null,
    maintenance:
      (coverageQ.data && coverageQ.data.complete < coverageQ.data.total) ||
      (doctorQ.data &&
        doctorQ.data.fixable.length + doctorQ.data.manual.length + doctorQ.data.uncommitted.length >
          0)
        ? "warn"
        : null,
  };


  const activeMeta = SETTINGS_GROUPS.find((item) => item.id === group) ?? SETTINGS_GROUPS[0];

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-dev-id="settings.root">
      <RouteHeader
        data-dev-id="settings.title"
        right={unmet.length > 0 ? headerAttention : headerReady}
      >
        <Text id="settings.title">Settings</Text>
      </RouteHeader>
      <div className="@container flex min-h-0 flex-1 flex-col overflow-hidden px-5 pb-4 pt-4">
        <MachineSetupBand
          loading={!s}
          steps={steps}
          onJump={jump}
          updateStanding={updateStanding.standing}
          updateBehind={updateQ.data?.behind ?? 0}
          updateState={updateQ.data?.state}
          onOpenUpdates={() => setGroup("general")}
        />

        <nav
          aria-label={navAria}
          className="mt-3 flex flex-none items-center gap-1 overflow-x-auto rounded-card border border-line bg-band p-1"
          data-dev-id="settings.nav"
        >
          <GroupNavButton
            id="general"
            label="General"
            labelId="settings.nav.general"
            active={group}
            onSelect={selectGroup}
            attention={groupAttention.general}
            data-dev-id="settings.nav-general"
          />
          <GroupNavButton
            id="library"
            label="Catalog"
            labelId="settings.nav.library"
            active={group}
            onSelect={selectGroup}
            attention={groupAttention.library}
            data-dev-id="settings.nav-library"
          />
          <GroupNavButton
            id="eda"
            label="EDA Tools"
            labelId="settings.nav.eda"
            active={group}
            onSelect={selectGroup}
            attention={groupAttention.eda}
            data-dev-id="settings.nav-eda"
          />
          <GroupNavButton
            id="sources"
            label="Data Sources"
            labelId="settings.nav.sources"
            active={group}
            onSelect={selectGroup}
            attention={groupAttention.sources}
            data-dev-id="settings.nav-sources"
          />
          <GroupNavButton
            id="maintenance"
            label="Maintenance"
            labelId="settings.nav.maintenance"
            active={group}
            onSelect={selectGroup}
            attention={groupAttention.maintenance}
            data-dev-id="settings.nav-maintenance"
          />
        </nav>

        <section className="mt-3 flex min-h-0 flex-1 flex-col overflow-hidden rounded-card border border-line bg-canvas">
          <div className="flex flex-none items-start gap-4 border-b border-line bg-band px-4 py-3">
            <Icon id={activeMeta.icon} className="mt-0.5 h-4 w-4 flex-none text-t2" />
            <div className="min-w-0">
              <h1 className="text-base font-semibold text-t1">{activeMeta.label}</h1>
              <p className="mt-0.5 text-xs text-t3">{activeMeta.description}</p>
            </div>
          </div>
          <div
            ref={settingsContentRef}
            data-dev-id="settings.content"
            className="grid min-h-0 flex-1 auto-rows-max grid-cols-1 gap-3 overflow-y-auto p-3 @3xl:grid-cols-2"
          >
            {group === "general" ? (
              <GeneralGroup />
            ) : group === "library" ? (
              <LibraryGroup />
            ) : group === "eda" ? (
              <EdaGroup />
            ) : group === "sources" ? (
              <SourcesGroup />
            ) : (
              <MaintenanceGroup />
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function GroupNavButton({
  id,
  label,
  labelId,
  active,
  onSelect,
  attention,
  "data-dev-id": devId,
}: {
  id: GroupId;
  label: string;
  labelId: string;
  active: GroupId;
  onSelect: (g: GroupId) => void;
  attention: "warn" | "neutral" | null;
  "data-dev-id"?: string;
}) {
  const selected = active === id;
  return (
    <button
      type="button"
      onClick={() => onSelect(id)}
      aria-current={selected ? "true" : undefined}
      data-dev-id={devId}
      className={cx(
        "flex min-w-[132px] flex-1 items-center justify-center gap-2 rounded-control px-3 py-2 text-sm transition-colors",
        selected
          ? "bg-raise2 font-semibold text-t1 shadow-[inset_0_-2px_0_var(--c-acc)]"
          : "text-t2 hover:bg-[var(--c-hover)] hover:text-t1",
      )}
    >
      <span className="min-w-0 truncate">
        <Text id={labelId}>{label}</Text>
      </span>
      {attention ? <Dot tone={attention} /> : null}
    </button>
  );
}

// The Machine Setup band: Settings opens by ANSWERING whether this machine is fully
// set up, instead of presenting a wall of knobs. Each unmet step is a clickable chip
// that jumps to (and opens) the section that fixes it; met steps read as a quiet roll
// call. Honest while loading: a reading state, never a fabricated verdict.
function MachineSetupBand({
  loading,
  steps,
  onJump,
  updateStanding,
  updateBehind,
  updateState,
  onOpenUpdates,
}: {
  loading: boolean;
  steps: SetupStep[];
  onJump: (step: SetupStep) => void;
  updateStanding: UpdateStanding;
  updateBehind: number;
  updateState?: string;
  onOpenUpdates: () => void;
}) {
  const unmet = steps.filter((st) => !st.met);
  return (
    <div
      className="grid flex-none grid-cols-1 gap-3 @3xl:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]"
      data-dev-id="settings.machine-band"
    >
      <Card className="flex min-w-0 items-center gap-4 px-4 py-3.5">
        <span className="grid h-9 w-9 flex-none place-items-center rounded-control border border-line2 bg-field text-t2">
          <Icon id="nav.update" className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <Eyebrow className="mb-0.5">
            <Text id="settings.delivery.title">Application Updates</Text>
          </Eyebrow>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-t1">
              <Text id="settings.delivery.mode">Automatic Convergence</Text>
            </span>
            {updateState === "offline" ? (
              <Badge tone="warn">
                <Text id="settings.delivery.offline">Offline</Text>
              </Badge>
            ) : updateStanding === "retrying" ? (
              <Badge tone="warn">
                <Text id="settings.delivery.retrying">Rerunning</Text>
              </Badge>
            ) : updateStanding === "blocked" ? (
              <Badge tone="err">
                <Text id="settings.delivery.blocked">Blocked</Text>
              </Badge>
            ) : updateStanding === "restart_required" ? (
              <Badge tone="warn">
                <Text id="settings.delivery.restart">Restart Required</Text>
              </Badge>
            ) : updateStanding === "updating" ? (
              <Badge tone="neutral">
                <Text id="settings.delivery.updating">Updating</Text>
              </Badge>
            ) : updateStanding === "available" ? (
              <Badge tone="warn">
                {updateBehind > 0 ? (
                  <Text id="settings.delivery.commits-ready" values={{ count: updateBehind }}>
                    {"{count} Commits Available"}
                  </Text>
                ) : (
                  <Text id="settings.delivery.update-ready">Update Available</Text>
                )}
              </Badge>
            ) : updateStanding === "current" ? (
              <Badge tone="ok">
                <Text id="settings.delivery.current">Current</Text>
              </Badge>
            ) : (
              <Badge tone="warn">
                <Text id="settings.delivery.unknown">Status Unknown</Text>
              </Badge>
            )}
          </div>
          <p className="mt-1 text-xs text-t3">
            <Text id="settings.delivery.lede">Install Stockroom.exe once. It follows the validated application revision on its own, checks at two-minute intervals, and keeps this window open while adopting updates.</Text>
          </p>
        </div>
        <div className="flex flex-none flex-col items-end gap-1.5">
          {updateStanding === "available" ? (
            <Button small variant="accent" onClick={onOpenUpdates}>
              <Text id="settings.delivery.review">Review Update</Text>
            </Button>
          ) : null}
          <a
            href="https://github.com/sadadsh/stockroom/releases"
            target="_blank"
            rel="noreferrer"
            className="text-2xs font-medium text-t2 underline decoration-line2 underline-offset-2 hover:text-t1"
          >
            <Text id="settings.delivery.get-exe">Get Stockroom.exe</Text>
          </a>
        </div>
      </Card>

      <Card className="min-w-0 px-4 py-3.5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <Eyebrow className="mb-0.5">
              <Text id="settings.machine.title">Machine Readiness</Text>
            </Eyebrow>
            {loading ? (
              <p className="text-sm text-t3">
                <Text id="settings.machine.loading">Reading this machine...</Text>
              </p>
            ) : unmet.length === 0 ? (
              <p className="text-sm font-semibold text-t1">
                <Text id="settings.machine.ready">This Machine Is Prepared</Text>
              </p>
            ) : (
              <p className="text-sm font-semibold text-t1">
                {unmet.length === 1 ? (
                  <Text id="settings.machine.one-unmet">1 Setup Step Needs Attention</Text>
                ) : (
                  <Text id="settings.machine.many-unmet" values={{ count: unmet.length }}>
                    {"{count} Setup Steps Need Attention"}
                  </Text>
                )}
              </p>
            )}
          </div>
          {!loading ? (
            <span className="text-2xs text-t3">
              <Text
                id="settings.machine.ready-count"
                values={{ ready: steps.length - unmet.length, total: steps.length }}
              >
                {"{ready} of {total} prepared"}
              </Text>
            </span>
          ) : null}
        </div>
        {!loading ? (
          <div className="mt-2.5 grid grid-cols-2 gap-1.5">
            {steps.map((st) =>
              st.met ? (
                <span
                  key={st.id}
                  className="inline-flex min-w-0 items-center gap-1.5 rounded-control border border-line bg-field px-2 py-1.5 text-2xs font-medium text-t3"
                >
                  <Dot tone="ok" />
                  <span className="truncate">
                    <Text id={st.metLabelId}>{st.metLabel}</Text>
                  </span>
                </span>
              ) : (
                <button
                  key={st.id}
                  type="button"
                  onClick={() => onJump(st)}
                  className="inline-flex min-w-0 items-center gap-1.5 rounded-control border border-warn/50 bg-field px-2 py-1.5 text-left text-2xs font-semibold text-t1 transition-colors hover:bg-[var(--c-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
                >
                  <Dot tone="warn" />
                  <span className="truncate">
                    <Text id={st.labelId}>{st.label}</Text>
                  </span>
                </button>
              ),
            )}
          </div>
        ) : null}
      </Card>
    </div>
  );
}

// The two theme choices, allocated once: nothing here reads state or props.
const THEME_OPTIONS: { value: Theme; label: string; id: string }[] = [
  { value: "dark", label: "Dark", id: "settings.appearance.dark" },
  { value: "light", label: "Light", id: "settings.appearance.light" },
];

function AppearanceSection() {
  const { theme, setTheme } = useTheme();
  return (
    <>
      <div className="flex items-center justify-between">
        <span className="text-sm text-t2">
          <Text id="settings.appearance.theme-label">Theme</Text>
        </span>
        <div
          className="inline-flex rounded-card border border-line2 p-0.5"
          data-dev-id="settings.appearance-theme"
        >
          {THEME_OPTIONS.map((o) => (
            <button
              key={o.value}
              type="button"
              aria-pressed={theme === o.value}
              onClick={() => setTheme(o.value)}
              className={cx(
                "rounded-control px-3 py-1 text-sm transition-colors",
                theme === o.value ? "bg-acc-soft font-medium text-t1" : "text-t3 hover:text-t2",
              )}
            >
              <Text id={o.id}>{o.label}</Text>
            </button>
          ))}
        </div>
      </div>
    </>
  );
}

function LibraryRepositoriesSection() {
  const scenarioMode = useScenarioUiState().settings?.libraryMode;
  const libraries = useOnboarding();
  const setLibrary = useSetLibrary();
  const { toast } = useToast();
  const [mode, setMode] = useState<SetLibraryBody["mode"] | "current">(scenarioMode ?? "create");
  const [path, setPath] = useState("");
  const [url, setUrl] = useState("");
  const cloneUrlLabel = useText("settings.library.clone-url", "Git Remote URL");
  const openFolderLabel = useText("settings.library.open-folder", "Existing Catalog Folder");
  const newFolderLabel = useText("settings.library.new-folder", "New Catalog Folder");
  const catalogReady = useCopyFormatter(
    "settings.library.toast-ready",
    "Catalog prepared at {root}.",
  );
  useEffect(() => {
    if (scenarioMode) setMode(scenarioMode);
  }, [scenarioMode]);

  function apply(body: SetLibraryBody) {
    if (setLibrary.isPending) return;
    setLibrary.mutate(body, {
      onSuccess: (result) => {
        setPath("");
        setUrl("");
        toast(catalogReady({ root: result.libraries_root }), "ok");
      },
      onError: (error) => toast(errMsg(error), "err"),
    });
  }

  return (
    <>
      {libraries.isLoading ? (
        <LoadingState dense id="settings.libraries-loading">
          Loading this machine's catalogs...
        </LoadingState>
      ) : libraries.isError ? (
        <ErrorState dense id="settings.libraries-failed" onRetry={() => libraries.refetch()}>
          This machine's libraries could not be listed.
        </ErrorState>
      ) : (
        <div>
          {libraries.data?.libraries.map((library) => {
            return (
              <div
                key={library.path}
                data-library-row
                data-dev-id="settings.profiles-row"
                className="flex items-center justify-between gap-3 border-b border-line py-2 last:border-b-0"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm text-t1">{library.name}</p>
                    <p className="truncate text-xs text-t3">{library.path}</p>
                  </div>
                  {library.active ? (
                    <Badge tone="ok">
                      <Text id="settings.library.active">Active</Text>
                    </Badge>
                  ) : null}
                  {!library.available ? (
                    <Badge tone="warn">
                      <Text id="settings.library.unavailable">Unavailable</Text>
                    </Badge>
                  ) : null}
                </div>
                {!library.active && library.available ? (
                  <Button
                    small
                    onClick={() => apply({ mode: "open", path: library.path })}
                    disabled={setLibrary.isPending}
                  >
                    <Text id="settings.profiles.activate">Switch Catalog</Text>
                  </Button>
                ) : null}
              </div>
            );
          })}
        </div>
      )}

      {mode === "current" ? (
        <p className="mt-3.5 text-xs text-t2">
          <Text id="settings.library.current-note">The active catalog above receives component changes.</Text>
        </p>
      ) : <div
        className="mt-3.5 space-y-2.5"
        data-dev-id="settings.profiles-create"
      >
        <div className="flex flex-wrap gap-2">
          {(["create", "open", "clone"] as const).map((choice) => (
            <Button
              key={choice}
              small
              variant={mode === choice ? "accent" : "default"}
              onClick={() => setMode(choice)}
            >
              {choice === "create" ? (
                <Text id="settings.library.mode-create">Create New</Text>
              ) : choice === "open" ? (
                <Text id="settings.library.mode-open">Open Existing</Text>
              ) : (
                <Text id="settings.library.mode-clone">Clone From Git</Text>
              )}
            </Button>
          ))}
        </div>
        {mode === "clone" ? (
          <input
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder={cloneUrlLabel}
            aria-label={cloneUrlLabel}
            className={INPUT_CLS}
          />
        ) : null}
        <input
          value={path}
          onChange={(event) => setPath(event.target.value)}
          placeholder={mode === "open" ? openFolderLabel : newFolderLabel}
          aria-label={mode === "open" ? openFolderLabel : newFolderLabel}
          className={INPUT_CLS}
        />
        <Button
          onClick={() =>
            apply(
              mode === "clone"
                ? { mode, url: url.trim(), dest: path.trim() }
                : { mode, path: path.trim() },
            )
          }
          disabled={!path.trim() || (mode === "clone" && !url.trim()) || setLibrary.isPending}
        >
          <Text id="settings.profiles.create">Set Up Catalog Git Remote</Text>
        </Button>
        <p className="text-xs text-t3">
          <Text id="settings.library.create-note">Creating a catalog initializes its own Git checkout. Stockroom source and other catalogs are never added to it.</Text>
        </p>
      </div>}
    </>
  );
}

function SyncSection() {
  const status = useSyncStatus();
  const sync = useDoSync();
  const connectRemote = useConnectLibraryRemote();
  const { toast } = useToast();
  const [remoteUrl, setRemoteUrl] = useState("");
  // The placeholder is an EXAMPLE of a repository URL, so it is routed but never reworded to a
  // real address; the aria-label is the field's actual name.
  const remotePlaceholder = useText(
    "settings.sync.remote-placeholder",
    "https://github.com/team/catalog.git",
  );
  const remoteAria = useText("settings.sync.remote-aria", "Catalog GitHub Remote URL");
  // One sentence per sync outcome, each read here because a toast has no element to wrap.
  const syncDiverged = useText(
    "settings.sync.toast-diverged",
    "Sharing failed: the components have diverged from the remote.",
  );
  const syncOffline = useText(
    "settings.sync.toast-offline",
    "Sharing failed: the remote is unreachable.",
  );
  const syncDenied = useText(
    "settings.sync.toast-denied",
    "Sharing failed: GitHub denied this Windows account. Accept the git remote invitation or ask its owner for write access, then sign in again.",
  );
  const syncNoRemote = useText(
    "settings.sync.toast-no-remote",
    "No remote is configured for these components.",
  );
  const syncConverged = useText(
    "settings.sync.toast-converged",
    "Both devices' catalog changes converged.",
  );
  // The three outcomes the last line can report, as whole sentences rather than a stitched verb:
  // an override has to be able to reword the sentence, which a spliced-in word would not allow.
  const syncPulled = useText("settings.sync.toast-pulled", "Pulled from the remote.");
  const syncPushed = useText("settings.sync.toast-pushed", "Pulled from and pushed to the remote.");
  const syncCurrent = useText("settings.sync.toast-current", "Nothing to pull or push.");
  const remoteConnected = useText(
    "settings.sync.toast-remote-connected",
    "Catalog git remote connected. The next share publishes its current timeline.",
  );

  function onSync() {
    sync.mutate(undefined, {
      onSuccess: (r) => {
        // Divergence and offline are FAILURES, surfaced verbatim and never faked
        // green; no-remote is informational; only a real pull/push/clean is ok.
        if (r.state === "diverged") {
          toast(syncDiverged, "err");
          return;
        }
        if (r.state === "offline") {
          toast(syncOffline, "err");
          return;
        }
        if (r.state === "denied") {
          toast(syncDenied, "err");
          return;
        }
        if (r.state === "no_remote") {
          toast(syncNoRemote, "neutral");
          return;
        }
        if (r.converged) {
          toast(syncConverged, "ok");
          return;
        }
        toast(r.pushed ? syncPushed : r.pulled ? syncPulled : syncCurrent, "ok");
      },
      onError: (e) => toast(errMsg(e), "err"),
    });
  }

  return (
    <>
      {status.isLoading ? (
        <LoadingState dense id="settings.sync-loading">
          Checking how this catalog compares with its remote...
        </LoadingState>
      ) : status.isError ? (
        <ErrorState dense id="settings.sync-failed" onRetry={() => status.refetch()}>
          The sync standing of this library could not be read.
        </ErrorState>
      ) : status.data ? (
        <>
          <StatusRow
            label="Branch"
            labelId="settings.sync.branch"
            value={<span className="tnum font-mono">{status.data.current_branch}</span>}
          />
          <StatusRow
            label="Remote"
            labelId="settings.sync.remote"
            value={
              status.data.has_remote ? (
                <span className="tnum font-mono">
                  <span className={status.data.ahead > 0 ? statusTone("ahead").text : undefined}>
                    <Text id="settings.sync.ahead-count" values={{ count: status.data.ahead }}>
                      {"{count} ahead"}
                    </Text>
                  </span>
                  {", "}
                  <span className={status.data.behind > 0 ? statusTone("behind").text : undefined}>
                    <Text id="settings.sync.behind-count" values={{ count: status.data.behind }}>
                      {"{count} behind"}
                    </Text>
                  </span>
                </span>
              ) : (
                "No remote configured"
              )
            }
          />
          {status.data.working_copy ? (
            <StatusRow
              label="Working Tree"
              labelId="settings.sync.working-copy"
              value={
                <span
                  className={
                    status.data.working_copy.mode === "rival_application_checkout"
                      ? "text-err-text"
                      : status.data.working_copy.mode === "embedded"
                        ? "text-ok-text"
                        : undefined
                  }
                  title={status.data.working_copy.detail}
                >
                  {status.data.working_copy.mode === "embedded" ? (
                    <Text id="settings.sync.checkout-managed">One Managed Checkout</Text>
                  ) : status.data.working_copy.mode === "rival_application_checkout" ? (
                    <Text id="settings.sync.checkout-rival">Rival App Checkout Detected</Text>
                  ) : (
                    <Text id="settings.sync.checkout-separate">Separate Catalog Checkout</Text>
                  )}
                </span>
              }
            />
          ) : null}
          {status.data.checkout_inventory ? (
            <StatusRow
              label="Checkout Contents"
              labelId="settings.sync.checkout-inventory"
              value={
                <span
                  className={
                    status.data.checkout_inventory.rival_count > 0
                      ? "text-err-text"
                      : status.data.checkout_inventory.state === "complete"
                        ? "text-ok-text"
                        : undefined
                  }
                  title={status.data.checkout_inventory.checkouts
                    .map(
                      (checkout) =>
                        `${checkout.classification}: ${checkout.path} @ ${checkout.revision}`,
                    )
                    .join("\n")}
                >
                  {status.data.checkout_inventory.state === "scanning" ? (
                    <Text id="settings.sync.inventory-scanning">Scanning This Computer</Text>
                  ) : status.data.checkout_inventory.rival_count === 1 ? (
                    <Text id="settings.sync.inventory-rival-one" values={{ count: 1 }}>
                      {"{count} Rival Checkout Detected"}
                    </Text>
                  ) : status.data.checkout_inventory.rival_count > 1 ? (
                    <Text
                      id="settings.sync.inventory-rival-many"
                      values={{ count: status.data.checkout_inventory.rival_count }}
                    >
                      {"{count} Rival Checkouts Detected"}
                    </Text>
                  ) : status.data.checkout_inventory.state === "complete" ? (
                    <Text id="settings.sync.inventory-canonical">Canonical Checkout Alone</Text>
                  ) : (
                    <Text id="settings.sync.inventory-incomplete">Scan Incomplete</Text>
                  )}
                </span>
              }
            />
          ) : null}
          <StatusRow
            label="Automatic Convergence"
            labelId="settings.sync.automatic-convergence"
            value={
              !status.data.last_sync ? (
                <Text id="settings.sync.last-waiting">Waiting For First Check</Text>
              ) : (
                <span
                  className={
                    ["diverged", "denied"].includes(status.data.last_sync.state)
                      ? "text-err-text"
                      : status.data.last_sync.state === "offline"
                        ? "text-warn"
                        : "text-ok-text"
                  }
                  title={status.data.last_sync.detail}
                >
                  {status.data.last_sync.state === "converged" ? (
                    <Text id="settings.sync.last-converged">Devices Converged</Text>
                  ) : status.data.last_sync.state === "synced" ? (
                    <Text id="settings.sync.last-current">Current</Text>
                  ) : (
                    status.data.last_sync.state
                      .split("_")
                      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
                      .join(" ")
                  )}
                </span>
              )
            }
          />
        </>
      ) : null}
      {status.data && !status.data.has_remote ? (
        <div className="mt-3.5 flex flex-wrap items-center gap-2.5">
          <input
            value={remoteUrl}
            onChange={(event) => setRemoteUrl(event.target.value)}
            placeholder={remotePlaceholder}
            aria-label={remoteAria}
            className={INPUT_CLS}
          />
          <Button
            onClick={() =>
              connectRemote.mutate(remoteUrl.trim(), {
                onSuccess: () => {
                  setRemoteUrl("");
                  toast(remoteConnected, "ok");
                },
                onError: (error) => toast(errMsg(error), "err"),
              })
            }
            disabled={!remoteUrl.trim() || connectRemote.isPending}
          >
            <Text id="settings.sync.connect-remote">Connect Catalog Git Remote</Text>
          </Button>
        </div>
      ) : null}
      <div className="mt-3.5 flex items-center gap-3">
        <Button
          variant="accent"
          onClick={onSync}
          disabled={sync.isPending}
          data-dev-id="settings.sync-action"
        >
          {sync.isPending ? (
            <Text id="settings.sync.action-busy">Sharing...</Text>
          ) : (
            <Text id="settings.sync.action">Pull And Push Catalog</Text>
          )}
        </Button>
        {sync.data ? (
          <span className="text-xs text-t3">Last sync: {sync.data.detail || sync.data.state}</span>
        ) : null}
      </div>
    </>
  );
}

function KiCadSection() {
  const sys = useSystemInfo();
  const settings = useSettings();
  const save = useUpdateSettings();
  const { toast } = useToast();
  // The manual re-wire job (moved here from the Doctor page in D3): wiring runs
  // automatically on launch and profile switch, and this button re-runs it on demand.
  const wireJob = useJob<WiringReport>();
  const [wiring, setWiring] = useState(false);
  const configPlaceholder = useText("settings.kicad.config-placeholder", "Auto-detected");
  const cliPlaceholder = useText("settings.kicad.cli-placeholder", "Auto-discovered");
  const toastAppliedWired = useText(
    "settings.kicad.toast-applied-wired",
    "KiCad settings applied. The components are wired.",
  );
  const toastApplied = useText("settings.kicad.toast-applied", "KiCad settings applied.");
  // The job carries its own failure detail when it has one; this is the sentence for when it does not.
  const wireFailed = useText("settings.kicad.wire-failed", "Wiring failed.");

  async function onWire() {
    setWiring(true);
    try {
      const { job_id } = await api.wireKicad();
      wireJob.run(job_id);
    } catch (e) {
      toast(errMsg(e), "err");
    } finally {
      setWiring(false);
    }
  }

  const wireBusy = wiring || wireJob.status === "running";
  const wireReport = wireJob.status === "done" ? wireJob.result : null;
  // null = untouched (show the saved value), so the inputs stay prefilled from
  // the server without an effect and a save simply reseeds them
  const [cfgDraft, setCfgDraft] = useState<string | null>(null);
  const [cliDraft, setCliDraft] = useState<string | null>(null);

  const cfgSaved = settings.data?.kicad_config_override ?? "";
  const cliSaved = settings.data?.kicad_cli_override ?? "";
  const cfgValue = cfgDraft ?? cfgSaved;
  const cliValue = cliDraft ?? cliSaved;
  const dirty = cfgValue.trim() !== cfgSaved || cliValue.trim() !== cliSaved;
  const scenarioPicker = useScenarioUiState().settings?.picker === "kicad";

  async function chooseConfigFolder() {
    try {
      const folder = await pickHostFolder("kicad-config");
      if (folder) setCfgDraft(folder);
    } catch (error) {
      toast(errMsg(error), "err");
    }
  }

  function onSave() {
    if (!dirty || save.isPending) return;
    save.mutate(
      {
        kicad_config_override: cfgValue.trim(),
        kicad_cli_override: cliValue.trim(),
      },
      {
        onSuccess: (r) => {
          setCfgDraft(null);
          setCliDraft(null);
          toast(r.kicad_wired ? toastAppliedWired : toastApplied, "ok");
        },
        onError: (e) => toast(errMsg(e), "err"),
      },
    );
  }

  return (
    <>
      {sys.isLoading ? (
        <LoadingState dense id="settings.kicad-loading">
          Reading how KiCad is set up on this machine...
        </LoadingState>
      ) : sys.isError ? (
        <ErrorState dense id="settings.kicad-failed" onRetry={() => sys.refetch()}>
          The KiCad setup on this machine could not be read.
        </ErrorState>
      ) : sys.data ? (
        <>
          <StatusRow
            label="Config Folder"
            labelId="settings.kicad.config-dir"
            value={sys.data.kicad_config_dir}
          />
          <StatusRow
            label="KiCad CLI"
            labelId="settings.kicad.cli"
            value={
              sys.data.kicad_cli_available ? (
                sys.data.kicad_cli_path
              ) : (
                <span className="text-warn">
                  <Text id="settings.kicad.cli-missing">Not found (previews unavailable)</Text>
                </span>
              )
            }
          />
          <StatusRow
            label="KiCad Running"
            labelId="settings.kicad.running"
            value={sys.data.kicad_running ? "Yes" : "No"}
          />
          <StatusRow
            label="KiCad Wiring"
            labelId="settings.kicad.wiring"
            value={
              settings.isLoading ? (
                "Loading..."
              ) : settings.data?.kicad_wired ? (
                <span className="text-ok-text">
                  <Text id="settings.kicad.wired">Wired to the active catalog</Text>
                </span>
              ) : (
                <span className="text-warn">
                  <Text id="settings.kicad.unwired">
                    Not wired so far (use Recheck And Wire KiCad below)
                  </Text>
                </span>
              )
            }
          />
        </>
      ) : null}

      {sys.data ? (
        <div className="mt-3.5 flex flex-col gap-3">
          <div>
            <Button onClick={onWire} disabled={wireBusy} data-dev-id="settings.kicad-wire">
              {wireBusy ? (
                <Text id="settings.kicad.wire-busy">Wiring...</Text>
              ) : (
                <Text id="settings.kicad.wire">Recheck And Wire KiCad</Text>
              )}
            </Button>
          </div>
          {wireJob.status === "running" && wireJob.progress?.message ? (
            <p className="text-xs text-t3">{wireJob.progress.message}...</p>
          ) : null}
          {wireJob.status === "error" ? (
            <p className="text-sm text-err-text">{wireJob.error ?? wireFailed}</p>
          ) : null}
          {wireReport ? (
            <div className="flex flex-col gap-1.5 rounded-control border border-line bg-raise2 p-3 text-xs">
              <div className="text-t2">
                Registered {wireReport.categories_registered.length}{" "}
                {wireReport.categories_registered.length === 1 ? "category" : "categories"}: added{" "}
                {wireReport.symbol_rows_added} symbol and {wireReport.footprint_rows_added}{" "}
                footprint {wireReport.footprint_rows_added === 1 ? "row" : "rows"}.
              </div>
              {wireReport.restart_needed ? (
                <div className="flex items-center gap-2 text-warn">
                  <Dot tone="warn" />
                  <span>
                    <Text id="settings.kicad.restart-needed">
                      Restart KiCad to load the updated tables.
                    </Text>
                  </span>
                </div>
              ) : (
                <div className="flex items-center gap-2 text-ok-text">
                  <Dot tone="ok" />
                  <span>
                    <Text id="settings.kicad.wired-set">KiCad is wired and set.</Text>
                  </span>
                </div>
              )}
            </div>
          ) : null}
        </div>
      ) : null}

      <div
        className="mt-3.5 flex flex-col gap-2.5"
        data-dev-id="settings.kicad-overrides"
        data-scenario-picker={scenarioPicker ? "kicad" : undefined}
      >
        <div className="flex flex-wrap items-center gap-2.5">
          <label htmlFor="kicad-config-override" className="w-52 flex-none text-xs text-t3">
            <Text id="settings.kicad.config-label">Config Folder Override</Text>
          </label>
          <input
            id="kicad-config-override"
            value={cfgValue}
            onChange={(e) => setCfgDraft(e.target.value)}
            placeholder={configPlaceholder}
            className={INPUT_CLS}
          />
          <Button onClick={chooseConfigFolder}>
            <Text id="settings.kicad.choose-config">Choose Folder</Text>
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <label htmlFor="kicad-cli-override" className="w-52 flex-none text-xs text-t3">
            <Text id="settings.kicad.cli-label">KiCad CLI Override</Text>
          </label>
          <input
            id="kicad-cli-override"
            value={cliValue}
            onChange={(e) => setCliDraft(e.target.value)}
            placeholder={cliPlaceholder}
            className={INPUT_CLS}
          />
        </div>
        <div>
          <Button onClick={onSave} disabled={!dirty || save.isPending}>
            {save.isPending ? (
              <Text id="settings.kicad.save-overrides-busy">Committing...</Text>
            ) : (
              <Text id="settings.kicad.save-overrides">Save Paths And Rewire</Text>
            )}
          </Button>
        </div>
      </div>
    </>
  );
}

function CubeMxSection() {
  const settings = useSettings();
  const save = useUpdateSettings();
  const { toast } = useToast();
  const [draft, setDraft] = useState<string | null>(null);
  const saved = settings.data?.stm_cubemx_source ?? "";
  const value = draft ?? saved;
  const dirty = value.trim() !== saved;
  const scenarioPicker = useScenarioUiState().settings?.picker === "cubemx";
  const folderPlaceholder = useText(
    "settings.cubemx.folder-placeholder",
    "Choose the CubeMX data folder",
  );
  const toastSaved = useText("settings.cubemx.toast-saved", "CubeMX data folder saved.");
  const toastNotSaved = useText(
    "settings.cubemx.toast-not-saved",
    "CubeMX data folder was not saved.",
  );

  async function chooseFolder() {
    try {
      const folder = await pickHostFolder("stm-cubemx");
      if (!folder) return;
      const result = await save.mutateAsync({ stm_cubemx_source: folder });
      setDraft(null);
      toast(
        result.stm_cubemx_source ? toastSaved : toastNotSaved,
        result.stm_cubemx_source ? "ok" : "err",
      );
    } catch (error) {
      toast(errMsg(error), "err");
    }
  }

  function saveDraft() {
    if (!dirty || save.isPending) return;
    save.mutate(
      { stm_cubemx_source: value.trim() },
      {
        onSuccess: () => {
          setDraft(null);
          toast(toastSaved, "ok");
        },
        onError: (error) => toast(errMsg(error), "err"),
      },
    );
  }

  return (
    <div className="flex flex-col gap-3" data-scenario-picker={scenarioPicker ? "cubemx" : undefined}>
      <p className="text-sm text-t2">
        <Text id="settings.cubemx.lede">
          Stockroom uses the STM32CubeMX MCU data as the native source for its spec matrix, pinouts, and compatibility tools.
        </Text>
      </p>
      <div className="flex flex-wrap items-center gap-2.5">
        <label htmlFor="stm-cubemx-source" className="w-40 flex-none text-xs text-t3">
          <Text id="settings.cubemx.folder-label">CubeMX Data Folder</Text>
        </label>
        <input
          id="stm-cubemx-source"
          value={value}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={folderPlaceholder}
          className={INPUT_CLS}
        />
        <Button onClick={chooseFolder} disabled={save.isPending}>
          <Text id="settings.cubemx.choose">Choose Folder</Text>
        </Button>
      </div>
      {dirty ? (
        <div>
          <Button onClick={saveDraft} disabled={save.isPending}>
            {save.isPending ? (
              <Text id="settings.cubemx.saving">Saving...</Text>
            ) : (
              <Text id="settings.cubemx.save">Save Folder</Text>
            )}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function DistributorSection() {
  const credentialsRefresh = useScenarioUiState().settings?.credentialsRefresh === true;
  const settings = useSettings();
  const save = useUpdateSettings();
  const { toast } = useToast();
  const [keyInput, setKeyInput] = useState("");
  const isSet = settings.data?.mouser_api_key_set ?? false;
  const keyPlaceholderNew = useText("settings.distributor.key-placeholder", "Paste a credential");
  const keyPlaceholderReplace = useText(
    "settings.distributor.key-placeholder-replace",
    "Paste a new credential to replace it",
  );
  const toastSaved = useText("settings.distributor.toast-saved", "Mouser credential saved.");
  const toastCleared = useText("settings.distributor.toast-cleared", "Mouser credential cleared.");
  // `VendorLogin` renders these as plain strings, so they are resolved here and handed down.
  const digikeyTitle = useText("settings.distributor.digikey-title", "DigiKey API Credentials");
  const digikeySaveLabel = useText(
    "settings.distributor.digikey-save",
    "Save DigiKey API Credentials",
  );
  const digikeySaved = useText(
    "settings.distributor.digikey-toast-saved",
    "DigiKey API credentials saved.",
  );

  function onSave() {
    const key = keyInput.trim();
    // guard the Enter path too (the button is disabled while pending, the input
    // is not), so a double-Enter cannot fire a duplicate save.
    if (!key || save.isPending) return;
    save.mutate(
      { mouser_api_key: key },
      {
        onSuccess: () => {
          setKeyInput("");
          toast(toastSaved, "ok");
        },
        onError: (e) => toast(errMsg(e), "err"),
      },
    );
  }

  function onClear() {
    save.mutate(
      { mouser_api_key: "" },
      {
        onSuccess: () => {
          setKeyInput("");
          toast(toastCleared, "ok");
        },
        onError: (e) => toast(errMsg(e), "err"),
      },
    );
  }

  return (
    <>
      <StatusRow
        label="Mouser API Credential"
        labelId="settings.distributor.key-label"
        value={
          settings.isLoading
            ? "Loading..."
            : isSet
              ? `Set (ending ${settings.data?.mouser_api_key_hint})`
              : "Not set"
        }
      />
      <div
        className="mt-3.5 flex flex-wrap items-center gap-2.5"
        data-dev-id="settings.distributor-key"
      >
        {credentialsRefresh ? (
          <p className="w-full text-xs text-warn">
            <Text id="settings.distributor.refresh-note">Replace the saved credentials, then validate source access.</Text>
          </p>
        ) : null}
        <label htmlFor="mouser-key" className="sr-only">
          <Text id="settings.distributor.key-field-label">Mouser API Credential</Text>
        </label>
        <input
          id="mouser-key"
          type="password"
          autoComplete="off"
          value={keyInput}
          onChange={(e) => setKeyInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onSave();
          }}
          placeholder={isSet ? keyPlaceholderReplace : keyPlaceholderNew}
          className={INPUT_CLS}
        />
        <Button onClick={onSave} disabled={!keyInput.trim() || save.isPending}>
          <Text id="settings.distributor.save-key">Save Mouser Credential</Text>
        </Button>
        {isSet ? (
          <Button variant="danger" onClick={onClear} disabled={save.isPending}>
            <Text id="settings.distributor.clear">Remove Mouser Credential</Text>
          </Button>
        ) : null}
      </div>
      <VendorLogin
        title={digikeyTitle}
        identifierLabel="DigiKey API Client ID"
        secretLabel="DigiKey API Client Secret"
        saveLabel={digikeySaveLabel}
        savedIdentifier={settings.data?.digikey_client_id ?? ""}
        secretSet={settings.data?.digikey_client_secret_set ?? false}
        secretHint={settings.data?.digikey_client_secret_hint ?? ""}
        pending={save.isPending}
        onSave={(clientId, secret) => {
          const patch: SettingsPatch = { digikey_client_id: clientId };
          if (secret) patch.digikey_client_secret = secret;
          save.mutate(patch, {
            onSuccess: () => toast(digikeySaved, "ok"),
            onError: (e) => toast(errMsg(e), "err"),
          });
        }}
      />
    </>
  );
}

// One saved credential pair: a non-secret identifier (the DigiKey API client_id) that is
// echoed, plus a masked secret that only ever shows a last-4 hint. These are catalogue API
// credentials Stockroom calls directly. No provider-WEBSITE login is stored anywhere: a person
// signs in to a provider page themselves, in the window Stockroom opens. The two field labels
// stay configurable so the row can carry either an id/secret or a name/value pair.
function VendorLogin({
  title,
  identifierLabel,
  secretLabel,
  saveLabel,
  identifierPlaceholder,
  savedIdentifier,
  secretSet,
  secretHint,
  pending,
  onSave,
}: {
  title: string;
  identifierLabel: string;
  secretLabel: string;
  saveLabel: string;
  identifierPlaceholder?: string;
  savedIdentifier: string;
  secretSet: boolean;
  secretHint: string;
  pending: boolean;
  onSave: (identifier: string, secret: string) => void;
}) {
  const [identifier, setIdentifier] = useState(savedIdentifier);
  const [secret, setSecret] = useState("");
  const [edited, setEdited] = useState(false);
  // The hint in the hole is the secret's last characters, which is a value; the sentence is ours.
  const secretSaved = useCopyFormatter(
    "settings.vendor-login.secret-saved",
    "Saved (ending {hint})",
  );
  const secretUnsaved = useText("settings.vendor-login.secret-unsaved", "Not saved");
  // The in-field hint of a credential that is already stored: the field is blank on purpose, so the
  // hint is what says the stored value is intact and what typing here would do to it.
  const replaceHint = useText(
    "settings.vendor-login.secret-replace",
    "Paste a new value to replace it",
  );
  // Prefill the saved identifier once it arrives, unless the user has started editing.
  useEffect(() => {
    if (!edited) setIdentifier(savedIdentifier);
  }, [savedIdentifier, edited]);
  const slug = identifierLabel.toLowerCase().replace(/\s+/g, "-");
  return (
    <div
      className="border-b border-line py-3 last:border-b-0"
      data-dev-id="settings.vendor-login-row"
    >
      <div className="mb-2 flex items-center justify-between gap-4">
        <span className="text-sm font-medium text-t1">{title}</span>
        <span className="flex-none text-xs text-t3">
          {secretSet ? secretSaved({ hint: secretHint }) : secretUnsaved}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2.5">
        <label htmlFor={`${slug}-id`} className="sr-only">
          {identifierLabel}
        </label>
        <input
          id={`${slug}-id`}
          type="text"
          autoComplete="off"
          aria-label={identifierLabel}
          value={identifier}
          onChange={(e) => {
            setEdited(true);
            setIdentifier(e.target.value);
          }}
          placeholder={identifierPlaceholder ?? identifierLabel}
          className={INPUT_CLS}
        />
        <label htmlFor={`${slug}-secret`} className="sr-only">
          {secretLabel}
        </label>
        <input
          id={`${slug}-secret`}
          type="password"
          autoComplete="off"
          aria-label={secretLabel}
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          placeholder={secretSet ? replaceHint : secretLabel}
          className={INPUT_CLS}
        />
        <Button
          className="min-w-[196px] justify-center"
          onClick={() => onSave(identifier.trim(), secret)}
          disabled={pending || (!identifier.trim() && !secret)}
        >
          {saveLabel}
        </Button>
      </div>
    </div>
  );
}

// GitHub authentication belongs to the current Windows user, not to Stockroom configuration.
// Git Credential Manager owns OAuth/device sign-in and credential storage. Repository access on
// GitHub remains the only collaboration authority; no PAT crosses the Stockroom API.
function GitHubSection() {
  const status = useSyncStatus();
  const loginJob = useJob<{ mode: string; accounts: string[] }>();
  const { toast } = useToast();
  const toastConnected = useText(
    "settings.github.toast-connected",
    "GitHub sign-in complete. Git remote permissions now control catalog sharing.",
  );
  const accounts = status.data?.github_auth.accounts ?? [];
  const pending = loginJob.status === "running";

  async function onSignIn() {
    if (pending) return;
    try {
      const ref = await api.startGitHubLogin();
      const final = await loginJob.run(ref.job_id);
      if (final.status !== "done") {
        throw new Error(final.error ?? "GitHub sign-in did not complete.");
      }
      await status.refetch();
      toast(toastConnected, "ok");
    } catch (error) {
      toast(error instanceof Error ? error.message : errMsg(error), "err");
    }
  }

  return (
    <>
      <StatusRow
        label="Connection"
        labelId="settings.github.connection"
        value={
          status.isLoading ? (
            <Text id="settings.github.connection-loading">Loading...</Text>
          ) : accounts.length ? (
            accounts.join(", ")
          ) : (
            <Text id="settings.github.connection-none">Not connected</Text>
          )
        }
      />
      <div
        className="mt-3.5 flex flex-wrap items-center gap-2.5"
        data-dev-id="settings.github-token"
      >
        <Button onClick={() => void onSignIn()} disabled={pending}>
          {pending ? (
            <Text id="settings.github.connect-waiting">Waiting For GitHub</Text>
          ) : (
            <Text id="settings.github.connect">Sign In With GitHub</Text>
          )}
        </Button>
        <p className="text-xs text-t3">
          <Text id="settings.github.no-secrets">Stockroom never receives or stores a GitHub password or personal access token.</Text>
        </p>
      </div>
    </>
  );
}

function UpdateSection() {
  const { query: check, view: standing } = useUpdateStanding();
  const targetRevision = updateTargetRevision(check.data);
  const branchUnknown = useText("settings.update.branch-unknown", "Unknown");
  const revisionMissing = useText("settings.update.revision-unavailable", "Unavailable");

  return (
    <>
      {check.isLoading ? (
        <LoadingState dense id="settings.update-loading">
          Checking for a newer Stockroom...
        </LoadingState>
      ) : check.isError ? (
        <ErrorState dense id="settings.update-failed" onRetry={() => check.refetch()}>
          Stockroom could not check for a newer version.
        </ErrorState>
      ) : (
        <>
          <StatusRow
            label="Updates"
            labelId="settings.update.delivery"
            value={
              check.data?.automatic_apply ? (
                <Text id="settings.update.delivery-open">Automatic while Stockroom is open</Text>
              ) : check.data?.automatic_on_launch ? (
                <Text id="settings.update.delivery-launch">Automatic when Stockroom opens</Text>
              ) : (
                <Text id="settings.update.delivery-unmanaged">Unmanaged</Text>
              )
            }
          />
          <StatusRow
            label="Application Branch"
            labelId="settings.update.branch"
            value={<span className="font-mono">{check.data?.channel || branchUnknown}</span>}
          />
          <StatusRow
            label="Installed Revision"
            labelId="settings.update.installed"
            value={
              <span className="font-mono">{check.data?.current_revision || revisionMissing}</span>
            }
          />
          {targetRevision ? (
            <StatusRow
              label="Latest Remote Revision"
              labelId="settings.update.latest"
              value={<span className="font-mono">{targetRevision}</span>}
            />
          ) : null}
          <StatusRow
            label="Update Status"
            labelId="settings.update.status"
            value={
              standing.standing === "checking" ? (
                <span className="text-t3">
                  <Text id="settings.update.status-checking">
                    Checking the application remote...
                  </Text>
                </span>
              ) : standing.standing === "current" ? (
                <span className="text-ok-text">
                  <Text id="settings.update.status-current">Current</Text>
                </span>
              ) : standing.standing === "available" ? (
                <span className="text-warn">
                  {check.data?.behind ? (
                    <Text
                      id="settings.update.status-behind"
                      values={{ count: check.data.behind, revision: shortRevision(targetRevision) }}
                    >
                      {"{count} commits available to install at {revision}"}
                    </Text>
                  ) : targetRevision ? (
                    <Text
                      id="settings.update.status-revision-ready"
                      values={{ revision: shortRevision(targetRevision) }}
                    >
                      {"Revision {revision} is available to install"}
                    </Text>
                  ) : (
                    <Text id="settings.update.status-ready">Update available to install</Text>
                  )}
                </span>
              ) : standing.standing === "updating" ? (
                <span className="text-acc">
                  <Text id="settings.update.status-updating">Automatic adoption of the validated release...</Text>
                </span>
              ) : standing.standing === "retrying" ? (
                <span className="text-warn">
                  <Text id="settings.update.status-retrying">Remote check incomplete; automatic reruns continue...</Text>
                </span>
              ) : standing.standing === "blocked" ? (
                <span className="text-err-text">
                  <Text id="settings.update.status-blocked">
                    Automatic convergence needs attention
                  </Text>
                </span>
              ) : standing.standing === "restart_required" ? (
                <span className="text-warn">
                  <Text id="settings.update.status-restart">
                    Restart Stockroom to finish adopting the installed revision
                  </Text>
                </span>
              ) : (
                <span className="text-warn">
                  {check.data?.state === "offline" ? (
                    <Text id="settings.update.status-offline">
                      Latest revision unknown while offline
                    </Text>
                  ) : check.data?.state === "no_remote" ? (
                    <Text id="settings.update.status-no-remote">
                      Application remote is not configured
                    </Text>
                  ) : check.data?.state === "diverged" ? (
                    <Text id="settings.update.status-diverged">
                      Local and remote histories diverged
                    </Text>
                  ) : check.data?.state === "up_to_date" &&
                    check.data?.current_revision &&
                    targetRevision ? (
                    <Text id="settings.update.status-mismatch">
                      Installed and latest remote revisions do not match
                    </Text>
                  ) : (
                    <Text id="settings.update.status-unverified">
                      Latest remote revision could not be validated
                    </Text>
                  )}
                </span>
              )
            }
          />
          {["retrying", "blocked", "restart_required", "unknown"].includes(standing.standing) &&
          standing.detail ? (
            <StatusRow
              label="Check Detail"
              labelId="settings.update.detail"
              value={standing.detail}
            />
          ) : null}
        </>
      )}
      <p className="mt-3 text-xs leading-relaxed text-t3">
        <Text id="settings.update.lede">Each installation follows the same validated remote revision on its own. New releases are staged beside the running app, health-checked, and adopted without closing this window; a failed release rolls back to the last sound backend.</Text>
      </p>
      <div className="mt-3.5 flex flex-wrap items-center gap-2">
        <a
          href="https://github.com/sadadsh/stockroom/releases"
          target="_blank"
          rel="noreferrer"
          className="inline-flex h-[27px] items-center rounded-control px-2 text-xs font-medium text-t2 underline decoration-line2 underline-offset-2 hover:text-t1"
        >
          <Text id="settings.update.download">Download Stockroom.exe</Text>
        </a>
      </div>
    </>
  );
}

// The General group's disclosures. Each group panel resolves its own cached queries (the same keys
// the page header already reads, so no extra request) and computes its own collapsed-row summaries,
// which keeps SettingsPage itself the page frame rather than the sum of all five panels.
function GeneralGroup() {
  const { theme } = useTheme();
  const { view: updateStanding } = useUpdateStanding();
  return (
    <>
        <SettingsDisclosure
          title="Appearance"
          titleId="settings.appearance.title"
          hint="Choose how Stockroom renders on this machine. The choice is saved at once."
          hintId="settings.appearance.hint"
          summary={
            theme === "light" ? (
              <Text id="settings.summary.light">Light</Text>
            ) : (
              <Text id="settings.summary.dark">Dark</Text>
            )
          }
          className="@3xl:col-span-2"
          data-dev-id="settings.appearance"
        >
          <AppearanceSection />
        </SettingsDisclosure>
        <SettingsDisclosure
          title="Automatic Updates"
          titleId="settings.update.title"
          hint="Stockroom checks its validated application branch at two-minute intervals and adopts a sound update on its own, without closing this window."
          hintId="settings.update.hint"
          summary={
            updateStanding.standing === "available" ? (
              <Badge tone="warn">
                <Text id="settings.summary.update-available">Update Available</Text>
              </Badge>
            ) : updateStanding.standing === "current" ? (
              <Text id="settings.summary.up-to-date-app">Current</Text>
            ) : updateStanding.standing === "updating" ? (
              <Text id="settings.summary.update-updating">Updating...</Text>
            ) : updateStanding.standing === "checking" ? (
              <Text id="settings.summary.update-checking">Checking...</Text>
            ) : updateStanding.standing === "retrying" ? (
              <Text id="settings.summary.update-retrying">Rerunning...</Text>
            ) : updateStanding.standing === "blocked" ? (
              <Text id="settings.summary.update-blocked">Update Blocked</Text>
            ) : updateStanding.standing === "restart_required" ? (
              <Badge tone="warn">
                <Text id="settings.summary.update-restart">Restart Required</Text>
              </Badge>
            ) : (
              <Text id="settings.summary.update-unknown">Update Unknown</Text>
            )
          }
          className="@3xl:col-span-2"
          data-dev-id="settings.update"
        >
          <UpdateSection />
        </SettingsDisclosure>
    </>
  );
}


function LibraryGroup() {
  const settingsQ = useSettings();
  const syncQ = useSyncStatus();
  const librariesQ = useOnboarding();
  const s = settingsQ.data;
  const sync = syncQ.data;
  const githubAccounts = sync?.github_auth.accounts ?? [];
  // A legacy app-owned token may still exist on an upgraded machine. It remains a temporary
  // compatibility signal, but the UI creates no new tokens and GCM is the durable authority.
  const githubConnected = githubAccounts.length > 0 || Boolean(s?.github_token_set);
  const syncSummary = !sync ? null : !sync.has_remote ? (
    <Text id="settings.summary.no-remote">No Remote</Text>
  ) : sync.behind > 0 ? (
    <Badge tone="warn">{`Behind ${sync.behind}`}</Badge>
  ) : sync.ahead > 0 ? (
    <Badge tone="neutral">{`Ahead ${sync.ahead}`}</Badge>
  ) : (
    <Text id="settings.summary.up-to-date">Up To Date</Text>
  );
  return (
    <>
        <SettingsDisclosure
          title="Catalog Checkouts"
          titleId="settings.profiles.title"
          hint="Each catalog is a separate Git checkout. Switching catalogs never changes Stockroom's application checkout."
          hintId="settings.profiles.hint"
          summary={
            librariesQ.data ? (
              <span>
                {librariesQ.data.libraries.find((library) => library.active)?.name ?? (
                  <Text id="settings.profiles.summary-fallback">Active Catalog</Text>
                )}
              </span>
            ) : null
          }
          data-dev-id="settings.profiles"
        >
          <LibraryRepositoriesSection />
        </SettingsDisclosure>
        <SettingsDisclosure
          title="Share Catalog Changes"
          titleId="settings.sync.title"
          hint="Pull collaborators' component changes and push local ones. This affects catalog data, not the Stockroom application."
          hintId="settings.sync.hint"
          summary={syncSummary}
          data-dev-id="settings.sync"
        >
          <SyncSection />
        </SettingsDisclosure>
        <SettingsDisclosure
          title="GitHub Access"
          titleId="settings.github.title"
          hint="Sign in with the Windows user's GitHub account. Git Credential Manager stores access outside Stockroom and GitHub remote permissions control collaboration."
          hintId="settings.github.hint"
          summary={
            s ? (
              githubConnected ? (
                <Text id="settings.summary.github-connected">Connected</Text>
              ) : (
                <Badge tone="neutral">
                  <Text id="settings.summary.github-off">Not Connected</Text>
                </Badge>
              )
            ) : null
          }
          className="@3xl:col-span-2"
          data-dev-id="settings.github"
        >
          <GitHubSection />
        </SettingsDisclosure>
    </>
  );
}


function EdaGroup() {
  const settingsQ = useSettings();
  const odbc = useOdbcStatus();
  const s = settingsQ.data;
  const odbcInstalled = odbc.data?.installed;
  return (
    <>
        <SettingsDisclosure
          title="KiCad Integration"
          titleId="settings.kicad.title"
          hint="Stockroom wires the active catalog checkout into KiCad on its own. Manual paths are advanced repair controls."
          hintId="settings.kicad.hint"
          summary={
            s ? (
              s.kicad_wired ? (
                <Text id="settings.summary.kicad-wired">Prepared</Text>
              ) : (
                <Badge tone="warn">
                  <Text id="settings.summary.kicad-unwired">Needs Attention</Text>
                </Badge>
              )
            ) : null
          }
          data-dev-id="settings.kicad"
        >
          <KiCadSection />
        </SettingsDisclosure>
        <SettingsDisclosure
          title="Altium Integration"
          titleId="settings.altium.title"
          hint="The database catalog follows the active catalog checkout. The SQLite ODBC driver is the one machine-level prerequisite."
          hintId="settings.altium.hint"
          summary={
            odbcInstalled === true ? (
              <Text id="settings.summary.odbc-ok">Prepared</Text>
            ) : odbcInstalled === false ? (
              <Badge tone="warn">
                <Text id="settings.summary.odbc-missing">Driver Missing</Text>
              </Badge>
            ) : null
          }
          data-dev-id="settings.altium"
        >
          <AltiumDbLibSection />
        </SettingsDisclosure>
        <SettingsDisclosure
          title="STM32CubeMX Data"
          titleId="settings.cubemx.title"
          hint="Choose the local CubeMX data folder once. Stockroom remembers it and builds the searchable MCU index on demand."
          hintId="settings.cubemx.hint"
          summary={
            s?.stm_cubemx_source ? (
              <Text id="settings.summary.cubemx-ready">Configured</Text>
            ) : (
              <Badge tone="neutral">
                <Text id="settings.summary.cubemx-optional">Optional</Text>
              </Badge>
            )
          }
          className="@3xl:col-span-2"
          data-dev-id="settings.cubemx"
        >
          <CubeMxSection />
        </SettingsDisclosure>
    </>
  );
}


function SourcesGroup() {
  const s = useSettings().data;
  // Procurement Rescan: when prices and stock were last refreshed. Through the same shared
  // `lastChecked`, so the collapsed row and the open body can never disagree about the date.
  const rescanState = useRescanState().data;
  const rescanSummary = !rescanState
    ? null
    : (() => {
        const { checkedAt, total } = lastChecked(rescanState);
        if (total === 0) return <Text id="settings.summary.never-rescanned">Never Run</Text>;
        return checkedAt ? (
          <span>
            {new Date(checkedAt).toLocaleDateString(undefined, {
              year: "numeric",
              month: "short",
              day: "numeric",
            })}
          </span>
        ) : (
          <span>{`${total} Checked`}</span>
        );
      })();
  return (
    <>
        <SettingsDisclosure
          title="Distributor APIs"
          titleId="settings.distributor.title"
          hint="Optional API credentials improve exact part lookup. Stockroom still works without them."
          hintId="settings.distributor.hint"
          summary={
            s ? (
              s.mouser_api_key_set || s.digikey_client_secret_set ? (
                <Text id="settings.summary.key-set">Configured</Text>
              ) : (
                <Badge tone="neutral">
                  <Text id="settings.summary.key-off">Optional</Text>
                </Badge>
              )
            ) : null
          }
          data-dev-id="settings.distributor"
        >
          <DistributorSection />
        </SettingsDisclosure>
        <SettingsDisclosure
          title="Refresh Procurement Data"
          titleId="settings.rescan.title"
          hint="Update price, stock, and life-stage data. Recent parts are skipped unless a full refresh is requested."
          hintId="settings.rescan.hint"
          summary={rescanSummary}
          data-dev-id="settings.rescan"
        >
          <RescanSection />
        </SettingsDisclosure>
    </>
  );
}


function MaintenanceGroup() {
  const coverageQ = useLibraryCoverage();
  const derivationQ = useLibraryDerivation();
  const cadQ = useCadInventory();
  const doctorQ = useDoctorScan();
  const lfsQ = useLibraryLfs();
  // Library Completion: the count IS the answer to the owner's central question, so it is shown
  // whatever the state; the tone is what changes. A gap some source can fill is warn, a library
  // with nothing outstanding is calm text.
  const cov = coverageQ.data;
  const completionSummary = !cov ? null : cov.complete >= cov.total ? (
    <Text id="settings.summary.all-complete">All Complete</Text>
  ) : (
    <Badge tone="warn">{`${cov.complete} of ${cov.total} Complete`}</Badge>
  );
  // Presentation Data: which ruleset built what is on screen, and whether anything is behind it.
  // A stale count is the actionable half, so it wins the row when there is one.
  const der = derivationQ.data;
  const derivationSummary = !der ? null : der.stale > 0 ? (
    <Badge tone="warn">{`${der.stale} Stale`}</Badge>
  ) : (
    <span>{der.ruleset}</span>
  );
  // Clear CAD Files: how much a clear would actually remove. `None` is a real, useful state - it
  // says the destructive action would do nothing, which is worth knowing before opening it.
  const cad = cadQ.data;
  const cadSummary = !cad ? null : cad.cleared > 0 ? (
    <span>{`${cad.cleared} ${cad.cleared === 1 ? "File" : "Files"}`}</span>
  ) : (
    <Text id="settings.summary.no-cad">None</Text>
  );
  // Library Health: how much needs a hand. Everything the scan reports is work, so they add up
  // into one number rather than three the row has no space to distinguish.
  const doc = doctorQ.data;
  const healthSummary = !doc
    ? null
    : (() => {
        const outstanding = doc.fixable.length + doc.manual.length + doc.uncommitted.length;
        return outstanding > 0 ? (
          <Badge tone="warn">{`${outstanding} To Fix`}</Badge>
        ) : (
          <Text id="settings.summary.healthy">Sound</Text>
        );
      })();
  // Library Sync: what this library carries to whoever clones it. LFS being OFF is the state that
  // decides everything else in the section, so it wins; a legacy blob is the one warning that
  // cannot be fixed from here (it needs a history rewrite this project forbids).
  const lfs = lfsQ.data;
  const librarySyncSummary = !lfs ? null : !lfs.installed || !lfs.enabled ? (
    <Text id="settings.summary.no-lfs">Not Using LFS</Text>
  ) : lfs.legacy_blobs > 0 ? (
    <Badge tone="warn">{`${lfs.legacy_blobs} Legacy`}</Badge>
  ) : // "0 In LFS" reads as a quantity when the thing being said is a STATE: LFS is wired and
  // holds nothing yet. Seen rendering exactly that against the real library, 2026-07-27.
  // Its siblings say "None" and "Healthy"; a zero dressed as a count is data vomit.
  lfs.objects === 0 ? (
    <Text id="settings.summary.lfs-empty">Nothing In LFS</Text>
  ) : (
    <span>{`${lfs.objects} In LFS`}</span>
  );

  return (
    <>
        <SettingsDisclosure
          title="Component Completeness"
          titleId="settings.completion.title"
          hint="Find parts missing a required schematic, footprint, or 3D representation and fill supported gaps."
          hintId="settings.completion.hint"
          summary={completionSummary}
          data-dev-id="settings.completion"
        >
          <LibraryCompletionSection />
        </SettingsDisclosure>
        <SettingsDisclosure
          title="Rebuild Presentation Data"
          titleId="settings.derivation.title"
          hint="Recompute shown names, descriptions, classes, and specifications from stored evidence. No network access is used."
          hintId="settings.derivation.hint"
          summary={derivationSummary}
          data-dev-id="settings.derivation"
        >
          <DerivationSection />
        </SettingsDisclosure>
        <SettingsDisclosure
          title="Repair Catalog"
          titleId="settings.health.title"
          hint="Check records, files, and Git state. Safe repairs are listed before the run; missing source files are never invented."
          hintId="settings.health.hint"
          summary={healthSummary}
          data-dev-id="settings.health"
        >
          <LibraryHealthSection />
        </SettingsDisclosure>
        <SettingsDisclosure
          title="Large File Storage"
          titleId="settings.librarysync.title"
          hint="Control which large CAD files travel through Git LFS and which machine-generated files remain local."
          hintId="settings.librarysync.hint"
          summary={librarySyncSummary}
          data-dev-id="settings.librarysync"
        >
          <LibrarySyncSection />
        </SettingsDisclosure>
        <SettingsDisclosure
          title="Reset Captured CAD"
          titleId="settings.cad-clear.title"
          hint="Destructive repair: remove captured schematic assets, footprints, and 3D models while preserving parts, specifications, datasheets, and source evidence."
          hintId="settings.cad-clear.hint"
          summary={cadSummary}
          className="@3xl:col-span-2 border-err/40"
          data-dev-id="settings.cad-clear"
        >
          <CadClearSection />
        </SettingsDisclosure>
    </>
  );
}
