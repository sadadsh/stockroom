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
  EnrichmentResult,
  PartDetail,
  SetLibraryBody,
  SettingsPatch,
} from "./types";
import { api, type ListPartsArgs, type SearchArgs } from "./client";
import { useJob } from "../lib/useJob";

// First-run library onboarding (M9c). Set/complete repoint the running engine at a
// different library, so EVERY server query is invalidated.
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

// The app reconciles with the remote in the background now (AppContext.start_background_sync), so
// a collaborator's part can land in the library while this window is open. Without a refetch the
// list would still only change on navigation, and the owner's complaint - "it shouldnt need to
// relaunch" - would be half-answered: pulled on disk, invisible on screen.
//
// Same shape and the same reasoning as useUpdateCheck below, which already runs on an interval for
// exactly this class of bug. `refetchOnWindowFocus` is what makes the common case feel instant:
// coming back to the window after adding a part elsewhere shows it immediately.
export function usePartsQuery(args: ListPartsArgs) {
  return useQuery({
    queryKey: ["parts", args.q ?? "", args.category ?? "", !!args.completeOnly],
    queryFn: () => api.listParts(args),
    placeholderData: keepPreviousData,
    refetchInterval: 2 * 60_000,
    refetchOnWindowFocus: true,
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

// Removing one element is a write like any other; the altium status and the capture
// needs both change with it, so those refresh too.
export function useDetachAsset() {
  const invalidate = useInvalidateAfterWrite();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; kind: string }) => api.detachAsset(vars.id, vars.kind),
    onSuccess: (_data, vars) => {
      invalidate(vars.id);
      qc.invalidateQueries({ queryKey: ["altium-status"] });
      qc.invalidateQueries({ queryKey: ["cad-source", vars.id] });
    },
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

// The land pattern behind the viewer's Footprint toggle. Fetched only alongside an open 3D view,
// and never retried: a part with no footprint legitimately 404s, and that is a hidden toggle, not
// an error worth three round trips.
export function useLandPattern(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ["land-pattern", id],
    queryFn: () => api.landPattern(id),
    enabled: enabled && !!id,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

// The pulled product photo through the backend proxy (the ProductPhoto fallback lane).
// Keyed by the vendor URL; a proxied miss (400/404) is an honest "no image" - do not
// hammer the vendor CDN with retries, and keep the answer for the session.
export function useProductImage(url: string, enabled: boolean) {
  return useQuery({
    queryKey: ["product-image", url],
    queryFn: () => api.productImage(url),
    enabled: enabled && !!url,
    staleTime: 60 * 60_000,
    retry: false,
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

// Where the LIBRARY's binary payloads are stored, and what the library repo is still sharing that
// it should not. Both are library-repo facts, so they invalidate together after either action.
export function useLibraryLfs() {
  return useQuery({ queryKey: ["library-lfs"], queryFn: () => api.getLibraryLfs() });
}

export function useLibraryHygiene() {
  return useQuery({ queryKey: ["library-hygiene"], queryFn: () => api.getLibraryHygiene() });
}

function useInvalidateLibrarySync() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["library-lfs"] });
    qc.invalidateQueries({ queryKey: ["library-hygiene"] });
    // both commit to the library repo, so its history and sync state move too
    qc.invalidateQueries({ queryKey: ["sync-status"] });
    qc.invalidateQueries({ queryKey: ["library-history"] });
  };
}

export function useAdoptLibraryLfs() {
  const invalidate = useInvalidateLibrarySync();
  return useMutation({ mutationFn: () => api.adoptLibraryLfs(), onSuccess: invalidate });
}

export function useSyncLibraryHygiene() {
  const invalidate = useInvalidateLibrarySync();
  return useMutation({ mutationFn: () => api.syncLibraryHygiene(), onSuccess: invalidate });
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

// Whether a 3D embed can run on this machine. Machine-level like the ODBC check, and it changes
// out-of-band (the user closes Altium, freeing the license seat), so re-check on window focus:
// coming back to the app after closing Altium must enable the action without a manual refresh.
export function useAltiumEmbedCapability() {
  return useQuery({
    queryKey: ["altium-embed-capability"],
    queryFn: () => api.altiumEmbedCapability(),
    refetchOnWindowFocus: true,
  });
}

// Embed a part's 3D model into its Altium footprint's .PcbLib by driving the installed Altium.
// Slow by nature (Altium boots), so the caller shows a pending state rather than assuming it is
// instant. Invalidates the part detail (the record gained an altium model ref), the list, the
// Altium status, and the capability itself: the run leaves Altium closed, so a seat that was
// reported busy may now be free.
export function useAltiumEmbedModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; replace?: boolean }) =>
      api.altiumEmbedModel(vars.id, vars.replace ?? false),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["altium-status"] });
      qc.invalidateQueries({ queryKey: ["altium-embed-capability"] });
      qc.invalidateQueries({ queryKey: ["parts"] });
      qc.invalidateQueries({ queryKey: ["part", vars.id] });
    },
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

