import type { IconRegistry } from "@astryxdesign/core/Icon";

import { ICON_BY_ID, type IconId } from "../../lib/iconRegistry";

function themeIcon(id: IconId) {
  const entry = ICON_BY_ID.get(id);
  if (!entry || entry.family !== "tabler-outline") {
    throw new Error(`Missing Tabler Outline theme icon: ${id}`);
  }
  return (
    <svg
      width="1em"
      height="1em"
      viewBox={entry.viewBox}
      fill="none"
      stroke="currentColor"
      strokeWidth={entry.strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      data-icon-family="tabler-outline"
      data-icon-id={id}
      dangerouslySetInnerHTML={{ __html: entry.body }}
    />
  );
}

/** Astryx semantic slots adapted to Stockroom's central, bundled Tabler Outline authority. */
export const neutralIconRegistry: IconRegistry = {
  close: themeIcon("action.close"),
  chevronDown: themeIcon("navigation.chevron-down"),
  chevronLeft: themeIcon("navigation.chevron-left"),
  chevronRight: themeIcon("overlay.chevron"),
  chevronsLeft: themeIcon("navigation.chevrons-left"),
  chevronsRight: themeIcon("navigation.chevrons-right"),
  check: themeIcon("overlay.check"),
  success: themeIcon("status.success"),
  error: themeIcon("status.error"),
  warning: themeIcon("status.warn"),
  info: themeIcon("status.info"),
  calendar: themeIcon("utility.calendar"),
  clock: themeIcon("utility.clock"),
  externalLink: themeIcon("action.external"),
  menu: themeIcon("action.menu"),
  moreHorizontal: themeIcon("action.more"),
  search: themeIcon("action.search"),
  arrowUp: themeIcon("action.sort-asc"),
  arrowDown: themeIcon("action.sort-desc"),
  arrowsUpDown: themeIcon("action.sort-swap"),
  funnel: themeIcon("finder.filter"),
  eyeSlash: themeIcon("action.hide"),
  viewColumns: themeIcon("action.columns"),
  copy: themeIcon("action.duplicate"),
  checkDouble: themeIcon("modal.check"),
  wrench: themeIcon("nav.settings"),
  stop: themeIcon("action.stop"),
  microphone: themeIcon("utility.microphone"),
};
