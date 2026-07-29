import { MODEL_RENDERER_PARAMETERS } from "./threeScene";

describe("3D scene theme contract", () => {
  it("keeps the WebGL canvas transparent so the host's light/dark stage token remains visible", () => {
    expect(MODEL_RENDERER_PARAMETERS).toEqual({ antialias: true, alpha: true });
  });
});