// Bulk import deliberately has NO hook here. Its state lives in `lib/bulkImportStore`, outside
// React, because the panel sits inside the Add-A-Part dialog and a register-sized run takes about
// 25 minutes: a `useJob` hook unmounts with the dialog and throws the finished report away. A dead
// hook left beside the real one is exactly the defect that made `enrich/bulk.py` look shipped for
// months, so it is removed rather than kept "just in case".

// The parts a bulk 3D embed would work on. Polled on window focus like the other Altium probes:
// the count changes when parts are added or captured elsewhere in the app, and an action that
// promises a stale number is worse than one that promises none.
export function useAltiumModelsPending() {
  return useQuery({
    queryKey: ["altium-models-pending"],
    queryFn: () => api.altiumModelsPending(),
    refetchOnWindowFocus: true,
  });
}

// Embed every pending 3D model in one action. A JOB, because each part that needs work costs an
// Altium boot and a whole library can run for minutes; the caller shows the streamed message,
// which names the part being embedded. On completion it invalidates everything the run changed:
// the pending count, the parts list and each detail (records gained an altium model ref), the
// Altium status, and the capability (the run leaves Altium closed, so a held seat may be free).
export function useAltiumEmbedModels() {
  const qc = useQueryClient();
  const job = useJob<import("./types").AltiumBulkEmbedResult>();
  const start = useCallback(
    async (partIds?: string[]) => {
      // `useJob.start` resolves when the stream ends and leaves the payload on `job.result`; the
      // invalidation runs after it either way, because a run that embedded 38 of 40 before failing
      // still changed 38 records and the surfaces must not keep showing the old state.
      await job.start(() => api.altiumEmbedModels(partIds));
      for (const key of [
        ["altium-models-pending"],
        ["parts"],
        ["part"],
        ["altium-status"],
        ["altium-embed-capability"],
      ]) {
        qc.invalidateQueries({ queryKey: key });
      }
    },
    [job, qc],
  );
  return { ...job, start };
}

// "Is my library complete?" -- read from the records on disk, network-free. Invalidated by
// anything that changes what a part holds (a completion run, an ingest, an attach), because a
// coverage number that lags the library is a number that lies.
export function useLibraryCoverage() {
  return useQuery({
    queryKey: ["library-coverage"],
    queryFn: () => api.libraryCoverage(),
  });
}

// What CAD the library holds, and what a clear would remove.
export function useCadInventory() {
  return useQuery({
    queryKey: ["library-cad"],
    queryFn: () => api.cadInventory(),
  });
}

// Which derivation ruleset produced the presentation data currently on screen.
export function useLibraryDerivation() {
  return useQuery({
    queryKey: ["library-derivation"],
    queryFn: () => api.libraryDerivation(),
  });
}

// Start a completion run. The mutation only STARTS the job; progress arrives over the job's
// SSE stream and the caller owns that, exactly as the bulk import does. The coverage query is
// invalidated when the run finishes, not when it starts.
export function useRunCompletion() {
  return useMutation({
    mutationFn: (input: { partIds?: string[]; limit?: number }) => api.runCompletion(input),
  });
}

// Ask a running job to stop. Deliberately NOT invalidating anything: stopping changes nothing
// by itself, and the run's own terminal result is what refreshes the surface.
export function useStopJob() {
  return useMutation({ mutationFn: (jobId: string) => api.stopJob(jobId) });
}
