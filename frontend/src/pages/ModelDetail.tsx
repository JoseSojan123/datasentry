import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Play } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";
import { axisProps, useChartColors } from "@/components/charts/colors";
import { TooltipBox } from "@/components/charts/ChartTooltip";
import { DistributionChart } from "@/components/charts/DistributionChart";
import { ModelTimeline } from "@/components/charts/ModelTimeline";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge, StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Callout, EmptyState, ErrorState, KV, LoadingBlock, Panel, Select, Stat, Tabs } from "@/components/ui/primitives";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/Table";
import { ApiError, get, post, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { fmtDate, fmtDay, fmtFrac, fmtInt, fmtNum, humanize } from "@/lib/format";
import { useMotion } from "@/lib/motion";
import type { MLModel, ModelEvaluation, Paged } from "@/lib/types";

interface SeriesRow {
  day: string;
  predictions: number;
  labelled: number;
  label_coverage: number;
  mean_score: number | null;
}

function VolumeChart({ rows }: { rows: SeriesRow[] }) {
  const c = useChartColors();
  const { reduced } = useMotion();
  return (
    <figure aria-label="Daily predictions and label coverage" style={{ height: 200 }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 6, right: 4, bottom: 0, left: -18 }}>
          <CartesianGrid vertical={false} stroke={c.border} strokeDasharray="2 4" />
          <XAxis dataKey="day" {...axisProps(c)} tickFormatter={(d: string) => fmtDay(d)} minTickGap={18} />
          <YAxis yAxisId="n" {...axisProps(c)} width={44} />
          <YAxis yAxisId="p" orientation="right" {...axisProps(c)} domain={[0, 1]} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} width={40} />
          <Bar yAxisId="n" dataKey="predictions" fill={c.ref} fillOpacity={0.45} radius={[2, 2, 0, 0]} isAnimationActive={!reduced} />
          <Bar yAxisId="n" dataKey="labelled" fill={c.info} fillOpacity={0.8} radius={[2, 2, 0, 0]} isAnimationActive={!reduced} />
          <Line yAxisId="p" dataKey="label_coverage" stroke={c.accent} strokeWidth={1.8} dot={false} isAnimationActive={!reduced} />
          <Tooltip
            cursor={{ fill: c.overlay, opacity: 0.5 }}
            content={({ active, payload }) =>
              active && payload?.length ? (
                <TooltipBox
                  title={fmtDay(payload[0].payload.day)}
                  rows={[
                    { label: "Predictions", value: fmtInt(payload[0].payload.predictions), color: c.ref },
                    { label: "With labels", value: fmtInt(payload[0].payload.labelled), color: c.info },
                    { label: "Coverage", value: fmtFrac(payload[0].payload.label_coverage), color: c.accent },
                    { label: "Mean score", value: fmtNum(payload[0].payload.mean_score, 3) },
                  ]}
                />
              ) : null
            }
          />
        </ComposedChart>
      </ResponsiveContainer>
    </figure>
  );
}

