/**
 * The kit's ONE import surface.
 *
 * Every route imports its primitives from `./primitives` and never has to know which sibling a
 * given piece happens to be declared in, so there is never a second parallel kit to drift against.
 * The pieces themselves live in:
 *
 *   - `primitivesKit.tsx`  the controls and surfaces (Card, Button, IconButton, TabStrip,
 *                          SegmentedControl, TabPanel, Panel, Field, Badge, Dot, Eyebrow,
 *                          SectionHeading, LegendSwatch)
 *   - `productState.tsx`   the product-state vocabulary (route header, section header, the five
 *                          states, retry, inline notice, bounded region, compact fact row,
 *                          attention item, data table)
 *   - `modalParts.tsx`     the modal frame
 *   - `typography.ts`      the semantic text roles and the scale behind them
 *
 * This file is a BARREL and holds no declarations of its own, which is the point: a module that
 * both declares components and re-exports a mixed bag of values is not a Fast Refresh boundary, so
 * editing any control in the kit reloaded the whole page instead of hot-swapping the control. Each
 * module above is now its own boundary and this file merely names them together.
 */
export * from "./primitivesKit";
export * from "./productState";
export * from "./modalParts";
export * from "./typography";
