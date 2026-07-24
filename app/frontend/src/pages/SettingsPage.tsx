/**
 * Settings (spec sections 5.3, 9, 11, 12): the per-machine controls that live
 * outside the library. Appearance (the theme toggle), library profiles (switch,
 * create, delete), library sync, the KiCad wiring status, the Mouser API key, and
 * the app self-update. Every section is honest about its state: offline/divergence
 * and a missing kicad-cli are surfaced verbatim, never faked green, and the Mouser
 * key is only ever shown as a last-4 hint.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError, api } from "../api/client";
import type { SettingsPatch, WiringReport } from "../api/types";
import { useJob } from "../lib/useJob";
import { AltiumDbLibSection } from "../components/AltiumDbLibSection";
import { SettingsDisclosure } from "../components/SettingsDisclosure";
import { LibraryHealthSection } from "../components/LibraryHealthSection";
import { RescanSection } from "../components/RescanSection";
import {
  useActivateProfile,
  useApplyUpdate,
  useCreateProfile,
  useDeleteProfile,
  useDoSync,
  useProfiles,
  useSettings,
  useSyncStatus,
  useSystemInfo,
  useUpdateCheck,
  useUpdateSettings,
  useLoadDevCreds,
  useOdbcStatus,
} from "../api/queries";
import { useTheme, type Theme } from "../lib/theme";
import { statusTone } from "../lib/statusTone";
import { useToast } from "../lib/toast";
import { Badge, Button, Card, Dot, Eyebrow, PanelTitle } from "../components/primitives";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Text, useText } from "../lib/copy";

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

// The five settings groups: what the machine runs (Application), the component
// library and its git remote (Library), each EDA's wiring (KiCad, Altium), and the
// distributor/sourcing credentials (Sourcing).
type GroupId = "application" | "library" | "kicad" | "altium" | "sourcing";

// One unmet setup step surfaced by the Machine Setup band; clicking it jumps to the
// owning group and opens the owning section.
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
  section: string;
}

export function SettingsPage() {
  // The page-level reads that feed the Machine Setup band, the nav dots, and the
  // collapsed-header summaries. Every one is a cached query a section also uses, so
  // this adds no extra request load.
  const settingsQ = useSettings();
  const odbc = useOdbcStatus();
  const syncQ = useSyncStatus();
  const updateQ = useUpdateCheck();
  const profilesQ = useProfiles();
  const { theme } = useTheme();

  const [group, setGroup] = useState<GroupId>("application");
  const [openSections, setOpenSections] = useState<Set<string>>(new Set());

  // Hidden dev combo (Ctrl+Alt+K): load API keys / logins from the per-machine
  // dev-creds.json so live validation is not blocked on retyping them. It lives at
  // the PAGE level deliberately - inside a section it dies whenever that section's
  // disclosure is collapsed (the grouped IA unmounts collapsed content), which
  // silently killed the hotkey (2026-07-24 report). A ref keeps the listener
  // subscribed once while always firing the latest handler.
  const loadDev = useLoadDevCreds();
  const { toast } = useToast();
  const fireDevLoad = useRef<() => void>(() => {});
  fireDevLoad.current = () => {
    if (loadDev.isPending) return;
    loadDev.mutate(undefined, {
      onSuccess: (res) =>
        toast(
          res.loaded.length
            ? `Loaded dev creds: ${res.loaded.join(", ")}.`
            : `No dev-creds.json at ${res.config_path}. Copy it there from another machine to load keys in one keystroke.`,
          res.loaded.length ? "ok" : "neutral",
        ),
      onError: (e) => toast(errMsg(e), "err"),
    });
  };
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

  // A section in an attention state opens itself the first time the data lands, so
  // the fix is one glance away instead of hidden behind a collapsed header.
  const seededRef = useRef(false);
  const s = settingsQ.data;
  const odbcInstalled = odbc.data?.installed;
  useEffect(() => {
    if (seededRef.current || !s) return;
    seededRef.current = true;
    const auto = new Set<string>();
    if (!s.kicad_wired) auto.add("kicad");
    if (odbcInstalled === false) auto.add("altium");
    if (auto.size > 0) setOpenSections((prev) => new Set([...prev, ...auto]));
  }, [s, odbcInstalled]);

  function toggle(id: string) {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function jump(step: SetupStep) {
    setGroup(step.group);
    setOpenSections((prev) => new Set(prev).add(step.section));
  }

  // A group with exactly ONE section auto-opens it on arrival: a single row hiding
  // behind a single dropdown would be pure friction.
  function selectGroup(g: GroupId) {
    setGroup(g);
    if (g === "kicad" || g === "altium") {
      setOpenSections((prev) => new Set(prev).add(g));
    }
  }

  // -- the Machine Setup verdict: is THIS machine fully set up? ---------------
  const steps: SetupStep[] = [];
  if (s) {
    steps.push({
      id: "kicad", label: "Wire KiCad", labelId: "settings.machine.step-kicad",
      metLabel: "KiCad Wired", metLabelId: "settings.machine.step-kicad-met",
      met: s.kicad_wired, group: "kicad", section: "kicad",
    });
    if (odbcInstalled !== null && odbcInstalled !== undefined) {
      steps.push({
        id: "odbc", label: "Install The ODBC Driver", labelId: "settings.machine.step-odbc",
        metLabel: "ODBC Driver Installed", metLabelId: "settings.machine.step-odbc-met",
        met: odbcInstalled, group: "altium", section: "altium",
      });
    }
    steps.push({
      id: "key", label: "Add A Distributor Key", labelId: "settings.machine.step-key",
      metLabel: "Distributor Key Saved", metLabelId: "settings.machine.step-key-met",
      met: s.mouser_api_key_set || s.digikey_client_secret_set,
      group: "sourcing", section: "distributor",
    });
    steps.push({
      id: "github", label: "Connect GitHub", labelId: "settings.machine.step-github",
      metLabel: "GitHub Connected", metLabelId: "settings.machine.step-github-met",
      met: s.github_token_set, group: "library", section: "github",
    });
  }
  const unmet = steps.filter((st) => !st.met);

  // -- per-group attention dots (mirror the unmet steps + an available update) --
  const groupAttention: Record<GroupId, "warn" | "neutral" | null> = {
    application: updateQ.data?.update_available ? "neutral" : null,
    library: unmet.some((st) => st.group === "library") ? "warn" : null,
    kicad: unmet.some((st) => st.group === "kicad") ? "warn" : null,
    altium: unmet.some((st) => st.group === "altium") ? "warn" : null,
    sourcing: unmet.some((st) => st.group === "sourcing") ? "warn" : null,
  };

  // -- collapsed-header summaries (live, from the same cached queries) ----------
  const sync = syncQ.data;
  const syncSummary = !sync
    ? null
    : !sync.has_remote
      ? <Text id="settings.summary.no-remote">No Remote</Text>
      : sync.behind > 0
        ? <Badge tone="warn">{`Behind ${sync.behind}`}</Badge>
        : sync.ahead > 0
          ? <Badge tone="neutral">{`Ahead ${sync.ahead}`}</Badge>
          : <Text id="settings.summary.up-to-date">Up To Date</Text>;
  const vendorCount = s
    ? [s.digikey_password_set, s.ul_password_set, s.snapeda_password_set, s.samacsys_password_set]
        .filter(Boolean).length
    : 0;

  const open = (id: string) => openSections.has(id);

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-dev-id="settings.root">
      <PanelTitle data-dev-id="settings.title">
        <Text id="settings.title">Settings</Text>
      </PanelTitle>
      <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-5">
        <div className="max-w-[980px] pb-10">
          <MachineSetupBand loading={!s} steps={steps} onJump={jump} />

          <div className="mt-5 flex items-start gap-6">
            {/* group nav: the five groups, an attention dot only where a setup step
                is unmet (calm otherwise) */}
            <nav
              aria-label="Settings Sections"
              className="sticky top-0 w-[188px] flex-none"
              data-dev-id="settings.nav"
            >
              <GroupNavButton id="application" label="Application" labelId="settings.nav.application"
                active={group} onSelect={selectGroup} attention={groupAttention.application}
                data-dev-id="settings.nav-application" />
              <GroupNavButton id="library" label="Library" labelId="settings.nav.library"
                active={group} onSelect={selectGroup} attention={groupAttention.library}
                data-dev-id="settings.nav-library" />
              <GroupNavButton id="kicad" label="KiCad" labelId="settings.nav.kicad"
                active={group} onSelect={selectGroup} attention={groupAttention.kicad}
                data-dev-id="settings.nav-kicad" />
              <GroupNavButton id="altium" label="Altium" labelId="settings.nav.altium"
                active={group} onSelect={selectGroup} attention={groupAttention.altium}
                data-dev-id="settings.nav-altium" />
              <GroupNavButton id="sourcing" label="Sourcing" labelId="settings.nav.sourcing"
                active={group} onSelect={selectGroup} attention={groupAttention.sourcing}
                data-dev-id="settings.nav-sourcing" />
            </nav>

            <div className="min-w-0 flex-1">
              {group === "application" ? (
                <>
                  <SettingsDisclosure
                    title="Appearance" titleId="settings.appearance.title"
                    hint="The theme is remembered the next time the window opens."
                    hintId="settings.appearance.hint"
                    summary={theme === "light"
                      ? <Text id="settings.summary.light">Light</Text>
                      : <Text id="settings.summary.dark">Dark</Text>}
                    open={open("appearance")} onToggle={() => toggle("appearance")}
                    data-dev-id="settings.appearance"
                  >
                    <AppearanceSection />
                  </SettingsDisclosure>
                  <SettingsDisclosure
                    title="App Update" titleId="settings.update.title"
                    hint="Pull the latest app from its repo. A non-fast-forward is surfaced, never force-applied."
                    hintId="settings.update.hint"
                    summary={updateQ.data
                      ? updateQ.data.update_available
                        ? <Badge tone="warn"><Text id="settings.summary.update-available">Update Available</Text></Badge>
                        : <Text id="settings.summary.up-to-date-app">Up To Date</Text>
                      : null}
                    open={open("update")} onToggle={() => toggle("update")}
                    data-dev-id="settings.update"
                  >
                    <UpdateSection />
                  </SettingsDisclosure>
                </>
              ) : group === "library" ? (
                <>
                  <SettingsDisclosure
                    title="Component Profiles" titleId="settings.profiles.title"
                    hint="Each profile is a separate set of components on disk. Switching one reloads the whole component view."
                    hintId="settings.profiles.hint"
                    summary={profilesQ.data ? <span>{profilesQ.data.active}</span> : null}
                    open={open("profiles")} onToggle={() => toggle("profiles")}
                    data-dev-id="settings.profiles"
                  >
                    <ProfilesSection />
                  </SettingsDisclosure>
                  <SettingsDisclosure
                    title="Component Sync" titleId="settings.sync.title"
                    hint="Push and pull the components against the remote. Offline and divergence are reported, never guessed."
                    hintId="settings.sync.hint"
                    summary={syncSummary}
                    open={open("sync")} onToggle={() => toggle("sync")}
                    data-dev-id="settings.sync"
                  >
                    <SyncSection />
                  </SettingsDisclosure>
                  <SettingsDisclosure
                    title="GitHub" titleId="settings.github.title"
                    hint="Connect a GitHub personal access token so adding or editing a part pushes it to the components repo on its own, and collaborators' changes pull in at launch. The repo owner can use a fine-grained token with Contents: write. A collaborator on someone else's repo needs a CLASSIC token with the repo scope (GitHub does not let a fine-grained token reach another user's repo), and must accept the repo invitation first. Stored per machine, never shown again."
                    hintId="settings.github.hint"
                    summary={s
                      ? s.github_token_set
                        ? <Text id="settings.summary.github-connected">Connected</Text>
                        : <Badge tone="neutral"><Text id="settings.summary.github-off">Not Connected</Text></Badge>
                      : null}
                    open={open("github")} onToggle={() => toggle("github")}
                    data-dev-id="settings.github"
                  >
                    <GitHubSection />
                  </SettingsDisclosure>
                  <SettingsDisclosure
                    title="Library Health" titleId="settings.health.title"
                    hint="Reconcile every part with its record and every file with the repository. Repair heals what it safely can and lists what needs your hand."
                    hintId="settings.health.hint"
                    open={open("health")} onToggle={() => toggle("health")}
                    data-dev-id="settings.health"
                  >
                    <LibraryHealthSection />
                  </SettingsDisclosure>
                </>
              ) : group === "kicad" ? (
                <SettingsDisclosure
                  title="KiCad" titleId="settings.kicad.title"
                  hint="Where the app writes KiCad's symbol and footprint tables, and whether the command-line tools that render previews were found. Wiring runs on its own at launch and on each profile switch. Leave the overrides blank to auto-detect."
                  hintId="settings.kicad.hint"
                  summary={s
                    ? s.kicad_wired
                      ? <Text id="settings.summary.kicad-wired">Wired</Text>
                      : <Badge tone="warn"><Text id="settings.summary.kicad-unwired">Not Wired</Text></Badge>
                    : null}
                  open={open("kicad")} onToggle={() => toggle("kicad")}
                  data-dev-id="settings.kicad"
                >
                  <KiCadSection />
                </SettingsDisclosure>
              ) : group === "altium" ? (
                <SettingsDisclosure
                  title="Altium Database Library" titleId="settings.altium.title"
                  hint="One git-synced library Altium reads, regenerated from this profile's records. Install it into Altium once, then it fills as you attach each part's Altium assets."
                  hintId="settings.altium.hint"
                  summary={odbcInstalled === true
                    ? <Text id="settings.summary.odbc-ok">Driver Installed</Text>
                    : odbcInstalled === false
                      ? <Badge tone="warn"><Text id="settings.summary.odbc-missing">Driver Missing</Text></Badge>
                      : null}
                  open={open("altium")} onToggle={() => toggle("altium")}
                  data-dev-id="settings.altium"
                >
                  <AltiumDbLibSection />
                </SettingsDisclosure>
              ) : (
                <>
                  <SettingsDisclosure
                    title="Distributor" titleId="settings.distributor.title"
                    hint="An optional Mouser API key lets enrichment supplement scraping. Enrichment works without it; the key is stored per machine and never shown again."
                    hintId="settings.distributor.hint"
                    summary={s
                      ? s.mouser_api_key_set || s.digikey_client_secret_set
                        ? <Text id="settings.summary.key-set">Key Saved</Text>
                        : <Badge tone="neutral"><Text id="settings.summary.key-off">Not Set</Text></Badge>
                      : null}
                    open={open("distributor")} onToggle={() => toggle("distributor")}
                    data-dev-id="settings.distributor"
                  >
                    <DistributorSection />
                  </SettingsDisclosure>
                  <SettingsDisclosure
                    title="Capture Credentials"
                    hint="The DigiKey account login signs you into DigiKey, and the API creds resolve the exact product page for enrichment. The provider logins clear each provider's wall inside DigiKey's CAD Models section, so the guided capture window can pull files without stopping to log in. Everything is stored per machine and each secret is never shown again."
                    summary={s ? <span>{`${vendorCount} of 4 Saved`}</span> : null}
                    open={open("vendor-logins")} onToggle={() => toggle("vendor-logins")}
                    data-dev-id="settings.vendor-logins"
                  >
                    <VendorLoginsSection />
                  </SettingsDisclosure>
                  <SettingsDisclosure
                    title="Procurement Rescan" titleId="settings.rescan.title"
                    hint="Refresh every part's price, stock and lifecycle status from Mouser and DigiKey. Parts checked recently are skipped unless you force a full pass."
                    hintId="settings.rescan.hint"
                    open={open("rescan")} onToggle={() => toggle("rescan")}
                    data-dev-id="settings.rescan"
                  >
                    <RescanSection />
                  </SettingsDisclosure>
                </>
              )}
            </div>
          </div>
        </div>
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
        "flex w-full items-center gap-2 rounded-control px-2.5 py-[7px] text-left text-sm transition-colors",
        selected
          ? "bg-acc-soft font-medium text-t1 shadow-[inset_2px_0_0_var(--c-acc)]"
          : "text-t2 hover:bg-[var(--c-hover)] hover:text-t1",
      )}
    >
      <span className="min-w-0 flex-1 truncate"><Text id={labelId}>{label}</Text></span>
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
}: {
  loading: boolean;
  steps: SetupStep[];
  onJump: (step: SetupStep) => void;
}) {
  const unmet = steps.filter((st) => !st.met);
  return (
    <Card className="px-4 py-3.5" data-dev-id="settings.machine-band">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Eyebrow className="mb-0.5">
            <Text id="settings.machine.title">Machine Setup</Text>
          </Eyebrow>
          {loading ? (
            <p className="text-sm text-t3">
              <Text id="settings.machine.loading">Reading this machine...</Text>
            </p>
          ) : unmet.length === 0 ? (
            <p className="text-sm font-medium text-t1">
              <Text id="settings.machine.ready">This Machine Is Ready</Text>
            </p>
          ) : (
            <p className="text-sm font-medium text-t1">
              {unmet.length === 1 ? "1 Setup Step Remaining" : `${unmet.length} Setup Steps Remaining`}
            </p>
          )}
        </div>
        {!loading ? (
          <div className="flex flex-wrap items-center gap-1.5">
            {steps.map((st) =>
              st.met ? (
                <span
                  key={st.id}
                  className="inline-flex items-center gap-1 rounded-control border border-line px-2 py-1 text-2xs font-medium text-t3"
                >
                  <Dot tone="ok" />
                  <Text id={st.metLabelId}>{st.metLabel}</Text>
                </span>
              ) : (
                <button
                  key={st.id}
                  type="button"
                  onClick={() => onJump(st)}
                  className="inline-flex items-center gap-1 rounded-control border border-acc bg-acc-soft px-2 py-1 text-2xs font-semibold text-t1 transition-colors hover:bg-[var(--c-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
                >
                  <Dot tone="warn" />
                  <Text id={st.labelId}>{st.label}</Text>
                </button>
              ),
            )}
          </div>
        ) : null}
      </div>
    </Card>
  );
}

