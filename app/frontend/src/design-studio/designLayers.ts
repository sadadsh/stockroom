/** Product-authored layers must remain inside the shared save grammar. */
export const DESIGN_TARGET_Z_INDEX_MIN = -9999;
export const DESIGN_TARGET_Z_INDEX_MAX = 9999;

/** The editor grid paints above every grammar-valid product target. */
export const DESIGN_STUDIO_GRID_Z_INDEX = DESIGN_TARGET_Z_INDEX_MAX + 1;
