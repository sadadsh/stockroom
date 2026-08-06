/**
 * WHICH DOCUMENT THE WORKSPACE DRAWS: three sources, in one order, decided in one place.
 *
 *   1. THE DEV MODE WORKING DRAFT, when there is one. What the owner is editing right now, held in
 *      the layout slice of `lib/devModeDraft.ts` - so an edit shows up in the real application on the
 *      next render, which is plan decision 5 (the live app IS the canvas).
 *   2. THE COMMITTED OVERRIDE (`lib/layout.overrides.ts`), when it is not `null`. A redesign that
 *      shipped through source, applied for everyone with Design Mode off, exactly as the committed
 *      token, copy, icon, element and behaviour overrides are.
 *   3. THE SHIPPED DEFAULT (`DEFAULT_WORKSPACE_LAYOUT`). The arrangement as transcribed in Phase 1.
 *
 * WHY THE ORDER IS THIS WAY ROUND. A working draft beats a commit because the whole point of editing
 * on the live app is seeing the edit; a commit beats the default because a committed redesign IS the
 * app (decision 4). Nothing merges: a layout document is a tree, and a half-applied tree is an
 * arrangement nobody described. One of the three wins whole.
 *
 * WHAT A NULL DRAFT MEANS, precisely: NO WORKING EDIT - not "no override". So dropping the working
 * draft (Reset all, or Design Mode's own revert) returns to whatever is COMMITTED, which is the app as
 * it ships on the owner's laptop. Reverting a committed arrangement is a change to source, and that is
 * the Phase 4 commit pipeline's business rather than a local reset's.
 *
 * WHY IT IS A MODULE OF ITS OWN. It is the only place in the app where "which arrangement" is
 * answered, it is pure, and it is therefore testable without mounting a workspace. The RENDERER stays
 * document-agnostic (`LayoutRenderer` never learns that overrides exist) and `workspaceBindings` asks
 * this one question at the one point it obtains its document.
 *
 * As shipped - a `null` committed override and no draft - this returns `DEFAULT_WORKSPACE_LAYOUT` BY
 * REFERENCE, which is why wiring it changes no byte of the rendered DOM. That is the Phase 1
 * dom-parity suite's claim, and it is the gate this file must not move.
 */
import { LAYOUT_OVERRIDES } from "../lib/layout.overrides";
import { DEFAULT_WORKSPACE_LAYOUT } from "./defaultWorkspaceLayout";
import type { LayoutDocument } from "./document";

export function resolveWorkspaceLayout(
  draft?: LayoutDocument | null,
): LayoutDocument {
  return draft ?? LAYOUT_OVERRIDES.workspace ?? DEFAULT_WORKSPACE_LAYOUT;
}
