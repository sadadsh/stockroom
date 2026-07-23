/**
 * TanStack Query hooks over the API client. Server state lives here so the page
 * stays declarative: change the search/category/completeOnly and the list
 * refetches; select a part and the detail loads. keepPreviousData keeps the list
 * from flickering to empty while a new search is in flight.
 */
import { useCallback, useEffect } from "react";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type {
  ConformBody,
  DesignRules,
  EnrichmentResult,
  FieldEdit,
  ManualFillBody,
  NetClass,
  PartDetail,
  SetBoardSettingsBody,
  SetLibraryBody,
  SettingsPatch,
  StackupBody,
} from "./types";
import { api, type ListPartsArgs, type SearchArgs } from "./client";
import { useJob } from "../lib/useJob";

// First-run library onboarding (M9c). Set/complete repoint the running engine at a
// different library, so EVERY server query is invalidated (parts, projects, facets, ...).
export function useOnboarding() {
  return useQuery({
    queryKey: ["onboarding"],
    queryFn: () => api.getOnboarding(),
    retry: false,
  });
}

export function useSetLibrary() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SetLibraryBody) => api.setLibrary(body),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useCompleteOnboarding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.completeOnboarding(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["onboarding"] }),
  });
}

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

// The modular search rail's filter dimensions, generated from the parts' specs and scoped by
// the current query/category so the counts track what the list shows. Its own key (not
// ["facets"]) so a normal facet invalidation and this can refetch independently.
export function useParametricFacets(args: SearchArgs, enabled = true) {
  return useQuery({
    queryKey: [
      "parametric-facets",
      args.q ?? "",
      args.category ?? "",
      !!args.completeOnly,
      [...(args.spec ?? [])].sort().join("|"),
    ],
    queryFn: () => api.parametricFacets(args),
    enabled,
    placeholderData: keepPreviousData,
  });
}

