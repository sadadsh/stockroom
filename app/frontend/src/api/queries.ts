/**
 * TanStack Query hooks over the API client. Server state lives here so the page
 * stays declarative: change the search/category/completeOnly and the list
 * refetches; select a part and the detail loads. keepPreviousData keeps the list
 * from flickering to empty while a new search is in flight.
 */
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { BoardSetupValue, DesignRules, NetClass } from "./types";
import { api, type ListPartsArgs } from "./client";

export function usePartsQuery(args: ListPartsArgs) {
  return useQuery({
    queryKey: ["parts", args.q ?? "", args.category ?? "", !!args.completeOnly],
    queryFn: () => api.listParts(args),
    placeholderData: keepPreviousData,
  });
}

export function useFacetsQuery() {
  return useQuery({
    queryKey: ["facets"],
    queryFn: () => api.facets(),
  });
}

// The duplicates surface (M6e). Any write can change the duplicate set (editing an
// MPN, deleting a member), so every mutation below also invalidates this key.
export function useDuplicates() {
  return useQuery({
    queryKey: ["duplicates"],
    queryFn: () => api.getDuplicates(),
  });
}

export function usePartDetailQuery(id: string | null) {
  return useQuery({
    queryKey: ["part", id],
    queryFn: () => api.partDetail(id as string),
    enabled: !!id,
  });
}

// The per-part git timeline (M6k). Read-only; a mutation invalidates the affected
// detail, and any write also grows this timeline, so it is invalidated alongside the
// detail after a write (see useInvalidateAfterWrite below).
export function usePartHistory(id: string | null) {
  return useQuery({
    queryKey: ["part-history", id],
    queryFn: () => api.partHistory(id as string),
    enabled: !!id,
  });
}

// The field-diff between two revs (M6k). `a` may be "" (the earliest side); `b` is
// the commit being inspected, so the query is disabled until one is chosen.
export function usePartDiff(id: string | null, a: string, b: string | null) {
  return useQuery({
    queryKey: ["part-diff", id, a, b],
    queryFn: () => api.partDiff(id as string, a, b as string),
    enabled: !!id && !!b,
  });
}

// A mutation rebuilds the derived index server-side, so after any write we
// invalidate the list, the facets, and the affected detail to read-after-write.
function useInvalidateAfterWrite() {
  const qc = useQueryClient();
  return (id: string) => {
    qc.invalidateQueries({ queryKey: ["parts"] });
    qc.invalidateQueries({ queryKey: ["facets"] });
    qc.invalidateQueries({ queryKey: ["duplicates"] });
    qc.invalidateQueries({ queryKey: ["part", id] });
    // a write commits, so the part's git timeline (M6k) gained an entry
    qc.invalidateQueries({ queryKey: ["part-history", id] });
  };
}

export function useEditField() {
  const invalidate = useInvalidateAfterWrite();
  return useMutation({
    mutationFn: (vars: { id: string; field: string; value: unknown }) =>
      api.editField(vars.id, vars.field, vars.value),
    onSuccess: (_data, vars) => invalidate(vars.id),
  });
}

export function useMoveCategory() {
  const invalidate = useInvalidateAfterWrite();
  return useMutation({
    mutationFn: (vars: { id: string; category: string }) =>
      api.moveCategory(vars.id, vars.category),
    onSuccess: (_data, vars) => invalidate(vars.id),
  });
}

export function useDeletePart() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deletePart(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["parts"] });
      qc.invalidateQueries({ queryKey: ["facets"] });
      qc.invalidateQueries({ queryKey: ["duplicates"] });
      qc.removeQueries({ queryKey: ["part", id] });
      qc.removeQueries({ queryKey: ["part-history", id] });
    },
  });
}

