/**
 * TanStack Query hooks over the STM Viewer slice of the API client, mirroring api/queries.ts.
 * Server state lives here so the page stays declarative: change the scope and the matrix
 * refetches; select a part and its pinout loads. The read hooks surface the Phase-3 409 "index
 * not built" as an ApiError the page branches on (never a thrown crash), and the build is a
 * useJob-backed mutation over the existing SSE stream.
 *
 * Phase 4 adds exactly these five hooks. useStmPinAf / useStmSignalCandidates /
 * useStmCompatUnion / useStmSuggestions are Phase 5's additions to this same file (INTERFACES.md
 * sections 5 + 7); adding them now with no consumer would be premature.
 */
import { useCallback } from "react";
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { api, type StmMcusArgs } from "./client";
import type { AfCheckBody, CompatUnionBody, StmStatusDTO } from "./types";
import { useJob } from "../lib/useJob";

// The build/source/stamp state. retry:false so a 409 (index not built) resolves to an error
// state immediately for the build gate, instead of retrying a state that only a build changes.
export function useStmStatus() {
  return useQuery({
    queryKey: ["stm-status"],
    queryFn: () => api.getStmStatus(),
    retry: false,
  });
}

// The MCU spec matrix, scoped by the coarse family/MCU selection + free-text q only (decision 3).
// keepPreviousData holds the prior rows on screen while a new scope loads, so the table never
// flashes empty. retry:false so a 409 reaches the build gate at once.
export function useStmMcus(scope: StmMcusArgs = {}) {
  return useQuery({
    queryKey: [
      "stm-mcus",
      scope.q ?? "",
      scope.family ?? "",
      scope.core ?? "",
      scope.package ?? "",
      scope.series ?? "",
    ],
    queryFn: () => api.getStmMcus(scope),
    placeholderData: keepPreviousData,
    retry: false,
  });
}

// The families option set for the scope picker.
export function useStmFamilies() {
  return useQuery({
    queryKey: ["stm-families"],
    queryFn: () => api.getStmFamilies(),
    retry: false,
  });
}

// One part's full pinout. Disabled until a part is selected (mirrors usePartDetailQuery), so the
// map area shows its empty state with no wasted request while nothing is chosen.
export function useStmPinout(part: string | null) {
  return useQuery({
    queryKey: ["stm-pinout", part],
    queryFn: () => api.getStmPinout(part as string),
    enabled: !!part,
    retry: false,
  });
}

// Build the derived index as a background job, streaming live progress over the SSE. The terminal
// result is the fresh StmStatusDTO; the caller re-queries the status/matrix on success so the
// build gate clears to the real surface.
export function useBuildStmIndex() {
  const job = useJob<StmStatusDTO>();
  const start = useCallback(() => job.start(() => api.buildStmIndex()), [job]);
  return { ...job, start };
}

// The socket-union of an assembled set (COMPAT-01/02/03/05). A plain useMutation mirroring
// useSetLibrary: the union body is either an explicit ref list or a (family, package) group, and
// the UnionDTO result is ephemeral React state, not a stored resource, so nothing is invalidated on
// success (ARCHITECTURE Pattern 2 — a synchronous Layer B read, NOT routed through useJob/SSE). The
// caller branches on ApiError.status === 409 to show the reused "index not built" state.
export function useStmCompatUnion() {
  return useMutation({
    mutationFn: (body: CompatUnionBody) => api.postStmCompatUnion(body),
  });
}

// One pin's complete AF0-15 set (SWAP-01). Disabled until a part AND a position are set, so the
// panel shows its prompt with no wasted call while nothing is selected. retry:false so a 409 reaches
// the reused not-built state at once.
export function useStmPinAf(part: string | null, position: string | null) {
  return useQuery({
    queryKey: ["stm-pin-af", part, position],
    queryFn: () => api.getStmPinAf(part as string, position as string),
    enabled: !!part && !!position,
    retry: false,
  });
}

// Every candidate pin for a chosen peripheral signal across the part (SWAP-02). Disabled until a
// part AND a signal are chosen, so nothing fetches until the user picks a signal to route.
export function useStmSignalCandidates(part: string | null, signal: string | null) {
  return useQuery({
    queryKey: ["stm-signal-candidates", part, signal],
    queryFn: () => api.getStmSignalCandidates(part as string, signal as string),
    enabled: !!part && !!signal,
    retry: false,
  });
}

// Auto-discovered compatible sets for a (package, family) scope (COMPAT-04). Enabled-gated on both,
// so it fires only once a group scope is chosen.
export function useStmSuggestions(
  pkg: string | null,
  family: string | null,
  tolerance?: number,
) {
  return useQuery({
    queryKey: ["stm-suggestions", pkg, family, tolerance ?? 0],
    queryFn: () => api.getStmCompatSuggestions(pkg as string, family as string, tolerance),
    enabled: !!pkg && !!family,
    retry: false,
  });
}

// Conflict-check a client-held assignment (COMPAT reconcile support). A plain useMutation mirroring
// useStmCompatUnion: the conflict result is ephemeral, not a stored resource, so nothing is
// invalidated. The held assignment lives in React state only, never persisted (CONTEXT decision 8).
export function useStmAfCheck() {
  return useMutation({
    mutationFn: (body: AfCheckBody) => api.postStmAfCheck(body),
  });
}
