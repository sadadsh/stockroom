import type {
  AssemblyRun,
  OpenProjectDocumentResult,
  ProjectAssignments,
  ProjectBom,
  ProjectCollaboration,
  ProjectPlacementGeometry,
  ProjectReviewEvidence,
  ProjectReviews,
  ProjectSummary,
  ProjectVisualBundle,
  ProjectWorkspace,
} from "../../api/types";
import type { ScenarioFixture } from "../scenario";
import { createScenarioFixtureValidatorRegistry } from "../scenarioFixtureValidation";
import { providerFixtureValidators } from "./providerFixtures";
import { ONBOARDING_READY } from "./componentFixtures";

export type ProjectEda = "kicad" | "altium";

export const PROJECT_IDS: Record<ProjectEda, string> = {
  kicad: "kicad-project",
  altium: "altium-project",
};

export const PROJECT_SUMMARIES: readonly [ProjectSummary, ProjectSummary] = [
  {
    id: PROJECT_IDS.kicad,
    name: "Power Board",
    root: "C:\\Projects\\Power",
    eda: "kicad",
    board_count: 1,
    sheet_count: 1,
    has_git: true,
    registered_at: "2026-08-11T12:00:00Z",
  },
  {
    id: PROJECT_IDS.altium,
    name: "Control Board",
    root: "C:\\Projects\\Control",
    eda: "altium",
    board_count: 1,
    sheet_count: 1,
    has_git: true,
    registered_at: "2026-08-11T12:00:00Z",
  },
];

const TOOL_CONTRACT: ProjectWorkspace["parity"]["tools"] = [
  "design",
  "bom",
  "assemble",
  "changes",
  "releases",
].map((key) => ({
  key: key as "design" | "bom" | "assemble" | "changes" | "releases",
  label: key,
  status: key === "releases" ? "planned" : "active",
  behavior: "identical",
  actions: [],
  inputs: [],
  states: [],
  results: [],
  recovery: [],
  acceptance: [],
}));

function names(eda: ProjectEda) {
  return eda === "kicad"
    ? {
        project: "Power Board",
        root: "C:\\Projects\\Power",
        descriptor: "Power.kicad_pro",
        board: "Power.kicad_pcb",
        schematic: "Power.kicad_sch",
        label: "KiCad",
        runtime: "KiCad CLI",
      }
    : {
        project: "Control Board",
        root: "C:\\Projects\\Control",
        descriptor: "Control.PrjPcb",
        board: "Control.PcbDoc",
        schematic: "Control.SchDoc",
        label: "Altium Designer",
        runtime: "Altium Designer",
      };
}

export function projectWorkspace(
  eda: ProjectEda,
  runtime: Partial<ProjectWorkspace["runtime"]> = {},
): ProjectWorkspace {
  const item = names(eda);
  return {
    project: {
      id: PROJECT_IDS[eda],
      name: item.project,
      root: item.root,
      pro_path: item.descriptor,
      board_paths: [item.board],
      sheet_paths: [item.schematic],
      eda,
      git_root: item.root,
    },
    eda_label: item.label,
    tools: ["design", "bom", "assemble", "changes", "releases"],
    parity: {
      schema: "stockroom-project-parity/1",
      edas: ["kicad", "altium"],
      strict: true,
      adapter_boundary: "native_io_only",
      tools: TOOL_CONTRACT,
    },
    runtime: {
      adapter_key: eda,
      available: true,
      status: "ready",
      version: eda === "kicad" ? "10.0" : "26",
      detail: "Native runtime ready.",
      ...runtime,
    },
    documents: [
      {
        document_id: `${eda}-project`,
        path: item.descriptor,
        label: `${item.project} Project`,
        kind: "project",
        exists: true,
        lock_required: false,
      },
      {
        document_id: `${eda}-schematic`,
        path: item.schematic,
        label: "Main Schematic",
        kind: "schematic",
        exists: true,
        lock_required: true,
      },
      {
        document_id: `${eda}-board`,
        path: item.board,
        label: "Main PCB",
        kind: "pcb",
        exists: true,
        lock_required: true,
      },
    ],
  };
}

