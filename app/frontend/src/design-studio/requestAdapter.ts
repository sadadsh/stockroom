import type { DesignScenario, ScenarioFixture } from "./scenario";
import { guardPreviewRequest } from "./mutationGuard";

export type { DesignScenario, ScenarioFixture } from "./scenario";

export type ApiRequestParams = Readonly<Record<string, string | readonly string[]>>;

export interface ApiRequestDescriptor {
  method: string;
  path: string;
  params: ApiRequestParams;
  body: unknown;
}

export interface ApiRequestAdapter {
  handle<T>(descriptor: ApiRequestDescriptor, live: () => Promise<T>): Promise<T>;
}

export class MissingScenarioFixtureError extends Error {
  readonly descriptor: ApiRequestDescriptor;
  readonly scenarioId: string;

  constructor(scenarioId: string, descriptor: ApiRequestDescriptor) {
    super(
      `Scenario '${scenarioId}' has no fixture for ${descriptor.method.toUpperCase()} ` +
        `${descriptor.path}. The request was not sent to live Stockroom data.`,
    );
    this.name = "MissingScenarioFixtureError";
    this.scenarioId = scenarioId;
    this.descriptor = descriptor;
  }
}

function sameValue(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true;
  if (Array.isArray(left) || Array.isArray(right)) {
    return (
      Array.isArray(left) &&
      Array.isArray(right) &&
      left.length === right.length &&
      left.every((entry, index) => sameValue(entry, right[index]))
    );
  }
  if (
    left === null ||
    right === null ||
    typeof left !== "object" ||
    typeof right !== "object"
  ) {
    return false;
  }
  const leftRecord = left as Record<string, unknown>;
  const rightRecord = right as Record<string, unknown>;
  const leftKeys = Object.keys(leftRecord).sort();
  const rightKeys = Object.keys(rightRecord).sort();
  return (
    sameValue(leftKeys, rightKeys) &&
    leftKeys.every((key) => sameValue(leftRecord[key], rightRecord[key]))
  );
}

function sameRequest(fixture: ScenarioFixture, descriptor: ApiRequestDescriptor): boolean {
  return (
    fixture.method.toUpperCase() === descriptor.method.toUpperCase() &&
    fixture.path === descriptor.path &&
    sameValue(fixture.params, descriptor.params) &&
    sameValue(fixture.body, descriptor.body)
  );
}

export function previewAdapter(scenario: DesignScenario): ApiRequestAdapter {
  return {
    async handle<T>(descriptor: ApiRequestDescriptor, live: () => Promise<T>): Promise<T> {
      const fixture = scenario.fixtures.find((candidate) => sameRequest(candidate, descriptor));
      if (fixture) return fixture.response as T;

      const classification = guardPreviewRequest(descriptor);
      if (classification === "studio-live") return live();
      throw new MissingScenarioFixtureError(scenario.id, descriptor);
    },
  };
}

const installedAdapters: { adapter: ApiRequestAdapter; active: boolean }[] = [];

function currentAdapter(): ApiRequestAdapter | null {
  for (let index = installedAdapters.length - 1; index >= 0; index -= 1) {
    if (installedAdapters[index].active) return installedAdapters[index].adapter;
  }
  return null;
}

/** Installs one scoped adapter and returns an idempotent restoration function. */
export function installApiRequestAdapter(adapter: ApiRequestAdapter): () => void {
  const registration = { adapter, active: true };
  installedAdapters.push(registration);
  return () => {
    if (!registration.active) return;
    registration.active = false;
    while (
      installedAdapters.length &&
      !installedAdapters[installedAdapters.length - 1]?.active
    ) {
      installedAdapters.pop();
    }
  };
}

/** The single client dispatch seam. With no installed adapter, live behavior is unchanged. */
export function dispatchApiRequest<T>(
  descriptor: ApiRequestDescriptor,
  live: () => Promise<T>,
): Promise<T> {
  return currentAdapter()?.handle(descriptor, live) ?? live();
}
