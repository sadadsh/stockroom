/**
 * Settings (spec sections 5.3, 9, 11, 12): the per-machine controls that live
 * outside the library. Appearance (the theme toggle), library profiles (switch,
 * create, delete), library sync, the KiCad wiring status, the Mouser API key, and
 * the app self-update. Every section is honest about its state: offline/divergence
 * and a missing kicad-cli are surfaced verbatim, never faked green, and the Mouser
 * key is only ever shown as a last-4 hint.
 */
import { useEffect, useState, type ReactNode } from "react";
import { ApiError, api } from "../api/client";
import type { SettingsPatch, WiringReport } from "../api/types";
import { useJob } from "../lib/useJob";
import { AltiumDbLibSection } from "../components/AltiumDbLibSection";
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
} from "../api/queries";
import { useTheme, type Theme } from "../lib/theme";
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

function Section({
  title,
  titleId,
  hint,
  hintId,
  children,
  "data-dev-id": devId,
}: {
  title: string;
  titleId?: string;
  hint?: string;
  hintId?: string;
  children: ReactNode;
  "data-dev-id"?: string;
}) {
  return (
    <section className="mb-6" data-dev-id={devId}>
      <Eyebrow className="mb-2">{titleId ? <Text id={titleId}>{title}</Text> : title}</Eyebrow>
      {hint ? (
        <p className="mb-2.5 text-xs text-t3">{hintId ? <Text id={hintId}>{hint}</Text> : hint}</p>
      ) : null}
      <Card className="px-4 py-3.5">{children}</Card>
    </section>
  );
}

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

export function SettingsPage() {
  return (
    <div className="flex min-h-0 flex-1 flex-col" data-dev-id="settings.root">
      <PanelTitle data-dev-id="settings.title">
        <Text id="settings.title">Settings</Text>
      </PanelTitle>
      <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-5">
        <div className="max-w-[860px] pb-10">
          <AppearanceSection />
          <ProfilesSection />
          <SyncSection />
          <GitHubSection />
          <KiCadSection />
          <LibraryHealthSection />
          <RescanSection />
          <AltiumDbLibSection />
          <DistributorSection />
          <VendorLoginsSection />
          <UpdateSection />
        </div>
      </div>
    </div>
  );
}

function AppearanceSection() {
  const { theme, setTheme } = useTheme();
  const options: { value: Theme; label: string; id: string }[] = [
    { value: "dark", label: "Dark", id: "settings.appearance.dark" },
    { value: "light", label: "Light", id: "settings.appearance.light" },
  ];
  return (
    <Section
      title="Appearance"
      titleId="settings.appearance.title"
      hint="The theme is remembered the next time the window opens."
      hintId="settings.appearance.hint"
      data-dev-id="settings.appearance"
    >
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
    </Section>
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
    <Section
      title="Component Profiles"
      titleId="settings.profiles.title"
      hint="Each profile is a separate set of components on disk. Switching one reloads the whole component view."
      hintId="settings.profiles.hint"
      data-dev-id="settings.profiles"
    >
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
                      variant="danger"
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
    </Section>
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
    <Section
      title="Component Sync"
      titleId="settings.sync.title"
      hint="Push and pull the components against the remote. Offline and divergence are reported, never guessed."
      hintId="settings.sync.hint"
      data-dev-id="settings.sync"
    >
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
                  {status.data.ahead} ahead, {status.data.behind} behind
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
    </Section>
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
    <Section
      title="KiCad"
      titleId="settings.kicad.title"
      hint="Where the app writes KiCad's symbol and footprint tables, and whether the command-line tools that render previews were found. Wiring runs on its own at launch and on each profile switch. Leave the overrides blank to auto-detect."
      hintId="settings.kicad.hint"
      data-dev-id="settings.kicad"
    >
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
    </Section>
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
    <Section
      title="Distributor"
      titleId="settings.distributor.title"
      hint="An optional Mouser API key lets enrichment supplement scraping. Enrichment works without it; the key is stored per machine and never shown again."
      hintId="settings.distributor.hint"
      data-dev-id="settings.distributor"
    >
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
    </Section>
  );
}

