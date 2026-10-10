import { Area, AreaChart, ResponsiveContainer } from "recharts";
import { useMotion } from "@/lib/motion";
import { useChartColors } from "./colors";

export function Sparkline({ values, tone = "accent", height = 32 }: { values: number[]; tone?: "accent" | "crit" | "warn" | "ok" | "info"; height?: number }) {
  const c = useChartColors();
  const { reduced } = useMotion();
  const color = c[tone];
  const data = values.map((v, i) => ({ i, v }));
  const id = `sp-${tone}`;
  return (
    <div style={{ height }} aria-hidden>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 2, bottom: 2, left: 0, right: 0 }}>
          <defs>
            <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.35} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area type="monotone" dataKey="v" stroke={color} strokeWidth={1.5} fill={`url(#${id})`} isAnimationActive={!reduced} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