// The rich search results (specs + sourcing per row) for the results table. `spec` is part of
// the key so toggling any facet refetches; disabled while the overlay is closed so it costs
// nothing until opened.
export function useSearchQuery(args: SearchArgs, enabled = true) {
  return useQuery({
    queryKey: [
      "search",
      args.q ?? "",
      args.category ?? "",
      !!args.completeOnly,
      [...(args.spec ?? [])].sort().join("|"),
    ],
    queryFn: () => api.searchParts(args),
    enabled,
    placeholderData: keepPreviousData,
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

// The CAD source + capture needs for a part (guided capture, spec section 5). Feeds
// the both-format checklist its `needs` and the Get CAD Files control its target URL.
// Kept separate from useGuidedCapture's OWN cad-source GET (fired again right before
// opening the remote page): this one only decides what the checklist shows, so a stale
// cached answer here can never open a dead page - the hook always re-resolves fresh at
// click time.
export function useCadSourceQuery(id: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["cad-source", id],
    queryFn: () => api.partCadSource(id as string),
    enabled: enabled && !!id,
    staleTime: 60_000,
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

// Attach a symbol / footprint reference to an existing part (assets no longer gate
// entry, so they are attached after the part lands). A write commits and can change
// the footprint-duplicate set, so it invalidates the same derived caches as any other
// write (list, facets, duplicates, the affected detail, the grown git timeline).
export function useAttachSymbol() {
  const invalidate = useInvalidateAfterWrite();
  return useMutation({
    mutationFn: (vars: { id: string; lib: string; name: string; tool?: string }) =>
      api.attachSymbol(vars.id, vars.lib, vars.name, vars.tool),
    onSuccess: (_data, vars) => invalidate(vars.id),
  });
}

export function useAttachFootprint() {
  const invalidate = useInvalidateAfterWrite();
  return useMutation({
    mutationFn: (vars: { id: string; lib: string; name: string; tool?: string }) =>
      api.attachFootprint(vars.id, vars.lib, vars.name, vars.tool),
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

// The per-part sourcing refresh is a WRITE-lane job (the record commits server-side with
// fresh price/stock/lifecycle), streamed over SSE like every job. When it finishes it
// invalidates the same views as any other part write, so refreshed procurement can never
// linger stale in the list, the facets, the open detail, or the timeline.
export function useRefreshSourcing(id: string) {
  const invalidate = useInvalidateAfterWrite();
  const job = useJob<PartDetail>();
  const run = useCallback(() => job.start(() => api.refreshSourcing(id)), [job, id]);
  const done = job.status === "done";
  useEffect(() => {
    if (done) invalidate(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- invalidate is a fresh
    // closure every render; done/id are the real triggers.
  }, [done, id]);
  return { ...job, run };
}

// Enrichment is a lookup, not a write: it returns sourced fields without touching the
// record, so there is nothing to invalidate here. Applying a candidate goes through
// useEditField, which does the read-after-write invalidation. It runs as a background job
// (the render tier can take seconds), so this streams the live fetching/rendering/
// extracting/validating stages and exposes the sourced EnrichmentResult on `result`.
export function useEnrichLookup() {
  const job = useJob<EnrichmentResult>();
  const runPart = useCallback(
    (mpn: string, category?: string, want?: string[]) =>
      job.start(() => api.enrichPart(mpn, category, want)),
    [job],
  );
  const runUrl = useCallback((url: string) => job.start(() => api.enrichFromUrl(url)), [job]);
  return { ...job, runPart, runUrl };
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

// Add a passive with no files (an MPN or a Mouser URL). A new part changes the
// parts list and the category/manufacturer facets, so refresh both.
export function usePassiveAdd() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: import("./types").PassiveAddBody) => api.passiveAdd(body),
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
    // The render shells out to kicad-cli; a cold first call can be slow or transiently
    // fail. Retry (instead of sticking on the fallback glyph forever) so the real
    // symbol/footprint replaces the placeholder once the render warms up.
    retry: 2,
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
    retry: 2,
  });
}

// Stock previews by footprint lib_id (the Add-A-Part flow shows a passive's built-in
// footprint + 3D model before it is committed, so there is no part id to key on).
export function useStockPreviewSvg(fp: string, enabled = true) {
  return useQuery({
    queryKey: ["stock-preview-svg", fp],
    queryFn: () => api.stockPreviewSvg(fp),
    enabled: enabled && !!fp,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useStockModelGlb(fp: string, enabled: boolean) {
  return useQuery({
    queryKey: ["stock-preview-glb", fp],
    queryFn: () => api.stockModelGlb(fp),
    enabled: enabled && !!fp,
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
    mutationFn: (patch: SettingsPatch) => api.updateSettings(patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
}

export function useLoadDevCreds() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.loadDevCreds(),
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
      // the Altium DbLib status is per-profile (path, counts, profile name), so a switch must
      // refetch it or the section shows the previous profile's data
      qc.invalidateQueries({ queryKey: ["altium-status"] });
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
        qc.invalidateQueries({ queryKey: ["altium-status"] });
      }
    },
  });
}

// The rail mounts this on boot, so the check must keep running on its own - otherwise a
// release pushed AFTER the app opened never surfaces until something else remounts the query
// (the reported bug: the Update pill only appeared after opening Settings, whose own observer
// forced a refetch). Each check does a real `git fetch` + ahead/behind, so re-run it on a modest
// interval and whenever the window regains focus; a stale window then discovers a new release
// within a couple minutes without any navigation. staleTime dedupes the boot + Settings observers.
export function useUpdateCheck() {
  return useQuery({
    queryKey: ["update-check"],
    queryFn: () => api.checkUpdate(),
    refetchInterval: 2 * 60_000,
    refetchOnWindowFocus: true,
    staleTime: 60_000,
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

// The last-known library-wide rescan state (Phase-1b-3), for the idle "last refreshed"
// summary. Read-only; the rescan job itself invalidates this (in useRescan) once its
// terminal result lands, so the summary is fresh the next time this is read.
export function useRescanState() {
  return useQuery({ queryKey: ["rescan-state"], queryFn: () => api.getRescanState() });
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

// Re-cost the cached BOM for a new build quantity / tax rate, purely over the already-built
// lines: synchronous, no job, no SSE. Unlike most mutations here this does NOT invalidate on
// success itself; the result IS the fresh BOM, so the caller writes it straight into
// ["project-bom", id] via setQueryData (a refetch would just re-fetch what is already in
// hand) and invalidates the procurement/diff caches that depend on it.
export function useRepriceBom() {
  return useMutation({
    mutationFn: ({ id, boards, tax_rate }: { id: string; boards?: number; tax_rate?: number }) =>
      api.repriceBom(id, { boards, tax_rate }),
  });
}

// The M7g ready-to-build verdict: completeness + ERC/DRC + BOM + git fused. Read-only; the
// section reactively refetches it when the checks/BOM caches change so it never disagrees
// with the sections below.
export function useBuildability(id: string | null) {
  return useQuery({
    queryKey: ["project-buildability", id],
    queryFn: () => api.getBuildability(id as string),
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

// The Fab panel's honest gate (M7i): board presence + kicad-cli availability. Disabled until a
// project is selected.
export function useProjectFab(id: string | null) {
  return useQuery({
    queryKey: ["project-fab", id],
    queryFn: () => api.getFab(id as string),
    enabled: !!id,
  });
}

// Raw text of one registered project KiCad file, for the kicanvas viewer (M7 #11). Disabled
// until both an id and a path are set; a project file rarely changes mid-session so it is cached.
export function useProjectFile(id: string | null, path: string | null) {
  return useQuery({
    queryKey: ["project-file", id, path],
    queryFn: () => api.projectFile(id as string, path as string),
    enabled: !!id && !!path,
    staleTime: 5 * 60 * 1000,
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

// A netclass-pattern write invalidates the design read (re-reads the committed patterns) and
// the project detail; it also evicts the cached ERC/DRC server-side (a pattern change alters
// DRC net grouping), so the checks query is invalidated to re-read the honest not-run shape.
export function useSetNetclassPatterns() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; patterns: { netclass: string; pattern: string }[] }) =>
      api.setNetclassPatterns(vars.id, vars.patterns),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["project-design", vars.id] });
      qc.invalidateQueries({ queryKey: ["project", vars.id] });
      qc.invalidateQueries({ queryKey: ["project-checks", vars.id] });
    },
  });
}

// --- M7h KiField bulk-field editor ---

// The project's derived rows-by-fields grid. Disabled until a project is selected.
export function useProjectFields(id: string | null) {
  return useQuery({
    queryKey: ["project-fields", id],
    queryFn: () => api.getFields(id as string),
    enabled: !!id,
  });
}

// A field write invalidates the grid read (re-reads the committed values), the project detail,
// and the ERC/DRC + BOM reads: a field change (Value/Footprint/MPN) alters the netlist/BOM, and
// the server evicts those caches, so the queries re-read the honest not-run / rebuild shape.
export function useSetFields() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; edits: FieldEdit[] }) => api.setFields(vars.id, vars.edits),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["project-fields", vars.id] });
      qc.invalidateQueries({ queryKey: ["project", vars.id] });
      qc.invalidateQueries({ queryKey: ["project-checks", vars.id] });
      qc.invalidateQueries({ queryKey: ["project-bom", vars.id] });
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
    mutationFn: (vars: { id: string } & SetBoardSettingsBody) => {
      const { id, ...body } = vars;
      return api.setBoardSettings(id, body);
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["project-settings", vars.id] });
      qc.invalidateQueries({ queryKey: ["project", vars.id] });
      qc.invalidateQueries({ queryKey: ["project-checks", vars.id] });
    },
  });
}

