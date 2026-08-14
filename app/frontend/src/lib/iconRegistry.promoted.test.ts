import { describe, expect, it } from "vitest";
import {
  faBox,
  faBoxOpen,
  faCircleQuestion,
  faMicrochip,
  type IconDefinition,
} from "@fortawesome/free-solid-svg-icons";
import material from "@iconify-json/material-symbols/icons.json";
import phosphor from "@iconify-json/ph/icons.json";
import tabler from "@iconify-json/tabler/icons.json";
import { ICON_BY_ID } from "./iconRegistry";

type IconifyCollection = {
  width?: number;
  height?: number;
  icons: Record<string, { body: string; width?: number; height?: number }>;
};

function fontAwesomeBody(icon: IconDefinition): { body: string; viewBox: string } {
  const [width, height, , , source] = icon.icon;
  if (typeof source !== "string") throw new Error(`expected one path for ${icon.iconName}`);
  return { body: `<path d="${source}"/>`, viewBox: `0 0 ${width} ${height}` };
}

function iconifyBody(
  collection: IconifyCollection,
  name: string,
): { body: string; viewBox: string } {
  const icon = collection.icons[name];
  if (!icon) throw new Error(`missing pinned catalogue icon ${name}`);
  const width = icon.width ?? collection.width ?? 24;
  const height = icon.height ?? collection.height ?? 24;
  return { body: icon.body, viewBox: `0 0 ${width} ${height}` };
}

function fittedBody(source: { body: string; viewBox: string }, targetViewBox: string): string {
  const [targetX, targetY, targetWidth, targetHeight] = targetViewBox.split(/\s+/).map(Number);
  const [, , sourceWidth, sourceHeight] = source.viewBox.split(/\s+/).map(Number);
  const scale = Math.min(targetWidth / sourceWidth, targetHeight / sourceHeight);
  const x = targetX + (targetWidth - sourceWidth * scale) / 2;
  const y = targetY + (targetHeight - sourceHeight * scale) / 2;
  return `<g transform="translate(${x} ${y}) scale(${scale})" fill="currentColor" stroke="none">${source.body}</g>`;
}

const PROMOTED: Record<string, { body: string; viewBox: string }> = {
  "action.external": iconifyBody(tabler, "circle-arrow-up-right-filled"),
  "brand.wordmark": fontAwesomeBody(faBoxOpen),
  "nav.about": iconifyBody(material, "info-rounded"),
  "nav.board": fontAwesomeBody(faBox),
  "nav.collapse-rail": iconifyBody(tabler, "square-rounded-chevron-right-filled"),
  "nav.components": iconifyBody(material, "book-2-rounded"),
  "nav.settings": iconifyBody(phosphor, "gear-six-fill"),
  "nav.stm": fontAwesomeBody(faMicrochip),
  "nav.theme": iconifyBody(phosphor, "moon-fill"),
  "nav.update": iconifyBody(tabler, "arrow-big-down-line-filled"),
};

describe("owner-promoted interface icons", () => {
  for (const [id, source] of Object.entries(PROMOTED)) {
    it(`${id} exactly fits its pinned catalogue source`, () => {
      const entry = ICON_BY_ID.get(id);
      expect(entry, id).toBeDefined();
      expect(entry?.body).toBe(fittedBody(source, entry!.viewBox));
    });
  }

  it("keeps the missing-CAD mark byte-identical to Font Awesome circle-question", () => {
    const source = fontAwesomeBody(faCircleQuestion);
    const entry = ICON_BY_ID.get("status.cad-missing");
    expect(entry?.viewBox).toBe(source.viewBox);
    expect(entry?.body).toBe(source.body);
  });
});
