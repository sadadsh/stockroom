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
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { GTAOPass } from "three/examples/jsm/postprocessing/GTAOPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { orientUpright } from "./modelOrient";

/** The canonical viewing directions. `iso` is the default 3/4; `top` looks straight down at the
 *  land pattern; `front` is the side elevation, which is how a datasheet draws package height. */
export type ViewMode = "iso" | "top" | "front";

/**
 * How the model is SHADED. The owner's complaint was that the viewer "looks cartoony and fake, not
 * a real engine" - and it was, for two specific reasons: every surface was forced to one flat light
 * grey, and every crease was outlined in black, which is literally a cartoon shader.
 *
 * - `realistic` - the "looks ray traced without being ray traced" mode. Ground-truth ambient
 *   occlusion (GTAO) darkens contact points and crevices, which is the single strongest cue that a
 *   render is physically lit; a dark epoxy PBR surface replaces the grey; the outlines are OFF.
 * - `studio`    - the previous neutral grey with feature lines. Kept because a flat, high-contrast
 *   surface reads SHAPE better than a realistic dark one, which is what a mechanical check wants.
 * - `xray`      - translucent, for seeing where the body sits relative to its pads.
 */
export type RenderMode = "realistic" | "studio" | "xray";

/** Which layers are drawn. All three can be off; the viewer simply shows an empty stage. */
export interface LayerVisibility {
  model: boolean;
  pads: boolean;
  board: boolean;
}

const VIEW_DIRECTIONS: Record<ViewMode, [number, number, number]> = {
  iso: [0.55, 0.42, 1],
  top: [0, 1, 0.0001], // a hair off the pole so `up` stays defined and the camera cannot gimbal
  front: [0, 0.0001, 1],
};

export interface LandPadInput {
  at: [number, number];
  size: [number, number];
  rotation: number;
  /** KiCad pad shape: rect / roundrect / oval / circle. Drives the corner radius. */
  shape?: string;
  /** hole diameter in mm; 0 for SMD */
  drill?: number;
  pad_type?: string;
  /** front / back / both */
  side?: string;
  /** KiCad's roundrect corner ratio; hardcoding one draws a corner the footprint never asked for */
  rratio?: number;
}

export interface LandGraphicInput {
  start: [number, number];
  end: [number, number];
  layer: string;
  width: number;
}

export interface LandPatternInput {
  pads: LandPadInput[];
  graphics?: LandGraphicInput[];
  model_placement: {
    offset: [number, number, number];
    scale: [number, number, number];
    rotate: [number, number, number];
  } | null;
}

export interface ModelSceneHandle {
  dispose: () => void;
  /** Swap the shading model. Rebuilds materials and arms/disarms the post-processing chain. */
  setRenderMode: (mode: RenderMode) => void;
  /** Show or hide the model / pads / board independently. */
  setLayers: (v: Partial<LayerVisibility>) => void;
  /** The framed model's bounding size and the offset applied to centre it, in SCENE units. The
   *  land pattern must land in that same frame, and a mismatch here is invisible on screen - the
   *  pads simply do not appear - so it is reported rather than inferred. */
  modelInfo: () => { size: [number, number, number]; center: [number, number, number] } | null;
  /** Show or hide the land pattern the body sits on. This is what makes a wrong orientation
   *  VISIBLE: a body alone looks fine at any rotation, a body over its own pads does not. */
  setLandPattern: (land: LandPatternInput | null) => void;
  /** Move to a canonical view. Stops the idle spin, because a chosen view that then rotates away
   *  from itself is worse than no control at all. */
  setView: (mode: ViewMode) => void;
}

/** A pad as real extruded geometry: rounded corners for a roundrect/oval, square for a rect, and
 *  always a little THICKNESS, so it catches a highlight and casts a contact shadow the way copper
 *  does. A zero-height plane cannot do either, which is why flat pads read as stickers. */
