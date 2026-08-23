import type { GuidedSetupStatus } from "../../api/types";

export const GUIDED_SETUP_READY: GuidedSetupStatus = {
  schema: 1,
  step: "ready",
  steps: [
    "choose_cad_tool",
    "catalog_repository",
    "connect_the_tool",
  ],
  ready: true,
  repository_ready: true,
  repository: {
    owner: "engineer",
    name: "stockroom-catalog",
    url: "https://github.com/engineer/stockroom-catalog.git",
  },
  github: {
    available: true,
    version: "2.80.0",
    authenticated: true,
    online: true,
    viewer: { login: "engineer", name: "PCB Engineer" },
    owners: [
      { login: "engineer", kind: "personal" },
      { login: "hardware-team", kind: "organization" },
    ],
    verified_repository: {
      owner: "engineer",
      name: "stockroom-catalog",
      url: "https://github.com/engineer/stockroom-catalog.git",
      visibility: "private",
      permission: "admin",
      writable: true,
    },
  },
  tool_connection: {
    tool: "kicad",
    installed: true,
    connected: true,
    restart_required: false,
    detail: "KiCad is connected.",
  },
  source_data: {
    decided: true,
    skipped: true,
    mouser_connected: false,
    digikey_connected: false,
  },
};

export const GUIDED_SETUP_CHOOSE_CAD: GuidedSetupStatus = {
  ...GUIDED_SETUP_READY,
  step: "choose_cad_tool",
  ready: false,
  repository_ready: false,
  repository: null,
  github: {
    available: true,
    version: "2.80.0",
    authenticated: false,
    online: true,
    viewer: null,
    owners: [],
  },
  tool_connection: {
    tool: null,
    installed: false,
    connected: false,
    restart_required: false,
    detail: "Choose KiCad or Altium.",
  },
  source_data: {
    decided: false,
    skipped: false,
    mouser_connected: false,
    digikey_connected: false,
  },
};

export function guidedSetupAt(
  step: GuidedSetupStatus["step"],
  overrides: Partial<GuidedSetupStatus> = {},
): GuidedSetupStatus {
  return {
    ...GUIDED_SETUP_READY,
    step,
    ready: step === "ready",
    ...overrides,
  };
}
