/**
 * Committed behavior overrides written by Dev Mode. Each entry changes how one compatible
 * control renders while preserving its value, options, disabled state, and change handler.
 * Generated whole by POST /api/dev/save.
 */
export type ChoicePreset = "dropdown" | "segmented" | "radio" | "searchable";

export interface BehaviorOverride {
  preset?: ChoicePreset;
  disabled?: boolean;
}

export const BEHAVIOR_OVERRIDES: Record<string, BehaviorOverride> = {};
