import { describe, expect, it } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { mountScenario } from "./testHarness";
import { stmScenarioIds } from "./stm";

describe("STM Design Studio scenarios", () => {
  it("clicks from MCU selection through pin and alternate-function inspection", async () => {
    const { user, liveRequest } = await mountScenario("stm.explorer-matrix");
    await user.click(await screen.findByText("STM32F407VETx"));
    fireEvent.click(document.querySelector('[data-position="23"]')!);
    expect(screen.getByRole("region", { name: "Alternate Functions" })).toBeVisible();
    expect(liveRequest).not.toHaveBeenCalled();
  });

  it.each(stmScenarioIds)("mounts the real production tree for %s", async (id) => {
    const { liveRequest } = await mountScenario(id);
    expect(document.querySelector('[data-dev-id="stm.root"]')).toBeVisible();
    expect(liveRequest).not.toHaveBeenCalled();
  });
});
