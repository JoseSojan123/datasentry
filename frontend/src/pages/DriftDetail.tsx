import { useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";
import { DistributionChart, histogramRows } from "@/components/charts/DistributionChart";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge, SeverityBadge, StatusBadge } from "@/components/ui/Badge";
import { Callout, EmptyState, ErrorState, KV, LoadingBlock, Panel, Stat } from "@/components/ui/primitives";
import { Table, Td, Th, Tr } from "@/components/ui/Table";
import { get } from "@/lib/api";
import { cn } from "@/lib/cn";
import { fmtDate, fmtDuration, fmtFrac, fmtInt, fmtNum, fmtP, humanize } from "@/lib/format";
import type { DriftEvaluation, DriftFeature } from "@/lib/types";

const effect = (f: DriftFeature) => (f.semantic_type === "numeric" ? { name: "PSI", v: f.statistics.psi } : { name: "JS", v: f.statistics.js_distance });
const STATUS_ORDER: Record<string, number> = { drift: 0, inconclusive: 1, no_drift: 2, insufficient_data: 3, skipped: 4 };

function FeatureEvidence({ f, cfg }: { f: DriftFeature; cfg: Record<string, any> }) {
  const st = f.statistics;
  const isNum = f.semantic_type === "numeric";
  const rows = isNum
    ? f.evidence?.histogram
      ? histogramRows(f.evidence.histogram.edges, f.evidence.histogram.reference, f.evidence.histogram.current)
      : []
    : (f.evidence?.categories ?? []).map((c: any) => ({ label: String(c.value), reference: c.reference, current: c.current }));
  const kv: [string, React.ReactNode][] = isNum
    ? [
        ["PSI", `${fmtNum(st.psi)} (warn ≥ ${cfg.psi_warning}, crit ≥ ${cfg.psi_critical})`],
        ["KS statistic", fmtNum(st.ks_statistic)],
        ["p (raw / adjusted)", `${fmtP(st.ks_p_value)} / ${fmtP(st.p_value_adjusted)}`],
        ["Mean ref → cur", `${fmtNum(st.mean_reference)} → ${fmtNum(st.mean_current)}`],
        ["Median ref → cur", `${fmtNum(st.median_reference)} → ${fmtNum(st.median_current)}`],
        ["Std dev ref → cur", `${fmtNum(st.std_reference)} → ${fmtNum(st.std_current)}`],
        ["Standardized mean difference", fmtNum(st.standardized_mean_difference)],
        ["Samples ref / cur", `${fmtInt(f.n_reference)} / ${fmtInt(f.n_current)}`],
      ]
    : [
        ["JS distance", `${fmtNum(st.js_distance)} (warn ≥ ${cfg.js_warning}, crit ≥ ${cfg.js_critical})`],
        ["PSI (for reference)", fmtNum(st.psi)],
        ["Chi-square", st.chi2_valid === false ? <span className="text-warn">not valid: {st.chi2_note}</span> : `${fmtNum(st.chi2, 2)} on ${st.chi2_dof} df`],
        ["p (raw / adjusted)", `${fmtP(st.chi2_p_value)} / ${fmtP(st.p_value_adjusted)}`],
        ["Categories ref → cur", `${st.categories_reference} → ${st.categories_current}`],
        ["New categories", st.new_categories?.length ? <span className="font-mono text-warn">{st.new_categories.join(", ")} ({fmtFrac(st.new_category_share, 1)} of rows)</span> : "none"],
        ["Missing categories", st.missing_categories?.length ? <span className="font-mono">{st.missing_categories.join(", ")}</span> : "none"],
        ["Samples ref / cur", `${fmtInt(f.n_reference)} / ${fmtInt(f.n_current)}`],
      ];
  return (
    <div className="space-y-5">
      <Callout tone={f.status === "drift" ? (f.severity === "critical" ? "crit" : "warn") : f.status === "inconclusive" ? "warn" : "neutral"}>
        <span className="text-fg">{f.explanation}</span>
      </Callout>
      {rows.length > 0 ? <DistributionChart ariaLabel={`Reference and current distribution of ${f.feature}`} rows={rows} height={240} /> : <EmptyState title="No distribution evidence stored" className="py-6" />}
      <KV items={kv} />
      <p className="text-xs text-faint">
        Method: {f.method === "psi+ks" ? "Population Stability Index on reference quantile bins with +0.5 smoothing, and the two-sample Kolmogorov–Smirnov test" : "Jensen–Shannon distance (base 2) and the chi-square test of homogeneity, with sparse categories pooled"}. p-values corrected with {humanize(st.correction ?? cfg.correction)}.
      </p>
    </div>
  );
}

