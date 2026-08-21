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
  DiscoveredProject,
  EnrichmentResult,
  GuidedRepositoryBody,
  GuidedSourceDataBody,
  GuidedToolConnectionResult,
  GitHubOwner,
  GitHubViewer,
  PartDetail,
  ProjectReviewCandidate,
  ProjectSummary,
  SetLibraryBody,
  SettingsPatch,
} from "./types";
import { api, type ListPartsArgs, type SearchArgs } from "./client";
import { invalidatePartCadProjection } from "./partCadProjectionQueries";
import type {
  ComponentDossier,
  ComponentProvidersView,
  CoverageArtifact,
  RepresentationKind,
} from "./dossierTypes";
import { useJob } from "../lib/useJob";

export function useProjects() {
  return useQuery({
    queryKey: ["projects"],
    queryFn: () => api.listProjects(),
    refetchOnWindowFocus: true,
  });
}

export function useProjectWorkspace(projectId: string | null) {
  return useQuery({
    queryKey: ["project-workspace", projectId],
    queryFn: () => api.projectWorkspace(projectId!),
    enabled: !!projectId,
  });
}

export function useProjectPlacementGeometry(projectId: string) {
  return useQuery({
    queryKey: ["project-placement-geometry", projectId],
    queryFn: () => api.projectPlacementGeometry(projectId),
    refetchOnWindowFocus: true,
    staleTime: 10_000,
  });
}

export function useProjectVisuals(projectId: string) {
  return useQuery({
    queryKey: ["project-visuals", projectId],
    queryFn: () => api.projectVisuals(projectId),
    enabled: !!projectId,
    refetchOnWindowFocus: true,
    staleTime: 10_000,
  });
}

export function useRefreshProjectVisuals(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.projectVisuals(projectId, true),
    onSuccess: (visuals) => {
      queryClient.setQueryData(["project-visuals", projectId], visuals);
      queryClient.invalidateQueries({
        queryKey: ["project-placement-geometry", projectId],
      });
      queryClient.invalidateQueries({
        queryKey: ["project-visual-artifact", projectId],
      });
    },
  });
}

export function useProjectVisualArtifact(
  projectId: string,
  artifactId: string,
) {
  return useQuery({
    queryKey: ["project-visual-artifact", projectId, artifactId],
    queryFn: () => api.projectVisualArtifact(projectId, artifactId),
    enabled: !!projectId && !!artifactId,
    staleTime: Number.POSITIVE_INFINITY,
  });
}

export function useLiveProjectBom(projectId: string, boards: number) {
  return useQuery({
    queryKey: ["project-bom-live", projectId, boards],
    queryFn: () => api.liveProjectBom(projectId, boards),
    refetchOnWindowFocus: true,
    // The board count is typed, so every keystroke mints a new key. Without this the
    // workbench falls back to its loading branch and unmounts the three-pane view -
    // including the board input itself - so the caret is lost after one character and a
    // two-digit count cannot be entered at all.
    placeholderData: keepPreviousData,
  });
}

export function useProjectBomExport(projectId: string) {
  return useMutation({
    mutationFn: (boards: number) => api.liveProjectBomExport(projectId, boards),
  });
}

export function useProjectAssignments(projectId: string) {
  return useQuery({
    queryKey: ["project-assignments", projectId],
    queryFn: () => api.projectAssignments(projectId),
    refetchOnWindowFocus: true,
  });
}

export function useAssignProjectGroup(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ refs, partId }: { refs: string[]; partId: string }) =>
      api.assignProjectGroup(projectId, refs, partId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["project-assignments", projectId],
      });
      queryClient.invalidateQueries({
        queryKey: ["project-bom-live", projectId],
      });
    },
  });
}

export function useProjectCollaboration(projectId: string) {
  return useQuery({
    queryKey: ["project-collaboration", projectId],
    queryFn: () => api.projectCollaboration(projectId),
    refetchInterval: (query) => (query.state.data?.session ? 15_000 : 5_000),
  });
}

export function useOpenProjectDocument(projectId: string) {
  return useMutation({
    mutationFn: (documentId: string) =>
      api.openProjectDocument(projectId, documentId),
  });
}

