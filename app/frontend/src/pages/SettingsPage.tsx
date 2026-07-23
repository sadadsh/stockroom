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
import { Badge, Button, Card, Dot, Eyebrow } from "../components/primitives";
import { ConfirmDialog } from "../components/ConfirmDialog";

function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

function errMsg(err: unknown): string {
  return err instanceof ApiError ? err.message : "Something went wrong.";
}

const INPUT_CLS =
  "min-w-0 flex-1 rounded-control border border-line2 bg-field px-3 py-2 " +
  "text-base text-t1 outline-none focus:border-acc disabled:opacity-50";

function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section className="mb-7">
      <Eyebrow className="mb-2">{title}</Eyebrow>
      {hint ? <p className="mb-2.5 text-xs text-t3">{hint}</p> : null}
      <Card className="px-4 py-3.5">{children}</Card>
    </section>
  );
}

function StatusRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-line py-2 last:border-b-0">
      <span className="flex-none text-xs text-t3">{label}</span>
      <span className="min-w-0 truncate text-right text-sm text-t2">{value}</span>
    </div>
  );
}

export function SettingsPage() {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-[30px] pt-[22px]">
      <div className="mx-auto max-w-[860px] pb-12">
        <h1 className="mb-6 text-title font-bold tracking-[-0.02em] text-t1">Settings</h1>
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
  );
}

