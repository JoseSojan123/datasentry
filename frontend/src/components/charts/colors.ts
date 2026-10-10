import { useMemo } from "react";
import { useTheme } from "@/lib/theme";

const VARS = ["accent", "crit", "warn", "info", "ok", "ref", "muted", "faint", "border", "border-strong", "text", "surface", "raised", "overlay"] as const;
export type ChartColors = Record<(typeof VARS)[number], string>;

/** Recharts needs concrete colours; resolve the CSS variables for the active theme. */
export function useChartColors(): ChartColors {
  const { resolved } = useTheme();
  return useMemo(() => {
    const cs = typeof window !== "undefined" ? getComputedStyle(document.documentElement) : null;
    const out = {} as ChartColors;
    for (const v of VARS) {
      const raw = cs?.getPropertyValue(`--${v}`).trim();
      out[v] = raw ? `rgb(${raw.split(/\s+/).join(",")})` : "#888";
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolved]);
}

export const axisProps = (c: ChartColors) => ({
  stroke: c.border,
  tick: { fill: c.faint, fontSize: 11, fontFamily: '"IBM Plex Mono", monospace' },
  tickLine: false,
  axisLine: { stroke: c.border },
});