export function projectCollaboration(
  eda: ProjectEda,
  repository: ProjectCollaboration["repository"] | undefined = undefined,
): ProjectCollaboration {
  const item = names(eda);
  return {
    repository: repository === undefined
      ? {
          root: item.root,
          remote: "origin",
          branch: "main",
          commit: "0123456789abcdef0123456789abcdef01234567",
          clean: true,
          dirty_paths: [],
          has_remote: true,
          has_upstream: true,
          ahead: 0,
          behind: 0,
        }
      : repository,
    session: null,
    recovery: null,
  };
}

export function projectGeometry(
  eda: ProjectEda,
  state: "ready" | "render-blocked" | "overlay-blocked" | "missing" = "ready",
): ProjectPlacementGeometry {
  const item = names(eda);
  const ready = state === "ready" || state === "render-blocked";
  const detail = state === "overlay-blocked"
    ? "The project is already open in the linked editor."
    : state === "missing"
      ? `${item.label} is not installed.`
      : "Placement data ready.";
  return {
    schema_version: 1,
    adapter: eda,
    status: ready ? "ready" : "blocked",
    runtime: { name: item.label, version: ready ? "fixture" : "", available: ready },
    boards: [item.board],
    placements: ready
      ? [
          {
            reference: "R1",
            board: item.board,
            x_mm: 10.25,
            y_mm: 18.5,
            rotation_deg: 90,
            side: "top",
            footprint: "R_0402_1005Metric",
          },
          {
            reference: "R2",
            board: item.board,
            x_mm: 24.5,
            y_mm: 18.5,
            rotation_deg: 270,
            side: "top",
            footprint: "R_0402_1005Metric",
          },
        ]
      : [],
    summary: { boards: 1, placements: ready ? 2 : 0, top: ready ? 2 : 0, bottom: 0 },
    source: { digest: `${eda}-source`, files: [{ path: item.board }], preserved: true },
    detail,
    digest: `${eda}-geometry-${state}`,
  };
}

export function projectVisuals(
  eda: ProjectEda,
  state: "geometry" | "blocked" | "native-ready" = "geometry",
): ProjectVisualBundle {
  const item = names(eda);
  const nativeReady = state === "native-ready";
  const blocked = state === "blocked";
  return {
    schema_version: 1,
    adapter: eda,
    status: blocked ? "blocked" : "ready",
    runtime: { name: item.runtime, version: "fixture" },
    documents: [
      {
        kind: "pcb",
        path: item.board,
        status: blocked ? "blocked" : "ready",
        detail: blocked
          ? "Native render is blocked while this fixture preview is active. Return to Real Data to render the PCB."
          : nativeReady
            ? "Native top board view is ready."
            : "Placement geometry is ready; native rendering has not run.",
        artifacts: nativeReady
          ? [{
              id: `${eda}-top`,
              kind: "pcb",
              path: item.board,
              view: "top",
              label: "Top copper, mask, and silkscreen",
              page: 1,
              media_type: "image/svg+xml",
              width: 1000,
              height: 620,
              bytes: 64,
              sha256: `${eda}-top-digest`,
            }]
          : [],
        scene: blocked
          ? undefined
          : {
              schema_version: 1,
              board: item.board,
              units: "mm",
              bounds: { min_x: 0, min_y: 0, max_x: 40, max_y: 30, width: 40, height: 30 },
              components: [
                {
                  reference: "R1",
                  x_mm: 10.25,
                  y_mm: 18.5,
                  rotation_deg: 90,
                  side: "top",
                  package: "R_0402_1005Metric",
                  part: "10k",
                  bounds: { min_x: -0.5, min_y: -0.25, max_x: 0.5, max_y: 0.25, width: 1, height: 0.5 },
                  pins: [{
                    number: "1",
                    net: "GND",
                    x_mm: 9.9,
                    y_mm: 18.5,
                    rotation_deg: 90,
                    side: "top",
                    layer: eda === "kicad" ? "F.Cu" : "TopLayer",
                    shape: { kind: "rounded-rect", width_mm: 0.5, height_mm: 0.6 },
                  }],
                },
                {
                  reference: "R2",
                  x_mm: 24.5,
                  y_mm: 18.5,
                  rotation_deg: 270,
                  side: "top",
                  package: "R_0402_1005Metric",
                  part: "10k",
                  bounds: { min_x: -0.5, min_y: -0.25, max_x: 0.5, max_y: 0.25, width: 1, height: 0.5 },
                  pins: [{
                    number: "2",
                    net: "GND",
                    x_mm: 24.1,
                    y_mm: 18.5,
                    rotation_deg: 270,
                    side: "top",
                    layer: eda === "kicad" ? "F.Cu" : "TopLayer",
                    shape: { kind: "rounded-rect", width_mm: 0.5, height_mm: 0.6 },
                  }],
                },
              ],
              vias: [],
              tracks: [],
              summary: { components: 2, pins: 2, vias: 0, tracks: 0, top: 2, bottom: 0 },
              source: { format: "ipc-2581", sha256: `${eda}-scene-digest` },
            },
      },
    ],
    summary: { documents: 1, artifacts: nativeReady ? 1 : 0, blocked: blocked ? 1 : 0 },
    detail: blocked
      ? "Native render is blocked while this fixture preview is active. Return to Real Data to render the PCB."
      : nativeReady
        ? "Native PCB view is ready."
        : "Placement geometry is ready.",
    digest: `${eda}-visuals-${state}`,
  };
}

