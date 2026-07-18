/**
 * A shared offscreen three.js renderer that turns a part's GLB into a single FLAT, FROZEN
 * PNG (a data URL) for the library-list icon. One WebGL context is reused across every
 * thumbnail - browsers cap live contexts (~16), so a per-row canvas is impossible - and
 * renders are serialized through a queue so the shared renderer is never driven
 * concurrently. The heavy three import keeps this in its own lazy chunk (callers import() it,
 * only when a 3D thumbnail is actually needed). The framing mirrors the detail hero's 3/4
 * view so the icon reads as a smaller version of the same render.
 */
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

// Render square at 2x the display box so the icon stays crisp on HiDPI, then display small.
const SIZE = 96;

// One shared NEUTRAL material every model is rendered in. The GLBs carry wildly different
// material colours (a tan connector, a near-black resistor, a gray inductor), which at icon
// size read as an indistinct set of shades; a single neutral surface makes each part read by
// its SHAPE, lit into form by the studio lights, not by an arbitrary colour. Shared + never
// disposed (disposeScene skips it), so it is created once for every thumbnail.
const NEUTRAL_MATERIAL = new THREE.MeshStandardMaterial({
  color: 0xa8a8ac,
  roughness: 0.62,
  metalness: 0.08,
});

// Replace every mesh's material with the shared neutral one, disposing the GLB's own
// materials (they are dereferenced and would otherwise leak).
function neutralize(root: THREE.Object3D): void {
  root.traverse((obj) => {
    const mesh = obj as THREE.Mesh;
    if (!mesh.isMesh) return;
    const old = mesh.material as THREE.Material | THREE.Material[] | undefined;
    if (Array.isArray(old)) old.forEach((m) => m.dispose());
    else old?.dispose();
    mesh.material = NEUTRAL_MATERIAL;
  });
}

let renderer: THREE.WebGLRenderer | null = null;
let rendererFailed = false;
let queue: Promise<unknown> = Promise.resolve();

function getRenderer(): THREE.WebGLRenderer | null {
  if (renderer) return renderer;
  if (rendererFailed) return null;
  try {
    const r = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      preserveDrawingBuffer: true, // required for toDataURL to read the rendered frame
    });
    r.setPixelRatio(1);
    r.setSize(SIZE, SIZE);
    renderer = r;
    return r;
  } catch {
    rendererFailed = true; // no WebGL (or three failed): every caller falls back to a glyph
    return null;
  }
}

function disposeScene(scene: THREE.Scene): void {
  scene.traverse((obj) => {
    const mesh = obj as THREE.Mesh;
    if (mesh.geometry) mesh.geometry.dispose();
    // materials were replaced with the shared NEUTRAL_MATERIAL, which is reused across every
    // thumbnail and must NOT be disposed here.
  });
}

function renderOne(glb: ArrayBuffer): Promise<string | null> {
  return new Promise((resolve) => {
    const r = getRenderer();
    if (!r) {
      resolve(null);
      return;
    }
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 1000);
    // The same even, shadow-free studio lighting as the detail hero.
    scene.add(new THREE.AmbientLight(0xffffff, 0.95));
    const key = new THREE.DirectionalLight(0xffffff, 1.1);
    key.position.set(1, 1.4, 1);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.5);
    fill.position.set(-1, -0.6, -1);
    scene.add(fill);

    let settled = false;
    const done = (url: string | null) => {
      if (settled) return;
      settled = true;
      disposeScene(scene);
      resolve(url);
    };
    try {
      new GLTFLoader().parse(
        glb,
        "",
        (gltf) => {
          try {
            scene.add(gltf.scene);
            neutralize(gltf.scene);
            // KiCad/STEP models are authored Z-up; three.js is Y-up, so an unrotated model
            // renders lying on its side, and a -90° turn lands it upside down - +90° stands it
            // right-side up. Rotate before framing.
            gltf.scene.rotation.x = Math.PI / 2;
            gltf.scene.updateMatrixWorld(true);
            // Center on the origin, back the camera off the bounding SPHERE (so no clip at
            // the 3/4 angle), place it along the hero's view direction.
            const box = new THREE.Box3().setFromObject(gltf.scene);
            const size = box.getSize(new THREE.Vector3());
            const center = box.getCenter(new THREE.Vector3());
            gltf.scene.position.sub(center);
            const radius = Math.max(size.length() * 0.5, 0.001);
            const vfov = (camera.fov * Math.PI) / 180;
            const dist = (radius / Math.sin(vfov / 2)) * 1.05;
            camera.position.copy(
              new THREE.Vector3(0.55, 0.42, 1).normalize().multiplyScalar(dist),
            );
            camera.near = radius / 100;
            camera.far = radius * 100;
            camera.updateProjectionMatrix();
            camera.lookAt(0, 0, 0);
            r.render(scene, camera);
            done(r.domElement.toDataURL("image/png"));
          } catch {
            done(null);
          }
        },
        () => done(null), // GLTFLoader rejected the GLB: fall back to the glyph
      );
    } catch {
      done(null);
    }
  });
}

/**
 * Render a part's GLB to a frozen PNG data URL (or null when there is no WebGL / the GLB is
 * unrenderable, so the caller keeps its glyph). Serialized through a shared queue.
 */
export function renderGlbThumbnail(glb: ArrayBuffer): Promise<string | null> {
  const run = queue.then(() => renderOne(glb));
  queue = run.catch(() => undefined); // keep the queue alive past a failed render
  return run;
}
