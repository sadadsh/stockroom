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
import { ViewHelper } from "three/examples/jsm/helpers/ViewHelper.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { GTAOPass } from "three/examples/jsm/postprocessing/GTAOPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import {
  DEFAULT_LAYERS,
  PAD_THICKNESS_MM,
  boardExtent,
  boardPlaneHalfExtents,
  boardStack,
  silkQuad,
  SILK_MAX_FRACTION,
} from "./boardPlane";
import { orientUpright } from "./modelOrient";
import {
  type Box,
  fitDistanceForBox,
  fitOrthoHalfHeight,
  halfExtents,
  screenUpFor,
  visibleBounds,
} from "./cameraFit";

/**
 * Ambient-occlusion settings for a part whose bounding-sphere radius is `modelRadius` SCENE units
 * (1 unit == 1mm). This is the contact darkening that makes a part read as sitting ON the board,
 * and it is the ONLY mechanism that can: a surface-mount body is far too thin for a cast shadow to
 * ground it (measured on the owner's USON - 0.55mm tall, key light at 49.8 degrees, so the shadow is
 * 0.46mm long and falls entirely underneath the part where no camera can see it).
 *
 * WHY IT PRODUCED NOTHING FOR THREE SESSIONS, since a plausible wrong answer here has already
 * survived several: the pass was set to `screenSpaceRadius: true, radius: 18`, and in that mode the
 * shader multiplies the radius by a scale derived from the view position 100px off centre
 * (`GTAOShader`, SCREEN_SPACE_RADIUS branch). At the distance this viewer frames a part from, 100px
 * is about 0.4mm of world, so radius 18 became a ~7mm sampling sphere around a 3.5mm part. Every
 * sample escaped into empty space, found no occluder, and returned "not occluded" everywhere.
 * MEASURED on the pass's own AO buffer: `stdev 0.00, 2 distinct levels` before, `stdev 3.20, 114
 * levels` after - and the render then changed across 7,326 pixels, all of them at the pad-to-body
 * contact where geometry actually converges.
 *
 * DERIVED, not a constant, and that is the point: the old value was tuned in millimetres for one
 * package, and this app shows everything from an 0402 to a 50mm connector. A fifth of the part's own
 * radius puts the sampling sphere at the scale of ITS OWN features at any size; the thickness is
 * half of that, so a sample is treated as an occluder only while it is genuinely close to the
 * surface rather than something across the board.
 */
export function aoSettings(modelRadius: number) {
  const radius = Math.max(modelRadius * 0.2, 1e-4);
  return { screenSpaceRadius: false, radius, distanceExponent: 1, thickness: radius * 0.5, scale: 1 };
}

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
  // Straight down, with no epsilon. The hair off the pole used to be here so `up` stayed defined;
  // it did not solve the problem, it hid it - the in-plane rotation then came out of the epsilon's
  // sign rather than being chosen, and came out 90 degrees away from the frustum the fit had sized.
  // `screenUpFor` now names the up vector for this direction, so the pole is a handled case.
  top: [0, 1, 0],
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
  /** Turn the idle spin on or off; returns the state actually in force (always false under
   *  prefers-reduced-motion, whatever was asked for). */
  setSpin: (wanted: boolean) => boolean;
}

/** The OS-level reduced-motion preference. Read at the moment it matters rather than cached, so a
 *  person who changes it does not have to reopen the viewer. */