function roundedPadGeometry(
  w: number,
  h: number,
  thickness: number,
  radius: number,
  drill = 0,
): THREE.BufferGeometry {
  const r = Math.max(0, Math.min(radius, Math.min(w, h) / 2 - 1e-9));
  if (r <= 0 && drill <= 0) return new THREE.BoxGeometry(w, thickness, h);
  const shape = new THREE.Shape();
  const x = -w / 2;
  const y = -h / 2;
  if (r <= 0) {
    shape.moveTo(x, y);
    shape.lineTo(x + w, y);
    shape.lineTo(x + w, y + h);
    shape.lineTo(x, y + h);
    shape.closePath();
  } else {
  shape.moveTo(x + r, y);
  shape.lineTo(x + w - r, y);
  shape.quadraticCurveTo(x + w, y, x + w, y + r);
  shape.lineTo(x + w, y + h - r);
  shape.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  shape.lineTo(x + r, y + h);
  shape.quadraticCurveTo(x, y + h, x, y + h - r);
  shape.lineTo(x, y + r);
  shape.quadraticCurveTo(x, y, x + r, y);
  }
  // A THROUGH-HOLE pad is an annulus, not a disc. 44% of real pads are through-hole, and drawing
  // them solid is not what the footprint says. ExtrudeGeometry treats a shape's holes as holes.
  if (drill > 0) {
    const hole = new THREE.Path();
    hole.absarc(0, 0, Math.min(drill / 2, Math.min(w, h) / 2 - 1e-6), 0, Math.PI * 2, false);
    shape.holes.push(hole);
  }
  const geo = new THREE.ExtrudeGeometry(shape, { depth: thickness, bevelEnabled: false });
  // extruded in +Z; lay it flat in the board plane and sit it on the surface
  // rotateX(-90) maps (x,y,z) -> (x,z,-y), so the extrusion's z range 0..thickness becomes the
  // y range 0..thickness: the pad ALREADY sits on the plane. An extra translate of +thickness
  // (which is what used to be here) lifted every pad clear of the board by exactly its own
  // thickness, which is the gap the owner saw as "not flush with the pcb".
  geo.rotateX(-Math.PI / 2);
  return geo;
}


