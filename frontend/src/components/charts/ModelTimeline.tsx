import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import { fmtDay, fmtFrac, fmtNum, humanize } from "@/lib/format";
import { useMotion } from "@/lib/motion";
import type { ModelEvaluation } from "@/lib/types";
import { axisProps, useChartColors } from "./colors";
import { TooltipBox } from "./ChartTooltip";

/**
 * Performance with its bootstrap interval, the baseline, and when input / prediction drift was detected.
 * Keeping these on one time axis is what lets a reader see that drift and degradation are different signals.
 */
export function ModelTimeline({ evaluations, metric, baseline, height = 260 }: { evaluations: ModelEvaluation[]; metric: string; baseline: number | null; height?: number }) {
  const c = useChartColors();
  const { reduced } = useMotion();
  const rows = [...evaluations]
    .sort((a, b) => (a.window_end ?? a.created_at).localeCompare(b.window_end ?? b.created_at))
    .map((e) => {
      const v = e.metrics?.[metric];
      const ci = e.metrics?.[`${metric}_ci95`] as [number, number] | null | undefined;
      const inputDrifted = (e.input_drift?.features ?? []).filter((f: any) => f.status === "drift").length;
      const predDrift = e.prediction_drift?.status === "drift";
      return {
        day: e.window_start ?? e.created_at,
        value: typeof v === "number" ? v : null,
        band: ci ? [ci[0], ci[1]] : null,
        inputDrifted,
        predDrift,
        driftMarker: inputDrifted > 0 || predDrift ? 1.02 : null,
        perf: e.performance?.status as string | undefined,
        coverage: e.label_coverage,
        n: e.n_labelled,
      };
    });
  return (
    <figure aria-label={`${metric} over time with 95% bootstrap interval and drift markers`}>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 10, right: 8, bottom: 0, left: -16 }}>
            <CartesianGrid vertical={false} stroke={c.border} strokeDasharray="2 4" />
            <XAxis dataKey="day" {...axisProps(c)} tickFormatter={(d: string) => fmtDay(d)} minTickGap={20} />
            <YAxis {...axisProps(c)} domain={[0, 1.05]} ticks={[0, 0.25, 0.5, 0.75, 1]} width={44} />
            {baseline !== null && <ReferenceLine y={baseline} stroke={c.ref} strokeDasharray="5 4" label={{ value: "baseline", position: "insideTopLeft", fill: c.faint, fontSize: 10 }} />}
            <Area dataKey="band" stroke="none" fill={c.accent} fillOpacity={0.14} isAnimationActive={!reduced} connectNulls={false} />
            <Line dataKey="value" stroke={c.accent} strokeWidth={2} dot={{ r: 2.5, fill: c.accent, strokeWidth: 0 }} activeDot={{ r: 4 }} isAnimationActive={!reduced} connectNulls={false} />
            <Scatter dataKey="driftMarker" fill={c.warn} shape="triangle" isAnimationActive={false} />
            <Tooltip
              cursor={{ stroke: c["border-strong"] }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const r = payload[0].payload;
                return (
                  <TooltipBox
                    title={fmtDay(r.day)}
                    rows={[
                      { label: metric.toUpperCase(), value: r.value === null ? "no labels" : fmtNum(r.value, 3), color: c.accent },
                      ...(r.band ? [{ label: "95% CI", value: `${fmtNum(r.band[0], 3)}–${fmtNum(r.band[1], 3)}` }] : []),
                      { label: "Performance", value: humanize(r.perf ?? "unknown") },
                      { label: "Labels", value: `${r.n} (${fmtFrac(r.coverage)})` },
                      { label: "Input drift", value: r.inputDrifted ? `${r.inputDrifted} feature(s)` : "none", color: r.inputDrifted ? c.warn : undefined },
                      { label: "Prediction drift", value: r.predDrift ? "yes" : "no", color: r.predDrift ? c.warn : undefined },
                    ]}
                  />
                );
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        <span className="flex items-center gap-1.5">
          <span className="h-0.5 w-3 rounded" style={{ background: c.accent }} /> {metric.toUpperCase()}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-3 rounded-sm" style={{ background: c.accent, opacity: 0.2 }} /> 95% bootstrap interval
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-0 w-3 border-t border-dashed" style={{ borderColor: c.ref }} /> Baseline
        </span>
        <span className="flex items-center gap-1.5">
          <span style={{ color: c.warn }}>▲</span> Drift detected that day
        </span>
      </figcaption>
    </figure>
  );
}