// Persisting specs (e.g. an enriched pinout) writes only the record JSON; specs
// are not indexed, so only the affected detail needs to re-read (never the list or
// facets). Mirrors the doctor-repair rule: invalidate exactly what changed.
export function useSetSpecs() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: {
      id: string;
      specs: Record<string, { value: unknown; source?: string; confidence?: string }>;
      overwrite?: boolean;
    }) => api.setSpecs(vars.id, vars.specs, vars.overwrite),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["part", vars.id] });
      // persisting specs commits, so the part's git timeline (M6k) gained an entry
      qc.invalidateQueries({ queryKey: ["part-history", vars.id] });
    },
  });
}

// Enrichment is a lookup, not a write: it returns sourced candidates without
// touching the record, so there is nothing to invalidate here. Applying a
// candidate goes through useEditField, which does the read-after-write invalidation.
export function useEnrichPart() {
  return useMutation({
    mutationFn: (vars: { mpn: string; category?: string; want?: string[] }) =>
      api.enrichPart(vars.mpn, vars.category, vars.want),
  });
}

// Committing a staging candidate adds a real part, so it invalidates the list and
// facets (the new part must appear in Components). A gate failure rejects with an
// ApiError carrying `missing`; the caller surfaces that, so no invalidation runs.
export function useIngestCommit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (candidate: import("./types").StagingCandidate) =>
      api.ingestCommit(candidate),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["parts"] });
      qc.invalidateQueries({ queryKey: ["facets"] });
    },
  });
}

// --- Previews (M6d): symbol/footprint SVG + 3D model GLB ---

// Read-only binary blobs rendered by the backend and cached there by content hash,
// so the client keeps them a while and never retries an honest 404 (no symbol) or 502
// (no 3D tooling). The viewer creates + revokes the object URL from the blob itself.
export function usePreviewSvg(
  kind: "symbol" | "footprint",
  id: string,
  opts: { rev?: string; enabled?: boolean } = {},
) {
  const rev = opts.rev ?? "";
  const enabled = opts.enabled ?? true;
  return useQuery({
    // rev is part of the key so an old-revision render (M6k overlay) caches apart from
    // the current one and switching revs refetches.
    queryKey: ["preview-svg", kind, id, rev],
    queryFn: () => api.previewSvg(kind, id, rev || undefined),
    enabled: enabled && !!id,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

// The 3D GLB is heavier (a STEP tessellation) so it is fetched only when the 3D view
// is actually open (enabled), never eagerly with the detail panel.
export function usePreviewGlb(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ["preview-glb", id],
    queryFn: () => api.modelGlb(id),
    enabled: enabled && !!id,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

// --- Settings page server state (M6g) ---

export function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => api.getSettings() });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: { mouser_api_key?: string }) => api.updateSettings(patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
}

export function useProfiles() {
  return useQuery({ queryKey: ["profiles"], queryFn: () => api.listProfiles() });
}

export function useSystemInfo() {
  return useQuery({ queryKey: ["system"], queryFn: () => api.getSystemInfo() });
}

export function useCreateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { name: string; archive?: boolean }) =>
      api.createProfile(vars.name, vars.archive),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profiles"] }),
  });
}

// Activating a profile swaps the whole library, so the parts list, facets, and
// the system readout (active_profile, part_count) all change under it. Refresh
// them alongside the profile list rather than leaving a stale Components view.
export function useActivateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.activateProfile(name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profiles"] });
      qc.invalidateQueries({ queryKey: ["system"] });
      qc.invalidateQueries({ queryKey: ["parts"] });
      qc.invalidateQueries({ queryKey: ["facets"] });
    },
  });
}

export function useDeleteProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.deleteProfile(name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profiles"] }),
  });
}

export function useSyncStatus() {
  return useQuery({
    queryKey: ["sync-status"],
    queryFn: () => api.getSyncStatus(),
  });
}

// A sync that pulled new commits changed the library on disk, so the parts view
// must refresh; a no-op/up-to-date sync leaves the parts view untouched (only the
// sync status changes). Either way the status readout is refreshed.
export function useDoSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.doSync(),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["sync-status"] });
      if (result.pulled) {
        qc.invalidateQueries({ queryKey: ["parts"] });
        qc.invalidateQueries({ queryKey: ["facets"] });
      }
    },
  });
}

