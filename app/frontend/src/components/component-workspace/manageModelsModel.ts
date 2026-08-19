import type {
  ComponentProvidersView,
  CoverageArtifact,
  CoverageStatus,
  ProviderCoverageRow,
} from "../../api/dossierTypes";

const SUPPLIED_STATUSES = new Set<CoverageStatus>(["available", "downloaded", "validated"]);

const ARTIFACTS: ReadonlyArray<CoverageArtifact> = ["symbol", "footprint", "model"];

export interface ManageModelsProvider {
  row: ProviderCoverageRow;
  complete: boolean;
  reachable: boolean;
  supplied: CoverageArtifact[];
  missing: CoverageArtifact[];
}

function describeProvider(row: ProviderCoverageRow): ManageModelsProvider {
  const supplied = ARTIFACTS.filter((artifact) => SUPPLIED_STATUSES.has(row[artifact].status));
  const missing = ARTIFACTS.filter((artifact) => !supplied.includes(artifact));

  return {
    row,
    complete: row.complete && missing.length === 0,
    reachable: row.url.trim().length > 0,
    supplied,
    missing,
  };
}

export function orderedManageModelsProviders(
  coverage: ComponentProvidersView,
): ManageModelsProvider[] {
  return coverage.rows
    .map(describeProvider)
    .sort((left, right) =>
      Number(right.row.captureAvailable) - Number(left.row.captureAvailable)
      || left.row.order - right.row.order,
    );
}

export function bestCompleteProvider(
  providers: readonly ManageModelsProvider[],
): ManageModelsProvider | null {
  return providers.find(
    (provider) => provider.complete && provider.reachable && provider.row.captureAvailable,
  ) ?? null;
}
