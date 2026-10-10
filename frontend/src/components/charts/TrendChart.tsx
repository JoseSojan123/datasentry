import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtDay } from "@/lib/format";
import { useMotion } from "@/lib/motion";
import { axisProps, useChartColors } from "./colors";
import { TooltipBox } from "./ChartTooltip";

export function StackedTrend({ data, series, height = 180, ariaLabel }: { data: Record<string, any>[]; series: { key: string; label: string; tone: "crit" | "warn" | "info" | "ok" | "ref" }[]; height?: number; ariaLabel: string }) {
  const c = useChartColors();
  const { reduced } = useMotion();
  return (
    <figure aria-label={ariaLabel} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -24 }}>
          <CartesianGrid vertical={false} stroke={c.border} strokeDasharray="2 4" />
          <XAxis dataKey="day" {...axisProps(c)} tickFormatter={(d: string) => fmtDay(d)} minTickGap={16} />
          <YAxis {...axisProps(c)} allowDecimals={false} width={40} />
          <Tooltip
            cursor={{ fill: c.overlay, opacity: 0.5 }}
            content={({ active, payload, label }) =>
              active && payload?.length ? <TooltipBox title={fmtDay(label as string)} rows={series.map((s) => ({ label: s.label, value: payload[0].payload[s.key] ?? 0, color: c[s.tone] }))} /> : null
            }
          />
          {series.map((s, i) => (
            <Bar key={s.key} dataKey={s.key} stackId="a" fill={c[s.tone]} fillOpacity={s.tone === "ref" ? 0.5 : 0.85} radius={i === series.length - 1 ? [2, 2, 0, 0] : 0} isAnimationActive={!reduced} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </figure>
  );
}

/** Fill a daily series for the last `days` days so gaps render as zero rather than disappearing. */
export function dailyPivot(rows: { day: string; count: number; [k: string]: any }[], key: string, days = 14): Record<string, any>[] {
  const out: Record<string, Record<string, any>> = {};
  const today = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - i));
    const k = d.toISOString().slice(0, 10);
    out[k] = { day: k };
  }
  for (const r of rows) {
    const k = r.day.slice(0, 10);
    if (!out[k]) continue;
    out[k][r[key]] = (out[k][r[key]] ?? 0) + r.count;
  }
  return Object.values(out);
}
