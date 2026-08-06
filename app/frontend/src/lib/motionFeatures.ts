/**
 * The Motion feature bundle, in its own module so it lands in its own chunk.
 *
 * Every animating surface in the app renders `m.*` from "motion/react-m" (the mini component,
 * which carries no animation runtime) under the single <LazyMotion> in main.tsx. That splits the
 * animation runtime out of the boot chunk instead of merely renaming the import: the bundle only
 * shrinks if the features arrive through a dynamic import, which is why this file exists rather
 * than a `features={domMax}` written inline.
 *
 * It has to be domMax, not domAnimation. The toast stack (src/lib/toast.tsx) sets `layout` on each
 * toast so the stack slides rather than jumps when one is dismissed from the middle, and the
 * `layout` prop is served by the `layout` feature, which ships only in domMax
 * (domMax = domAnimation + drag + layout). Under domAnimation the prop would be silently inert.
 *
 * Deferring is safe because nothing animates on boot: every m.* surface is a modal, a toast, a
 * capture pill or an enrich stage, all of which appear only after an interaction, long after this
 * chunk has landed.
 */
import { domMax } from "motion/react";

export default domMax;
