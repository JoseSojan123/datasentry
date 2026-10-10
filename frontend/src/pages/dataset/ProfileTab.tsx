import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { DistributionChart, histogramRows } from "@/components/charts/DistributionChart";
import { Badge } from "@/components/ui/Badge";
import { EmptyState, ErrorState, KV, LoadingBlock, Meter, Panel } from "@/components/ui/primitives";
import { cn } from "@/lib/cn";
import { get } from "@/lib/api";
import { fmtDate, fmtInt, fmtNum, fmtPct, fmtSeconds } from "@/lib/format";
import type { Dataset, Profile, Version } from "@/lib/types";

const TYPE_TONE: Record<string, "info" | "accent" | "ok" | "warn" | "neutral"> = { numeric: "info", categorical: "accent", datetime: "ok", boolean: "warn", text: "neutral" };

function ColumnDetail({ c }: { c: Record<string, any> }) {
  const t = c.semantic_type;
  const kv: [string, React.ReactNode][] = [
    ["Missing", `${fmtInt(c.missing_count)} (${fmtPct(c.missing_pct)})`],
    ["Distinct", fmtInt(c.distinct_count)],
  ];
  if (t === "numeric") {
    kv.push(["Mean", fmtNum(c.mean)], ["Std dev", fmtNum(c.std)], ["Min / max", `${fmtNum(c.min)} / ${fmtNum(c.max)}`], ["Median (Q1–Q3)", `${fmtNum(c.median)} (${fmtNum(c.q1)}–${fmtNum(c.q3)})`], ["P5 / P95", `${fmtNum(c.p05)} / ${fmtNum(c.p95)}`], ["Skewness", fmtNum(c.skewness, 2)], ["Zeros / negatives", `${fmtInt(c.zero_count)} / ${fmtInt(c.negative_count)}`], ["Outliers", c.outlier_fences ? `${fmtInt(c.outlier_count)} (${fmtPct(c.outlier_pct)}) outside [${fmtNum(c.outlier_fences[0])}, ${fmtNum(c.outlier_fences[1])}], Tukey k=1.5` : "—"]);
  } else if (t === "datetime") {
    kv.push(["Earliest", fmtDate(c.min)], ["Latest", fmtDate(c.max)], ["Coverage", `${fmtNum(c.coverage_days, 2)} days`], ["Typical interval", fmtSeconds(c.expected_interval_seconds)], ["Gaps", `${fmtInt(c.gap_count)} longer than ${c.gap_factor ?? 1.5}× the typical interval${c.largest_gap_seconds ? `; largest ${fmtSeconds(c.largest_gap_seconds)}` : ""}`], ["Duplicate timestamps", fmtInt(c.duplicate_timestamps)]);
  } else if (t === "text") {
    kv.push(["Length min / mean / max", `${fmtInt(c.min_length)} / ${fmtNum(c.mean_length, 1)} / ${fmtInt(c.max_length)}`], ["Empty strings", fmtInt(c.empty_string_count)]);
  } else if (t === "categorical" || t === "boolean") {
    kv.push(["Rare categories (<1%)", fmtInt(c.rare_category_count)]);
    if (c.unexpected_category_count) kv.push(["Unexpected categories", <span key="u" className="text-warn">{(c.unexpected_categories ?? []).join(", ")}</span>]);
  }
  if (c.is_constant) kv.push(["Constant", <span key="k" className="text-warn">every non-null value is identical</span>]);

  const hist = c.histogram;
  const byDay = c.by_day ? Object.entries(c.by_day as Record<string, number>) : [];
  return (
    <div className="space-y-5">
      <KV items={kv} />
      {hist?.edges && hist?.counts && (
        <div>
          <div className="label mb-2">Distribution</div>
          <DistributionChart ariaLabel={`Histogram of ${c.name}`} rows={histogramRows(hist.edges, hist.counts, hist.counts)} height={180} single />
        </div>
      )}
      {byDay.length > 1 && (
        <div>
          <div className="label mb-2">Rows per day</div>
          <DistributionChart ariaLabel={`Rows per day in ${c.name}`} rows={byDay.map(([d, n]) => ({ label: d.slice(5), reference: n, current: n }))} height={160} single />
        </div>
      )}
      {c.top_values?.length > 0 && (
        <div>
          <div className="label mb-2">Most common values</div>
          <ul className="space-y-1.5">
            {c.top_values.slice(0, 10).map((tv: any, i: number) => (
              <li key={i} className="grid grid-cols-[minmax(0,1fr)_120px_64px] items-center gap-3 text-sm">
                <span className="truncate font-mono text-fg" title={String(tv.value)}>
                  {tv.value === null ? <span className="text-faint">null</span> : String(tv.value)}
                </span>
                <Meter value={tv.frequency} label={`${tv.value} share`} />
                <span className="text-right font-mono text-muted">{fmtPct(tv.frequency * 100)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function ProfileTab({ ds }: { ds: Dataset }) {
  const v = ds.current_version;
  const version = useQuery({ queryKey: ["version", v?.id], queryFn: () => get<Version>(`/versions/${v!.id}`), enabled: !!v });
  const profile = useQuery({ queryKey: ["profile", v?.id], queryFn: () => get<Profile>(`/versions/${v!.id}/profile`), enabled: !!v && v.ingestion_status === "succeeded" });
  const columns = useMemo(() => version.data?.columns ?? [], [version.data]);
  const [sel, setSel] = useState<string | null>(null);
  const selected = sel ?? columns[0]?.name ?? null;

  if (!v) return <EmptyState title="No versions to profile" />;
  if (v.ingestion_status !== "succeeded") return <EmptyState title="This version failed ingestion">There is no profile because the file could not be parsed.</EmptyState>;
  if (profile.isError) return <ErrorState error={profile.error} retry={() => profile.refetch()} />;
  if (!profile.data || !version.data) return <LoadingBlock rows={8} />;
  const cols = profile.data.columns;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(260px,360px)_1fr]">
      <Panel title="Columns" description={`${columns.length} columns · profiled in ${fmtNum(profile.data.duration_ms, 0)} ms`} bodyClassName="p-0">
        <ul role="listbox" aria-label="Columns" className="max-h-[560px] divide-y divide-line overflow-y-auto">
          {columns.map((c) => {
            const p = cols[c.name] ?? {};
            const active = c.name === selected;
            return (
              <li key={c.name} role="option" aria-selected={active}>
                <button onClick={() => setSel(c.name)} className={cn("flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors", active ? "bg-overlay" : "hover:bg-raised")}>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-mono text-sm text-fg">{c.name}</span>
                    <span className="mt-0.5 flex items-center gap-2 text-xs text-faint">
                      <Badge tone={TYPE_TONE[c.semantic_type]} className="h-4 px-1 text-2xs">
                        {c.semantic_type}
                      </Badge>
                      {fmtInt(p.distinct_count)} distinct
                    </span>
                  </span>
                  <span className={cn("font-mono text-xs", p.missing_pct > 5 ? "text-warn" : "text-faint")} title="missing">
                    {fmtPct(p.missing_pct)}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </Panel>
      {selected && cols[selected] && (
        <Panel title={<span className="font-mono">{selected}</span>} description={`${cols[selected].semantic_type} · ${columns.find((c) => c.name === selected)?.physical_type}`}>
          <ColumnDetail c={cols[selected]} />
        </Panel>
      )}
    </div>
  );
}
