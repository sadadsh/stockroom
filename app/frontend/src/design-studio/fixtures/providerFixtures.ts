import type { CadVariantDocument } from "../../api/cadVariantClient";
import type { CadSourceResponse } from "../../api/types";
import type { ScenarioFixture } from "../scenario";
import { createScenarioFixtureValidatorRegistry } from "../scenarioFixtureValidation";
import {
  COMPONENT_ID,
  componentFixtureValidators,
  componentReadFixtures,
} from "./componentFixtures";

export type ProviderFixtureState =
  | "loading"
  | "ready"
  | "sign-in"
  | "waiting-for-person"
  | "format-selection"
  | "download-armed"
  | "one-file"
  | "multiple-files"
  | "partial-retained"
  | "unavailable"
  | "timeout"
  | "canceled"
  | "error"
  | "selected-file-recovery"
  | "returned-to-stockroom"
  | "complete";

interface AddPartFilesResponse {
  part_id: string;
  selected_files: number;
  attached: string[];
  ignored: string[];
  remaining: string[];
  complete: boolean;
}

function cadSource(state: ProviderFixtureState): CadSourceResponse {
  const complete = state === "complete";
  return {
    mpn: "LM358DR",
    needs: complete ? [] : ["kicad_symbol", "kicad_footprint", "kicad_model", "altium_symbol", "altium_footprint"],
    completion_evidence: complete
      ? { state: "verified", manifest_digest: `sha256:${"a".repeat(64)}`, reason: "Verified retained set" }
      : null,
    sources: [{
      key: "ultralibrarian",
      label: "Ultra Librarian",
      url: "https://example.invalid/ultralibrarian/lm358dr",
      tools: ["kicad", "altium"],
      aggregator: true,
      instruction:
        state === "sign-in"
          ? "Sign in to continue. Stockroom never enters credentials."
          : state === "format-selection"
            ? "Choose KiCad and Altium formats, then download."
            : "Download the complete verified set.",
      capture_available: !["unavailable", "error"].includes(state),
    }],
    url: "https://example.invalid/ultralibrarian/lm358dr",
    vendor: "ultralibrarian",
  };
}

function variants(state: ProviderFixtureState): CadVariantDocument {
  const hasRetained = ["partial-retained", "one-file", "multiple-files", "complete"].includes(state);
  if (!hasRetained) return { partId: COMPONENT_ID, inventories: [], pairs: [], supplementary: [] };
  const kicadId = "variant-ultralibrarian-kicad";
  const altiumId = "variant-ultralibrarian-altium";
  return {
    partId: COMPONENT_ID,
    inventories: [
      {
        tool: "kicad",
        activeVariantId: state === "complete" ? kicadId : null,
        variants: [{
          id: kicadId,
          provider: "Ultra Librarian",
          format: "KiCad",
          artifacts: [
            { kind: "symbol", fileName: "LM358.kicad_sym" },
            { kind: "footprint", fileName: "LM358.kicad_mod" },
            { kind: "model", fileName: "LM358.step" },
          ],
          evidenceDigest: "sha256:kicad-fixture",
          verificationState: "reverified",
          trustRank: 1,
          trustLabel: "Provider Evidence",
        }],
      },
      {
        tool: "altium",
        activeVariantId: state === "complete" ? altiumId : null,
        variants: [{
          id: altiumId,
          provider: "Ultra Librarian",
          format: "Altium",
          artifacts: [
            { kind: "symbol", fileName: "LM358.SchLib" },
            { kind: "footprint", fileName: "LM358.PcbLib" },
            { kind: "model", fileName: "LM358.step" },
          ],
          evidenceDigest: "sha256:altium-fixture",
          verificationState: "reverified",
          trustRank: 1,
          trustLabel: "Provider Evidence",
        }],
      },
    ],
    pairs: [{
      kicadVariantId: kicadId,
      altiumVariantId: altiumId,
      provider: "Ultra Librarian",
      trustRank: 1,
      verificationState: "reverified",
      trustLabel: "Provider Evidence",
    }],
    supplementary: [],
  };
}

