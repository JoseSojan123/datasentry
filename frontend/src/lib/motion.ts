import type { Transition, Variants } from "framer-motion";
import { useTheme } from "./theme";

export const ease = [0.22, 0.8, 0.32, 1] as const;
export const spring: Transition = { type: "spring", stiffness: 420, damping: 34, mass: 0.7 };

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 6 },
  show: { opacity: 1, y: 0, transition: { duration: 0.28, ease } },
};

export const stagger: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.035, delayChildren: 0.02 } },
};

/** Returns variants that collapse to instant state changes when reduced motion is on. */
export function useMotion() {
  const { reducedMotion } = useTheme();
  return {
    reduced: reducedMotion,
    fadeUp: reducedMotion ? { hidden: { opacity: 1 }, show: { opacity: 1 } } : fadeUp,
    stagger: reducedMotion ? {} : stagger,
    t: (d = 0.25): Transition => (reducedMotion ? { duration: 0 } : { duration: d, ease }),
  };
}