function AppearanceSection() {
  const { theme, setTheme } = useTheme();
  const options: { value: Theme; label: string; id: string }[] = [
    { value: "dark", label: "Dark", id: "settings.appearance.dark" },
    { value: "light", label: "Light", id: "settings.appearance.light" },
  ];
  return (
    <>
      <div className="flex items-center justify-between">
        <span className="text-sm text-t2"><Text id="settings.appearance.theme-label">Theme</Text></span>
        <div className="inline-flex rounded-card border border-line2 p-0.5" data-dev-id="settings.appearance-theme">
          {options.map((o) => (
            <button
              key={o.value}
              type="button"
              aria-pressed={theme === o.value}
              onClick={() => setTheme(o.value)}
              className={cx(
                "rounded-control px-3 py-1 text-sm transition-colors",
                theme === o.value
                  ? "bg-acc-soft font-medium text-t1"
                  : "text-t3 hover:text-t2",
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

function ProfilesSection() {
  const profiles = useProfiles();
  const activate = useActivateProfile();
  const create = useCreateProfile();
  const del = useDeleteProfile();
  const { toast } = useToast();
  const [newName, setNewName] = useState("");
  const [archive, setArchive] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const namePlaceholder = useText("settings.profiles.name-placeholder", "New Profile Name");
  const deleteTitle = useText("settings.profiles.delete-title", "Delete Profile");
  const deleteConfirm = useText("settings.profiles.delete-confirm", "Delete");

  function onActivate(name: string) {
    activate.mutate(name, {
      onSuccess: () => toast(`Switched to ${name}.`, "ok"),
      onError: (e) => toast(errMsg(e), "err"),
    });
  }

  function onCreate() {
    const name = newName.trim();
    // guard the keyboard (Enter) path too, not just the disabled button, so a
    // rapid double-Enter cannot fire a duplicate create for the same name.
    if (!name || create.isPending) return;
    create.mutate(
      { name, archive },
      {
        onSuccess: () => {
          setNewName("");
          setArchive(false);
          toast(`Created ${name}.`, "ok");
        },
        onError: (e) => toast(errMsg(e), "err"),
      },
    );
  }

  function onConfirmDelete() {
    const name = pendingDelete;
    if (!name) return;
    del.mutate(name, {
      onSuccess: () => {
        setPendingDelete(null);
        toast(`Deleted ${name}.`, "ok");
      },
      onError: (e) => {
        setPendingDelete(null);
        toast(errMsg(e), "err");
      },
    });
  }

  return (
    <>
      {profiles.isLoading ? (
        <p className="py-1 text-sm text-t3">Loading profiles...</p>
      ) : profiles.isError ? (
        <p className="py-1 text-sm text-err">Could not load profiles.</p>
      ) : (
        <div>
          {profiles.data?.profiles.map((name) => {
            const active = name === profiles.data?.active;
            return (
              <div
                key={name}
                data-profile-row
                data-dev-id="settings.profiles-row"
                className="flex items-center justify-between gap-3 border-b border-line py-2 last:border-b-0"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <span className="truncate text-sm text-t1">{name}</span>
                  {active ? <Badge tone="ok">Active</Badge> : null}
                </div>
                {!active ? (
                  <div className="flex flex-none items-center gap-2">
                    <Button
                      small
                      onClick={() => onActivate(name)}
                      disabled={activate.isPending}
                    >
                      <Text id="settings.profiles.activate">Activate</Text>
                    </Button>
                    <Button
                      small
                      variant="ghost-danger"
                      onClick={() => setPendingDelete(name)}
                    >
                      <Text id="settings.profiles.delete">Delete</Text>
                    </Button>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}

      <div className="mt-3.5 flex flex-wrap items-center gap-2.5" data-dev-id="settings.profiles-create">
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onCreate();
          }}
          placeholder={namePlaceholder}
          className={INPUT_CLS}
        />
        <label className="flex flex-none cursor-pointer select-none items-center gap-1.5 text-xs text-t2">
          <input
            type="checkbox"
            checked={archive}
            onChange={(e) => setArchive(e.target.checked)}
          />
          <Text id="settings.profiles.archive">Archive Profile</Text>
        </label>
        <Button
          onClick={onCreate}
          disabled={!newName.trim() || create.isPending}
        >
          <Text id="settings.profiles.create">Create</Text>
        </Button>
      </div>

      <ConfirmDialog
        open={pendingDelete !== null}
        title={deleteTitle}
        body={
          <>
            Delete the profile <b>{pendingDelete}</b>? Its parts remain on disk; just
            the profile entry is removed.
          </>
        }
        confirmLabel={deleteConfirm}
        danger
        busy={del.isPending}
        onConfirm={onConfirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </>
  );
}

function SyncSection() {
  const status = useSyncStatus();
  const sync = useDoSync();
  const { toast } = useToast();

  function onSync() {
    sync.mutate(undefined, {
      onSuccess: (r) => {
        // Divergence and offline are FAILURES, surfaced verbatim and never faked
        // green; no-remote is informational; only a real pull/push/clean is ok.
        if (r.state === "diverged") {
          toast("Sync failed: the components have diverged from the remote.", "err");
          return;
        }
        if (r.state === "offline") {
          toast("Sync failed: the remote is unreachable.", "err");
          return;
        }
        if (r.state === "denied") {
          toast(
            "Sync failed: the remote refused this token (403). A collaborator must accept the repo invitation and use a CLASSIC personal access token with the repo scope; a fine-grained token cannot reach another user's repo.",
            "err",
          );
          return;
        }
        if (r.state === "no_remote") {
          toast("No remote is configured for these components.", "neutral");
          return;
        }
        const parts: string[] = [];
        if (r.pulled) parts.push("pulled");
        if (r.pushed) parts.push("pushed");
        const what = parts.length ? parts.join(" and ") : "up to date";
        toast(`Sync ${what}.`, "ok");
      },
      onError: (e) => toast(errMsg(e), "err"),
    });
  }

  return (
    <>
      {status.isLoading ? (
        <p className="py-1 text-sm text-t3">Checking sync status...</p>
      ) : status.isError ? (
        <p className="py-1 text-sm text-err">Could not read sync status.</p>
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
                    {status.data.ahead} ahead
                  </span>
                  {", "}
                  <span className={status.data.behind > 0 ? statusTone("behind").text : undefined}>
                    {status.data.behind} behind
                  </span>
                </span>
              ) : (
                "No remote configured"
              )
            }
          />
        </>
      ) : null}
      <div className="mt-3.5 flex items-center gap-3">
        <Button variant="accent" onClick={onSync} disabled={sync.isPending} data-dev-id="settings.sync-action">
          {sync.isPending ? "Syncing..." : <Text id="settings.sync.action">Sync Now</Text>}
        </Button>
        {sync.data ? (
          <span className="text-xs text-t3">
            Last sync: {sync.data.detail || sync.data.state}
          </span>
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
        <p className="py-1 text-sm text-t3">Reading KiCad status...</p>
      ) : sys.isError ? (
        <p className="py-1 text-sm text-err">Could not read KiCad status.</p>
      ) : sys.data ? (
        <>
          <StatusRow
            label="Config Directory"
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
                <span className="text-warn">Not found (previews unavailable)</span>
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
                <span className="text-ok">Wired to the active profile</span>
              ) : (
                <span className="text-warn">Not wired so far (use Wire KiCad below)</span>
              )
            }
          />
        </>
      ) : null}

      {sys.data ? (
        <div className="mt-3.5 flex flex-col gap-3">
          <div>
            <Button onClick={onWire} disabled={wireBusy} data-dev-id="settings.kicad-wire">
              {wireBusy ? "Wiring..." : <Text id="settings.kicad.wire">Wire KiCad</Text>}
            </Button>
          </div>
          {wireJob.status === "running" && wireJob.progress?.message ? (
            <p className="text-xs text-t3">{wireJob.progress.message}...</p>
          ) : null}
          {wireJob.status === "error" ? (
            <p className="text-sm text-err">{wireJob.error ?? "Wiring failed."}</p>
          ) : null}
          {wireReport ? (
            <div className="flex flex-col gap-1.5 rounded-control border border-line bg-raise2 p-3 text-xs">
              <div className="text-t2">
                Registered {wireReport.categories_registered.length}{" "}
                {wireReport.categories_registered.length === 1 ? "category" : "categories"}: added{" "}
                {wireReport.symbol_rows_added} symbol and {wireReport.footprint_rows_added} footprint{" "}
                {wireReport.footprint_rows_added === 1 ? "row" : "rows"}.
              </div>
              {wireReport.restart_needed ? (
                <div className="flex items-center gap-2 text-warn">
                  <Dot tone="warn" />
                  <span>Restart KiCad to load the updated tables.</span>
                </div>
              ) : (
                <div className="flex items-center gap-2 text-ok">
                  <Dot tone="ok" />
                  <span>KiCad is wired and set.</span>
                </div>
              )}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="mt-3.5 flex flex-col gap-2.5" data-dev-id="settings.kicad-overrides">
        <div className="flex flex-wrap items-center gap-2.5">
          <label
            htmlFor="kicad-config-override"
            className="w-52 flex-none text-xs text-t3"
          >
            <Text id="settings.kicad.config-label">Config Directory Override</Text>
          </label>
          <input
            id="kicad-config-override"
            value={cfgValue}
            onChange={(e) => setCfgDraft(e.target.value)}
            placeholder={configPlaceholder}
            className={INPUT_CLS}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <label
            htmlFor="kicad-cli-override"
            className="w-52 flex-none text-xs text-t3"
          >
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
            {save.isPending ? "Applying..." : <Text id="settings.kicad.save-overrides">Save Overrides</Text>}
          </Button>
        </div>
      </div>
    </>
  );
}

function DistributorSection() {
  const settings = useSettings();
  const save = useUpdateSettings();
  const { toast } = useToast();
  const [keyInput, setKeyInput] = useState("");
  const isSet = settings.data?.mouser_api_key_set ?? false;
  const keyPlaceholderNew = useText("settings.distributor.key-placeholder", "Paste a key");
  const keyPlaceholderReplace = useText(
    "settings.distributor.key-placeholder-replace",
    "Paste a new key to replace it",
  );
  const toastSaved = useText("settings.distributor.toast-saved", "Mouser key saved.");
  const toastCleared = useText("settings.distributor.toast-cleared", "Mouser key cleared.");

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
        label="Mouser API Key"
        labelId="settings.distributor.key-label"
        value={
          settings.isLoading
            ? "Loading..."
            : isSet
              ? `Set (ending ${settings.data?.mouser_api_key_hint})`
              : "Not set"
        }
      />
      <div className="mt-3.5 flex flex-wrap items-center gap-2.5" data-dev-id="settings.distributor-key">
        <label htmlFor="mouser-key" className="sr-only">
          Mouser API Key
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
        <Button
          onClick={onSave}
          disabled={!keyInput.trim() || save.isPending}
        >
          <Text id="settings.distributor.save-key">Save Key</Text>
        </Button>
        {isSet ? (
          <Button variant="danger" onClick={onClear} disabled={save.isPending}>
            <Text id="settings.distributor.clear">Clear</Text>
          </Button>
        ) : null}
      </div>
    </>
  );
}

// One saved credential pair: a non-secret identifier (a username, or the DigiKey API
// client_id) that is echoed, plus a masked secret that only ever shows a last-4 hint.
// The guided capture window uses these to auto-fill each sign-in and then keeps the
// session, so the user signs in once. The two field labels are configurable so the same
// row can carry a username/password pair or a Client ID / Client Secret pair.
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
  // Prefill the saved identifier once it arrives, unless the user has started editing.
  useEffect(() => {
    if (!edited) setIdentifier(savedIdentifier);
  }, [savedIdentifier, edited]);
  const slug = identifierLabel.toLowerCase().replace(/\s+/g, "-");
  return (
    <div className="border-b border-line py-3 last:border-b-0" data-dev-id="settings.vendor-login-row">
      <div className="mb-2 flex items-center justify-between gap-4">
        <span className="text-sm font-medium text-t1">{title}</span>
        <span className="flex-none text-xs text-t3">
          {secretSet ? `Saved (ending ${secretHint})` : "Not saved"}
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
          placeholder={secretSet ? "Paste a new value to replace it" : secretLabel}
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

// A titled subgroup inside the credential section, so the DigiKey creds and the
// in-DigiKey CAD provider logins read as two distinct tiers, not one flat list.
function CredentialGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mt-4 first:mt-0">
      <Eyebrow className="mb-0.5">{label}</Eyebrow>
      {children}
    </div>
  );
}

function VendorLoginsSection() {
  const settings = useSettings();
  const save = useUpdateSettings();
  const { toast } = useToast();
  const d = settings.data;

  function saveLogin(patch: SettingsPatch, name: string) {
    save.mutate(patch, {
      onSuccess: () => toast(`${name} saved.`, "ok"),
      onError: (e) => toast(errMsg(e), "err"),
    });
  }

  return (
    <>
      <CredentialGroup label="DigiKey">
        <VendorLogin
          title="DigiKey API Creds"
          identifierLabel="DigiKey API Client ID"
          secretLabel="DigiKey API Client Secret"
          saveLabel="Save DigiKey API Creds"
          savedIdentifier={d?.digikey_client_id ?? ""}
          secretSet={d?.digikey_client_secret_set ?? false}
          secretHint={d?.digikey_client_secret_hint ?? ""}
          pending={save.isPending}
          onSave={(clientId, secret) => {
            const patch: SettingsPatch = { digikey_client_id: clientId };
            if (secret) patch.digikey_client_secret = secret;
            saveLogin(patch, "DigiKey API creds");
          }}
        />
        <VendorLogin
          title="DigiKey Account Login"
          identifierLabel="DigiKey Account Username"
          secretLabel="DigiKey Account Password"
          saveLabel="Save DigiKey Account Login"
          savedIdentifier={d?.digikey_username ?? ""}
          secretSet={d?.digikey_password_set ?? false}
          secretHint={d?.digikey_password_hint ?? ""}
          pending={save.isPending}
          onSave={(username, password) => {
            const patch: SettingsPatch = { digikey_username: username };
            if (password) patch.digikey_password = password;
            saveLogin(patch, "DigiKey account login");
          }}
        />
      </CredentialGroup>
      <CredentialGroup label="In-DigiKey CAD Providers">
        <VendorLogin
          title="Ultra Librarian"
          identifierLabel="Ultra Librarian Username"
          secretLabel="Ultra Librarian Password"
          saveLabel="Save Ultra Librarian Login"
          savedIdentifier={d?.ul_username ?? ""}
          secretSet={d?.ul_password_set ?? false}
          secretHint={d?.ul_password_hint ?? ""}
          pending={save.isPending}
          onSave={(username, password) => {
            const patch: SettingsPatch = { ul_username: username };
            if (password) patch.ul_password = password;
            saveLogin(patch, "Ultra Librarian login");
          }}
        />
        <VendorLogin
          title="SnapEDA"
          identifierLabel="SnapEDA Username"
          secretLabel="SnapEDA Password"
          saveLabel="Save SnapEDA Login"
          savedIdentifier={d?.snapeda_username ?? ""}
          secretSet={d?.snapeda_password_set ?? false}
          secretHint={d?.snapeda_password_hint ?? ""}
          pending={save.isPending}
          onSave={(username, password) => {
            const patch: SettingsPatch = { snapeda_username: username };
            if (password) patch.snapeda_password = password;
            saveLogin(patch, "SnapEDA login");
          }}
        />
        <VendorLogin
          title="SamacSys"
          identifierLabel="SamacSys Username"
          secretLabel="SamacSys Password"
          saveLabel="Save SamacSys Login"
          savedIdentifier={d?.samacsys_username ?? ""}
          secretSet={d?.samacsys_password_set ?? false}
          secretHint={d?.samacsys_password_hint ?? ""}
          pending={save.isPending}
          onSave={(username, password) => {
            const patch: SettingsPatch = { samacsys_username: username };
            if (password) patch.samacsys_password = password;
            saveLogin(patch, "SamacSys login");
          }}
        />
      </CredentialGroup>
    </>
  );
}

// The GitHub sign-in: paste a fine-grained personal access token so the app can auto-push a part
// add to the library repo and pull collaborators' changes. Each collaborator connects their own
// token; the repo owner grants them write access on GitHub. The token is stored per machine and
// never shown again.
function GitHubSection() {
  const settings = useSettings();
  const save = useUpdateSettings();
  const { toast } = useToast();
  const [tokenInput, setTokenInput] = useState("");
  const isSet = settings.data?.github_token_set ?? false;
  const tokenPlaceholderNew = useText("settings.github.token-placeholder", "Paste a token to connect");
  const tokenPlaceholderReplace = useText(
    "settings.github.token-placeholder-replace",
    "Paste a new token to replace it",
  );
  const toastConnected = useText(
    "settings.github.toast-connected",
    "Connected to GitHub. Part changes now push on their own.",
  );
  const toastDisconnected = useText("settings.github.toast-disconnected", "Disconnected from GitHub.");

  function onSave() {
    const token = tokenInput.trim();
    if (!token || save.isPending) return;
    save.mutate(
      { github_token: token },
      {
        onSuccess: () => {
          setTokenInput("");
          toast(toastConnected, "ok");
        },
        onError: (e) => toast(errMsg(e), "err"),
      },
    );
  }

  function onClear() {
    save.mutate(
      { github_token: "" },
      {
        onSuccess: () => {
          setTokenInput("");
          toast(toastDisconnected, "ok");
        },
        onError: (e) => toast(errMsg(e), "err"),
      },
    );
  }

  return (
    <>
      <StatusRow
        label="Connection"
        labelId="settings.github.connection"
        value={
          settings.isLoading
            ? "Loading..."
            : isSet
              ? `Connected (token ending ${settings.data?.github_token_hint})`
              : "Not connected"
        }
      />
      <div className="mt-3.5 flex flex-wrap items-center gap-2.5" data-dev-id="settings.github-token">
        <label htmlFor="github-token" className="sr-only">
          GitHub Personal Access Token
        </label>
        <input
          id="github-token"
          type="password"
          autoComplete="off"
          value={tokenInput}
          onChange={(e) => setTokenInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onSave();
          }}
          placeholder={isSet ? tokenPlaceholderReplace : tokenPlaceholderNew}
          className={INPUT_CLS}
        />
        <Button onClick={onSave} disabled={!tokenInput.trim() || save.isPending}>
          <Text id="settings.github.connect">Connect</Text>
        </Button>
        {isSet ? (
          <Button variant="danger" onClick={onClear} disabled={save.isPending}>
            <Text id="settings.github.disconnect">Disconnect</Text>
          </Button>
        ) : null}
      </div>
    </>
  );
}

function UpdateSection() {
  const check = useUpdateCheck();
  const apply = useApplyUpdate();
  const { toast } = useToast();
  const toastRestart = useText("settings.update.toast-restart", "Update applied. Restart to finish.");
  const toastApplied = useText("settings.update.toast-applied", "Update applied.");

  function onApply() {
    apply.mutate(undefined, {
      onSuccess: (r) => {
        if (r.restart_requested) {
          toast(toastRestart, "neutral");
        } else if (r.updated) {
          toast(toastApplied, "ok");
        } else {
          toast(r.detail || r.state, "neutral");
        }
      },
      onError: (e) => toast(errMsg(e), "err"),
    });
  }

  const available = check.data?.update_available ?? false;

  return (
    <>
      {check.isLoading ? (
        <p className="py-1 text-sm text-t3">Checking for updates...</p>
      ) : check.isError ? (
        <p className="py-1 text-sm text-err">Could not check for updates.</p>
      ) : (
        <StatusRow
          label="Status"
          labelId="settings.update.status"
          value={
            check.data?.state === "offline" ? (
              <span className="text-warn">Could not reach the update server</span>
            ) : available ? (
              "Update available"
            ) : (
              "Up to date"
            )
          }
        />
      )}
      <div className="mt-3.5 flex items-center gap-3">
        {available ? (
          <Button variant="accent" onClick={onApply} disabled={apply.isPending} data-dev-id="settings.update-apply">
            {apply.isPending ? "Applying..." : <Text id="settings.update.apply">Apply Update</Text>}
          </Button>
        ) : null}
        <Button
          small
          onClick={() => check.refetch()}
          disabled={check.isFetching}
        >
          <Text id="settings.update.check-again">Check Again</Text>
        </Button>
      </div>
    </>
  );
}
