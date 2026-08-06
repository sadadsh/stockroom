/**
 * A WORKSPACE RENDER CONTEXT, for tests that mount a layout document rather than the workspace.
 *
 * `ComponentWorkspace` assembles this object from its own queries, refs and writes; a test that
 * wants to render an ARBITRARY layout document through the shipped piece bindings needs the same
 * object without the component that owns it. So this states the whole context with inert callbacks
 * and real refs, and nothing else.
 *
 * IT OWNS NOTHING, deliberately. Every callback is a no-op and every ref starts empty: a piece under
 * test is being asked what it RENDERS, not what it does when pressed, and a fixture that recorded
 * calls would invite invariant tests to start asserting behaviour that belongs in the behaviour
 * suites. A test that needs a call recorded passes its own function through `over`.
 */
import type { MutableRefObject } from "react";
import type { ComponentDossier, RepresentationKind } from "../api/dossierTypes";
import type { SpecFilter } from "../components/component-workspace/specificationRows";
import type { WorkspaceActivity } from "../components/component-workspace/WorkspaceStatusBar";
import type { WorkspaceRenderContext } from "../layout/workspaceRenderContext";
import type { RepresentationLayout } from "../lib/uiSession";

export interface WorkspaceRenderFixtureOptions {
  componentId?: string;
  /** `all` is the resting state: three expanded CAD modules, which is what ships. */
  layout?: RepresentationLayout;
  filter?: SpecFilter;
  activity?: WorkspaceActivity;
  refreshing?: boolean;
}

function emptyRef<T>(): MutableRefObject<T | null> {
  return { current: null };
}

const noop = () => {};

export function workspaceRenderFixture(
  dossier: ComponentDossier,
  over: WorkspaceRenderFixtureOptions = {},
): WorkspaceRenderContext {
  return {
    componentId: over.componentId ?? "lm358",
    dossier,
    header: {
      manageItems: [],
      onQualitySegment: noop,
      onOpenDatasheet: noop,
      onFindDatasheet: noop,
    },
    cad: {
      layout: over.layout ?? "all",
      onLayout: noop,
      onCompareSources: noop,
      onOpenFullPreview: noop,
      assetRefs: { current: {} } as MutableRefObject<
        Partial<Record<RepresentationKind, HTMLElement | null>>
      >,
    },
    specifications: {
      filter: over.filter ?? "all",
      onFilter: noop,
      scrollRef: emptyRef<HTMLDivElement>(),
      onViewPinout: noop,
    },
    sourcing: {
      onViewOffers: noop,
      onViewProvenance: noop,
      onOpenDocument: noop,
      onRefresh: noop,
      refreshing: over.refreshing ?? false,
      scrollRef: emptyRef<HTMLDivElement>(),
    },
    status: { activity: over.activity ?? "idle" },
  };
}
