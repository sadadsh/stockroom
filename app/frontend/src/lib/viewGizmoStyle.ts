/**
 * One deliberately monochrome instrument-style palette for the 3D orientation cube.
 *
 * The old red/green/blue faces made a technical camera control read like a toy. Face
 * luminance still differs enough to preserve orientation, while labels and hover state
 * carry interaction without introducing a second colour language into the viewer.
 */
const BORDER = { size: 1, color: 0x4a4a4a } as const;
const LIGHT_HOVER = {
  color: 0xf5f5f5,
  labelColor: 0x171717,
  opacity: 1,
  border: { size: 1, color: 0x171717 },
} as const;

function darkFace(label: string, color: number) {
  return {
    label,
    color,
    labelColor: 0xf5f5f5,
    border: BORDER,
    hover: LIGHT_HOVER,
  };
}

function lightFace(label: string, color: number) {
  return {
    label,
    color,
    labelColor: 0x171717,
    border: BORDER,
    hover: LIGHT_HOVER,
  };
}

export const MONOCHROME_VIEW_GIZMO = {
  size: 104,
  resolution: 256,
  radius: 0.04,
  smoothness: 6,
  background: {
    color: 0x5c5c5c,
    opacity: 0.96,
    hover: { color: 0x707070, opacity: 1 },
  },
  // Keep the corner hit regions, but make them crisp grayscale joints rather than
  // the large coloured bulbs that made the old cube read like a toy.
  corners: {
    enabled: true,
    color: 0x686868,
    opacity: 1,
    scale: 0.18,
    radius: 0.08,
    smoothness: 4,
    hover: { color: 0xe8e8e8, opacity: 1, scale: 0.19 },
  },
  edges: {
    enabled: true,
    color: 0x747474,
    opacity: 1,
    radius: 0.04,
    smoothness: 4,
    scale: 1,
    hover: { color: 0xf5f5f5, opacity: 1, scale: 1 },
  },
  faces: {
    x: lightFace("RIGHT", 0xd8d8d8),
    nx: lightFace("LEFT", 0xa8a8a8),
    y: lightFace("TOP", 0xeeeeee),
    ny: darkFace("BOTTOM", 0x828282),
    z: lightFace("FRONT", 0xc2c2c2),
    nz: darkFace("BACK", 0x686868),
  },
} as const;
