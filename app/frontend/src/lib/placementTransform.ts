import * as THREE from "three";

export interface KiCadModelPlacement {
  offset: [number, number, number];
  rotate: [number, number, number];
  scale: [number, number, number];
}

const STEP_TO_GLTF_BASIS = new THREE.Matrix4().makeRotationX(-Math.PI / 2);
const GLTF_TO_STEP_BASIS = STEP_TO_GLTF_BASIS.clone().invert();

/**
 * Convert KiCad's complete model-placement matrix into the renderer's Y-up frame.
 *
 * KiCad applies `T · Rz(-z) · Ry(-y) · Rx(-x) · S` in its Z-up model frame
 * (mirroring the OpenGL and ray-tracing implementations in KiCad itself). STEP
 * conversion wraps the authored model in B = rotateX(-90°), so placement outside
 * that wrapper must be the conjugate `B · K · B⁻¹`.
 *
 * Conjugating the whole matrix matters: swapping three Euler fields happens to
 * work for one non-zero axis but changes rotation order when two axes are non-zero,
 * and leaving scale unswapped assigns KiCad Y scale to render Y instead of render Z.
 */
export function kicadModelPlacementMatrix(
  placement: KiCadModelPlacement,
): THREE.Matrix4 {
  const [ox, oy, oz] = placement.offset;
  const [rx, ry, rz] = placement.rotate.map((degrees) => (degrees * Math.PI) / 180);
  const [sx, sy, sz] = placement.scale.map((value) => value || 1);

  const kicad = new THREE.Matrix4()
    .makeTranslation(ox, oy, oz)
    .multiply(new THREE.Matrix4().makeRotationZ(-rz))
    .multiply(new THREE.Matrix4().makeRotationY(-ry))
    .multiply(new THREE.Matrix4().makeRotationX(-rx))
    .multiply(new THREE.Matrix4().makeScale(sx, sy, sz));

  return STEP_TO_GLTF_BASIS.clone().multiply(kicad).multiply(GLTF_TO_STEP_BASIS);
}
