/**
 * Settings (spec sections 5.3, 9, 11, 12): the per-machine controls that live
 * outside the library. Appearance (the theme toggle), library profiles (switch,
 * create, delete), library sync, the KiCad wiring status, the Mouser API key, and
 * the app self-update. Every section is honest about its state: offline/divergence
 * and a missing kicad-cli are surfaced verbatim, never faked green, and the Mouser
 * key is only ever shown as a last-4 hint.
 */
import { useState, type ReactNode } from "react";
import { ApiError } from "../api/client";
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
import { Badge, Button, Card, Eyebrow } from "../components/primitives";
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
    <>
      <div className="flex h-14 flex-none items-center px-[18px]">
        <div className="text-lg font-semibold text-t1">Settings</div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-[30px] pt-[22px]">
        <div className="max-w-[720px] pb-12">
          <AppearanceSection />
          <ProfilesSection />
          <SyncSection />
          <GitHubSection />
          <KiCadSection />
          <DistributorSection />
          <UpdateSection />
        </div>
      </div>
    </>
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
      title="Library Profiles"
      hint="Each profile is a separate library on disk. Switching one reloads the whole component view."
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
          toast("Sync failed: the library has diverged from its remote.", "err");
          return;
        }
        if (r.state === "offline") {
          toast("Sync failed: the remote is unreachable.", "err");
          return;
        }
        if (r.state === "denied") {
          toast(
            "Sync failed: cannot sign in to the library remote (a private repo, or missing git credentials). Check the repo access or its URL.",
            "err",
          );
          return;
        }
        if (r.state === "no_remote") {
          toast("No remote is configured for this library.", "neutral");
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
      title="Library Sync"
      hint="Pull and push the library repository. Offline and divergence are reported, never guessed."
    >
      {status.isLoading ? (
        <p className="py-1 text-sm text-t3">Checking sync status...</p>
      ) : status.isError ? (
        <p className="py-1 text-sm text-err">Could not read sync status.</p>
      ) : status.data ? (
        <>
          <StatusRow label="Branch" value={<span>{status.data.current_branch}</span>} />
          <StatusRow
            label="Remote"
            value={
              status.data.has_remote
                ? `${status.data.ahead} ahead, ${status.data.behind} behind`
                : "No remote configured"
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
              ? "KiCad settings applied. The library is wired."
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
      hint="Where the app writes KiCad library tables, and whether the command-line tools that render previews were found. Wiring runs automatically on launch and on every profile or library switch. Leave the overrides blank to auto-detect."
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
            label="Library Wiring"
            value={
              settings.isLoading ? (
                "Loading..."
              ) : settings.data?.kicad_wired ? (
                <span className="text-ok">Wired to the active library</span>
              ) : (
                <span className="text-warn">
                  Not wired yet (the Doctor page can wire it manually)
                </span>
              )
            }
          />
        </>
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
      hint="Connect a GitHub personal access token so adding or editing a part pushes it to the library repo automatically, and collaborators' changes pull in on launch. Create a fine-grained token with Contents: write on the library repo. Each collaborator connects their own token (and needs write access, granted by the repo owner). Stored per machine, never shown again."
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
          value={available ? "Update available" : "Up to date"}
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