export default function DriftDetail() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const q = useQuery({ queryKey: ["drift", Number(id)], queryFn: () => get<DriftEvaluation>(`/drift/${id}`) });
  if (q.isError) return <Panel><ErrorState error={q.error} retry={() => q.refetch()} /></Panel>;
  if (!q.data) return <LoadingBlock rows={8} />;
  const e = q.data;
  const features = [...(e.features ?? [])].sort((a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9) || (effect(b).v ?? 0) - (effect(a).v ?? 0));
  const selName = params.get("feature") ?? features[0]?.feature;
  const sel = features.find((f) => f.feature === selName) ?? features[0];
  const s = e.summary;

  return (
    <>
      <PageHeader
        title={`Drift · ${e.dataset_name ?? `dataset ${e.dataset_id}`}`}
        crumbs={[{ label: "Drift", to: "/drift" }, { label: `#${e.id}` }]}
        meta={
          <>
            <SeverityBadge severity={e.overall_severity} />
            <span className="text-sm text-faint">
              version #{e.reference_version_id} → #{e.current_version_id} · {fmtDate(e.created_at)} · {e.trigger}
            </span>
          </>
        }
      />
      <div className="mb-4 grid grid-cols-2 gap-4 md:grid-cols-5">
        <div className="panel p-4"><Stat label="Drifted" value={`${s.features_drifted}/${s.features_evaluated}`} tone={s.features_drifted ? "crit" : "ok"} /></div>
        <div className="panel p-4"><Stat label="Inconclusive" value={s.features_inconclusive} tone={s.features_inconclusive ? "warn" : undefined} /></div>
        <div className="panel p-4"><Stat label="Insufficient data" value={s.features_insufficient} /></div>
        <div className="panel p-4"><Stat label="Rows ref / cur" value={<span className="text-xl">{fmtInt(s.n_reference)} / {fmtInt(s.n_current)}</span>} /></div>
        <div className="panel col-span-2 p-4 md:col-span-1"><Stat label="Computed in" value={<span className="text-xl">{fmtDuration(s.duration_ms)}</span>} /></div>
      </div>
      {e.other_findings.length > 0 && (
        <Panel title="Other distribution findings" className="mb-4" bodyClassName="p-0">
          <ul className="divide-y divide-line">
            {e.other_findings.map((o, i) => (
              <li key={i} className="flex flex-wrap items-start gap-3 px-4 py-3">
                <SeverityBadge severity={o.severity} />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">
                    {humanize(o.kind)} <code className="ml-1 rounded-sm bg-overlay px-1 font-mono text-xs text-muted">{o.feature}</code>
                  </div>
                  <p className="mt-0.5 text-sm text-muted">{o.explanation}</p>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      )}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <Panel title="Features" bodyClassName="p-0">
          <Table label="Per-feature drift results">
            <thead>
              <tr>
                <Th>Feature</Th>
                <Th>Status</Th>
                <Th align="right">Effect</Th>
                <Th align="right">p adj.</Th>
              </tr>
            </thead>
            <tbody>
              {features.map((f) => {
                const ef = effect(f);
                return (
                  <Tr key={f.id} onClick={() => setParams({ feature: f.feature }, { replace: true })} className={cn(f.feature === sel?.feature && "bg-overlay")}>
                    <Td>
                      <button className="text-left font-mono text-sm text-fg" aria-pressed={f.feature === sel?.feature}>
                        {f.feature}
                      </button>
                      <div className="text-xs text-faint">{f.semantic_type}</div>
                    </Td>
                    <Td>
                      <span className="flex flex-wrap items-center gap-1">
                        <StatusBadge status={f.status} />
                        {f.severity !== "none" && f.status === "drift" && <SeverityBadge severity={f.severity} />}
                      </span>
                    </Td>
                    <Td align="right" mono>
                      {ef.v !== undefined && ef.v !== null ? (
                        <>
                          <span className="text-faint">{ef.name}</span> {fmtNum(ef.v)}
                        </>
                      ) : (
                        "—"
                      )}
                    </Td>
                    <Td align="right" mono className={f.significant ? "text-fg" : "text-faint"}>
                      {fmtP(f.statistics.p_value_adjusted)}
                    </Td>
                  </Tr>
                );
              })}
            </tbody>
          </Table>
        </Panel>
        {sel && (
          <Panel title={<span className="font-mono">{sel.feature}</span>} actions={<Badge>{sel.method}</Badge>}>
            <FeatureEvidence f={sel} cfg={e.config} />
          </Panel>
        )}
      </div>
    </>
  );
}