export function useConnectProjectRemote(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (url: string) => api.connectProjectRemote(projectId, url),
    onSuccess: (result) => {
      queryClient.setQueryData(
        ["project-collaboration", projectId],
        result.collaboration,
      );
      queryClient.invalidateQueries({ queryKey: ["project-reviews", projectId] });
    },
  });
}

export function useStartWorkSession(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { owner: string; branch: string; documents: string[] }) =>
      api.startWorkSession(projectId, body),
    onSuccess: (state) =>
      queryClient.setQueryData(["project-collaboration", projectId], state),
  });
}

export function useShareWorkSession(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      sessionId,
      message,
    }: {
      sessionId: string;
      message: string;
    }) => api.shareWorkSession(projectId, sessionId, message),
    onSuccess: (state) =>
      queryClient.setQueryData(["project-collaboration", projectId], state),
  });
}

export function useResumeWorkSession(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) => api.resumeWorkSession(projectId, sessionId),
    onSuccess: (state) =>
      queryClient.setQueryData(["project-collaboration", projectId], state),
  });
}

export function useFinishWorkSession(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) => api.finishWorkSession(projectId, sessionId),
    onSuccess: (result) => {
      queryClient.setQueryData(
        ["project-collaboration", projectId],
        result.collaboration,
      );
      queryClient.invalidateQueries({ queryKey: ["project-reviews", projectId] });
    },
  });
}

export function useProjectReviews(projectId: string, enabled = true) {
  return useQuery({
    queryKey: ["project-reviews", projectId],
    queryFn: () => api.projectReviews(projectId),
    enabled,
    refetchOnWindowFocus: true,
  });
}

export function useProjectReviewEvidence(
  projectId: string,
  candidate: ProjectReviewCandidate | undefined,
) {
  return useQuery({
    queryKey: [
      "project-review-evidence",
      projectId,
      candidate?.branch,
      candidate?.commit,
      candidate?.base_branch,
      candidate?.base_commit,
    ],
    queryFn: () => api.projectReviewEvidence(projectId, candidate!),
    enabled: !!candidate?.ready,
    staleTime: Number.POSITIVE_INFINITY,
  });
}

export function useValidateProjectReview(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (candidate: {
      branch: string;
      commit: string;
      base_branch: string;
      base_commit: string;
    }) => api.validateProjectReview(projectId, candidate),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["project-review-evidence", projectId],
      }),
  });
}

export function useApproveProjectReview(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (candidate: {
      branch: string;
      commit: string;
      base_branch: string;
      base_commit: string;
    }) => api.approveProjectReview(projectId, candidate),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-reviews", projectId] });
      queryClient.invalidateQueries({
        queryKey: ["project-collaboration", projectId],
      });
    },
  });
}

export function useRequestProjectChanges(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (decision: {
      branch: string;
      commit: string;
      base_branch: string;
      base_commit: string;
      reviewer: string;
      message: string;
    }) => api.requestProjectChanges(projectId, decision),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-reviews", projectId] });
      queryClient.invalidateQueries({
        queryKey: ["project-collaboration", projectId],
      });
    },
  });
}

export function useDiscoverProjects() {
  return useMutation({
    mutationFn: (candidate: string) => api.discoverProjects(candidate),
  });
}

export function useSystemProjectDiscovery(enabled = true) {
  return useQuery({
    queryKey: ["system-project-discovery"],
    queryFn: () => api.discoverSystemProjects(),
    enabled,
    refetchOnWindowFocus: false,
  });
}

export function useRegisterProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (project: Pick<DiscoveredProject, "root" | "eda">) =>
      api.registerProject(project.root, project.eda),
    onSuccess: (project) => {
      queryClient.setQueryData<ProjectSummary[]>(["projects"], (current = []) => [
        ...current.filter((candidate) => candidate.id !== project.id),
        project,
      ]);
      return queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useActiveAssembly(projectId: string) {
  return useQuery({
    queryKey: ["project-assembly", projectId],
    queryFn: () => api.activeAssembly(projectId),
    refetchInterval: 2_000,
  });
}

export function useStartAssembly(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ operator, boards }: { operator: string; boards: number }) =>
      api.startAssembly(projectId, operator, boards),
    onSuccess: (run) =>
      queryClient.setQueryData(["project-assembly", projectId], run),
  });
}

