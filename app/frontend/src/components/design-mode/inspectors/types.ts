import type { TargetInspection } from "../../../design-studio/targetDomains";

export interface DomainInspectorProps {
  inspection: TargetInspection;
  affectedTargetIds: readonly string[];
  setElementProperty: (property: string, value: string) => void;
  resetElementProperty: (property: string) => void;
}
