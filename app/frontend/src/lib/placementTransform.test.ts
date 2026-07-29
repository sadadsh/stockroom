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

  it("does not reinterpret a literal zero scale as an omitted identity scale", () => {
    const matrix = kicadModelPlacementMatrix({
      offset: [0, 0, 0],
      rotate: [0, 0, 0],
      scale: [1, 0, 2],
    });
    const sourcePoint = new THREE.Vector3(3, 4, 5);
    const basis = new THREE.Matrix4().makeRotationX(-Math.PI / 2);
    const sourceTransform = new THREE.Matrix4().makeScale(1, 0, 2);

    const expected = sourcePoint.clone().applyMatrix4(sourceTransform).applyMatrix4(basis);
    const actual = sourcePoint
      .clone()
      .applyMatrix4(basis)
      .applyMatrix4(matrix);

    expectVector(actual, expected);
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

  const realRotationsAt270: Array<{
    name: string;
    footprintBlob: string;
    placement: KiCadModelPlacement;
  }> = [
    {
      name: "73251-2120",
      footprintBlob: "ef978568216287b9a66fca383994abaf4c48a7a4",
      placement: { offset: [0, 0, 0], rotate: [0, 0, 270], scale: [1, 1, 1] },
    },
    {
      name: "103AT-2",
      footprintBlob: "775d9d5e476f7d9bca5cea1c69c98760f3598053",
      placement: { offset: [0, 0, 0], rotate: [0, 0, 270], scale: [1, 1, 1] },
    },
    {
      name: "TPD4E05U06DQAR",
      footprintBlob: "8198518ba1bcb36b7f3573b2fd7ed0225c539d7a",
      placement: { offset: [0, 0, 0], rotate: [0, 0, 270], scale: [1, 1, 1] },
    },
    {
      name: "DRV2605LDGSR",
      footprintBlob: "5087a644dd5271bcef9df4ca23b1a5b934023461",
      placement: { offset: [0, 0, 0], rotate: [0, 0, 270], scale: [1, 1, 1] },
    },
    {
      name: "MAX6817EUT+T",
      footprintBlob: "f41d28f37a82ee3098a5c012f4b9fec99c7bf72a",
      placement: { offset: [0, 0, 0], rotate: [0, 0, 270], scale: [1, 1, 1] },
    },
    {
      name: "TLV7021DBVR",
      footprintBlob: "028e822e6ad8e1a582325ca9b2096660c96ce168",
      placement: { offset: [0, 0, 0], rotate: [0, 0, 270], scale: [1, 1, 1] },
    },
    {
      name: "AF0603FR-072R2L",
      footprintBlob: "32dea0ebb7903aa30037b61591ed098bf8d67637",
      placement: { offset: [0, 0, 0], rotate: [0, 0, 270], scale: [1, 1, 1] },
    },
    {
      name: "TPS2121RUXR",
      footprintBlob: "a20f1029faeeae58dcffbc14aec4d18c5ec48bf6",
      placement: { offset: [0, 0, 0], rotate: [0, 0, 270], scale: [1, 1, 1] },
    },
    {
      name: "DMG3414U-7",
      footprintBlob: "d99fedb8ca22d5eb172f86eeeddc545ae552aeda",
      placement: { offset: [0, 0, 0], rotate: [0, 0, 270], scale: [1, 1, 1] },
    },
    {
      name: "DMN2056U-7",
      footprintBlob: "8c235d4398c9254e9524889643e989fee79cc00d",
      placement: { offset: [0, 0, 0], rotate: [0, 0, 270], scale: [1, 1, 1] },
    },
  ];

  it.each(realRotationsAt270)(
    "$name matches the KiCad 10 native GLB node for the real 270-degree pair",
    ({ placement, footprintBlob }) => {
      // scripts/verify_3d_rotation_corpus.py recovers each immutable blob from
      // dbaaf71f3aeb04cc322e76975a6549372a69142e and asks KiCad 10.0.4 to
      // export it. Every native component node is +90 degrees about render Y:
      // KiCad therefore applies the negative of the footprint's +270 source-Z
      // rotation. The opposite sign differs by 2.0 in the linear matrix.
      expect(footprintBlob).toHaveLength(40);
      const expected = new THREE.Matrix4().makeRotationY(Math.PI / 2);
      const actual = kicadModelPlacementMatrix(placement);
      actual.elements.forEach((value, index) => {
        expect(value).toBeCloseTo(expected.elements[index], 12);
      });
      const opposite = kicadModelPlacementMatrix({
        ...placement,
        rotate: [0, 0, -270],
      });
      const oppositeError = Math.max(
        ...opposite.elements.map((value, index) =>
          Math.abs(value - expected.elements[index]),
        ),
      );
      expect(oppositeError).toBeCloseTo(2, 12);
    },
  );

  it("matches the full affine matrix proven by KiCad's native geometry export", () => {
    // This oracle was measured using the real installed Bosch LGA footprint and
    // STEP model. KiCad and Stockroom produced the same placed world bounds to
    // 5.7e-8 mm after combined offset, three-axis rotation, and anisotropic scale.
    const placement: KiCadModelPlacement = {
      offset: [8.89, -24.13, 1.25],
      rotate: [35, -20, 270],
      scale: [1.2, 0.8, 1.5],
    };
    const expected = new THREE.Matrix4().set(
      0,
      -0.8603646545265691,
      0.6553216354311935,
      8.89,
      -0.41042417199080244,
      1.1546266969800858,
      0.431188435756605,
      1.25,
      -1.12763114494309,
      -0.42024974938985316,
      -0.15693975597520898,
      24.13,
      0,
      0,
      0,
      1,
    );
    const actual = kicadModelPlacementMatrix(placement);
    actual.elements.forEach((value, index) => {
      expect(value).toBeCloseTo(expected.elements[index], 12);
    });
  });
});