export function useRecordAssemblyEvent(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      runId,
      placementId,
      state,
      scannedMpn = "",
      note = "",
    }: {
      runId: string;
      placementId: string;
      state: "done" | "skipped" | "reworked" | "issue";
      scannedMpn?: string;
      note?: string;
    }) =>
      api.recordAssemblyEvent(projectId, runId, {
        placement_id: placementId,
        state,
        scanned_mpn: scannedMpn,
        note,
      }),
    onSuccess: (run) =>
      queryClient.setQueryData(["project-assembly", projectId], run),
  });
}

export function useCompleteAssembly(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => api.completeAssembly(projectId, runId),
    onSuccess: () => queryClient.setQueryData(["project-assembly", projectId], null),
  });
}

export function useOnboarding() {
  return useQuery({
    queryKey: ["onboarding"],
    queryFn: () => api.getOnboarding(),
    retry: false,
    // Design Studio and Vitest fixtures are immutable evidence packets; production revalidates
    // connectivity and repository/tool readiness continuously.
    refetchInterval: import.meta.env.MODE === "test" ? false : 10_000,
    refetchIntervalInBackground: true,
  });
}

export function useSetLibrary() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SetLibraryBody) => api.setLibrary(body),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useOnboardingGitHubRepositories(owner: string, enabled: boolean) {
  return useQuery({
    queryKey: ["onboarding", "github-repositories", owner],
    queryFn: () => api.getOnboardingGitHubRepositories(owner),
    enabled: enabled && owner.length > 0,
    retry: false,
  });
}

export function useOnboardingGitHubLogin() {
  const qc = useQueryClient();
  const job = useJob<{ viewer: GitHubViewer; owners: GitHubOwner[] }>();
  const start = useCallback(async () => {
    const terminal = await job.start(() => api.startOnboardingGitHubLogin());
    if (terminal.status === "done") {
      await qc.invalidateQueries({ queryKey: ["onboarding"] });
    }
    return terminal;
  }, [job, qc]);
  return { ...job, start };
}

export function useSetGuidedRepository() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: GuidedRepositoryBody) => api.setGuidedRepository(body),
    onSuccess: async (status) => {
      qc.setQueryData(["onboarding"], status);
      await qc.invalidateQueries();
    },
  });
}

export function useConnectGuidedTool() {
  const qc = useQueryClient();
  const job = useJob<GuidedToolConnectionResult>();
  const start = useCallback(async () => {
    const terminal = await job.start(() => api.connectGuidedTool());
    if (terminal.status === "done") {
      await qc.invalidateQueries({ queryKey: ["onboarding"] });
    }
    return terminal;
  }, [job, qc]);
  return { ...job, start };
}

export function useSaveGuidedSourceData() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: GuidedSourceDataBody) => api.saveGuidedSourceData(body),
    onSuccess: (status) => qc.setQueryData(["onboarding"], status),
  });
}

export function useCompleteOnboarding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.completeOnboarding(),
    onSuccess: (status) => qc.setQueryData(["onboarding"], status),
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

// The opened component's dossier. Invalidated wherever the part detail is, because every
// write that changes a record changes what this projects.
export function usePartDossierQuery(id: string | null) {
  return useQuery({
    queryKey: ["part-workspace", id],
    queryFn: () => api.partDossier(id as string),
    enabled: !!id,
  });
}

/**
 * The four specification writes, and the one rule they all obey.
 *
 * Each endpoint answers with the FULL updated dossier, and the answer REPLACES the cached
 * document rather than being merged into it. An override does not change one value: it changes
 * that value, its verification state, the conflict state of the row, its group's count, the
 * category completeness score, the quality summary and the revision history, all at once. A
 * partial merge would leave most of those stale while looking like it had saved.
 *
 * On failure nothing is written to the cache at all, so the row reverts to exactly what the
 * server last said and the caller reports what failed. A write that silently appeared to save
 * is worse than one that visibly did not.
 */
