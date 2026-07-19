/**
 * Orient a loaded 3D model so it sits UPRIGHT on its largest face, robust to the mixed-source
 * GLBs' inconsistent authored axes (a fixed rotation stood some parts on their face or upside
 * down). Two steps:
 *   1. stand the SHORTEST bounding-box axis vertical (Y), so a flat part lies flat;
 *   2. choose the direction so the BODY points up. By the KiCad convention the model origin is
 *      the board / mounting plane and the component body extends AWAY from it, so the side of
 *      the box that reaches farther from the origin is "up".
 * Call before framing; the caller updates the world matrix.
 */
import * as THREE from "three";

export function orientUpright(root: THREE.Object3D): void {
  const box = new THREE.Box3().setFromObject(root);
  const s = box.getSize(new THREE.Vector3());
  if (s.z <= s.x && s.z <= s.y) {
    // Z shortest: turn it to +Y, from whichever Z side the body reaches farther.
    root.rotation.x = Math.abs(box.max.z) >= Math.abs(box.min.z) ? -Math.PI / 2 : Math.PI / 2;
  } else if (s.x <= s.y && s.x <= s.z) {
    // X shortest: turn it to +Y.
    root.rotation.z = Math.abs(box.max.x) >= Math.abs(box.min.x) ? Math.PI / 2 : -Math.PI / 2;
  } else if (Math.abs(box.max.y) < Math.abs(box.min.y)) {
    // Y is already the shortest (part lies flat) but the body sits on -Y: flip it upright.
    root.rotation.x = Math.PI;
  }
}