function AppearanceSection() {
  const { theme, setTheme } = useTheme();
  const options: { value: Theme; label: string }[] = [
    { value: "dark", label: "Dark" },
    { value: "light", label: "Light" },
  ];
  return (
    <Section title="Appearance" hint="The theme is remembered the next time the window opens.">
      <div className="flex items-center justify-between">
        <span className="text-sm text-t2">Theme</span>
        <div className="inline-flex rounded-card border border-line2 p-0.5">
          {options.map((o) => (
            <button
              key={o.value}
              type="button"
              aria-pressed={theme === o.value}
              onClick={() => setTheme(o.value)}
              className={cx(
                "rounded-control px-3 py-1 text-sm transition-colors",
                theme === o.value
                  ? "bg-raise2 text-t1"
                  : "text-t3 hover:text-t2",
              )}
            >
              {o.label}
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
      hint="Each profile is a separate set of components on disk. Switching one reloads the whole component view."
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
                      Activate
                    </Button>
                    <Button
                      small
                      variant="danger"
                      onClick={() => setPendingDelete(name)}
                    >
                      Delete
                    </Button>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}

      <div className="mt-3.5 flex flex-wrap items-center gap-2.5">
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onCreate();
          }}
          placeholder="New Profile Name"
          className={INPUT_CLS}
        />
        <label className="flex flex-none cursor-pointer select-none items-center gap-1.5 text-xs text-t2">
          <input
            type="checkbox"
            checked={archive}
            onChange={(e) => setArchive(e.target.checked)}
          />
          Archive Profile
        </label>
        <Button
          onClick={onCreate}
          disabled={!newName.trim() || create.isPending}
        >
          Create
        </Button>
      </div>

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete Profile"
        body={
          <>
            Delete the profile <b>{pendingDelete}</b>? Its parts stay on disk; only
            the profile entry is removed.
          </>
        }
        confirmLabel="Delete"
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
          toast("Sync failed: your components have diverged from the remote.", "err");
          return;
        }
        if (r.state === "offline") {
          toast("Sync failed: the remote is unreachable.", "err");
          return;
        }
        if (r.state === "denied") {
          toast(
            "Sync failed: the remote refused this token (403). If you are a collaborator, accept the repo invitation and use a CLASSIC personal access token with the repo scope; a fine-grained token cannot access a repo owned by another user.",
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
        const what = parts.length ? parts.join(" and ") : "already up to date";
        toast(`Sync ${what}.`, "ok");
      },
      onError: (e) => toast(errMsg(e), "err"),
    });
  }

  return (
    <Section
      title="Component Sync"
      hint="Sync your components with the remote. Offline and divergence are reported, never guessed."
    >
      {status.isLoading ? (
        <p className="py-1 text-sm text-t3">Checking sync status...</p>
      ) : status.isError ? (
        <p className="py-1 text-sm text-err">Could not read sync status.</p>
      ) : status.data ? (
        <>
          <StatusRow
            label="Branch"
            value={<span className="tnum font-mono">{status.data.current_branch}</span>}
          />
          <StatusRow
            label="Remote"
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
        <Button variant="accent" onClick={onSync} disabled={sync.isPending}>
          {sync.isPending ? "Syncing..." : "Sync Now"}
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
          toast(
            r.kicad_wired
              ? "KiCad settings applied. Your components are wired."
              : "KiCad settings applied.",
            "ok",
          );
        },
        onError: (e) => toast(errMsg(e), "err"),
      },
    );
  }

  return (
    <Section
      title="KiCad"
      hint="Where the app writes KiCad's symbol and footprint tables, and whether the command-line tools that render previews were found. Wiring runs automatically on launch and on every profile switch. Leave the overrides blank to auto-detect."
    >
      {sys.isLoading ? (
        <p className="py-1 text-sm text-t3">Reading KiCad status...</p>
      ) : sys.isError ? (
        <p className="py-1 text-sm text-err">Could not read KiCad status.</p>
      ) : sys.data ? (
        <>
          <StatusRow label="Config Directory" value={sys.data.kicad_config_dir} />
          <StatusRow
            label="KiCad CLI"
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
            value={sys.data.kicad_running ? "Yes" : "No"}
          />
          <StatusRow
            label="KiCad Wiring"
            value={
              settings.isLoading ? (
                "Loading..."
              ) : settings.data?.kicad_wired ? (
                <span className="text-ok">Wired to the active profile</span>
              ) : (
                <span className="text-warn">Not wired yet (use Wire KiCad below)</span>
              )
            }
          />
        </>
      ) : null}

      {sys.data ? (
        <div className="mt-3.5 flex flex-col gap-3">
          <div>
            <Button onClick={onWire} disabled={wireBusy}>
              {wireBusy ? "Wiring..." : "Wire KiCad"}
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
                  <span>KiCad is wired and ready.</span>
                </div>
              )}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="mt-3.5 flex flex-col gap-2.5">
        <div className="flex flex-wrap items-center gap-2.5">
          <label
            htmlFor="kicad-config-override"
            className="w-52 flex-none text-xs text-t3"
          >
            Config Directory Override
          </label>
          <input
            id="kicad-config-override"
            value={cfgValue}
            onChange={(e) => setCfgDraft(e.target.value)}
            placeholder="Auto-detected"
            className={INPUT_CLS}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <label
            htmlFor="kicad-cli-override"
            className="w-52 flex-none text-xs text-t3"
          >
            KiCad CLI Override
          </label>
          <input
            id="kicad-cli-override"
            value={cliValue}
            onChange={(e) => setCliDraft(e.target.value)}
            placeholder="Auto-discovered"
            className={INPUT_CLS}
          />
        </div>
        <div>
          <Button onClick={onSave} disabled={!dirty || save.isPending}>
            {save.isPending ? "Applying..." : "Save Overrides"}
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
          toast("Mouser key saved.", "ok");
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
          toast("Mouser key cleared.", "ok");
        },
        onError: (e) => toast(errMsg(e), "err"),
      },
    );
  }

  return (
    <Section
      title="Distributor"
      hint="An optional Mouser API key lets enrichment supplement scraping. Enrichment works without it; the key is stored per machine and never shown again."
    >
      <StatusRow
        label="Mouser API Key"
        value={
          settings.isLoading
            ? "Loading..."
            : isSet
              ? `Set (ending ${settings.data?.mouser_api_key_hint})`
              : "Not set"
        }
      />
      <div className="mt-3.5 flex flex-wrap items-center gap-2.5">
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
          placeholder={isSet ? "Paste a new key to replace it" : "Paste a key"}
          className={INPUT_CLS}
        />
        <Button
          onClick={onSave}
          disabled={!keyInput.trim() || save.isPending}
        >
          Save Key
        </Button>
        {isSet ? (
          <Button variant="danger" onClick={onClear} disabled={save.isPending}>
            Clear
          </Button>
        ) : null}
      </div>
    </Section>
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
  identifierPlaceholder = "Username or email",
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
    <div className="border-b border-line py-3 last:border-b-0">
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
          placeholder={identifierPlaceholder}
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
    <Section
      title="Capture Credentials"
      hint="The DigiKey account login signs you into DigiKey, and the API creds resolve the exact product page for enrichment. The provider logins clear each provider's wall inside DigiKey's CAD Models section, so the guided capture window can pull files without stopping to log in. Everything is stored per machine and each secret is never shown again."
    >
      <CredentialGroup label="DigiKey">
        <VendorLogin
          title="DigiKey API Creds"
          identifierLabel="DigiKey API Client ID"
          secretLabel="DigiKey API Client Secret"
          saveLabel="Save DigiKey API Creds"
          identifierPlaceholder="Client ID"
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

  function onSave() {
    const token = tokenInput.trim();
    if (!token || save.isPending) return;
    save.mutate(
      { github_token: token },
      {
        onSuccess: () => {
          setTokenInput("");
          toast("Connected to GitHub. Your part changes will push automatically.", "ok");
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
          toast("Disconnected from GitHub.", "ok");
        },
        onError: (e) => toast(errMsg(e), "err"),
      },
    );
  }

  return (
    <Section
      title="GitHub"
      hint="Connect a GitHub personal access token so adding or editing a part pushes it to your components repo automatically, and collaborators' changes pull in on launch. The repo owner can use a fine-grained token with Contents: write. A collaborator on someone else's repo needs a CLASSIC token with the repo scope (GitHub does not let a fine-grained token reach another user's repo), and must accept the repo invitation first. Stored per machine, never shown again."
    >
      <StatusRow
        label="Connection"
        value={
          settings.isLoading
            ? "Loading..."
            : isSet
              ? `Connected (token ending ${settings.data?.github_token_hint})`
              : "Not connected"
        }
      />
      <div className="mt-3.5 flex flex-wrap items-center gap-2.5">
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
          placeholder={isSet ? "Paste a new token to replace it" : "Paste a token to connect"}
          className={INPUT_CLS}
        />
        <Button onClick={onSave} disabled={!tokenInput.trim() || save.isPending}>
          Connect
        </Button>
        {isSet ? (
          <Button variant="danger" onClick={onClear} disabled={save.isPending}>
            Disconnect
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

  function onApply() {
    apply.mutate(undefined, {
      onSuccess: (r) => {
        if (r.restart_requested) {
          toast("Update applied. Restart to finish.", "neutral");
        } else if (r.updated) {
          toast("Update applied.", "ok");
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
      hint="Pull the latest app from its repository. A non-fast-forward is surfaced, never force-applied."
    >
      {check.isLoading ? (
        <p className="py-1 text-sm text-t3">Checking for updates...</p>
      ) : check.isError ? (
        <p className="py-1 text-sm text-err">Could not check for updates.</p>
      ) : (
        <StatusRow
          label="Status"
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
          <Button variant="accent" onClick={onApply} disabled={apply.isPending}>
            {apply.isPending ? "Applying..." : "Apply Update"}
          </Button>
        ) : null}
        <Button
          small
          onClick={() => check.refetch()}
          disabled={check.isFetching}
        >
          Check Again
        </Button>
      </div>
    </Section>
  );
}