export function projectBom(eda: ProjectEda): ProjectBom {
  const item = names(eda);
  return {
    project: item.project,
    ran_at: "2026-08-11T12:00:00Z",
    boards: 1,
    priced: false,
    line_count: 2,
    component_count: 3,
    lines: [
      {
        refs: ["R1", "R2"],
        qty: 2,
        value: "10k",
        mpn: "RC0402FR-0710KL",
        manufacturer: "Yageo",
        footprint: "R_0402_1005Metric",
        description: "Resistor",
        package: "0402",
        basic: false,
        in_library: true,
        library_part_id: "resistor-10k",
        final_qty: 2,
        final_unit_price: null,
        line_total: null,
      },
      {
        refs: ["C1"],
        qty: 1,
        value: "100n",
        mpn: "",
        manufacturer: "",
        footprint: "C_0402_1005Metric",
        description: "Capacitor",
        package: "0402",
        basic: false,
        in_library: false,
        library_part_id: "",
        final_qty: 1,
        final_unit_price: null,
        line_total: null,
      },
    ],
    summary: { state: "unpriced", total_cost: 0, priced_lines: 0, unpriced_lines: 2, line_count: 2, currency: "USD" },
    evidence: {
      eda,
      variant: "Default",
      source_commit: "0123456789abcdef",
      source_documents: [item.schematic],
      bom_digest: `${eda}-bom-digest`,
      repository_pinned: true,
    },
  };
}

export function projectAssignments(eda: ProjectEda): ProjectAssignments {
  const item = names(eda);
  return {
    project: item.project,
    eda,
    under_git: true,
    binding: { field: "StockroomPartId", writable: true, reason: "" },
    components: 3,
    unassigned: 1,
    bound: [],
    groups: [{
      key: "100n|C_0402_1005Metric",
      lib_id: "Device:C",
      value: "100n",
      footprint: "C_0402_1005Metric",
      refs: ["C1"],
      count: 1,
      sheets: ["Main Schematic"],
      candidates: [],
    }],
  };
}

