import { describe, expect, it } from "vitest";

import { ICON_BY_ID } from "./iconRegistry";
import { TABLER_SOURCE_BY_ID, tablerBody } from "./tablerIconSources";

describe("curated product icon sources", () => {
  it("renders every semantic default from its exact pinned Tabler Outline asset", () => {
    for (const [id, source] of Object.entries(TABLER_SOURCE_BY_ID)) {
      const entry = ICON_BY_ID.get(id);
      expect(entry, id).toBeDefined();
      expect(entry?.family, id).toBe("tabler-outline");
      expect(entry?.sourceIcon, id).toBe(source.sourceIcon);
      expect(entry?.body, id).toBe(tablerBody(source.raw));
    }
  });
});
