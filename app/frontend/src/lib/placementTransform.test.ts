import { describe, expect, it } from "vitest";
import * as THREE from "three";
import {
  type KiCadModelPlacement,
  kicadModelPlacementMatrix,
} from "./placementTransform";

const IDENTITY: KiCadModelPlacement = {
  offset: [0, 0, 0],
  rotate: [0, 0, 0],
  scale: [1, 1, 1],
};

function expectVector(actual: THREE.Vector3, expected: THREE.Vector3) {
  actual.toArray().forEach((value, index) => {
    expect(value).toBeCloseTo(expected.getComponent(index), 9);
  });
}

describe("kicadModelPlacementMatrix", () => {
  it("keeps identity placement as identity", () => {
    const matrix = kicadModelPlacementMatrix(IDENTITY);
    matrix.elements.forEach((value, index) => {
      expect(value).toBeCloseTo(new THREE.Matrix4().elements[index], 12);
    });
  });

  it("maps KiCad offset and anisotropic scale into the Y-up render axes", () => {
    const matrix = kicadModelPlacementMatrix({
      offset: [2, 3, 4],
      rotate: [0, 0, 0],
      scale: [5, 6, 7],
    });
    const position = new THREE.Vector3();
    const rotation = new THREE.Quaternion();
    const scale = new THREE.Vector3();
    matrix.decompose(position, rotation, scale);

    expectVector(position, new THREE.Vector3(2, 4, -3));
    expectVector(scale, new THREE.Vector3(5, 7, 6));
  });

  it("preserves KiCad's transform order when several rotation axes are non-zero", () => {
    const placement: KiCadModelPlacement = {
      offset: [0.4, -0.7, 1.2],
      rotate: [37, 81, -24],
      scale: [1.1, 0.8, 1.6],
    };
    const degrees = placement.rotate.map((value) => (value * Math.PI) / 180);
    const sourceTransform = new THREE.Matrix4()
      .makeTranslation(...placement.offset)
      .multiply(new THREE.Matrix4().makeRotationZ(-degrees[2]))
      .multiply(new THREE.Matrix4().makeRotationY(-degrees[1]))
      .multiply(new THREE.Matrix4().makeRotationX(-degrees[0]))
      .multiply(new THREE.Matrix4().makeScale(...placement.scale));
    const basis = new THREE.Matrix4().makeRotationX(-Math.PI / 2);
    const sourcePoint = new THREE.Vector3(0.6, -1.4, 2.3);

    const expected = sourcePoint.clone().applyMatrix4(sourceTransform).applyMatrix4(basis);
    const normalizedPoint = sourcePoint.clone().applyMatrix4(basis);
    const actual = normalizedPoint.applyMatrix4(kicadModelPlacementMatrix(placement));

    expectVector(actual, expected);
  });
});
