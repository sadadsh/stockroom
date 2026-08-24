import { describe, expect, it } from "vitest";
import {
  generatedDesignId,
  transformStockroomJsx,
} from "../../scripts/design-identity-transform.mjs";

describe("automatic design identity transform", () => {
  it("adds stable global identities to every Stockroom host element", async () => {
    const source = `
      export function ProviderCard() {
        return <section><button><span>Open</span></button></section>;
      }
    `;
    const filename = "D:/repo/app/frontend/src/components/ProviderCard.tsx";
    const first = await transformStockroomJsx(source, filename);
    const second = await transformStockroomJsx(source, filename);

    expect(first).toBe(second);
    expect(first?.match(/data-design-id=/g)).toHaveLength(3);
    expect(first).toContain(generatedDesignId("components/ProviderCard.tsx", "ProviderCard", "section", 3, 15));
  });

  it("keeps authored ids authoritative and excludes editor chrome and technical CAD geometry", async () => {
    const source = `
      export function Preview() {
        return <><div data-dev-id="cad.preview"><svg data-design-technical-content="true"><path d="M0 0" /></svg></div><aside /></>;
      }
    `;
    const transformed = await transformStockroomJsx(
      source,
      "D:/repo/app/frontend/src/components/cad/Preview.tsx",
    );

    expect(transformed?.match(/data-design-id=/g)).toHaveLength(1);
    expect(transformed).not.toMatch(/<div[^>]+data-design-id/);
    expect(
      await transformStockroomJsx(
        "export function Toolbar(){ return <header />; }",
        "D:/repo/app/frontend/src/components/design-mode/Toolbar.tsx",
      ),
    ).toBeNull();
  });

  it("preserves a rendered list key as a durable occurrence discriminator", async () => {
    const transformed = await transformStockroomJsx(
      `export function Rows({ rows }) { return <>{rows.map((row) => <span key={row.id}>{row.label}</span>)}</>; }`,
      "D:/repo/app/frontend/src/components/Rows.tsx",
    );

    expect(transformed).toContain("data-design-key={row.id}");
  });
});