export function assemblyRun(eda: ProjectEda, completed = false): AssemblyRun {
  const item = names(eda);
  const placements: AssemblyRun["placements"] = ["R1", "R2"].map((reference, index) => ({
    placement_id: `${eda}-placement-${index + 1}`,
    board_index: 1,
    native_id: `${eda}-native-${reference}`,
    reference,
    sheet: "Main Schematic",
    value: "10k",
    footprint: "R_0402_1005Metric",
    part_id: "resistor-10k",
    mpn: "RC0402FR-0710KL",
    manufacturer: "Yageo",
    state: completed ? "done" : "pending",
    last_event: null,
  }));
  return {
    schema_version: 1,
    id: `${eda}-assembly-1`,
    project_id: PROJECT_IDS[eda],
    project_name: item.project,
    eda,
    operator: "Sadad",
    boards: 1,
    source_commit: "0123456789abcdef",
    project_digest: `${eda}-project-digest`,
    started_at: "2026-08-11T12:00:00Z",
    completed_at: completed ? "2026-08-11T13:00:00Z" : "",
    status: completed ? "completed" : "active",
    receipt: completed
      ? {
          run_id: `${eda}-assembly-1`,
          source_commit: "0123456789abcdef",
          project_digest: `${eda}-project-digest`,
          event_digest: `${eda}-event-digest`,
          completed_at: "2026-08-11T13:00:00Z",
          digest: `${eda}-receipt-digest`,
        }
      : undefined,
    placements,
    events: [],
    progress: {
      total: 2,
      complete: completed ? 2 : 0,
      resolved: completed ? 2 : 0,
      percent: completed ? 100 : 0,
      counts: { pending: completed ? 0 : 2, done: completed ? 2 : 0, skipped: 0, reworked: 0, issue: 0 },
    },
  };
}

export const SHARED_REVIEWS: ProjectReviews = {
  base_branch: "main",
  candidates: [{
    branch: "work/nadia/power-board",
    commit: "aaaaaaaaaaaa1111aaaaaaaaaaaa1111aaaaaaaa",
    base_branch: "main",
    base_commit: "0123456789abcdef0123456789abcdef01234567",
    fork_commit: "0123456789abcdef0123456789abcdef01234567",
    changed_paths: ["Power.kicad_pcb"],
    commit_count: 1,
    ready: true,
    blocked_reason: "",
    events: [],
  }],
};

export const SHARED_REVIEW_EVIDENCE: ProjectReviewEvidence = {
  schema_version: 1,
  project_id: PROJECT_IDS.kicad,
  project_name: "Power Board",
  eda: "kicad",
  branch: SHARED_REVIEWS.candidates[0].branch,
  commit: SHARED_REVIEWS.candidates[0].commit,
  base_branch: "main",
  base_commit: SHARED_REVIEWS.candidates[0].base_commit,
  source_digest: "review-source",
  documents: [{ path: "Power.kicad_pcb", kind: "pcb", bytes: 4096, sha256: "board-sha" }],
  bom: {
    variant: "Default",
    line_count: 1,
    component_count: 2,
    digest: "review-bom",
    lines: [{
      refs: ["R1", "R2"],
      qty: 2,
      value: "10k",
      mpn: "RC0402FR-0710KL",
      manufacturer: "Yageo",
      footprint: "R_0402_1005Metric",
      package: "0402",
      description: "Resistor",
      datasheet: "",
      basic: false,
      identity_ready: true,
    }],
  },
  semantic_audit: {
    components: 2,
    sheets: 1,
    counts: { by_severity: { error: 0, warning: 0, info: 0 }, by_kind: {} },
    findings: [],
    digest: "review-audit",
  },
  blockers: [],
  warnings: [],
  reviewable: true,
  native_validation: { status: "passed", detail: "Native checks passed." },
  visual_diff: { status: "passed", detail: "No unexpected visual changes." },
  digest: "review-evidence",
};

export interface ProjectFixtureOptions {
  projects?: readonly ProjectSummary[];
  listBehavior?: ScenarioFixture<ProjectSummary[], undefined>["behavior"];
  selectedEda?: ProjectEda;
  workspaceBehavior?: ScenarioFixture<ProjectWorkspace, undefined>["behavior"];
  runtimeState?: "ready" | "missing";
  geometryState?: "ready" | "render-blocked" | "overlay-blocked" | "missing";
  visualState?: "geometry" | "blocked" | "native-ready";
  repository?: ProjectCollaboration["repository"];
  diverged?: boolean;
  reviews?: ProjectReviews;
  reviewEvidence?: ProjectReviewEvidence;
  completedAssembly?: boolean;
  blockNativeActions?: boolean;
}