// The object-conform catalog + honest state for a project (M7f-B), read once for the editor.
export function useProjectConform(id: string | null) {
  return useQuery({
    queryKey: ["project-conform", id],
    queryFn: () => api.getConform(id as string),
    enabled: !!id,
  });
}

// A conform preview is a pure dry-run: no cache is touched (it neither writes nor commits).
export function usePreviewConform() {
  return useMutation({
    mutationFn: (vars: { id: string } & ConformBody) => {
      const { id, ...body } = vars;
      return api.previewConform(id, body);
    },
  });
}

// Applying a conform re-reads the catalog/state and the project detail, and evicts the cached
// ERC/DRC server-side (a text size/thickness change can alter DRC), so the checks query is
// invalidated to re-read the honest not-run shape rather than a stale pass.
export function useApplyConform() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string } & ConformBody) => {
      const { id, ...body } = vars;
      return api.applyConform(id, body);
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["project-conform", vars.id] });
      qc.invalidateQueries({ queryKey: ["project", vars.id] });
      qc.invalidateQueries({ queryKey: ["project-checks", vars.id] });
    },
  });
}

// The stackup + copper layers + thickness + fab-preset catalog for a project (M7f-C).
export function useProjectStackup(id: string | null) {
  return useQuery({
    queryKey: ["project-stackup", id],
    queryFn: () => api.getStackup(id as string),
    enabled: !!id,
  });
}

