export const DEFAULT_FRONTEND_BUILD_INPUTS: readonly string[];

export function frontendContentRevision(
  frontendRoot: string,
  inputs?: readonly string[],
): string;

export function assertProductionBuildEnvironment(
  environment?: Readonly<Record<string, string | undefined>>,
): void;
