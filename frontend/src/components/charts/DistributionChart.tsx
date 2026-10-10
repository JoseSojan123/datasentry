import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtNum } from "@/lib/format";
import { useMotion } from "@/lib/motion";
import { axisProps, useChartColors } from "./colors";
import { TooltipBox } from "./ChartTooltip";

export interface DistRow {
  label: string;
  reference: number;
  current: number;
}

/** Reference vs current distribution as share of rows (counts normalised so different sample sizes compare fairly). */
export function DistributionChart({ rows, height = 220, ariaLabel, single }: { rows: DistRow[]; height?: number; ariaLabel: string; single?: boolean }) {
  const c = useChartColors();
  const { reduced } = useMotion();
  const refTotal = rows.reduce((s, r) => s + r.reference, 0) || 1;
  const curTotal = rows.reduce((s, r) => s + r.current, 0) || 1;
  const data = rows.map((r) => ({ ...r, refPct: (r.reference / refTotal) * 100, curPct: (r.current / curTotal) * 100 }));
  return (
    <figure aria-label={ariaLabel} className="w-full">
      <div style={{ height }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} barGap={1} barCategoryGap="14%" margin={{ top: 6, right: 6, bottom: 0, left: -18 }}>
            <CartesianGrid vertical={false} stroke={c.border} strokeDasharray="2 4" />
            <XAxis dataKey="label" {...axisProps(c)} interval="preserveStartEnd" minTickGap={18} />
            <YAxis {...axisProps(c)} tickFormatter={(v: number) => `${v.toFixed(0)}%`} width={48} />
            <Tooltip
              cursor={{ fill: c.overlay, opacity: 0.5 }}
              content={({ active, payload }) =>
                active && payload?.length ? (
                  <TooltipBox
                    title={payload[0].payload.label}
                    rows={single ? [{ label: "Rows", value: `${payload[0].payload.current} (${fmtNum(payload[0].payload.curPct, 2)}%)`, color: c.accent }] : [
                      { label: "Reference", value: `${fmtNum(payload[0].payload.refPct, 2)}% (${payload[0].payload.reference})`, color: c.ref },
                      { label: "Current", value: `${fmtNum(payload[0].payload.curPct, 2)}% (${payload[0].payload.current})`, color: c.accent },
                    ]}
                  />
                ) : null
              }
            />
            {!single && <Bar dataKey="refPct" name="Reference" fill={c.ref} fillOpacity={0.45} radius={[2, 2, 0, 0]} isAnimationActive={!reduced} animationDuration={500} />}
            <Bar dataKey="curPct" name="Current" fill={c.accent} radius={[2, 2, 0, 0]} isAnimationActive={!reduced} animationDuration={600} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      {!single && <figcaption className="mt-2 flex items-center gap-4 text-xs text-muted">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm" style={{ background: c.ref, opacity: 0.6 }} /> Reference
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm" style={{ background: c.accent }} /> Current
        </span>
        <span className="ml-auto text-faint">share of rows</span>
      </figcaption>}
    </figure>
  );
}

/** Build rows from a shared-edge histogram. */
export function histogramRows(edges: number[], reference: number[], current: number[]): DistRow[] {
  return reference.map((r, i) => ({ label: fmtNum(edges[i], 2), reference: r, current: current[i] ?? 0 }));
}
