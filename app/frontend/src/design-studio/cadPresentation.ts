import type {
  CadPresentationOverride,
  DesignDocument,
  FootprintPresentationOverride,
  Model3dPresentationOverride,
  SymbolPresentationOverride,
} from "./document";
import type { Theme } from "../lib/theme";

export const CAD_PRESENTATION_KIND_ATTRIBUTE = "data-design-cad-kind";
export const CAD_PRESENTATION_TARGET_ATTRIBUTE = "data-design-cad-target";

export type CadPresentationKind = keyof CadPresentationOverride;

export interface CadPresentationPatchByKind {
  symbol: Partial<SymbolPresentationOverride>;
  footprint: Partial<FootprintPresentationOverride>;
  model3d: Partial<Model3dPresentationOverride>;
}

export interface CadPresentationTarget {
  kind: CadPresentationKind;
  targetId: string;
}

function isKind(value: string | null): value is CadPresentationKind {
  return value === "symbol" || value === "footprint" || value === "model3d";
}

export function cadPresentationTarget(element: Element): CadPresentationTarget | null {
  const marked = element.closest<HTMLElement>(`[${CAD_PRESENTATION_KIND_ATTRIBUTE}]`)
    ?? element.querySelector<HTMLElement>(`[${CAD_PRESENTATION_KIND_ATTRIBUTE}]`);
  if (!marked) return null;
  const kind = marked.getAttribute(CAD_PRESENTATION_KIND_ATTRIBUTE);
  const targetId = marked.getAttribute(CAD_PRESENTATION_TARGET_ATTRIBUTE);
  return isKind(kind) && targetId ? { kind, targetId } : null;
}

export function updateCadPresentationDocument<K extends CadPresentationKind>(
  document: DesignDocument,
  targetId: string,
  kind: K,
  patch: CadPresentationPatchByKind[K],
): DesignDocument {
  const active = document.variations[document.activeVariationId];
  if (!active) {
    const current = document.cadPresentation[targetId] ?? {};
    return {
      ...document,
      cadPresentation: {
        ...document.cadPresentation,
        [targetId]: { ...current, [kind]: { ...(current[kind] ?? {}), ...patch } },
      },
    };
  }
  const inherited = document.cadPresentation[targetId] ?? {};
  const local = active.patch.cadPresentation?.[targetId];
  const current = local && local !== null ? local : inherited;
  return {
    ...document,
    variations: {
      ...document.variations,
      [active.id]: {
        ...active,
        patch: {
          ...active.patch,
          cadPresentation: {
            ...active.patch.cadPresentation,
            [targetId]: { ...current, [kind]: { ...(current[kind] ?? {}), ...patch } },
          },
        },
      },
    },
  };
}

export function resetCadPresentationDocument(
  document: DesignDocument,
  targetId: string,
): DesignDocument {
  const active = document.variations[document.activeVariationId];
  if (!active) {
    const cadPresentation = { ...document.cadPresentation };
    delete cadPresentation[targetId];
    return { ...document, cadPresentation };
  }
  return {
    ...document,
    variations: {
      ...document.variations,
      [active.id]: {
        ...active,
        patch: {
          ...active.patch,
          cadPresentation: { ...active.patch.cadPresentation, [targetId]: null },
        },
      },
    },
  };
}

export function updateCadPresentationThemeDocument<K extends CadPresentationKind>(
  document: DesignDocument,
  targetId: string,
  kind: K,
  patch: CadPresentationPatchByKind[K],
  theme: Theme,
): DesignDocument {
  const active = document.variations[document.activeVariationId];
  if (!active) return updateCadPresentationDocument(document, targetId, kind, patch);
  const currentTheme = active.themes?.[theme] ?? {};
  const local = currentTheme.cadPresentation?.[targetId];
  const current = local && local !== null ? local : {};
  return {
    ...document,
    variations: {
      ...document.variations,
      [active.id]: {
        ...active,
        themes: {
          ...active.themes,
          [theme]: {
            ...currentTheme,
            cadPresentation: {
              ...currentTheme.cadPresentation,
              [targetId]: {
                ...current,
                [kind]: { ...(current[kind] ?? {}), ...patch },
              },
            },
          },
        },
      },
    },
  };
}
