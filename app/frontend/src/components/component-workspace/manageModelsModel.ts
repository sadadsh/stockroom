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
  supplied: CoverageArtifact[];
  missing: CoverageArtifact[];
}

function describeProvider(row: ProviderCoverageRow): ManageModelsProvider {
  const supplied = ARTIFACTS.filter((artifact) => SUPPLIED_STATUSES.has(row[artifact].status));
  const missing = ARTIFACTS.filter((artifact) => !supplied.includes(artifact));

  return {
    row,
    complete: row.complete && missing.length === 0,
    supplied,
    missing,
  };
}

export function orderedManageModelsProviders(
  coverage: ComponentProvidersView,
): ManageModelsProvider[] {
  const providers = coverage.rows.map(describeProvider);
  return [
    ...providers.filter((provider) => provider.complete),
    ...providers.filter((provider) => !provider.complete),
  ];
}

export function bestCompleteProvider(
  providers: readonly ManageModelsProvider[],
): ManageModelsProvider | null {
  return providers.find((provider) => provider.complete) ?? null;
}