export function providerReadFixtures(state: ProviderFixtureState): ScenarioFixture[] {
  const componentFixtures = componentReadFixtures().map((fixture) =>
    state === "selected-file-recovery" && fixture.path === `/api/previews/model/${COMPONENT_ID}.glb`
      ? { ...fixture, behavior: undefined }
      : fixture,
  );
  const variantFixture: ScenarioFixture<CadVariantDocument, undefined> = {
    method: "GET",
    path: `/api/library/parts/${COMPONENT_ID}/cad-variants`,
    params: {},
    body: undefined,
    response: variants(state),
    behavior: state === "loading" ? { state: "pending" } : undefined,
  };
  const fixtures: ScenarioFixture[] = [
    ...componentFixtures,
    {
      method: "GET",
      path: `/api/library/parts/${COMPONENT_ID}/cad-source`,
      params: {},
      body: undefined,
      response: cadSource(state),
      behavior:
        state === "timeout"
          ? { state: "error", status: 504, message: "The provider timed out." }
          : state === "error"
            ? { state: "error", status: 500, message: "The provider failed." }
            : undefined,
    } satisfies ScenarioFixture<CadSourceResponse, undefined>,
    variantFixture,
  ];
  if (state === "selected-file-recovery") {
    fixtures.push({
      method: "POST",
      path: `/api/library/parts/${COMPONENT_ID}/files`,
      params: {},
      body: { paths: ["C:\\Downloads\\LM358DR.zip"] },
      response: {
        part_id: COMPONENT_ID,
        selected_files: 1,
        attached: ["kicad_symbol", "kicad_footprint"],
        ignored: [],
        remaining: ["kicad_model", "altium_symbol", "altium_footprint"],
        complete: false,
      },
      localOutcome: {
        state: "succeeded",
        target: COMPONENT_ID,
        detail: "Attached the selected recovery archive in fixture memory.",
      },
    } satisfies ScenarioFixture<AddPartFilesResponse, { paths: string[] }>);
  }
  if (state === "download-armed") {
    fixtures.push({
      method: "POST",
      path: "/api/library/capture/batches/batch-provider-fixture/provider/show",
      params: {},
      body: undefined,
      response: {
        workflow_batch_id: "batch-provider-fixture",
        part_id: COMPONENT_ID,
        visible: true,
      },
      localOutcome: {
        state: "succeeded",
        target: "provider-tab",
        detail: "Brought the in-memory provider host target forward.",
      },
    } satisfies ScenarioFixture<{
      workflow_batch_id: string;
      part_id: string;
      visible: boolean;
    }, undefined>);
  }
  return fixtures;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export const providerFixtureValidators = createScenarioFixtureValidatorRegistry({
  [`GET /api/library/parts/${COMPONENT_ID}/cad-source`]: (fixture) =>
    fixture.body === undefined && isRecord(fixture.response) && typeof fixture.response.mpn === "string" && Array.isArray(fixture.response.needs) && Array.isArray(fixture.response.sources),
  [`GET /api/library/parts/${COMPONENT_ID}/cad-variants`]: (fixture) =>
    fixture.body === undefined && isRecord(fixture.response) && fixture.response.partId === COMPONENT_ID && Array.isArray(fixture.response.inventories) && Array.isArray(fixture.response.pairs) && Array.isArray(fixture.response.supplementary),
  [`POST /api/library/parts/${COMPONENT_ID}/files`]: (fixture) =>
    isRecord(fixture.body) && Array.isArray(fixture.body.paths) && fixture.body.paths.every((path) => typeof path === "string") &&
    isRecord(fixture.response) && fixture.response.part_id === COMPONENT_ID && typeof fixture.response.selected_files === "number" &&
    Array.isArray(fixture.response.attached) && Array.isArray(fixture.response.ignored) && Array.isArray(fixture.response.remaining) &&
    typeof fixture.response.complete === "boolean",
  "POST /api/library/capture/batches/batch-provider-fixture/provider/show": (fixture) =>
    fixture.body === undefined && isRecord(fixture.response) &&
    fixture.response.workflow_batch_id === "batch-provider-fixture" &&
    fixture.response.part_id === COMPONENT_ID && typeof fixture.response.visible === "boolean",
}, componentFixtureValidators);
