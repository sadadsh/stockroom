import type {
  EditableTargetDomain,
  TargetInspection,
} from "../../../design-studio/targetDomains";

export interface DomainInspectorProps {
  inspection: TargetInspection;
  inspections: readonly TargetInspection[];
  affectedTargetIds: readonly string[];
  boxOverrideIds?: readonly string[];
  setDomainProperty: (domain: EditableTargetDomain, property: string, value: string) => void;
  resetDomainProperty: (domain: EditableTargetDomain, property: string) => void;
}