export type SpecificationWrite =
  | { kind: "set-override"; key: string; value: string; note?: string; verified?: boolean }
  | { kind: "clear-override"; key: string }
  | { kind: "set-preferred-source"; key: string; sourceId: string }
  | { kind: "clear-preferred-source"; key: string };

function runSpecificationWrite(id: string, write: SpecificationWrite): Promise<ComponentDossier> {
  if (write.kind === "set-override") {
    return api.setSpecificationOverride(id, write.key, write.value, {
      note: write.note,
      verified: write.verified,
    });
  }
  if (write.kind === "clear-override") {
    return api.clearSpecificationOverride(id, write.key);
  }
  if (write.kind === "set-preferred-source") {
    return api.setSpecificationPreferredSource(id, write.key, write.sourceId);
  }
  return api.clearSpecificationPreferredSource(id, write.key);
}

export function useWriteSpecification(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (write: SpecificationWrite) => runSpecificationWrite(id, write),
    onSuccess: (dossier: ComponentDossier) => {
      qc.setQueryData(["part-workspace", id], dossier);
      // Deliberately NOT the general post-write invalidation: that one invalidates the dossier
      // itself, which would throw away the authoritative document the endpoint just returned and
      // re-ask for it. The answer IS the new state; re-fetching it is how the value flickers back
      // to the old one for a frame and how two sources of truth get reintroduced.
      //
      // Everything a specification write genuinely changes ELSEWHERE is invalidated: the list and
      // the facets index normalized values, the duplicate set can turn on an identity field, and
      // the write commits, so the part's timeline gained an entry.
      qc.invalidateQueries({ queryKey: ["parts"] });
      qc.invalidateQueries({ queryKey: ["facets"] });
      qc.invalidateQueries({ queryKey: ["duplicates"] });
      qc.invalidateQueries({ queryKey: ["part", id] });
      qc.invalidateQueries({ queryKey: ["part-history", id] });
    },
  });
}

/**
 * Choosing which provider supplies a component's CAD.
 *
 * Four writes on one hook for the same reason the specification writes share one: they address
 * one decision from two scopes and answer with the same document, and four hooks would be four
 * places for the cache handling to drift apart.
 *
 * What a change would REPLACE is not asked for here. It travels on the dossier itself
 * (`cadAssets.preference.options`), planned by the same backend function that refuses the write,
 * so the confirmation a person approves and the decision the record makes cannot describe
 * different outcomes - and no round trip stands between deciding and being shown.
 */
export type CadPreferenceWrite =
  | { kind: "set-set-source"; provider: string }
  | { kind: "clear-set-source" }
  | { kind: "set-asset-source"; asset: RepresentationKind; provider: string }
  | { kind: "clear-asset-source"; asset: RepresentationKind };

function runCadPreferenceWrite(
  id: string,
  write: CadPreferenceWrite,
): Promise<ComponentDossier> {
  if (write.kind === "set-set-source") return api.setCadPreferredSource(id, write.provider);
  if (write.kind === "clear-set-source") return api.clearCadPreferredSource(id);
  if (write.kind === "set-asset-source") {
    return api.setCadAssetPreferredSource(id, write.asset, write.provider);
  }
  return api.clearCadAssetPreferredSource(id, write.asset);
}

export function useWriteCadPreference(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (write: CadPreferenceWrite) => runCadPreferenceWrite(id, write),
    onSuccess: (dossier: ComponentDossier) => {
      // The endpoint answers with the whole recomputed dossier, so it is written straight into
      // the cache rather than invalidated: re-asking would discard the authoritative document
      // and reintroduce the second source of truth it exists to prevent.
      qc.setQueryData(["part-workspace", id], dossier);
      // The decision commits, so the part's timeline gained an entry.
      qc.invalidateQueries({ queryKey: ["part-history", id] });
    },
  });
}