function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true
  );
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
  // A TECHNICAL top view needs an ORTHOGRAPHIC camera. Under perspective, "top" still shows the
  // sides of the package - the further a face sits from the optical axis the more of its side is
  // visible - so a pad and the body above it do not line up, and lining them up is the one thing a
  // top view is for. Orthographic has no vanishing point, so the footprint reads as its true
  // outline. The frustum is sized in refitCamera; these bounds are placeholders.
  const orthoCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 1000);
  // Which camera is rendering. Swapped by setView, and every consumer (the render pass, the resize
  // handler, the controls, the fit) must read THIS rather than capturing one at construction.
  let activeCamera: THREE.PerspectiveCamera | THREE.OrthographicCamera = camera;

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
  // A RIM light, behind and above, aimed back at the camera side. This is the single biggest realism
  // lever for a DARK body and the reason the owner's USON read as "a flat dark box": a near-black
  // moulded package lit only from the front has no edge - its silhouette dissolves into a dark
  // background, so there is no form to see, however good the material is. A rim puts a bright sliver
  // along the top and far edges, which is what separates object from background in every real product
  // photograph. Deliberately cool and modest: warm or strong reads as a second key and flattens the
  // key's own modelling.
  const rim = new THREE.DirectionalLight(0xdce6f5, 1.5);
  rim.position.set(-0.9, 1.6, -1.5);
  scene.add(rim);

  /**
   * OrbitControls derives its whole orbit FRAME from `object.up` **in its constructor**
   * (`_quat = setFromUnitVectors(object.up, [0,1,0])`, r169 line 132) and never rebuilds it. It
   * then re-derives the camera's position from spherical coordinates in that frame on every
   * `update()`, which the render loop calls every frame.
   *
   * So the moment the bound camera changes, or the bound camera's `up` changes, the controls are
   * driving the camera in one frame while the renderer draws it in another - the two literally
   * fight each other, every frame, and a static screenshot cannot show it because the end state
   * of a settled tween still looks correct. Rebinding is the only fix that uses public API: the
   * constructor is the one place that frame is ever computed.
   */
  // DECLARED BEFORE `makeControls` IS CALLED. `let` bindings are hoisted but UNINITIALISED, so a
  // function that closes over one and is invoked before the declaration line runs throws
  // "Cannot access 'spinWanted' before initialization". These sat below `let controls =
  // makeControls(camera)` and did exactly that: mountModelScene threw, Glb3DView caught it, and the
  // whole viewer degraded to "This device could not render the 3D preview." Nothing in the suite can
  // see it - jsdom has no WebGL, so threeScene is mocked in every test.
  //
  // Whether the idle spin is WANTED, separate from `controls.autoRotate`, which the fixed views also
  // turn off: a "top" view that rotates away from top is not a top view, so the two reasons to stop
  // spinning must not overwrite each other.
  let spinWanted = true;
  // Has the PERSON said anything about spinning? `prefers-reduced-motion` is an OS-level DEFAULT,
  // and treating it as a veto meant the owner asking for auto-rotation got none, silently, with no
  // way to get it - the switch was on and the scene still would not turn. So the media query decides
  // the STARTING state, and the moment someone touches the control their choice wins. That is also
  // what the query is for: it expresses "do not surprise me with motion", not "never move".
  let spinChosen = false;
  // The view in force, so the spin switch knows whether spinning is even legal (only free iso spins).
  let viewMode: ViewMode = "iso";
  // The axis gizmo. Constructed lazily in `mountGizmo` once the DOM parent exists. It is REBOUND on
  // every camera swap for the same reason GTAOPass had to be: a helper that captures its camera at
  // construction keeps pointing at the camera it was born with, and the orthographic top view would
  // then spin a gizmo describing a camera nobody is looking through. That bug has been paid for
  // twice in this file already.
  let viewHelper: ViewHelper | null = null;
  /** The camera the live gizmo was CONSTRUCTED with, since ViewHelper does not expose it. */
  let gizmoCamera: THREE.Camera | null = null;

  let controls = makeControls(camera);
  function makeControls(cam: THREE.PerspectiveCamera | THREE.OrthographicCamera) {
    const next = new OrbitControls(cam, renderer.domElement);
    next.enableDamping = true;
    next.dampingFactor = 0.08;
    // Gently auto-spin like SnapEDA's viewer; the per-frame controls.update() in the
    // render loop advances it. Dragging still works and simply overrides the spin.
    // Gated on BOTH the user's own preference and the OS one. The 300ms view tween below already
    // honoured prefers-reduced-motion while this PERPETUAL rotation ignored it - exactly the wrong way
    // round, since a continuous spin is what that media query exists to stop (vestibular safety). The
    // owner separately asked for "an option to stop rotation", and one switch serves both.
    next.autoRotate = spinWanted && (spinChosen || !prefersReducedMotion());
    next.autoRotateSpeed = 1.6;
    return next;
  }
  /** The `up` the live controls were BUILT with, so a change to it can be detected. */
  const boundUp = new THREE.Vector3(0, 1, 0);

  /**
   * Re-bind the controls when the camera they must drive, or that camera's up, has changed.
   * Cheap and rare - at most once per view change - and it preserves the orbit target and the
   * spin state, so the user sees continuity rather than a reset.
   */
  function rebindControls(cam: THREE.PerspectiveCamera | THREE.OrthographicCamera) {
    if (controls.object === cam && boundUp.equals(cam.up)) return;
    const target = controls.target.clone();
    const spinning = controls.autoRotate;
    controls.dispose();
    controls = makeControls(cam);
    controls.target.copy(target);
    controls.autoRotate = spinning;
    boundUp.copy(cam.up);
    controls.update();
  }

  // Captured once the model is framed, so a view change re-uses the SAME fit distance and the
  // part cannot appear to grow or shrink when you merely look at it from a different side.
  let fitDistance = 0;
  // The point the camera orbits: the centre of whatever is VISIBLE, not a fixed origin. Held here
  // so a canonical view change re-uses the same target the fit chose.
  const fitTarget = new THREE.Vector3();
  let viewTween = 0;
  // The Y of the model's underside, captured when it is framed, so the land pattern lands exactly
  // under the body rather than at an arbitrary y=0.
  let modelBaseY = 0;
  let modelSize: THREE.Vector3 | null = null;
  // The land pattern most recently handed in, kept so it can be REBUILT once the model's bounds are
  // known. `Glb3DView` calls setLandPattern synchronously right after mountModelScene returns, but
  // `loader.parse` is callback-based - so at that moment `modelSize` is still null and the board
  // thickness (now derived from the component's height) would silently take its unknown-height
  // fallback on every single part. The fix would have looked correct in the diff and done nothing.
  let lastLand: LandPatternInput | null = null;
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
  // Placeholder only: the real radius is DERIVED FROM THE MODEL once it loads (see `aoRadius`
  // below), because a fixed millimetre value is right for one package and wrong for every other
  // size of part this app has to show.
  gtao.updateGtaoMaterial(aoSettings(1));
  // ON. A long-standing comment here claimed this pass was what rendered the model pure black, and
  // that claim is now DISPROVEN by measurement rather than argued away: with the pass forced off and
  // nothing else changed, the same package still measured rgb(4,4,4) on its top face and rgb(2,2,2)
  // on its front - identical to the pass being on. The black came from the GLB's own materials
  // taking glTF's `metallicFactor: 1.0` default, which the converter now states explicitly. The
  // comment is deleted rather than softened because a plausible-sounding cause written down as fact
  // is exactly what kept the real one hidden for two sessions.
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
  // ONE definition, shared with the toolbar chips (see DEFAULT_LAYERS in boardPlane, which is the
  // three-free module Glb3DView can import without pulling this one - and three - into the main
  // bundle). It used to be a literal here plus a matching literal in the control, held together by a
  // comment; a chip that reports a state the scene is not in is a control that lies, so the two
  // literals became one value. Both layers are BUILT as soon as a land pattern is available (see
  // setLandPattern) and these flags only decide visibility. Before that, the board mesh was only
  // ever CONSTRUCTED inside setLandPattern, and setLandPattern was only called by the Pads toggle -
  // so at load the PCB chip read "on" while no board existed at all, and turning PCB on did nothing.
  const layers: LayerVisibility = { ...DEFAULT_LAYERS };

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
      // Size the ambient occlusion to THIS part, now that its real extent is known. Same reasoning
      // as the shadow frustum immediately below: a radius that is right for one package is wrong
      // for every other size, and here that failure is silent - the AO simply returns "nothing is
      // occluded" and looks like a pass that is switched off.
      gtao.updateGtaoMaterial(aoSettings(radius));
      // aim the key + scale its shadow frustum to the model so the shadow is crisp, not clipped
      key.position.set(radius * 1.6, radius * 2.6, radius * 1.5);
      kd.left = kd.bottom = -radius * 2.2;
      kd.right = kd.top = radius * 2.2;
      kd.near = radius * 0.05;
      kd.far = radius * 8;
      kd.updateProjectionMatrix();
      fill.position.set(-radius * 1.4, -radius * 0.3, -radius);

      // Point the camera down the canonical 3/4 direction, then let the SHARED fit decide how
      // far along it to sit. One fit path, not two: a second copy of this arithmetic beside
      // refitCamera would be free to disagree with it, and the disagreement would show up only
      // as a model that changes size when a layer is toggled.
      camera.position.set(...VIEW_DIRECTIONS.iso);
      refitCamera();
      // The component's height is only knowable HERE, and the board's thickness is derived from it.
      // Any land pattern handed in before this point was built against the unknown-height fallback
      // and against a `modelBaseY` of 0, so rebuild it now that both are real. Fires at most once
      // (this callback runs once), and setLandPattern re-fits the camera itself.
      if (lastLand) setLandPattern(lastLand);
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
    // both paths follow the ACTIVE camera: leaving the pass bound to the perspective one rendered
    // a perspective image through an orthographic view's controls, which looks like the view
    // control simply not working.
    renderPass.camera = activeCamera;
    // Same trap as GTAOPass below, with a twist: ViewHelper CLOSES OVER its camera in the
    // constructor and exposes no field to rebind (checked in the installed source, not assumed), so
    // it cannot be pointed at a new one - it has to be REBUILT. Cheap, because this only fires when
    // the view actually swaps projection, and the alternative is a gizmo describing a camera nobody
    // is looking through.
    if (viewHelper && gizmoCamera !== activeCamera) rebuildGizmo();
    // GTAO renders its OWN depth/normal G-buffer, from its OWN camera reference - which the pass
    // captures at construction and never updates. Left alone, the orthographic top view drew its
    // beauty pass through one camera while the occlusion multiplied over it was computed through
    // another, still sitting at the three-quarter position: an AO map aligned to nothing on screen.
    // The `PERSPECTIVE_CAMERA` define has to move with it, because the shader reconstructs view
    // position from depth differently for the two projections and the pass only sets that define in
    // its constructor.
    if (gtao.camera !== activeCamera) {
      gtao.camera = activeCamera;
      gtao.gtaoMaterial.defines.PERSPECTIVE_CAMERA = activeCamera === camera ? 1 : 0;
      gtao.gtaoMaterial.needsUpdate = true;
    }
    if (renderMode === "realistic") composer.render();
    else renderer.render(scene, activeCamera);
    // THE AXIS GIZMO, drawn last and over the top (owner, 2026-07-26: "one of those 3d view things
    // where u can look at different views"). three's own ViewHelper, not a hand-rolled cube: it is
    // maintained, it already labels and hit-tests its axes, and reproducing that is exactly the
    // wheel-reinvention the rules warn about.
    //
    // It needs its own clearDepth or the composer's output buffer occludes it, and it is rendered
    // OUTSIDE the composer so the AO pass never processes it as scene geometry.
    if (viewHelper) {
      renderer.autoClear = false;
      renderer.clearDepth();
      viewHelper.render(renderer);
      renderer.autoClear = true;
    }
    raf = requestAnimationFrame(tick);
  };
  // Mounted after the loop is armed so the first frame already carries it. The parent is the
  // renderer's own container, and the helper draws into a corner viewport of the same canvas -
  // no second canvas, no second context.
  /** three's ViewHelper draws into a FIXED 128px corner viewport (`const dim = 128`, read from the
   *  installed source - it is not configurable and we do not fork vendor code). In the ~280px
   *  detail tile that is 45% of the width, which is an axis gizmo wearing the stage rather than
   *  sitting in its corner. So it appears only where 128px reads as a corner: measured against the
   *  live canvas, so the modal gets it, the tile does not, and a resize re-decides on its own
   *  rather than needing a context flag threaded down. */
  const GIZMO_MIN_STAGE_PX = 420;
  function gizmoFits() {
    return renderer.domElement.clientWidth >= GIZMO_MIN_STAGE_PX;
  }

  function rebuildGizmo() {
    try {
      viewHelper?.dispose?.();
      viewHelper = null;
      gizmoCamera = null;
      if (!gizmoFits()) return;
      viewHelper = new ViewHelper(activeCamera, renderer.domElement);
      gizmoCamera = activeCamera;
      // Its "look at" point must be the point the controls actually orbit, or clicking an axis
      // frames a different subject than dragging does.
      viewHelper.center.copy(controls.target);
    } catch {
      // A helper that fails to construct must never take the viewer down with it: the 3D view is
      // the feature, the gizmo is an affordance on top of it.
      viewHelper = null;
      gizmoCamera = null;
    }
  }
  rebuildGizmo();
  raf = requestAnimationFrame(tick);

  const onResize = () => {
    // crossing the threshold in either direction adds or removes the gizmo
    if (gizmoFits() !== Boolean(viewHelper)) rebuildGizmo();
    const w = container.clientWidth || width;
    const h = container.clientHeight || height;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
    composer.setSize(w, h);
    // the orthographic frustum is re-derived from the new aspect by refitCamera below
    // REFIT, do not just restretch. The required distance is a function of the ASPECT
    // (`fitDistanceForBox(half, dir, fov, aspect)`), because a perspective fov is VERTICAL and a
    // wide frame is therefore width-limited while a tall one is height-limited. Updating the
    // aspect without recomputing the distance leaves the camera at the distance the OLD shape
    // needed, so the subject is mis-framed until something else happens to refit.
    //
    // MEASURED 2026-07-25, which is how this was found: when the detail sheet's stage went from
    // 266x540 (portrait) to 494x240 (landscape), the model kept the far distance the portrait fit
    // had required and rendered at ~28% of the frame width, with FIT_MARGIN saying it should fill
    // ~87%. Pre-existing rather than new - it fires on any real window resize too, which is
    // exactly the case no test covered and no screenshot had ever been taken across.
    refitCamera();
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
        const original = originalMaterials.get(m);
        m.material = original ?? (realisticMaterial as THREE.Material);
        // The VENDOR's colour is kept - that is what realism means here, and substituting an invented
        // epoxy was the mistake this mode was built to stop. But a STEP carries colour and NOTHING
        // else, so the converter has to supply every surface property, and an extreme value it guessed
        // is not vendor intent: roughness 1.0 is a chalk-matte that kills every highlight, 0.0 is a
        // mirror. Neither is moulded epoxy. Only the extremes are corrected; anything the converter
        // stated in a plausible range is left exactly as it is.
        if (original && "roughness" in original) {
          const std = original as THREE.MeshStandardMaterial;
          if (std.roughness >= 0.98) std.roughness = 0.55;
          else if (std.roughness <= 0.02) std.roughness = 0.25;
          // a moulded body picks up the studio room; leaving this at a default 1.0 with a dark
          // basecolour is most of why the surface showed no reflection at all
          if (std.envMapIntensity < 1) std.envMapIntensity = 1.15;
        }
      }
    } else {
      const next = mode === "xray" ? xrayMaterial : studioMaterial;
      if (next) for (const m of modelMeshes) m.material = next;
    }
    // The outlines are the cartoon. They earn their place only in studio mode, where a flat
    // high-contrast surface is deliberately reading SHAPE rather than pretending to be real.
    for (const l of outlineSegments) l.visible = mode === "studio";
  }

  /**
   * Re-frame the camera around whatever is currently VISIBLE, keeping the direction it is
   * already looking from.
   *
   * The fit used to be computed once, from the model alone, at load. The board and the land
   * pattern are built later and are far larger than the part, so switching the PCB on shoved it
   * out of frame; and a thin part alone in a tall stage came out at about a tenth of the
   * viewport. Only the DISTANCE changes here - moving the camera's angle when someone toggles a
   * layer would read as the viewer wrestling them for control.
   */
  function refitCamera(forDirection?: [number, number, number]) {
    const boxes: Box[] = [];
    const add = (object: THREE.Object3D | null) => {
      if (!object || !object.visible) return;
      const b = new THREE.Box3().setFromObject(object);
      if (b.isEmpty()) return;
      boxes.push({ min: b.min.toArray(), max: b.max.toArray() });
    };
    add(root.visible ? root : null);
    add(landGroup);
    // THE BOARD IS DELIBERATELY NOT IN THE FIT. Owner 2026-07-26: "the view should be zoomed in and
    // centered on the model". The plane is effectively infinite (boardPlane.BOARD_PLANE_HALF_MM), so
    // fitting it would zoom out to 250mm and render the part as a speck - and even at the old, modest
    // sizes it was the board that decided the frame, which is why the part kept reading as lost on a
    // table. The subject is the part and its pads; the surface it stands on is context, not content.
    const bounds = visibleBounds(boxes);
    if (!bounds || bounds.radius <= 0) return; // all hidden: hold the last good frame, don't lurch
    const centre = new THREE.Vector3(...bounds.centre);
    // preserve the current viewing DIRECTION relative to the target; only the distance moves.
    // `forDirection` overrides it for a view the camera has not MOVED to yet: setView tweens over
    // ~260ms, so fitting from the live position would size the frame for the direction being left
    // behind. That is what left the orthographic top view framed by the ISO fit - a frustum sized
    // for a three-quarter silhouette, with the subject small inside it and the shadow plane's own
    // edge visible in the corner.
    // Read the live direction off the camera that is ACTUALLY rendering. Reading it off the
    // perspective one unconditionally meant that any refit while the top view was up - a resize, a
    // layer toggle - re-sized the orthographic frustum for the three-quarter direction the
    // perspective camera was still parked at.
    const direction = forDirection
      ? new THREE.Vector3(...forDirection).normalize()
      : activeCamera.position.clone().sub(controls.target);
    if (direction.lengthSq() === 0) direction.set(...VIEW_DIRECTIONS.iso);
    direction.normalize();
    // ONE screen basis for the fit and for the cameras, and it needs the SUBJECT to choose: looking
    // straight down there is no horizon to keep level, so the in-plane rotation is a free choice
    // and the fit picks whichever turn needs the smaller frustum. The extents therefore have to be
    // measured before the cameras are oriented, not after.
    const half = halfExtents(boxes);
    // ONLY the orthographic camera's up is ever touched. The perspective camera keeps world up
    // for its whole life, because it is the camera OrbitControls was built against and its up is
    // baked into the controls' orbit frame at construction - mutating it made the controls drive
    // the free 3/4 view about one axis while it rendered about another. For every direction the
    // perspective camera is actually used from, `screenUpFor` returns world up anyway, so nothing
    // is lost by leaving it alone; the pole is the ortho camera's case exclusively.
    orthoCamera.up.set(...screenUpFor(direction.toArray(), half, camera.aspect));
    // Fit the BOX, not its enclosing sphere. A sphere fit is exact for a sphere and wasteful for a
    // component package: its radius comes from the long diagonal while the on-screen silhouette
    // comes from the short one, so the camera backed off for space nothing occupied. MEASURED on
    // the owner's 3.5x1.4x0.6mm part at a 494x240 stage: the part covered ~37% of the frame height
    // at a correct sphere fit. The box fit is still safe through the whole idle spin - it projects
    // the footprint's SWEPT circle, so no angle can grow out of the frame.
    fitDistance = half
      ? fitDistanceForBox(half, direction.toArray(), camera.fov, camera.aspect)
      : bounds.radius * 4;
    // The orthographic frustum is sized from the same visible set. Done on EVERY refit, not only
    // when the top view is active, so switching to it never shows one frame of a stale frustum.
    if (half) {
      const halfH = fitOrthoHalfHeight(half, direction.toArray(), camera.aspect);
      const halfW = halfH * (camera.aspect || 1);
      orthoCamera.left = -halfW;
      orthoCamera.right = halfW;
      orthoCamera.top = halfH;
      orthoCamera.bottom = -halfH;
    }
    // FRAME the centre of what is visible, but ORBIT the model's own centre (owner, 2026-07-26:
    // "use the center of the model as an axis ... to rotate around"). Those are two different
    // points and conflating them is what made the package swing around a spot below and outside
    // itself: the pads sit under the part, so the visible-bounds centre drops toward them, and it
    // MOVES whenever a layer is toggled - so turning pads on visibly shifted the axis. `modelCenter`
    // is captured once at load and stays put.
    // ONE point serves as the target AND as the point the camera position is derived from. They
    // must be the same or the camera stops looking along its own fit direction: aiming at the model
    // while standing where the BOUNDS centre put you throws the subject off-frame, which is exactly
    // what the first cut of this change did - the part sat up and to the left with the board filling
    // the stage.
    const orbit = modelCenter ?? centre;
    fitTarget.copy(orbit);
    controls.target.copy(orbit);
    viewHelper?.center.copy(orbit);
    if (!forDirection) {
      activeCamera.position.copy(orbit).add(direction.clone().multiplyScalar(fitDistance));
    }
    camera.near = Math.max(bounds.radius / 100, 1e-4);
    camera.far = bounds.radius * 100;
    camera.updateProjectionMatrix();
    // The orthographic camera shares the standoff. Its distance does not affect the projection, but
    // it still has to sit OUTSIDE the geometry or near-plane clipping slices the subject in half -
    // hence a generous near/far around the same standoff. It only INHERITS the perspective
    // camera's position while the perspective camera is the one in use; once the top view is up,
    // the ortho camera owns its own position and copying over it would yank the view back.
    if (activeCamera !== orthoCamera) orthoCamera.position.copy(camera.position);
    orthoCamera.near = 0.01;
    orthoCamera.far = Math.max(bounds.radius * 200, 10);
    orthoCamera.lookAt(orbit);
    // the ortho camera's up may just have changed, and the controls' orbit frame is derived from
    // it at construction only, so they have to be rebuilt or they will fight the camera
    rebindControls(activeCamera);
    orthoCamera.updateProjectionMatrix();
    controls.update();
  }

  function setLayers(v: Partial<LayerVisibility>) {
    Object.assign(layers, v);
    root.visible = layers.model;
    if (landGroup) landGroup.visible = layers.pads;
    if (boardMesh) boardMesh.visible = layers.board;
    // the visible set just changed, so the frame that fitted the old set no longer fits this one
    refitCamera();
  }

  /** Tween the camera to a canonical direction. Short and ease-OUT, because the user is watching
   *  the very start of this motion: it must move immediately, not creep. Under the 300ms ceiling
   *  for UI motion, and skipped entirely under prefers-reduced-motion, where the position simply
   *  snaps - reduced motion means less movement, not a missing feature. */
  function setView(mode: ViewMode) {
    if (!fitDistance) return;
    viewMode = mode;
    // 3D IS the spinning view - it is the free orbit, and stopping the spin when the user asks for
    // it made the control look broken. The FIXED views (top/front) are the ones that must hold
    // still, because a "top" view that rotates away from top is not a top view.
    // iso is the free orbit and the only view that may spin - but only if the user still wants it.
    controls.autoRotate =
      mode === "iso" && spinWanted && (spinChosen || !prefersReducedMotion());
    // Swap the projection with the view. OrbitControls binds a camera at construction, so its
    // `object` has to be reassigned too, or the user would orbit the camera that is not rendering.
    activeCamera = mode === "top" ? orthoCamera : camera;
    // NOT `controls.object = activeCamera`. Reassigning the object leaves the orbit frame the
    // constructor computed from the OLD camera's up in place, so the controls keep driving the new
    // camera about the previous camera's axis.
    rebindControls(activeCamera);
    // Re-fit for the direction we are moving TO, not the one we are leaving.
    refitCamera(VIEW_DIRECTIONS[mode]);
    // The bare shadow-catcher is a horizontal plane. Edge-on from a top view it contributes
    // nothing and its own edge reads as a stray quad behind the part, so it stands down for the
    // views that look along an axis and returns for the free 3/4 view where it grounds the model.
    if (groundPlane) groundPlane.visible = mode === "iso" && !boardMesh;
    // orbit whatever the fit chose as the centre, so a canonical view frames the same subject the
    // free view does instead of snapping back to a fixed origin the content may not sit on.
    const target = new THREE.Vector3(...VIEW_DIRECTIONS[mode])
      .normalize()
      .multiplyScalar(fitDistance)
      .add(fitTarget);
    cancelAnimationFrame(viewTween);
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      activeCamera.position.copy(target);
      activeCamera.lookAt(fitTarget);
      controls.target.copy(fitTarget);
      controls.update();
      return;
    }
    const from = activeCamera.position.clone();
    const start = performance.now();
    const DURATION = 260;
    const step = () => {
      const t = Math.min(1, (performance.now() - start) / DURATION);
      // easeOutQuint: a strong ease-out, the curve family the built-in `ease-out` is too weak for
      const e = 1 - Math.pow(1 - t, 5);
      activeCamera.position.lerpVectors(from, target, e);
      controls.target.copy(fitTarget);
      controls.update();
      if (t < 1) viewTween = requestAnimationFrame(step);
    };
    viewTween = requestAnimationFrame(step);
  }

  const disposeScene = () => {
    cancelAnimationFrame(raf);
    resizeObserver?.disconnect();
    controls.dispose();
    // The gizmo owns geometry, materials and its own sprite textures. This viewer is mounted and
    // unmounted every time a part is opened, so leaking them once per part is leaking them forever.
    viewHelper?.dispose?.();
    viewHelper = null;
    gizmoCamera = null;
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
    // remembered so the model-loaded callback can rebuild it against the real component height
    lastLand = land;
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
    if (!land || !land.pads.length) {
      // the board and pads have just been REMOVED; the frame that held them is now far too wide
      refitCamera();
      return;
    }

    // 1 scene unit == 1 MILLIMETRE (the model is scaled up by 1000 on load), so KiCad's pad
    // coordinates need no conversion at all. Kept as a named constant so the unit contract is
    // stated rather than implied by bare arithmetic.
    const MM_TO_SCENE = 1;
    // declared before the pad loop, because a back-side pad is positioned relative to it.
    // DERIVED from the part, not fixed at 0.6mm: the owner's "the pcb should be a plane less than its
    // own component". A USON-14 body is ~0.55mm, so the old flat 0.6mm board was thicker than the
    // component standing on it. `boardPlaneThickness` guarantees strictly-thinner at every height.
    // ONE source of truth for the whole stack, pure and unit-tested (boardPlane.ts): a perspective
    // 3/4 render cannot settle these relationships, so they are asserted there rather than eyeballed
    // here. `padThickness` is hoisted out of the pad loop because the STACK needs it too.
    // modelBaseY, not a fresh `-modelSize.y/2`: one definition of the model's base, so a second copy
    // cannot drift from the one the shadow plane and the camera fit already use.
    const stack = boardStack(modelBaseY, (modelSize?.y ?? 0) * MM_TO_SCENE);
    const boardThickness = stack.boardThickness * MM_TO_SCENE;
    const padThickness = PAD_THICKNESS_MM * MM_TO_SCENE;
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
      const thickness = padThickness;
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

    // ONE material for every silk segment. It was built INSIDE the loop, so a footprint with
    // twenty silk graphics allocated twenty identical MeshPhysicalMaterials - each compiling its
    // own shader program the first time it is drawn, and each needing disposal. They differ only in
    // GEOMETRY, so there is nothing per-segment to carry.
    let silkMat: THREE.MeshPhysicalMaterial | null = null;
    const silkMaterial = () => {
      if (silkMat) return silkMat;
      silkMat = new THREE.MeshPhysicalMaterial({
        // Silkscreen is MATTE EPOXY INK, not paint on a screen. This was MeshBasicMaterial, which is
        // UNLIT by definition: it ignored the key light, the environment and every shadow, so it
        // stayed the same flat grey whatever the board did and read as a sticker laid over a lit
        // render. The owner's "the silkscreen needs to look realistic" is mostly this material class.
        //
        // Real silk is slightly off-white (never paper white), rough enough to kill any mirror
        // reflection, and dielectric. A trace of clearcoat is what makes it read as CURED ink
        // sitting on the mask rather than as bare pigment.
        color: 0xe8e9e6,
        roughness: 0.82,
        metalness: 0.0,
        clearcoat: 0.18,
        clearcoatRoughness: 0.6,
        envMapIntensity: 0.5,
        // ink lies ON the mask; without this the underside vanishes when the board is seen from below
        side: THREE.DoubleSide,
      });
      return silkMat;
    };

    // The cap the owner chose: a fraction of the part's SHORT horizontal axis, so it scales with
    // the part rather than being a magic millimetre value that is wrong at both extremes.
    const silkCap = modelSize
      ? Math.min(modelSize.x, modelSize.z) * SILK_MAX_FRACTION
      : undefined;
    // SILKSCREEN + COURTYARD. Pads alone are not the land pattern: the silk outline and the pin-1
    // marker are how a person recognises the part, and the courtyard is the keep-out it gets
    // checked against. Drawn a hair above the mask so they are not z-fighting with it.
    // Ink thickness. Silk is ~10-15um of cured epoxy, so it stands very slightly off the mask - enough
    // that it is not co-planar (which z-fights) and enough for the key light to find its edge now that
    // the material is lit rather than flat.
    const silkY = 0.014;
    for (const g of land.graphics ?? []) {
      // DOCUMENTATION layers never exist on a physical board, so they have no place in a physical
      // render. F.Fab was already excluded on exactly that reasoning; the COURTYARD is the same kind
      // of thing - a keep-out annotation, not ink - and it was breaking the rule its neighbour
      // follows. Drawn at its real width it also became the loudest thing in the frame and, because
      // the board was sized from pad centres, it hung off the board edge into mid-air. Owner
      // 2026-07-26: "the 3d footprint looks horribly wrong now."
      if (g.layer.endsWith("Fab") || g.layer.endsWith("CrtYd")) continue;
      // A FLAT QUAD at the footprint's own stroke width, not a THREE.Line. WebGL ignores
      // `LineBasicMaterial.linewidth`, so every graphic used to render as a 1-pixel hairline no
      // matter the zoom: the silkscreen outline and the pin-1 marker were in the scene graph and
      // invisible on screen, which is exactly why the land pattern read as "just the pads". The
      // width the backend extracted from the footprint was being thrown away here. See
      // boardPlane.silkQuad for the geometry and for why LineSegments2 was rejected.
      const q = silkQuad(g.start, g.end, g.width, silkCap);
      if (!q) continue;
      const mat = silkMaterial();
      const geo = new THREE.PlaneGeometry(q.length * MM_TO_SCENE, q.width * MM_TO_SCENE);
      // PlaneGeometry is authored in XY. Lay it into the board plane (XZ), then turn it along the
      // segment. Order matters: rotate into the plane FIRST, then spin about the plane's normal.
      geo.rotateX(-Math.PI / 2);
      const mesh = new THREE.Mesh(geo, mat);
      mesh.rotation.y = q.angleY;
      mesh.position.set(q.cx * MM_TO_SCENE, silkY, q.cz * MM_TO_SCENE);
      // lit ink takes the board's shadow like anything else on the surface
      mesh.receiveShadow = true;
      group.add(mesh);
    }

    // THE PCB the pads sit on. Without a substrate the pads float in space, which is the other
    // half of "the 3d footprint looks nothing like the model": a land pattern is a thing ON a
    // board, and the green solder mask is the visual anchor that says so. Sized from the pad
    // extents with a margin, so it frames the pattern instead of dwarfing it.
    // A PLANE, not a tile. Sized from EVERYTHING that stands on it (pad centres PLUS pad sizes plus
    // every graphic - see boardExtent, which fixed a board narrower than its own footprint), then
    // grown well past it so the eye reads surface rather than object. Owner 2026-07-26: "the pcb
    // render should legitimately add a plane to the 3d view not just another floating component."
    const plane = boardPlaneHalfExtents(boardExtent(land.pads, land.graphics ?? []));
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
      // MEASURED on the owner's window after the plane became effectively infinite: the mask ran
      // rgb(55) near the camera to rgb(150) at the horizon, while the component body sat at rgb(77) -
      // so the part was DARKER than its own background and read as a silhouette on a bright floor.
      // That is Fresnel: a clearcoat mirrors the studio room at grazing incidence, and a 250mm plane
      // is almost entirely grazing. A small dark slab hid it; an infinite one cannot.
      //
      // Matte black solder mask does not mirror a room at a glancing angle. Clearcoat cut to a trace,
      // roughness up, and the environment contribution down - so the surface stays board-dark all the
      // way out and the part is the lightest thing in frame, which is what makes it read as ON the
      // board rather than cut out of it.
      color: 0x08090b,
      roughness: 0.78,
      metalness: 0.0,
      clearcoat: 0.02,
      clearcoatRoughness: 0.9,
      // Measured again after the de-gloss: near 45, far 98. With a near-BLACK basecolour that far
      // value is almost entirely the environment, not the material - so the environment is the knob.
      // Target was far < 60, i.e. board-dark all the way out with the part the lightest thing present.
      envMapIntensity: 0.03,
      // ...and the environment turned out NOT to be the whole knob, which is why that target was
      // still missed. With envMapIntensity already at 0.03 the far field measured 96 while the
      // component body measured 88 - the board was brighter than the part standing on it, the exact
      // thing the paragraph above set out to stop. The remainder is DIRECT-light specular: a
      // dielectric keeps 4% reflectance whatever its base colour, and across a near-infinite plane
      // almost every pixel is at a grazing angle where Fresnel drives that toward 100%. A flat plane
      // under a directional light has a constant DIFFUSE response, so the smooth near-to-far ramp
      // that was being read as "environment" is specular from the key and rim.
      //
      // `specularIntensity` is the property that scales exactly that term for a non-metal, and it
      // had never been touched. Matte black solder mask is not a 4%-reflective polish; cutting it is
      // physically what the surface is, not a fudge to hit a number.
      specularIntensity: 0.35,
    });
    const substrateMat = new THREE.MeshPhysicalMaterial({
      color: 0x241f19,
      roughness: 0.88,
      metalness: 0.0,
      envMapIntensity: 0.35,
    });
    boardMesh = new THREE.Mesh(
      new THREE.BoxGeometry(plane.halfX * 2 * MM_TO_SCENE, boardT, plane.halfZ * 2 * MM_TO_SCENE),
      // BoxGeometry material order: +x, -x, +y(top), -y(bottom), +z, -z
      [substrateMat, substrateMat, maskMat, maskMat, substrateMat, substrateMat],
    );
    // The stack, bottom to top: board, then pads ON the board, then the part ON the pads. So the
    // board's TOP face is one pad-thickness BELOW the component's base, not level with it.
    //
    // This is the clipping bug (owner 2026-07-26: "the 3d model clips into the pads and pcb"). Both
    // the board top AND the pad group used to sit at `modelBaseY`, and pad geometry extrudes UPWARD
    // from its group origin - so every pad occupied `modelBaseY .. modelBaseY + padThickness`, i.e.
    // the full pad thickness was buried inside the component body. A real reflowed joint does the
    // opposite: the pad holds the part up off the board.
    boardMesh.position.set(0, stack.boardCenterY, 0);
    boardMesh.receiveShadow = true;
    boardMesh.visible = layers.board;
    scene.add(boardMesh);
    // The bare shadow-catcher belongs to the no-board case. Left visible underneath a real board it
    // catches the same light a few hundredths of a millimetre lower and reads as a dark seam right
    // where the pads meet the surface - which is exactly what "the pads are not flush" looks like.
    if (groundPlane) groundPlane.visible = false;
    // One pad-thickness below the model's base, so a front pad's TOP face lands exactly on the body's
    // underside: the part rests ON the pads instead of having them driven up into it. The group's
    // origin remains the board's top face, which is the contract the pad loop's positions rely on
    // (a back-side pad is placed at `-boardThickness - thickness` relative to this origin, and that
    // stays flush against the board's underside because both moved together).
    group.position.y = stack.padGroupY;
    group.visible = layers.pads;
    scene.add(group);
    landGroup = group;
    // the board and the pads are BIGGER than the part and only exist from here on, so the frame
    // that fitted the bare model would push them off screen. This is the moment the visible set
    // grows, so it is the moment to re-fit.
    refitCamera();
  }

  return {
    dispose: () => {
      cancelAnimationFrame(viewTween);
      setLandPattern(null);
      disposeScene();
    },
    setView,
    /** Turn the idle spin on or off. Returns the state actually in force, which is false whenever the
     *  OS asks for reduced motion no matter what was requested. */
    setSpin: (wanted: boolean) => {
      spinWanted = wanted;
      spinChosen = true;
      const on = wanted && !prefersReducedMotion();
      controls.autoRotate = on && viewMode === "iso";
      return on;
    },
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