// A stackup preview is a pure dry-run: no cache is touched (it neither writes nor commits).
export function usePreviewStackup() {
  return useMutation({
    mutationFn: (vars: { id: string } & StackupBody) => {
      const { id, ...body } = vars;
      return api.previewStackup(id, body);
    },
  });
}

// Applying a stackup change re-reads the stackup + project detail and evicts the cached ERC/DRC
// (a stackup/thickness change can alter DRC/impedance), so the checks query is invalidated to
// re-read the honest not-run shape rather than a stale pass.
export function useApplyStackup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string } & StackupBody) => {
      const { id, ...body } = vars;
      return api.applyStackup(id, body);
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["project-stackup", vars.id] });
      qc.invalidateQueries({ queryKey: ["project", vars.id] });
      qc.invalidateQueries({ queryKey: ["project-checks", vars.id] });
    },
  });
}

// A dry-run of Prepare / Complete-All for one project (M7f-D): what a Prepare would annotate + fill
// from the library + leave incomplete. Disabled until a project is selected.
export function useProjectPrepare(id: string | null) {
  return useQuery({
    queryKey: ["project-prepare", id],
    queryFn: () => api.getPrepare(id as string),
    enabled: !!id,
  });
}

// Invalidate everything a Prepare / Fill / Restore changes: the prepare dry-run (fewer refs remain),
// the project detail (git head moved), and the cached ERC/DRC + BOM (the netlist/BOM changed, so a
// stale pass is evicted and re-read as the honest not-run/not-built shape). Also the revision list.
function useInvalidateAfterPrepare() {
  const qc = useQueryClient();
  // Memoize so the returned function has a STABLE identity: it is a useEffect dependency in
  // PrepareForm, and a fresh closure each render would re-fire the effect (a redundant invalidation
  // round) on every render while the job sits in "done".
  return useCallback(
    (id: string) => {
      qc.invalidateQueries({ queryKey: ["project-prepare", id] });
      qc.invalidateQueries({ queryKey: ["project", id] });
      qc.invalidateQueries({ queryKey: ["project-checks", id] });
      qc.invalidateQueries({ queryKey: ["project-bom", id] });
      qc.invalidateQueries({ queryKey: ["project-revisions", id] });
    },
    [qc],
  );
}

export { useInvalidateAfterPrepare };

// Manually link one placed component to a chosen library part (M7f-D). Invalidates the prepare
// dry-run + the derived caches so the residual re-reads after the fill.
export function useManualFill() {
  const invalidate = useInvalidateAfterPrepare();
  return useMutation({
    mutationFn: (vars: { id: string } & ManualFillBody) => {
      const { id, ...body } = vars;
      return api.manualFill(id, body);
    },
    onSuccess: (_data, vars) => invalidate(vars.id),
  });
}

// Undo the project's last Prepare / Fill (M7f-D). Invalidates the same derived caches.
export function useRestore() {
  const invalidate = useInvalidateAfterPrepare();
  return useMutation({
    mutationFn: (id: string) => api.restore(id),
    onSuccess: (_data, id) => invalidate(id),
  });
}

// The Altium Database Library status for the active profile (place-ready count + per-part rows).
export function useAltiumStatus() {
  return useQuery({ queryKey: ["altium-status"], queryFn: () => api.altiumStatus() });
}

// Whether the machine's 64-bit SQLite3 ODBC driver is registered. Machine-level (not per-profile),
// and it changes out-of-band when the user runs the installer, so re-check on window focus: after
// installing in the opened browser and returning to the app, the section reflects it without a
// manual refresh.
export function useOdbcStatus() {
  return useQuery({
    queryKey: ["altium-odbc-status"],
    queryFn: () => api.altiumOdbcStatus(),
    refetchOnWindowFocus: true,
  });
}

// Regenerate the DbLib over every place-ready part. A write (commits + may push), so it refreshes
// the status the count is read from.
export function useAltiumRegenerate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.altiumRegenerate(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["altium-status"] }),
  });
}

// Attach a part's Altium assets by native paths, then the part becomes place-ready. Invalidates
// the Altium status plus the part list/detail (the record gained altium refs).
export function useAltiumAttach() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; paths: string[] }) => api.altiumAttach(vars.id, vars.paths),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["altium-status"] });
      qc.invalidateQueries({ queryKey: ["parts"] });
      qc.invalidateQueries({ queryKey: ["part", vars.id] });
    },
  });
}