function WindowDetail({ e }: { e: ModelEvaluation }) {
  const feats: any[] = e.input_drift?.features ?? [];
  const [sel, setSel] = useState<string | null>(null);
  const sorted = [...feats].sort((a, b) => (a.status === "drift" ? 0 : 1) - (b.status === "drift" ? 0 : 1) || (b.psi ?? 0) - (a.psi ?? 0));
  const f = sorted.find((x) => x.feature === sel) ?? sorted[0];
  const perf = e.performance ?? {};
  const pd = e.prediction_drift ?? {};
  const cm: number[][] | undefined = e.metrics?.confusion_matrix;
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Panel title="Performance" description={`${fmtInt(e.n_labelled)} of ${fmtInt(e.n_predictions)} predictions labelled (${fmtFrac(e.label_coverage)})`} actions={<StatusBadge status={perf.status ?? "unknown"} />}>
        <p className="text-sm text-muted">{perf.explanation ?? perf.note ?? e.metrics?.note ?? "No labelled predictions in this window."}</p>
        {e.metrics && e.metrics.status !== "no_labels" && (
          <KV
            className="mt-4"
            items={Object.entries(e.metrics)
              .filter(([k, v]) => typeof v === "number" && !["n_labelled", "n_predictions", "label_coverage"].includes(k))
              .map(([k, v]) => [k.replace(/_/g, " ").toUpperCase(), fmtNum(v as number, 3)])}
          />
        )}
        {cm && e.metrics?.labels && (
          <div className="mt-4">
            <div className="label mb-1.5">Confusion matrix (rows: actual, columns: predicted)</div>
            <table className="font-mono text-sm">
              <thead>
                <tr>
                  <th />
                  {e.metrics.labels.map((l: string) => (
                    <th key={l} className="px-3 py-1 font-normal text-faint">
                      {l}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {cm.map((row, i) => (
                  <tr key={i}>
                    <th className="pr-3 text-right font-normal text-faint">{e.metrics.labels[i]}</th>
                    {row.map((v, j) => (
                      <td key={j} className={cn("border border-line px-3 py-1 text-right", i === j ? "bg-ok/10" : v ? "bg-crit/5" : "")}>
                        {v}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <Panel title="Prediction drift" actions={pd.available === false ? <Badge>unavailable</Badge> : <StatusBadge status={pd.status} />}>
        <p className="text-sm text-muted">{pd.explanation ?? pd.note ?? "Not computed for this window."}</p>
        {pd.evidence?.categories && (
          <div className="mt-4">
            <DistributionChart ariaLabel="Predicted class distribution, reference versus current" rows={pd.evidence.categories.map((c: any) => ({ label: String(c.value), reference: c.reference, current: c.current }))} height={170} />
          </div>
        )}
        {pd.evidence?.histogram && (
          <div className="mt-4">
            <DistributionChart ariaLabel="Prediction distribution, reference versus current" rows={pd.evidence.histogram.reference.map((r: number, i: number) => ({ label: fmtNum(pd.evidence.histogram.edges[i], 2), reference: r, current: pd.evidence.histogram.current[i] }))} height={170} />
          </div>
        )}
      </Panel>
      <Panel title="Input drift" description={e.input_drift?.method} bodyClassName="p-0">
        {!sorted.length ? (
          <EmptyState title="No input features to compare" className="py-8">
            {e.input_drift?.note ?? "Register a reference dataset and an input schema for this version."}
          </EmptyState>
        ) : (
          <>
            <ul className="max-h-56 divide-y divide-line overflow-y-auto">
              {sorted.map((x) => (
                <li key={x.feature}>
                  <button onClick={() => setSel(x.feature)} aria-pressed={x.feature === f?.feature} className={cn("flex w-full items-center gap-2 px-4 py-2 text-left", x.feature === f?.feature ? "bg-overlay" : "hover:bg-raised")}>
                    <span className="min-w-0 flex-1 truncate font-mono text-sm">{x.feature}</span>
                    <span className="font-mono text-xs text-faint">{x.psi !== undefined ? `PSI ${fmtNum(x.psi)}` : ""}</span>
                    <StatusBadge status={x.status} />
                  </button>
                </li>
              ))}
            </ul>
            {f && (
              <div className="border-t border-line p-4">
                <p className="mb-3 text-sm text-muted">{f.explanation}</p>
                {f.bins && f.reference_distribution && (
                  <DistributionChart ariaLabel={`Distribution of ${f.feature}, training reference versus this window`} rows={f.bins.map((b: string, i: number) => ({ label: b, reference: f.reference_distribution[i], current: f.current_distribution[i] }))} height={170} />
                )}
              </div>
            )}
          </>
        )}
      </Panel>
    </div>
  );
}

export default function ModelDetail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const { can } = useAuth();
  const [tab, setTab] = useState<"monitoring" | "evaluations" | "predictions" | "version">("monitoring");
  const [verSel, setVerSel] = useState<string | null>(null);
  const [evalSel, setEvalSel] = useState<number | null>(null);
  const [predPage, setPredPage] = useState(1);
  const model = useQuery({ queryKey: ["model", Number(id)], queryFn: () => get<MLModel>(`/models/${id}`) });
  const version = verSel ?? model.data?.versions[model.data.versions.length - 1]?.version ?? null;
  const mv = model.data?.versions.find((v) => v.version === version);
  const evals = useQuery({ queryKey: ["model-evals", Number(id), version], queryFn: () => get<Paged<ModelEvaluation>>(`/models/${id}/evaluations${qs({ model_version: version, page_size: 60 })}`), enabled: !!version });
  const series = useQuery({ queryKey: ["model-series", Number(id), version], queryFn: () => get<{ items: SeriesRow[] }>(`/models/${id}/series${qs({ model_version: version })}`), enabled: !!version });
  const preds = useQuery({ queryKey: ["model-preds", Number(id), version, predPage], queryFn: () => get<Paged<any>>(`/models/${id}/predictions${qs({ model_version: version, page: predPage, page_size: 25 })}`), enabled: !!version && tab === "predictions", placeholderData: keepPreviousData });
  const evaluate = useMutation({
    mutationFn: () => post<ModelEvaluation>(`/models/${id}/evaluate`, { model_version: version }),
    onSuccess: (e) => {
      toast.success(`Evaluated ${fmtInt(e.n_predictions)} predictions (${fmtFrac(e.label_coverage)} labelled).`);
      void qc.invalidateQueries({ queryKey: ["model-evals", Number(id)] });
      void qc.invalidateQueries({ queryKey: ["model", Number(id)] });
      setEvalSel(e.id);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Evaluation failed."),
  });

  if (model.isError) return <Panel><ErrorState error={model.error} retry={() => model.refetch()} /></Panel>;
  if (!model.data) return <LoadingBlock rows={8} />;
  const m = model.data;
  const list = evals.data?.items ?? [];
  const current = list.find((e) => e.id === evalSel) ?? list[0];
  const metric = m.task === "classification" ? "f1" : "rmse";
  const baseline = typeof mv?.baseline_metrics?.[metric] === "number" ? (mv.baseline_metrics[metric] as number) : null;

  return (
    <>
      <PageHeader
        title={m.name}
        crumbs={[{ label: "Models", to: "/models" }, { label: m.name }]}
        description={m.description ?? undefined}
        meta={
          <>
            <Badge>{m.task}</Badge>
            <Badge tone={m.criticality === "critical" ? "crit" : m.criticality === "high" ? "warn" : "neutral"}>{m.criticality} criticality</Badge>
            {m.open_incidents > 0 && (
              <Link to={`/incidents?model_id=${m.id}`}>
                <Badge tone="crit">{m.open_incidents} open incident(s)</Badge>
              </Link>
            )}
            {m.target && <span className="text-sm text-faint">target: {m.target}</span>}
          </>
        }
        actions={
          <>
            {m.versions.length > 1 && (
              <Select aria-label="Model version" value={version ?? ""} onChange={(e) => setVerSel(e.target.value)} className="w-36">
                {m.versions.map((v) => (
                  <option key={v.id} value={v.version}>
                    v{v.version}
                  </option>
                ))}
              </Select>
            )}
            {can("editor") && mv && (
              <Button variant="primary" icon={<Play className="h-4 w-4" />} loading={evaluate.isPending} onClick={() => evaluate.mutate()}>
                Evaluate latest 24 h
              </Button>
            )}
          </>
        }
      />
      {!mv ? (
        <Panel>
          <EmptyState title="No versions yet">Register a version with its input schema and baseline metrics using the SDK; predictions and labels are logged against a version.</EmptyState>
        </Panel>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
            <div className="panel p-4"><Stat label="Predictions logged" value={fmtInt(m.prediction_count)} /></div>
            <div className="panel p-4"><Stat label={`Baseline ${metric.toUpperCase()}`} value={baseline !== null ? fmtNum(baseline, 3) : "—"} hint={mv.baseline_metrics?.evaluated_on} /></div>
            <div className="panel p-4"><Stat label="Latest window" value={current ? <StatusBadge status={current.status} className="text-sm" /> : "—"} hint={current ? `performance ${humanize(current.performance?.status ?? "unknown")}` : undefined} /></div>
            <div className="panel p-4"><Stat label="Feature logging" value={<span className="flex items-center gap-1.5 text-xl"><Lock className="h-4 w-4 text-faint" />{mv.feature_logging}</span>} hint={`retained ${mv.retention_days} days`} /></div>
          </div>
          <Tabs
            className="mb-4"
            value={tab}
            onChange={setTab}
            tabs={[
              { id: "monitoring", label: "Monitoring" },
              { id: "evaluations", label: "Evaluations", count: evals.data?.total },
              { id: "predictions", label: "Predictions" },
              { id: "version", label: "Version" },
            ]}
          />
          {tab === "monitoring" && (
            <div className="space-y-4">
              <Panel title={`${metric.toUpperCase()} by evaluation window`} description="Degradation is flagged only when the whole 95% bootstrap interval is worse than the baseline by more than the tolerance. Otherwise a drop is reported as inconclusive.">
                {evals.isLoading ? <LoadingBlock rows={4} /> : list.length === 0 ? <EmptyState title="No evaluations yet">Run an evaluation, or schedule a model evaluation job.</EmptyState> : <ModelTimeline evaluations={list} metric={metric} baseline={baseline} />}
              </Panel>
              {current && (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="label">Window</span>
                    <Select aria-label="Evaluation window" value={current.id} onChange={(e) => setEvalSel(Number(e.target.value))} className="w-auto min-w-[220px]">
                      {list.map((e) => (
                        <option key={e.id} value={e.id}>
                          {fmtDay(e.window_start)} – {fmtDay(e.window_end)} · {e.status}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <WindowDetail e={current} />
                </>
              )}
              <Panel title="Prediction volume and label arrival" description="Labels for recent days are often still missing; that is expected, not a failure.">
                {series.data?.items.length ? <VolumeChart rows={series.data.items} /> : <LoadingBlock rows={3} />}
              </Panel>
            </div>
          )}
          {tab === "evaluations" && (
            <Panel bodyClassName="p-0">
              <Table label="Evaluations">
                <thead>
                  <tr>
                    <Th>Window</Th>
                    <Th>Status</Th>
                    <Th>Performance</Th>
                    <Th align="right">{metric.toUpperCase()}</Th>
                    <Th align="right">Labels</Th>
                    <Th align="right">Input drift</Th>
                    <Th>Prediction drift</Th>
                    <Th>Trigger</Th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((e) => (
                    <Tr
                      key={e.id}
                      onClick={() => {
                        setEvalSel(e.id);
                        setTab("monitoring");
                      }}
                    >
                      <Td className="whitespace-nowrap text-sm">
                        {fmtDay(e.window_start)} – {fmtDay(e.window_end)}
                      </Td>
                      <Td>
                        <StatusBadge status={e.status} />
                      </Td>
                      <Td>
                        <StatusBadge status={e.performance?.status ?? "unknown"} />
                      </Td>
                      <Td align="right" mono>
                        {fmtNum(e.metrics?.[metric], 3)}
                      </Td>
                      <Td align="right" mono>
                        {fmtFrac(e.label_coverage)}
                      </Td>
                      <Td align="right" mono>
                        {e.input_drift?.features_drifted ?? 0}
                      </Td>
                      <Td>{e.prediction_drift?.status ? <StatusBadge status={e.prediction_drift.status} /> : "—"}</Td>
                      <Td className="text-sm text-muted">{e.trigger}</Td>
                    </Tr>
                  ))}
                </tbody>
              </Table>
            </Panel>
          )}
          {tab === "predictions" && (
            <Panel bodyClassName="p-0" title="Recent predictions" description={mv.feature_logging === "full" ? "Feature values are stored because this version uses full logging." : `Feature values are not stored for this version (logging: ${mv.feature_logging}). Only identifiers, outputs and labels are shown.`}>
              {!preds.data ? (
                <div className="p-4">
                  <LoadingBlock />
                </div>
              ) : (
                <>
                  <Table label="Predictions">
                    <thead>
                      <tr>
                        <Th>Record</Th>
                        <Th>Predicted at</Th>
                        <Th align="right">Prediction</Th>
                        <Th align="right">Score</Th>
                        <Th align="right">Label</Th>
                        {mv.feature_logging === "full" && <Th>Features</Th>}
                      </tr>
                    </thead>
                    <tbody>
                      {preds.data.items.map((p: any) => (
                        <Tr key={p.record_id}>
                          <Td mono>{p.record_id}</Td>
                          <Td className="whitespace-nowrap text-sm text-muted">{fmtDate(p.predicted_at)}</Td>
                          <Td align="right" mono>
                            {p.prediction}
                          </Td>
                          <Td align="right" mono>
                            {fmtNum(p.score, 3)}
                          </Td>
                          <Td align="right" mono className={p.label === null ? "text-faint" : p.label === p.prediction ? "text-ok" : "text-crit"}>
                            {p.label ?? "pending"}
                          </Td>
                          {mv.feature_logging === "full" && <Td className="max-w-[320px] truncate font-mono text-xs text-muted">{p.features ? JSON.stringify(p.features) : "—"}</Td>}
                        </Tr>
                      ))}
                    </tbody>
                  </Table>
                  <div className="border-t border-line">
                    <Pagination page={preds.data.page} pages={preds.data.pages} total={preds.data.total} onPage={setPredPage} />
                  </div>
                </>
              )}
            </Panel>
          )}
          {tab === "version" && (
            <div className="grid gap-4 lg:grid-cols-2">
              <Panel title={`Version ${mv.version}`}>
                <KV
                  items={[
                    ["Registered", fmtDate(mv.created_at)],
                    ["Feature logging", mv.feature_logging],
                    ["Retention", `${mv.retention_days} days`],
                    ["Reference", mv.reference_source ? <Link key="r" to={`/datasets/${mv.reference_source.dataset_id}`} className="link">dataset {mv.reference_source.dataset_id}, v{mv.reference_source.version}</Link> : "none"],
                    ...Object.entries(mv.baseline_metrics).map(([k, v]) => [`Baseline ${humanize(k)}`, typeof v === "number" ? fmtNum(v, 4) : String(v)] as [string, string]),
                    ...Object.entries(mv.artifact).map(([k, v]) => [humanize(k), String(v)] as [string, string]),
                  ]}
                />
              </Panel>
              <Panel title="Input schema" bodyClassName="p-0">
                <Table label="Input schema">
                  <thead>
                    <tr>
                      <Th>Feature</Th>
                      <Th>Type</Th>
                      <Th>Reference profile</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {mv.input_schema.map((f) => (
                      <Tr key={f.name}>
                        <Td mono>{f.name}</Td>
                        <Td className="text-sm text-muted">{f.type}</Td>
                        <Td>{mv.reference_features.includes(f.name) ? <Badge tone="ok">available</Badge> : <Badge tone="warn">missing</Badge>}</Td>
                      </Tr>
                    ))}
                  </tbody>
                </Table>
              </Panel>
              <Callout tone="neutral" className="lg:col-span-2">
                With aggregate logging, DataSentry stores per-window histograms on the reference bins instead of raw feature values, so input drift can be measured without keeping individual records. Raw records older than the retention period are purged by the maintenance job.
              </Callout>
            </div>
          )}
          {current && current.schema_violation_count > 0 && (
            <Callout tone="warn" className="mt-4">
              {fmtInt(current.schema_violation_count)} prediction(s) in this window did not match the input schema.
            </Callout>
          )}
        </>
      )}
    </>
  );
}
