/**
 * Electronics marks Tabler does not provide. They use the same 24 px, 2 px, round outline frame as
 * the curated Tabler defaults, but preserve the component's actual circuit identity.
 */
export const STOCKROOM_ELECTRICAL_BODY_BY_ID = Object.freeze({
  "category.crystal":
    '<path d="M3 12h4"/><path d="M8 7v10"/><rect x="10" y="8" width="4" height="8" rx="1"/><path d="M16 7v10"/><path d="M17 12h4"/>',
  "category.fuse":
    '<path d="M3 12h4"/><rect x="7" y="9" width="10" height="6" rx="1"/><path d="M17 12h4"/>',
  "category.led":
    '<path d="M22 12h-6"/><path d="M2 12h6"/><path d="M8 7l8 5l-8 5v-10"/><path d="M16 7v10"/><path d="M17 6l4-4"/><path d="M18 2h3v3"/>',
  "category.opamp":
    '<path d="M5 4l14 8l-14 8z"/><path d="M2 9h3"/><path d="M2 15h3"/><path d="M19 12h3"/><path d="M7.5 8h3"/><path d="M9 6.5v3"/><path d="M7.5 15h3"/>',
  "category.transformer":
    '<path d="M3 6h3M3 18h3M18 6h3M18 18h3"/><path d="M7 6c3 1 3 3 0 4c3 1 3 3 0 4c3 1 3 3 0 4"/><path d="M17 6c-3 1-3 3 0 4c-3 1-3 3 0 4c-3 1-3 3 0 4"/><path d="M11 4v16M13 4v16"/>',
  "category.transistor":
    '<path d="M3 12h5"/><path d="M8 7v10"/><path d="M8 10l7-5h4"/><path d="M8 14l7 5h4"/><path d="M13 16l2 3l-4 1"/>',
} as const);

export type StockroomElectricalIconId = keyof typeof STOCKROOM_ELECTRICAL_BODY_BY_ID;
