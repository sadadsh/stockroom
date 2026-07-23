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
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
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
  // Filmic tone mapping so the bright metal highlights + deep shadow sides don't clip: this is
  // what turns a flat gray blob into a form with readable light-to-dark gradients.
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, width / height, 0.01, 1000);

  // IMAGE-BASED LIGHTING: a neutral studio room supplies realistic reflections + soft occlusion,
  // so the monochrome surface actually reads as a lit 3D object (the single biggest legibility win
  // over flat directional light on a matte gray). PMREM prefilters it for the standard material.
  const pmrem = new THREE.PMREMGenerator(renderer);
  const envRT = pmrem.fromScene(new RoomEnvironment(), 0.03);
  scene.environment = envRT.texture;

  // A strong shadow-casting key defines the primary highlight + drops a contact shadow that grounds
  // the part; a soft fill keeps the far side from going black. The environment handles the rest.
  const key = new THREE.DirectionalLight(0xffffff, 2.1);
  key.position.set(1.4, 2.2, 1.3);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  key.shadow.bias = -0.0005;
  const kd = key.shadow.camera as THREE.OrthographicCamera;
  kd.left = kd.bottom = -2; kd.right = kd.top = 2; kd.near = 0.1; kd.far = 20;
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xffffff, 0.4);
  fill.position.set(-1.2, -0.2, -0.9);
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
      // A brushed-metal surface: reflective enough that the studio environment paints bright
      // highlights + dark shadow zones across it (high internal contrast = readable form on ANY
      // tile background), yet still monochrome so the part reads by shape, not by GLB colour.
      // A refined matte surface, lit by the studio environment. Rough + low metalness so it reads
      // as a real matte component, not a shiny plastic toy.
      const neutral = new THREE.MeshStandardMaterial({
        color: 0xc2c4ca,
        roughness: 0.52,
        metalness: 0.22,
        envMapIntensity: 1.1,
      });
      // SUBTLE feature lines so the part is legible even at a flat angle (a bare matte grey blob is
      // impossible to read). NOT the old cartoon: a thin, soft, dark-grey line at low opacity on
      // only the sharper creases (>~34 deg), so the silhouette + major features read without the
      // comic "outline every edge in black" look.
      const edgeMat = new THREE.LineBasicMaterial({
        color: 0x26272c,
        transparent: true,
        opacity: 0.42,
      });
      gltf.scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        if (!mesh.isMesh) return;
        const old = mesh.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(old)) old.forEach((m) => m.dispose());
        else old?.dispose();
        mesh.material = neutral;
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        if (mesh.geometry) {
          mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry, 34), edgeMat));
        }
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

      // A soft CONTACT SHADOW under the part: a shadow-only plane at the model's base catches the
      // key light, grounding the object and adding depth (a floating monochrome shape reads as flat;
      // a grounded one reads as solid). Sized + placed relative to the model so it works at any scale.
      const bottomY = -size.y / 2;
      const ground = new THREE.Mesh(
        new THREE.PlaneGeometry(radius * 8, radius * 8),
        new THREE.ShadowMaterial({ opacity: 0.28 }),
      );
      ground.rotation.x = -Math.PI / 2;
      ground.position.y = bottomY - radius * 0.02;
      ground.receiveShadow = true;
      scene.add(ground);
      // aim the key + scale its shadow frustum to the model so the shadow is crisp, not clipped
      key.position.set(radius * 1.6, radius * 2.6, radius * 1.5);
      kd.left = kd.bottom = -radius * 2.2;
      kd.right = kd.top = radius * 2.2;
      kd.near = radius * 0.05;
      kd.far = radius * 8;
      kd.updateProjectionMatrix();
      fill.position.set(-radius * 1.4, -radius * 0.3, -radius);

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
    envRT.texture.dispose();
    pmrem.dispose();
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