// One vendor's saved login: a username (echoed, not secret) plus a masked password.
// The guided capture window uses these to auto-fill the first login and then keeps
// the session, so the user signs in once.
function VendorLogin({
  label,
  savedUsername,
  passwordSet,
  passwordHint,
  pending,
  onSave,
}: {
  label: string;
  savedUsername: string;
  passwordSet: boolean;
  passwordHint: string;
  pending: boolean;
  onSave: (username: string, password: string) => void;
}) {
  const [username, setUsername] = useState(savedUsername);
  const [password, setPassword] = useState("");
  const [edited, setEdited] = useState(false);
  const usernamePlaceholder = useText("settings.vendor-logins.username-placeholder", "Username or email");
  const passwordPlaceholderNew = useText("settings.vendor-logins.password-placeholder", "Password");
  const passwordPlaceholderReplace = useText(
    "settings.vendor-logins.password-placeholder-replace",
    "Paste a new password to replace it",
  );
  // Prefill the saved username once it arrives, unless the user has started editing.
  useEffect(() => {
    if (!edited) setUsername(savedUsername);
  }, [savedUsername, edited]);
  const slug = label.toLowerCase().replace(/\s+/g, "-");
  return (
    <div className="border-b border-line py-3 last:border-b-0" data-dev-id="settings.vendor-login-row">
      <div className="mb-2 flex items-center justify-between gap-4">
        <span className="text-sm font-medium text-t1">{label}</span>
        <span className="flex-none text-xs text-t3">
          {passwordSet ? `Password set (ending ${passwordHint})` : "No password saved"}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2.5">
        <label htmlFor={`${slug}-user`} className="sr-only">
          {label} Username
        </label>
        <input
          id={`${slug}-user`}
          type="text"
          autoComplete="off"
          value={username}
          onChange={(e) => {
            setEdited(true);
            setUsername(e.target.value);
          }}
          placeholder={usernamePlaceholder}
          className={INPUT_CLS}
        />
        <label htmlFor={`${slug}-pass`} className="sr-only">
          {label} Password
        </label>
        <input
          id={`${slug}-pass`}
          type="password"
          autoComplete="off"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder={passwordSet ? passwordPlaceholderReplace : passwordPlaceholderNew}
          className={INPUT_CLS}
        />
        <Button
          className="min-w-[176px] justify-center"
          onClick={() => onSave(username.trim(), password)}
          disabled={pending || (!username.trim() && !password)}
        >
          <Text id="settings.vendor-logins.save">Save</Text> {label} Login
        </Button>
      </div>
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
      onSuccess: () => toast(`${name} login saved.`, "ok"),
      onError: (e) => toast(errMsg(e), "err"),
    });
  }

  return (
    <Section
      title="Vendor Logins"
      titleId="settings.vendor-logins.title"
      hint="Saved Ultra Librarian and SnapEDA logins let the guided capture window log in on its own and remain signed in across parts. Both are stored per machine and the password is never shown again."
      hintId="settings.vendor-logins.hint"
      data-dev-id="settings.vendor-logins"
    >
      <VendorLogin
        label="Ultra Librarian"
        savedUsername={d?.ul_username ?? ""}
        passwordSet={d?.ul_password_set ?? false}
        passwordHint={d?.ul_password_hint ?? ""}
        pending={save.isPending}
        onSave={(username, password) => {
          const patch: SettingsPatch = { ul_username: username };
          if (password) patch.ul_password = password;
          saveLogin(patch, "Ultra Librarian");
        }}
      />
      <VendorLogin
        label="SnapEDA"
        savedUsername={d?.snapeda_username ?? ""}
        passwordSet={d?.snapeda_password_set ?? false}
        passwordHint={d?.snapeda_password_hint ?? ""}
        pending={save.isPending}
        onSave={(username, password) => {
          const patch: SettingsPatch = { snapeda_username: username };
          if (password) patch.snapeda_password = password;
          saveLogin(patch, "SnapEDA");
        }}
      />
    </Section>
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
    <Section
      title="GitHub"
      titleId="settings.github.title"
      hint="Connect a GitHub personal access token so adding or editing a part pushes it to the components repo on its own, and collaborators' changes pull in at launch. The repo owner can use a fine-grained token with Contents: write. A collaborator on someone else's repo needs a CLASSIC token with the repo scope (GitHub does not let a fine-grained token reach another user's repo), and must accept the repo invitation first. Stored per machine, never shown again."
      hintId="settings.github.hint"
      data-dev-id="settings.github"
    >
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
    </Section>
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
    <Section
      title="App Update"
      titleId="settings.update.title"
      hint="Pull the latest app from its repo. A non-fast-forward is surfaced, never force-applied."
      hintId="settings.update.hint"
      data-dev-id="settings.update"
    >
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
    </Section>
  );
}