function projectFixturesForEda(eda: ProjectEda, options: ProjectFixtureOptions): ScenarioFixture[] {
  const selected = eda === (options.selectedEda ?? "kicad");
  const runtime = selected && options.runtimeState === "missing"
    ? { available: false, status: "not-installed", version: "", detail: `${names(eda).label} is not installed.` }
    : {};
  const repository = selected
    ? options.repository === undefined
      ? projectCollaboration(eda).repository
      : options.repository
    : projectCollaboration(eda).repository;
  const collaboration = projectCollaboration(
    eda,
    selected && options.diverged && repository
      ? { ...repository, ahead: 1, behind: 1 }
      : repository,
  );
  const geometryState = selected ? options.geometryState ?? "ready" : "ready";
  const visualState = selected ? options.visualState ?? "geometry" : "geometry";
  const visual = projectVisuals(eda, visualState);
  const boardDocumentId = `${eda}-board`;
  const previewMessage = "Fixture Preview blocked this native action. Exit fixture preview and return to Real Data to continue.";
  const openResult: OpenProjectDocumentResult = {
    opened: true,
    document_id: boardDocumentId,
    path: names(eda).board,
  };
  const fixtures: ScenarioFixture[] = [
    {
      method: "GET",
      path: `/api/projects/${PROJECT_IDS[eda]}/workspace`,
      params: {},
      body: undefined,
      response: projectWorkspace(eda, runtime),
      behavior: selected ? options.workspaceBehavior : undefined,
    } satisfies ScenarioFixture<ProjectWorkspace, undefined>,
    {
      method: "GET",
      path: `/api/projects/${PROJECT_IDS[eda]}/collaboration`,
      params: {},
      body: undefined,
      response: collaboration,
    } satisfies ScenarioFixture<ProjectCollaboration, undefined>,
    {
      method: "GET",
      path: `/api/projects/${PROJECT_IDS[eda]}/board-geometry`,
      params: {},
      body: undefined,
      response: projectGeometry(eda, geometryState),
    } satisfies ScenarioFixture<ProjectPlacementGeometry, undefined>,
    {
      method: "GET",
      path: `/api/projects/${PROJECT_IDS[eda]}/visuals`,
      params: {},
      body: undefined,
      response: visual,
    } satisfies ScenarioFixture<ProjectVisualBundle, undefined>,
    {
      method: "GET",
      path: `/api/projects/${PROJECT_IDS[eda]}/visuals`,
      params: { refresh: "true" },
      body: undefined,
      response: visual,
      behavior: selected && options.blockNativeActions
        ? { state: "error", status: 409, message: previewMessage }
        : undefined,
      localOutcome: selected && options.blockNativeActions
        ? { state: "failed", target: "projects.placement-stage", detail: previewMessage }
        : { state: "succeeded", target: "projects.placement-stage" },
    } satisfies ScenarioFixture<ProjectVisualBundle, undefined>,
    {
      method: "GET",
      path: `/api/projects/${PROJECT_IDS[eda]}/visuals/${eda}-top`,
      params: {},
      body: undefined,
      response: new Blob(["<svg viewBox='0 0 1000 620'></svg>"], { type: "image/svg+xml" }),
    } satisfies ScenarioFixture<Blob, undefined>,
    {
      method: "GET",
      path: `/api/projects/${PROJECT_IDS[eda]}/bom/live`,
      params: { boards: "1" },
      body: undefined,
      response: projectBom(eda),
    } satisfies ScenarioFixture<ProjectBom, undefined>,
    {
      method: "GET",
      path: `/api/projects/${PROJECT_IDS[eda]}/assign`,
      params: {},
      body: undefined,
      response: projectAssignments(eda),
    } satisfies ScenarioFixture<ProjectAssignments, undefined>,
    {
      method: "GET",
      path: `/api/projects/${PROJECT_IDS[eda]}/assemblies/active`,
      params: {},
      body: undefined,
      response: assemblyRun(eda, selected && !!options.completedAssembly),
    } satisfies ScenarioFixture<AssemblyRun | null, undefined>,
    {
      method: "GET",
      path: `/api/projects/${PROJECT_IDS[eda]}/reviews`,
      params: {},
      body: undefined,
      response: selected ? options.reviews ?? { base_branch: "main", candidates: [] } : { base_branch: "main", candidates: [] },
    } satisfies ScenarioFixture<ProjectReviews, undefined>,
    {
      method: "POST",
      path: `/api/projects/${PROJECT_IDS[eda]}/documents/${boardDocumentId}/open`,
      params: {},
      body: undefined,
      response: openResult,
      behavior: selected && options.blockNativeActions
        ? { state: "error", status: 409, message: previewMessage }
        : undefined,
      localOutcome: selected && options.blockNativeActions
        ? { state: "failed", target: boardDocumentId, detail: previewMessage }
        : { state: "succeeded", target: boardDocumentId },
    } satisfies ScenarioFixture<OpenProjectDocumentResult, undefined>,
  ];
  if (selected && options.reviewEvidence) {
    const candidate = options.reviews?.candidates[0] ?? SHARED_REVIEWS.candidates[0];
    fixtures.push({
      method: "POST",
      path: `/api/projects/${PROJECT_IDS[eda]}/reviews/evidence`,
      params: {},
      body: {
        branch: candidate.branch,
        commit: candidate.commit,
        base_branch: candidate.base_branch,
        base_commit: candidate.base_commit,
      },
      response: options.reviewEvidence,
      localOutcome: { state: "succeeded", target: candidate.commit },
    } satisfies ScenarioFixture<ProjectReviewEvidence, {
      branch: string;
      commit: string;
      base_branch: string;
      base_commit: string;
    }>);
  }
  return fixtures;
}

