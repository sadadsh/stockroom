/**
 * The three.js half of the 3D model viewer (M6d), isolated from the React component so
 * the component's states (loading / error / mounted) stay testable in jsdom while the
 * actual WebGL rendering is verified in the Windows pixel gate. mountModelScene sets up
 * a renderer, frames the GLB to fit, adds orbit controls (drag to rotate, wheel to zoom,
 * right-drag to pan) and an animation loop, and returns a dispose function that tears the
 * whole thing down (GL context, listeners, DOM node) so re-opening never leaks a context.
 *
 * This module top-level-imports three, so callers import() it lazily — three lands in its
 * own chunk that only loads when a 3D preview is actually opened.
 */
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { orientUpright } from "./modelOrient";

export function mountModelScene(
  container: HTMLElement,
  glb: ArrayBuffer,
  onError?: () => void,
): () => void {
  const width = container.clientWidth || 640;
  const height = container.clientHeight || 460;

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(width, height);
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, width / height, 0.01, 1000);

  // Even, shadow-free studio lighting so a bare mechanical model reads clearly from
  // any angle without a floor or a hard key light.
  scene.add(new THREE.AmbientLight(0xffffff, 0.9));
  const key = new THREE.DirectionalLight(0xffffff, 1.1);
  key.position.set(1, 1.4, 1);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xffffff, 0.5);
  fill.position.set(-1, -0.6, -1);
  scene.add(fill);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  // Gently auto-spin like SnapEDA's viewer; the per-frame controls.update() in the
  // render loop advances it. Dragging still works and simply overrides the spin.
  controls.autoRotate = true;
  controls.autoRotateSpeed = 1.6;

  const loader = new GLTFLoader();
  const root = new THREE.Group();
  scene.add(root);

  loader.parse(
    glb,
    "",
    (gltf) => {
      root.add(gltf.scene);
      // Render every part in ONE neutral surface (the app's 3D renders are monochrome - no
      // per-material colour), so a model reads by its lit form, not by the GLB's arbitrary
      // colour. Disposed with the scene below (all meshes share this one material).
      const neutral = new THREE.MeshStandardMaterial({
        color: 0xa8a8ac,
        roughness: 0.62,
        metalness: 0.08,
      });
      gltf.scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        if (!mesh.isMesh) return;
        const old = mesh.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(old)) old.forEach((m) => m.dispose());
        else old?.dispose();
        mesh.material = neutral;
      });
      // Sit the part upright on its largest face (see orientUpright), so a flat part lies flat
      // and the body points up, and the auto-spin turns it about that vertical axis.
      orientUpright(gltf.scene);
      gltf.scene.updateMatrixWorld(true);
      // frame the model: center it on the origin and back the camera off to fit. Use the
      // bounding-SPHERE radius (half the box diagonal) so the model never clips at any
      // auto-rotate angle, then place the camera along a fixed 3/4 view direction at just
      // the fit distance (a small pad, not the old non-normalized offset that pushed the
      // camera ~1.6x too far and left the model a tiny object in a big empty chamber).
      const box = new THREE.Box3().setFromObject(gltf.scene);
      const size = box.getSize(new THREE.Vector3());
      const center = box.getCenter(new THREE.Vector3());
      gltf.scene.position.sub(center);
      const radius = Math.max(size.length() * 0.5, 0.001);
      // The frame is usually wider than tall; fit the sphere to the SHORTER (vertical)
      // extent so the model reads large, and account for aspect so a portrait frame still
      // fits horizontally.
      const vfov = (camera.fov * Math.PI) / 180;
      const fitH = radius / Math.sin(vfov / 2);
      const fitW = radius / Math.sin(vfov / 2) / Math.min(1, camera.aspect);
      const dist = Math.max(fitH, fitW) * 0.98;
      const dir = new THREE.Vector3(0.55, 0.42, 1).normalize();
      camera.position.copy(dir.multiplyScalar(dist));
      camera.near = radius / 100;
      camera.far = radius * 100;
      camera.updateProjectionMatrix();
      controls.target.set(0, 0, 0);
      controls.update();
    },
    () => {
      // GLTFLoader rejected the GLB (a format three does not accept, or a truncated
      // cache file). This fires asynchronously, after mountModelScene has returned, so
      // it is the only channel that can tell the component to show an honest message
      // instead of leaving a lit, empty canvas.
      onError?.();
    },
  );

  let raf = 0;
  const tick = () => {
    controls.update();
    renderer.render(scene, camera);
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);

  const onResize = () => {
    const w = container.clientWidth || width;
    const h = container.clientHeight || height;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  };
  const resizeObserver =
    typeof ResizeObserver !== "undefined" ? new ResizeObserver(onResize) : null;
  resizeObserver?.observe(container);

  return () => {
    cancelAnimationFrame(raf);
    resizeObserver?.disconnect();
    controls.dispose();
    scene.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (mesh.geometry) mesh.geometry.dispose();
      const mat = mesh.material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
      else mat?.dispose();
    });
    renderer.dispose();
    // dispose() frees GPU caches but leaves the WebGL context alive until GC; browsers
    // cap live contexts (~16), so without this every 3D-preview open would leak one and
    // the viewer would eventually stop rendering. forceContextLoss releases it now.
    renderer.forceContextLoss?.();
    if (renderer.domElement.parentNode === container) {
      container.removeChild(renderer.domElement);
    }
  };
}