/**
 * Record one person's correction to a provider's coverage of one component.
 *
 * The backend answers with the RECOMPUTED coverage, so the returned document is written straight
 * into the workspace cache rather than triggering a refetch: it is the same projection the
 * workspace already carries, and re-asking would only let the two disagree for a frame. The write
 * is still committed to the record, so the workspace is invalidated afterwards to pick up anything
 * else the commit changed.
 */
export function useSetProviderCoverage(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      provider: string;
      artifact: CoverageArtifact;
      status: "available" | "not_available" | "";
      note?: string;
    }) => api.setPartProviderCoverage(id, input),
    onSuccess: (providers: ComponentProvidersView) => {
      qc.setQueryData(
        ["part-workspace", id],
        (current: ComponentDossier | undefined) =>
          current ? { ...current, cadSourceCoverage: providers } : current,
      );
      qc.invalidateQueries({ queryKey: ["part-history", id] });
    },
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

// The canonical per-part CAD completion read. It feeds the checklist, the selected-part
// readiness chip, and the final post-capture readback. Capture invalidates this key after every
// terminal result, so the screen reconciles with the committed projection without a restart.
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
//
// Returned through `useCallback` so it has a STABLE identity: `useQueryClient` hands back the same
// client for the life of a provider, so nothing here can go stale. That stability is what lets the
// one effect-driven caller (`useRefreshSourcing`) list this in its dependencies honestly instead of
// omitting it and explaining why - an omission that only stayed correct while the closure kept
// reading nothing but `qc`.
function useInvalidateAfterWrite() {
  const qc = useQueryClient();
  return useCallback((id: string) => {
    qc.invalidateQueries({ queryKey: ["parts"] });
    qc.invalidateQueries({ queryKey: ["facets"] });
    qc.invalidateQueries({ queryKey: ["duplicates"] });
    void invalidatePartCadProjection(qc, id);
    qc.invalidateQueries({ queryKey: ["library-coverage"] });
    qc.invalidateQueries({ queryKey: ["library-cad"] });
    qc.invalidateQueries({ queryKey: ["altium-status"] });
    qc.invalidateQueries({ queryKey: ["altium-models-pending"] });
    // a write commits, so the part's git timeline (M6k) gained an entry
    qc.invalidateQueries({ queryKey: ["part-history", id] });
  }, [qc]);
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

/**
 * What the Manage menu's shell actions may offer for one component.
 *
 * Read once per opened component and kept, because the answer changes when an application is
 * installed or a CAD set is attached - not while a menu is open. A host with no native window
 * answers `supported: false` and the three items are never drawn.
 */
export function usePartShellQuery(id: string | null) {
  return useQuery({
    queryKey: ["part-shell", id],
    queryFn: () => api.partShell(id!),
    enabled: !!id,
    staleTime: 60_000,
  });
}

/*
 * The three shell actions invalidate NOTHING, deliberately.
 *
 * They are mutations only in the HTTP sense - they ask the host to do something outside the
 * application - and none of them changes a byte the cache holds. Revealing a folder opens a file
 * browser; exporting writes into a machine-local export directory that is not the library; opening
 * in another application launches that application. Adding an invalidation would refetch the
 * dossier to observe a change that cannot have happened, so the cost would be real and the benefit
 * imaginary. `query-mutation-missing-invalidation` flags all three, and it is right to ask: this
 * comment is the answer, not an oversight.
 */
export function useRevealPartFiles() {
  return useMutation({
    mutationFn: (id: string) => api.revealPartFiles(id),
  });
}

export function useExportPart() {
  return useMutation({
    mutationFn: (vars: { partId: string; format: string }) => api.exportPart(vars),
  });
}

export function useOpenPartIn() {
  return useMutation({
    mutationFn: (vars: { partId: string; applicationId: string; format: string }) =>
      api.openPartIn(vars),
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

export function useRestoreDeletedPart() {
  const invalidate = useInvalidateAfterWrite();
  return useMutation({
    mutationFn: (id: string) => api.restoreDeletedPart(id),
    onSuccess: (_data, id) => invalidate(id),
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
      // The opened component reads the PROJECTION, not the record, and a persisted pinout is a
      // specification: without this the sheet that just applied one kept showing the old table.
      qc.invalidateQueries({ queryKey: ["part-workspace", vars.id] });
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
  }, [done, id, invalidate]);
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
      qc.invalidateQueries({ queryKey: ["duplicates"] });
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
      qc.invalidateQueries({ queryKey: ["duplicates"] });
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

/**
 * A symbol's pins and body geometry.
 *
 * Fetched only when the symbol module is actually expanded. Never retried: a part with no
 * symbol legitimately 404s and a part whose library cannot be parsed will not parse on a second
 * ask either, and both are states the module has to SAY rather than spin on.
 */
export function useSymbolGeometry(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ["symbol-geometry", id],
    queryFn: () => api.symbolGeometry(id),
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
    onSuccess: async (_settings, patch) => {
      await qc.invalidateQueries({ queryKey: ["settings"] });
      if (patch.primary_eda !== undefined) {
        await qc.invalidateQueries({ queryKey: ["onboarding"] });
      }
    },
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

export function useConnectLibraryRemote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (url: string) => api.connectLibraryRemote(url),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sync-status"] }),
  });
}

// The rail mounts this on boot, so the check must keep running on its own - otherwise a
// release pushed AFTER the app opened never surfaces until something else remounts the query
// (the reported bug: the Update pill only appeared after opening Settings, whose own observer
// forced a refetch). While the host's first remote check is still pending, retry quickly so the
// footer does not sit at "Unknown" for two minutes. Once standing is known, each check does a real
// `git fetch` + ahead/behind, so back off to the normal interval. staleTime dedupes the boot +
// Settings observers.
export function useUpdateCheck() {
  return useQuery({
    queryKey: ["update-check"],
    queryFn: () => api.checkUpdate(),
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      // `checking` is the state the host actually reports while its first remote probe runs,
      // so omitting it here left the footer on the slow two-minute interval for exactly the
      // window this fast path exists to cover.
      return !state ||
        state === "unverified" ||
        state === "updating" ||
        state === "checking"
        ? 5_000
        : 2 * 60_000;
    },
    refetchOnWindowFocus: true,
    staleTime: 60_000,
  });
}

// There is deliberately NO useApplyUpdate hook. Convergence adopts a verified release on its own,
// so nothing in the UI ever called it - and a mutation hook that no component mounts is the same
// defect the bulk-import note above describes: it made a manual escape hatch LOOK shipped while
// "Updating..." had no exit at all. The real exit is now a bound: an adoption that never completes
// degrades to a blocked standing that says so (see lib/updateStanding.ts, ADOPTION_STALL_MS).
// `api.applyUpdate` stays on the client - it is the backend's contract, not a dead UI affordance.

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

export function useCatalogBuildStatus() {
  return useQuery({
    queryKey: ["catalog-build-status"],
    queryFn: () => api.catalogBuildStatus(),
    refetchOnWindowFocus: true,
    refetchInterval: (query) => query.state.data?.state === "building" ? 1_000 : false,
  });
}

export function useCatalogBuild() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.catalogBuild(),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["catalog-build-status"] });
      await qc.invalidateQueries({ queryKey: ["parts"] });
    },
  });
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

export function useAltiumSetup() {
  return useMutation({ mutationFn: () => api.altiumSetup() });
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

/**
 * What one library-wide run finished alone, and what still needs a person.
 *
 * `live` polls while the batch is still working, because each part's report is retained as that
 * part settles: the worklist is meant to fill in as the run goes, not to appear only at the end.
 * The query stays keyed on the batch alone so a poll updates the SAME rows rather than growing a
 * new cache entry per status transition.
 */
export function useCaptureWorklist(batchId: string | null, live: boolean) {
  return useQuery({
    queryKey: ["capture-worklist", batchId],
    queryFn: () => api.captureWorklist(batchId as string),
    enabled: !!batchId,
    // Five seconds, not one: the projection re-reads one retained report per item, and a
    // thousand-part batch does not need that walk three times a minute faster than a provider
    // can settle a single part.
    refetchInterval: live ? 5_000 : false,
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