export function projectReadFixtures(options: ProjectFixtureOptions = {}): ScenarioFixture[] {
  const projects = [...(options.projects ?? PROJECT_SUMMARIES)];
  return [
    { method: "GET", path: "/api/onboarding", params: {}, body: undefined, response: ONBOARDING_READY },
    {
      method: "GET",
      path: "/api/projects",
      params: {},
      body: undefined,
      response: projects,
      behavior: options.listBehavior,
    } satisfies ScenarioFixture<ProjectSummary[], undefined>,
    ...projectFixturesForEda("kicad", options),
    ...projectFixturesForEda("altium", options),
  ];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isProjectSummary(value: unknown): value is ProjectSummary {
  return isRecord(value) && typeof value.id === "string" && typeof value.name === "string" &&
    (value.eda === "kicad" || value.eda === "altium") && typeof value.root === "string" &&
    typeof value.board_count === "number" && typeof value.sheet_count === "number" &&
    typeof value.has_git === "boolean" && typeof value.registered_at === "string";
}

function isWorkspace(value: unknown): value is ProjectWorkspace {
  return isRecord(value) && isRecord(value.project) && typeof value.project.id === "string" &&
    (value.project.eda === "kicad" || value.project.eda === "altium") &&
    isRecord(value.runtime) && Array.isArray(value.documents) &&
    value.documents.every((document) => isRecord(document) && typeof document.document_id === "string" && typeof document.path === "string") &&
    isRecord(value.parity) && value.parity.schema === "stockroom-project-parity/1";
}

function isCollaboration(value: unknown): value is ProjectCollaboration {
  return isRecord(value) && (value.repository === null || (isRecord(value.repository) &&
    typeof value.repository.branch === "string" && typeof value.repository.clean === "boolean" &&
    typeof value.repository.ahead === "number" && typeof value.repository.behind === "number"));
}

function isGeometry(value: unknown): value is ProjectPlacementGeometry {
  return isRecord(value) && (value.adapter === "kicad" || value.adapter === "altium") &&
    (value.status === "ready" || value.status === "blocked") && Array.isArray(value.boards) &&
    Array.isArray(value.placements) && isRecord(value.summary) && isRecord(value.source);
}

function isVisuals(value: unknown): value is ProjectVisualBundle {
  return isRecord(value) && (value.adapter === "kicad" || value.adapter === "altium") &&
    (value.status === "ready" || value.status === "blocked") && Array.isArray(value.documents) &&
    value.documents.every((document) => isRecord(document) && Array.isArray(document.artifacts)) &&
    isRecord(value.summary) && typeof value.digest === "string";
}

function isBom(value: unknown): value is ProjectBom {
  return isRecord(value) && Array.isArray(value.lines) && typeof value.line_count === "number" &&
    isRecord(value.summary) && isRecord(value.evidence);
}

function isAssignments(value: unknown): value is ProjectAssignments {
  return isRecord(value) && (value.eda === "kicad" || value.eda === "altium") &&
    Array.isArray(value.bound) && Array.isArray(value.groups) && isRecord(value.binding);
}

function isAssembly(value: unknown): value is AssemblyRun | null {
  return value === null || (isRecord(value) && (value.eda === "kicad" || value.eda === "altium") &&
    Array.isArray(value.placements) && Array.isArray(value.events) && isRecord(value.progress));
}

function isReviews(value: unknown): value is ProjectReviews {
  return isRecord(value) && typeof value.base_branch === "string" && Array.isArray(value.candidates) &&
    value.candidates.every((candidate) => isRecord(candidate) && typeof candidate.branch === "string" && typeof candidate.commit === "string");
}

function isReviewEvidence(value: unknown): value is ProjectReviewEvidence {
  return isRecord(value) && typeof value.project_id === "string" && typeof value.commit === "string" &&
    Array.isArray(value.documents) && isRecord(value.bom) && isRecord(value.semantic_audit) &&
    isRecord(value.native_validation) && isRecord(value.visual_diff);
}

function validatorEntries(): Record<string, (fixture: ScenarioFixture) => boolean> {
  const validators: Record<string, (fixture: ScenarioFixture) => boolean> = {
    "GET /api/projects": (fixture) => fixture.body === undefined && Array.isArray(fixture.response) && fixture.response.every(isProjectSummary),
  };
  for (const eda of ["kicad", "altium"] as const) {
    const id = PROJECT_IDS[eda];
    validators[`GET /api/projects/${id}/workspace`] = (fixture) => fixture.body === undefined && isWorkspace(fixture.response);
    validators[`GET /api/projects/${id}/collaboration`] = (fixture) => fixture.body === undefined && isCollaboration(fixture.response);
    validators[`GET /api/projects/${id}/board-geometry`] = (fixture) => fixture.body === undefined && isGeometry(fixture.response);
    validators[`GET /api/projects/${id}/visuals`] = (fixture) => fixture.body === undefined && isVisuals(fixture.response);
    validators[`GET /api/projects/${id}/visuals/${eda}-top`] = (fixture) => fixture.body === undefined && fixture.response instanceof Blob;
    validators[`GET /api/projects/${id}/bom/live`] = (fixture) => fixture.body === undefined && isBom(fixture.response);
    validators[`GET /api/projects/${id}/assign`] = (fixture) => fixture.body === undefined && isAssignments(fixture.response);
    validators[`GET /api/projects/${id}/assemblies/active`] = (fixture) => fixture.body === undefined && isAssembly(fixture.response);
    validators[`GET /api/projects/${id}/reviews`] = (fixture) => fixture.body === undefined && isReviews(fixture.response);
    validators[`POST /api/projects/${id}/documents/${eda}-board/open`] = (fixture) => fixture.body === undefined && isRecord(fixture.response) && fixture.response.opened === true && typeof fixture.response.document_id === "string";
    validators[`POST /api/projects/${id}/reviews/evidence`] = (fixture) => isRecord(fixture.body) && typeof fixture.body.commit === "string" && isReviewEvidence(fixture.response);
  }
  return validators;
}

export const projectFixtureValidators = createScenarioFixtureValidatorRegistry(
  validatorEntries(),
  providerFixtureValidators,
);