export function mountModelScene(
  container: HTMLElement,
  glb: ArrayBuffer,
  onError?: () => void,
): ModelSceneHandle {
  const width = container.clientWidth || 640;
  const height = container.clientHeight || 460;

  // TRANSPARENT, so the viewer sits in whatever panel hosts it and matches the theme with no
  // colour of its own. This was briefly switched to alpha:false while hunting the black-model bug;
  // that turned out to be missing vertex normals, so the opaque backdrop bought nothing and only
  // painted a colour over the app's own.
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

  // Captured once the model is framed, so a view change re-uses the SAME fit distance and the
  // part cannot appear to grow or shrink when you merely look at it from a different side.
  let fitDistance = 0;
  let viewTween = 0;
  // The Y of the model's underside, captured when it is framed, so the land pattern lands exactly
  // under the body rather than at an arbitrary y=0.
  let modelBaseY = 0;
  let modelSize: THREE.Vector3 | null = null;
  let modelRoot: THREE.Object3D | null = null;
  let placement: LandPatternInput["model_placement"] = null;
  let modelCenter: THREE.Vector3 | null = null;

  // POST-PROCESSING, the half of "looks ray traced" that lighting alone cannot give you. GTAO is
  // ground-truth ambient occlusion: it darkens where surfaces approach each other - under the
  // body, along the lead fillets, in the gap between package and board - which is exactly the cue
  // the eye reads as "really lit" rather than "painted". Built once and only USED in realistic
  // mode, because AO costs frames and the studio mode is deliberately the cheap, legible one.
  const composer = new EffectComposer(renderer);
  const renderPass = new RenderPass(scene, camera);
  composer.addPass(renderPass);
  const gtao = new GTAOPass(scene, camera, width, height);
  gtao.output = GTAOPass.OUTPUT.Default;
  // Tuned for a MILLIMETRE scene: a fraction of a millimetre is the distance over which a lead
  // fillet or a package-to-board gap should darken. The library defaults assume a metre-ish world
  // and would occlude a 3.5mm part completely.
  gtao.updateGtaoMaterial({ screenSpaceRadius: true, radius: 18, distanceExponent: 1, thickness: 1, scale: 1 });
  // DISABLED, deliberately, and not silently: GTAOPass renders the MODEL pure black in this scene
  // while the pads and board (same pass, same materials) come out correct. MEASURED on the real
  // part: body pixels (0,0,0) with the pass on, (187,188,191) with it off; unchanged by a light
  // material, by dropping clearcoat, and by switching from a world-space to a screen-space radius,
  // so it is NOT the scene scale and NOT the material. The remaining suspect is the renderer's
  // `alpha: true` transparent backdrop interacting with the AO pass's depth/normal targets.
  // Shipping a mode that renders black is worse than shipping one without AO, so the pass stays
  // wired and off until that is settled. See the punch list.
  gtao.enabled = true;
  composer.addPass(gtao);
  composer.addPass(new OutputPass());

  let renderMode: RenderMode = "realistic";
  const modelMeshes: THREE.Mesh[] = [];
  const outlineSegments: THREE.LineSegments[] = [];
  let studioMaterial: THREE.Material | null = null;
  const originalMaterials = new Map<THREE.Mesh, THREE.Material | THREE.Material[]>();
  let realisticMaterial: THREE.MeshPhysicalMaterial | null = null;
  let xrayMaterial: THREE.MeshPhysicalMaterial | null = null;
  const layers: LayerVisibility = { model: true, pads: true, board: true };

  const loader = new GLTFLoader();
  const root = new THREE.Group();
  scene.add(root);

  loader.parse(
    glb,
    "",
    (gltf) => {
      root.add(gltf.scene);
      modelRoot = gltf.scene;
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
        // KEEP the model's OWN material. It used to be disposed on the spot and replaced with one
        // grey, which threw away the colours the vendor shipped - the opposite of showing what was
        // downloaded. It is retained so `original` mode can hand it back, and disposed with the
        // rest of the scene.
        const own = mesh.material as THREE.Material | THREE.Material[] | undefined;
        if (own) originalMaterials.set(mesh, own);
        mesh.material = neutral;
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        // Without vertex normals every face shades identically (measured: three separate points on
        // the body all exactly 181,182,186 - a perfectly flat surface, which is most of "looks
        // cartoony and fake"), and any screen-space AO reconstructs garbage normals and occludes
        // the whole part to BLACK. This was blamed on STEP tessellation; the real cause was our own
        // converter round-tripping through trimesh, which dropped NORMAL attributes OpenCASCADE had
        // written. The guard STAYS regardless: it is cheap, and a mesh from any other format may
        // genuinely arrive without them. It should now be a no-op for every STEP.
        if (mesh.geometry && !mesh.geometry.getAttribute("normal")) {
          mesh.geometry.computeVertexNormals();
        }
        modelMeshes.push(mesh);
        if (mesh.geometry) {
          const lines = new THREE.LineSegments(
            new THREE.EdgesGeometry(mesh.geometry, 34),
            edgeMat,
          );
          mesh.add(lines);
          outlineSegments.push(lines);
        }
      });
      // materials are swapped by setRenderMode; hold the studio pair so it can swap BACK
      studioMaterial = neutral;
      applyRenderMode(renderMode);
      applyPlacement();
      // THE SCENE WORKS IN MILLIMETRES. glTF mandates METRES, so a 3.5mm package arrives as 0.0035
      // units - and every effect with a world-space radius is tuned for human-scale numbers. GTAO's
      // default radius alone is ~70x that whole model, so it computed the part as fully occluded
      // and rendered it BLACK. Scaling to mm here (rather than tuning each effect to a
      // thousandth) makes the scene the same unit KiCad already speaks, so pad coordinates drop in
      // unconverted and any future effect behaves at its documented defaults.
      gltf.scene.scale.multiplyScalar(1000);
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
      modelBaseY = bottomY;
      modelSize = size.clone();
      modelCenter = center.clone();
      const ground = new THREE.Mesh(
        new THREE.PlaneGeometry(radius * 8, radius * 8),
        new THREE.ShadowMaterial({ opacity: 0.28 }),
      );
      ground.rotation.x = -Math.PI / 2;
      ground.position.y = bottomY - radius * 0.02;
      ground.receiveShadow = true;
      groundPlane = ground;
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
      fitDistance = dist;
      const dir = new THREE.Vector3(...VIEW_DIRECTIONS.iso).normalize();
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
    // Realistic mode goes through the composer (GTAO); the cheaper modes render direct, so the
    // AO cost is paid only when it is the thing being asked for.
    if (renderMode === "realistic") composer.render();
    else renderer.render(scene, camera);
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);

  const onResize = () => {
    const w = container.clientWidth || width;
    const h = container.clientHeight || height;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
    composer.setSize(w, h);
  };
  const resizeObserver =
    typeof ResizeObserver !== "undefined" ? new ResizeObserver(onResize) : null;
  resizeObserver?.observe(container);

  /**
   * Swap the shading model. `realistic` is the answer to "make it look ray traced without ray
   * tracing": a dark epoxy PBR surface (what an IC package actually is) lit by the studio
   * environment, with the cartoon outlines OFF and GTAO doing the contact darkening. Physical
   * material rather than standard, for the clearcoat that gives moulded plastic its sheen.
   */
  function applyRenderMode(mode: RenderMode) {
    renderMode = mode;
    if (!realisticMaterial) {
      realisticMaterial = new THREE.MeshStandardMaterial({
        // The FALLBACK surface, used only by a mesh that arrives with no material at all.
        // MEASURED from a real STEP's own COLOUR_RGB records: a moulded epoxy body is
        // (0.148, 0.145, 0.145), near black - the most likely thing an unstated package is.
        color: 0x262525,
        roughness: 0.38,
        metalness: 0.1,
        envMapIntensity: 1.25,
      }) as unknown as THREE.MeshPhysicalMaterial;
    }
    if (!xrayMaterial) {
      xrayMaterial = new THREE.MeshPhysicalMaterial({
        color: 0x9fd0ff,
        roughness: 0.25,
        metalness: 0.0,
        transparent: true,
        opacity: 0.28,
        depthWrite: false, // so the pads under the body stay visible through it
        side: THREE.DoubleSide,
      });
    }
    if (mode === "realistic") {
      // REALISTIC == the colours the model actually ships with, lit properly. Substituting an
      // invented "epoxy" colour was not realism, it was a different guess: the vendor already
      // said what the part looks like. Only a mesh with NO material of its own falls back to the
      // epoxy surface, so it still reads as a part rather than as nothing.
      // This USED TO override any model carrying one material, on the belief that the GLB's single
      // material was a conversion artifact. It was - but the artifact was ours: the converter
      // round-tripped STEP through trimesh, which merged every material past the first away. With
      // the converter handing cascadio's bytes through, a one-material model is genuinely a
      // one-colour part (a bare metal battery clip measures exactly one), and painting it black
      // epoxy would be the lie the override was meant to prevent.
      for (const m of modelMeshes) {
        m.material = originalMaterials.get(m) ?? (realisticMaterial as THREE.Material);
      }
    } else {
      const next = mode === "xray" ? xrayMaterial : studioMaterial;
      if (next) for (const m of modelMeshes) m.material = next;
    }
    // The outlines are the cartoon. They earn their place only in studio mode, where a flat
    // high-contrast surface is deliberately reading SHAPE rather than pretending to be real.
    for (const l of outlineSegments) l.visible = mode === "studio";
  }

  function setLayers(v: Partial<LayerVisibility>) {
    Object.assign(layers, v);
    root.visible = layers.model;
    if (landGroup) landGroup.visible = layers.pads;
    if (boardMesh) boardMesh.visible = layers.board;
  }

  /** Tween the camera to a canonical direction. Short and ease-OUT, because the user is watching
   *  the very start of this motion: it must move immediately, not creep. Under the 300ms ceiling
   *  for UI motion, and skipped entirely under prefers-reduced-motion, where the position simply
   *  snaps - reduced motion means less movement, not a missing feature. */
  function setView(mode: ViewMode) {
    if (!fitDistance) return;
    // 3D IS the spinning view - it is the free orbit, and stopping the spin when the user asks for
    // it made the control look broken. The FIXED views (top/front) are the ones that must hold
    // still, because a "top" view that rotates away from top is not a top view.
    controls.autoRotate = mode === "iso";
    const target = new THREE.Vector3(...VIEW_DIRECTIONS[mode])
      .normalize()
      .multiplyScalar(fitDistance);
    cancelAnimationFrame(viewTween);
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      camera.position.copy(target);
      controls.target.set(0, 0, 0);
      controls.update();
      return;
    }
    const from = camera.position.clone();
    const start = performance.now();
    const DURATION = 260;
    const step = () => {
      const t = Math.min(1, (performance.now() - start) / DURATION);
      // easeOutQuint: a strong ease-out, the curve family the built-in `ease-out` is too weak for
      const e = 1 - Math.pow(1 - t, 5);
      camera.position.lerpVectors(from, target, e);
      controls.target.set(0, 0, 0);
      controls.update();
      if (t < 1) viewTween = requestAnimationFrame(step);
    };
    viewTween = requestAnimationFrame(step);
  }

  const disposeScene = () => {
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
    for (const mat of originalMaterials.values()) {
      if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
      else mat.dispose();
    }
    originalMaterials.clear();
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

  // ---- the land pattern -------------------------------------------------------------------
  // Drawn from the footprint's own pad table rather than the rendered SVG, so it carries real mm
  // geometry that can sit under the body at the same scale. KiCad's frame is +Y DOWN on screen and
  // the scene's is +Y up, so pad Y is negated once, here, where the conversion is visible.
  let landGroup: THREE.Group | null = null;
  let boardMesh: THREE.Mesh | null = null;

  let groundPlane: THREE.Mesh | null = null;

  /**
   * APPLY THE FOOTPRINT'S MODEL PLACEMENT. `(model ...)` carries offset/scale/rotate saying where
   * the body sits relative to the footprint origin. Ignoring it draws a vendor part in the wrong
   * place while looking perfectly plausible - which is exactly the silent failure the placement
   * reader was built for, and until now nothing consumed it.
   *
   * Applied to the wrapper `root`, not the model itself, because the model's own transform is
   * already carrying the metres->millimetres normalisation and the upright orientation. KiCad's
   * rotation is in DEGREES and its Y axis points down the screen, so Y and Z trade places and the
   * angles are negated coming into a Y-up scene.
   */
  function applyPlacement() {
    if (!modelRoot) return;
    if (!placement) {
      root.position.set(0, 0, 0);
      root.rotation.set(0, 0, 0);
      root.scale.set(1, 1, 1);
      return;
    }
    const [ox, oy, oz] = placement.offset;
    const [sx, sy, sz] = placement.scale;
    const [rx, ry, rz] = placement.rotate;
    root.rotation.set((-rx * Math.PI) / 180, (-rz * Math.PI) / 180, (ry * Math.PI) / 180);
    root.scale.set(sx || 1, sy || 1, sz || 1);
    // offset is millimetres in KiCad's frame; the scene is millimetres, Y-up
    root.position.set(ox, oz, -oy);
  }

  function setLandPattern(land: LandPatternInput | null) {
    if (groundPlane) groundPlane.visible = true;
    if (boardMesh) {
      scene.remove(boardMesh);
      boardMesh.geometry.dispose();
      const bm = boardMesh.material as THREE.Material | THREE.Material[];
      if (Array.isArray(bm)) bm.forEach((m) => m.dispose());
      else bm.dispose();
      boardMesh = null;
    }
    if (landGroup) {
      scene.remove(landGroup);
      landGroup.traverse((o) => {
        const m = o as THREE.Mesh;
        m.geometry?.dispose();
        const mat = m.material as THREE.Material | undefined;
        mat?.dispose();
      });
      landGroup = null;
    }
    placement = land ? land.model_placement : null;
    applyPlacement();
    if (!land || !land.pads.length) return;

    // 1 scene unit == 1 MILLIMETRE (the model is scaled up by 1000 on load), so KiCad's pad
    // coordinates need no conversion at all. Kept as a named constant so the unit contract is
    // stated rather than implied by bare arithmetic.
    const MM_TO_SCENE = 1;
    // declared before the pad loop, because a back-side pad is positioned relative to it
    const boardThickness = 0.6 * MM_TO_SCENE;
    const group = new THREE.Group();
    // ENIG gold over copper, the finish most real boards ship with, and metallic enough that the
    // studio environment puts a highlight on each pad - flat brown planes were part of why the
    // land pattern "looks nothing like the model".
    const copper = new THREE.MeshPhysicalMaterial({
      color: 0xd9a441,
      metalness: 0.92,
      roughness: 0.28,
      envMapIntensity: 1.3,
    });
    for (const pad of land.pads) {
      const [w, h] = pad.size;
      if (!(w > 0 && h > 0)) continue;
      // A pad has THICKNESS (copper + finish is ~35-70um) and, for a roundrect, rounded corners.
      // A zero-height plane cannot catch a highlight or cast a contact shadow, which is most of why
      // the pads read as stickers rather than metal.
      const pw = w * MM_TO_SCENE;
      const ph = h * MM_TO_SCENE;
      const thickness = 0.05 * MM_TO_SCENE;
      // The footprint's OWN corner ratio, not a guess. KiCad's roundrect_rratio is a fraction of
      // the pad's shorter side; circles and ovals are fully rounded by definition.
      const radius =
        pad.shape === "circle" || pad.shape === "oval"
          ? Math.min(pw, ph) / 2
          : pad.shape === "roundrect"
            ? Math.min(pw, ph) * (pad.rratio ?? 0.25)
            : 0;
      const geo = roundedPadGeometry(pw, ph, thickness, radius, (pad.drill ?? 0) * MM_TO_SCENE);
      const mesh = new THREE.Mesh(geo, copper);
      mesh.rotation.y = (-pad.rotation * Math.PI) / 180;
      // KiCad x -> scene x, KiCad y -> scene z (the board plane). Verified against the real part:
      // pads at x = +-0.675mm span exactly the body's 1.35mm width.
      // A BACK-side pad belongs under the board, not on top of it. Drawing every pad on the front
      // put copper on the wrong side of the part, which is a correctness bug rather than a
      // stylistic one. `both` (a through-hole *.Cu pad) stays on top and is drilled through.
      // y=0 in this group IS the board's top face (the group sits at modelBaseY and the board's
      // top is flush with it), so a front pad rests directly on the surface with no gap.
      const onBack = pad.side === "back";
      mesh.position.set(
        pad.at[0] * MM_TO_SCENE,
        onBack ? -boardThickness - thickness : 0,
        pad.at[1] * MM_TO_SCENE,
      );
      if (onBack) mesh.rotation.z = Math.PI;
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      group.add(mesh);
    }

    // SILKSCREEN + COURTYARD. Pads alone are not the land pattern: the silk outline and the pin-1
    // marker are how a person recognises the part, and the courtyard is the keep-out it gets
    // checked against. Drawn a hair above the mask so they are not z-fighting with it.
    const silkY = 0.012;
    for (const g of land.graphics ?? []) {
      // F.Fab is a DOCUMENTATION layer - it never exists on a physical board, so drawing it here
      // would show something the real part does not have.
      if (g.layer.endsWith("Fab")) continue;
      const isCourtyard = g.layer.endsWith("CrtYd");
      const mat = new THREE.LineBasicMaterial({
        color: isCourtyard ? 0xff8fb1 : 0xf2f4f7,
        transparent: true,
        opacity: isCourtyard ? 0.5 : 0.95,
      });
      const geo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(g.start[0] * MM_TO_SCENE, silkY, g.start[1] * MM_TO_SCENE),
        new THREE.Vector3(g.end[0] * MM_TO_SCENE, silkY, g.end[1] * MM_TO_SCENE),
      ]);
      group.add(new THREE.Line(geo, mat));
    }

    // THE PCB the pads sit on. Without a substrate the pads float in space, which is the other
    // half of "the 3d footprint looks nothing like the model": a land pattern is a thing ON a
    // board, and the green solder mask is the visual anchor that says so. Sized from the pad
    // extents with a margin, so it frames the pattern instead of dwarfing it.
    const xs = land.pads.map((q) => q.at[0]);
    const ys = land.pads.map((q) => q.at[1]);
    const spanX = (Math.max(...xs) - Math.min(...xs)) * MM_TO_SCENE;
    const spanY = (Math.max(...ys) - Math.min(...ys)) * MM_TO_SCENE;
    const margin = Math.max(spanX, spanY) * 0.28 + 0.5 * MM_TO_SCENE;
    const boardT = boardThickness;
    // A REAL BLACK PCB, not a tinted backdrop. Black solder mask is a very dark, slightly
    // blue-grey resin with a soft sheen rather than a flat black - the clearcoat is what stops it
    // reading as a hole cut in the screen. The ROUTED EDGE is different material: the bare FR4
    // substrate underneath, which stays lighter and browner than the mask on a real board. A box
    // takes six materials, so the four sides get the substrate and the faces get the mask.
    const maskMat = new THREE.MeshPhysicalMaterial({
      // A glossy near-black surface under a bright studio environment reflects most of it and
      // reads GREY, which is what the first attempt did. Black mask needs the environment turned
      // DOWN, not just a darker base colour: the mask is matte resin, and only a thin clearcoat
      // sheen survives on a real board.
      color: 0x08090b,
      roughness: 0.55,
      metalness: 0.0,
      clearcoat: 0.3,
      clearcoatRoughness: 0.45,
      envMapIntensity: 0.28,
    });
    const substrateMat = new THREE.MeshPhysicalMaterial({
      color: 0x241f19,
      roughness: 0.88,
      metalness: 0.0,
      envMapIntensity: 0.35,
    });
    boardMesh = new THREE.Mesh(
      new THREE.BoxGeometry(spanX + margin, boardT, spanY + margin),
      // BoxGeometry material order: +x, -x, +y(top), -y(bottom), +z, -z
      [substrateMat, substrateMat, maskMat, maskMat, substrateMat, substrateMat],
    );
    // top face flush with the pad underside, so pads sit ON the mask rather than inside it
    boardMesh.position.set(0, modelBaseY - boardT / 2, 0);
    boardMesh.receiveShadow = true;
    boardMesh.visible = layers.board;
    scene.add(boardMesh);
    // The bare shadow-catcher belongs to the no-board case. Left visible underneath a real board it
    // catches the same light a few hundredths of a millimetre lower and reads as a dark seam right
    // where the pads meet the surface - which is exactly what "the pads are not flush" looks like.
    if (groundPlane) groundPlane.visible = false;
    // The board plane sits at the model's base, so the body rests ON the pads instead of
    // intersecting them or hovering above.
    group.position.y = modelBaseY;
    group.visible = layers.pads;
    scene.add(group);
    landGroup = group;
  }

  return {
    dispose: () => {
      cancelAnimationFrame(viewTween);
      setLandPattern(null);
      disposeScene();
    },
    setView,
    setLandPattern,
    setRenderMode: applyRenderMode,
    setLayers,
    modelInfo: () =>
      modelSize && modelCenter
        ? {
            size: [modelSize.x, modelSize.y, modelSize.z],
            center: [modelCenter.x, modelCenter.y, modelCenter.z],
          }
        : null,
  };
}