export function useUpdateCheck() {
  return useQuery({
    queryKey: ["update-check"],
    queryFn: () => api.checkUpdate(),
  });
}

export function useApplyUpdate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.applyUpdate(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["update-check"] }),
  });
}

// --- Doctor page server state (M6f) ---

// The library-health scan. Read-only, so it just fetches; the repair mutation below
// invalidates it so the page reflects the healed state the moment repair returns.
export function useDoctorScan() {
  return useQuery({ queryKey: ["doctor-scan"], queryFn: () => api.scanDoctor() });
}

// Repair heals drift + rewrites non-portable model links + commits stray files in one
// scoped commit. It changes what the scan reports, but NOT the derived index (the JSON
// records are the source of truth and are left untouched), so it invalidates only the
// doctor scan, never the parts list or facets.
export function useRepairLibrary() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.repairLibrary(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["doctor-scan"] }),
  });
}

// --- Projects page server state (M7a) ---

// The registered-project list, served warm from the derived project index. Register
// and delete rebuild that index server-side, so both mutations invalidate ["projects"].
export function useProjectsQuery() {
  return useQuery({ queryKey: ["projects"], queryFn: () => api.listProjects() });
}

// The full canonical record for one project. Disabled until a project is selected.
export function useProjectQuery(id: string | null) {
  return useQuery({
    queryKey: ["project", id],
    queryFn: () => api.getProject(id as string),
    enabled: !!id,
  });
}

// The read-only health audit for one project. Disabled until a project is selected;
// it reads against the ACTIVE profile's footprint/model dirs at request time.
export function useProjectAudit(id: string | null) {
  return useQuery({
    queryKey: ["project-audit", id],
    queryFn: () => api.projectAudit(id as string),
    enabled: !!id,
  });
}

// The cached last ERC/DRC run for one project (M7b). Disabled until a project is
// selected; it returns an honest not-run shape (ran_at null) before the first run.
export function useProjectChecks(id: string | null) {
  return useQuery({
    queryKey: ["project-checks", id],
    queryFn: () => api.getChecks(id as string),
    enabled: !!id,
  });
}

// The cached last BOM build for one project (M7c). Disabled until a project is selected;
// it returns an honest not-built shape (ran_at null) before the first build.
export function useProjectBom(id: string | null) {
  return useQuery({
    queryKey: ["project-bom", id],
    queryFn: () => api.getBom(id as string),
    enabled: !!id,
  });
}

// The procurement view (M7d) over the cached BOM: per-line orderability + sourcing/stock
// risk + lead time. Disabled until a project is selected; an honest not-built shape before a
// build. Invalidated when the BOM (re)builds so it re-reads the fresh sourcing data.
export function useProjectProcurement(id: string | null) {
  return useQuery({
    queryKey: ["project-procurement", id],
    queryFn: () => api.getProcurement(id as string),
    enabled: !!id,
  });
}

// The project's git history (M7d) for the revision-diff pickers. Disabled until a project is
// selected; under_git false / empty for a project not under git.
export function useProjectRevisions(id: string | null) {
  return useQuery({
    queryKey: ["project-revisions", id],
    queryFn: () => api.getRevisions(id as string),
    enabled: !!id,
  });
}

// The BOM diff between revision `a` and `b` (blank = the current build) (M7d). Disabled until
// a revision A is chosen; keyed on both revs so switching either re-fetches. A BOM (re)build
// invalidates ["project-diff", id] so the cost/lead deltas re-read the fresh prices.
export function useBomDiff(id: string, a: string | null, b: string) {
  return useQuery({
    queryKey: ["project-diff", id, a, b],
    queryFn: () => api.getBomDiff(id, a as string, b),
    enabled: !!a,
  });
}

// Registering a project rebuilds the project index server-side, so the list must
// re-read to show the new project. Nothing else in the app reads project state.
export function useRegisterProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (root: string) => api.registerProject(root),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

// Deleting a project rebuilds the index (invalidate the list) and removes the now-gone
// project's detail + audit caches so a stale selection never reads a deleted record.
export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteProject(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.removeQueries({ queryKey: ["project", id] });
      qc.removeQueries({ queryKey: ["project-audit", id] });
      qc.removeQueries({ queryKey: ["project-checks", id] });
      qc.removeQueries({ queryKey: ["project-bom", id] });
      qc.removeQueries({ queryKey: ["project-procurement", id] });
      qc.removeQueries({ queryKey: ["project-revisions", id] });
      qc.removeQueries({ queryKey: ["project-design", id] });
      qc.removeQueries({ queryKey: ["project-settings", id] });
    },
  });
}

// --- Editor: design rules + net classes (M7e) ---

// The project's current net classes + design rules read from its .kicad_pro, validated
// against the chosen fab floor (keyed on the floor so switching it re-reads). Disabled
// until a project is selected.
export function useProjectDesign(id: string | null, floor: string) {
  return useQuery({
    queryKey: ["project-design", id, floor],
    queryFn: () => api.getDesign(id as string, floor),
    enabled: !!id,
    // The floor is part of the key, so switching it is a DIFFERENT cache entry, not a
    // refetch. keepPreviousData holds the prior floor's data on screen while the new one
    // loads, so the Editor never unmounts (and never re-seeds) mid-fetch on a floor change.
    placeholderData: keepPreviousData,
  });
}

// A net-class / design-rule write invalidates the design read (re-reads the committed
// classes + fresh validation) and the project detail; it also evicts the cached ERC/DRC
// server-side (a rules change can alter DRC), so the checks query is invalidated to re-read
// the honest not-run shape rather than a stale pass.
export function useSetNetClasses() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; classes: NetClass[]; deleted: string[]; floor: string }) =>
      api.setNetClasses(vars.id, vars.classes, { deleted: vars.deleted, floor: vars.floor }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["project-design", vars.id] });
      qc.invalidateQueries({ queryKey: ["project", vars.id] });
      qc.invalidateQueries({ queryKey: ["project-checks", vars.id] });
    },
  });
}

export function useSetDesignRules() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: {
      id: string;
      rules: DesignRules;
      track_widths?: unknown[];
      via_dimensions?: unknown[];
      diff_pair_dimensions?: unknown[];
    }) =>
      api.setDesignRules(vars.id, vars.rules, {
        track_widths: vars.track_widths,
        via_dimensions: vars.via_dimensions,
        diff_pair_dimensions: vars.diff_pair_dimensions,
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["project-design", vars.id] });
      qc.invalidateQueries({ queryKey: ["project", vars.id] });
      qc.invalidateQueries({ queryKey: ["project-checks", vars.id] });
    },
  });
}

// --- Editor: board setup + thickness (M7f-A) ---

// The project's current board setup + overall thickness read from its primary .kicad_pcb,
// with the effective via-protection defaults filled server-side. Disabled until a project
// is selected.
export function useProjectSettings(id: string | null) {
  return useQuery({
    queryKey: ["project-settings", id],
    queryFn: () => api.getBoardSettings(id as string),
    enabled: !!id,
  });
}

// A board-setup / thickness write re-reads the committed settings and the project detail,
// and evicts the cached ERC/DRC server-side (a board-setup change can alter DRC), so the
// checks query is invalidated to re-read the honest not-run shape rather than a stale pass.
export function useSetProjectSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: {
      id: string;
      board_setup?: Record<string, BoardSetupValue>;
      thickness?: number;
    }) =>
      api.setBoardSettings(vars.id, { board_setup: vars.board_setup, thickness: vars.thickness }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["project-settings", vars.id] });
      qc.invalidateQueries({ queryKey: ["project", vars.id] });
      qc.invalidateQueries({ queryKey: ["project-checks", vars.id] });
    },
  });
}
