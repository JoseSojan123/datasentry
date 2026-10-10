import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ArrowRight, Boxes, Database, FlaskConical, ShieldAlert, Upload, Waves } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { dailyPivot, StackedTrend } from "@/components/charts/TrendChart";
import { PageHeader } from "@/components/layout/PageHeader";
import { HealthIndicator, SeverityBadge, StatusBadge, UrgencyTag } from "@/components/ui/Badge";
import { Button, ButtonLink } from "@/components/ui/Button";
import { EmptyState, ErrorState, LoadingBlock, Meter, Panel, Skeleton, Stat } from "@/components/ui/primitives";
import { ApiError, get, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtFrac, fmtInt, fmtRelative, humanize } from "@/lib/format";
import { useMotion } from "@/lib/motion";
import type { Overview as OverviewT } from "@/lib/types";

function Onboarding() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { can } = useAuth();
  const load = useMutation({
    mutationFn: () => post("/demo/sample-data"),
    onSuccess: () => {
      toast.success("Sample data loaded. Monitoring ran on every version.");
      void qc.invalidateQueries();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not load sample data."),
  });
  return (
    <Panel>
      <EmptyState
        icon={<Database className="h-5 w-5" />}
        title="No datasets yet"
        action={
          can("editor") ? (
            <>
              <Button variant="primary" icon={<Upload className="h-4 w-4" />} onClick={() => navigate("/datasets/new")}>
                Upload a CSV, Parquet or JSON file
              </Button>
              <Button icon={<FlaskConical className="h-4 w-4" />} loading={load.isPending} onClick={() => load.mutate()}>
                Load labelled synthetic sample data
              </Button>
            </>
          ) : undefined
        }
      >
        Upload a file to profile it and start monitoring, or load the synthetic sample: a transactions dataset with injected nulls, unexpected currencies and drift, a lineage graph, and a credit model with delayed labels.
      </EmptyState>
    </Panel>
  );
}

export default function Overview() {
  const q = useQuery({ queryKey: ["overview"], queryFn: () => get<OverviewT>("/overview"), refetchInterval: 30_000 });
  const { fadeUp, stagger } = useMotion();
  const d = q.data;

  return (
    <>
      <PageHeader title="Overview" description="Current state of every monitored dataset and model, computed from stored check, drift and incident records." />
      {q.isError ? (
        <Panel>
          <ErrorState error={q.error} retry={() => q.refetch()} />
        </Panel>
      ) : !d ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      ) : d.datasets.total === 0 && d.models.length === 0 ? (
        <Onboarding />
      ) : (
        <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-4">
          <motion.div variants={fadeUp} className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <div className="panel p-4">
              <Stat label="Datasets" value={fmtInt(d.datasets.total)} />
              <div className="mt-3 flex h-1.5 overflow-hidden rounded-full bg-overlay" aria-hidden>
                {(["healthy", "warning", "failing", "unknown"] as const).map((h) => (
                  <div key={h} className={{ healthy: "bg-ok", warning: "bg-warn", failing: "bg-crit", unknown: "bg-faint/50" }[h]} style={{ width: `${(d.datasets[h] / Math.max(1, d.datasets.total)) * 100}%` }} />
                ))}
              </div>
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
                <span>
                  <span className="text-ok">●</span> {d.datasets.healthy} healthy
                </span>
                <span>
                  <span className="text-warn">●</span> {d.datasets.warning} warning
                </span>
                <span>
                  <span className="text-crit">●</span> {d.datasets.failing} failing
                </span>
              </div>
            </div>
            <Link to="/incidents" className="panel block p-4 transition-colors hover:border-line-strong">
              <Stat label="Open incidents" value={fmtInt(d.incidents.open)} tone={d.incidents.critical ? "crit" : d.incidents.open ? "warn" : "ok"} hint={`${d.incidents.critical} critical · ${d.incidents.warning} warning`} />
            </Link>
            <div className="panel p-4">
              <Stat label="Resolved in 7 days" value={fmtInt(d.incidents.resolved_7d)} hint="verified or closed with a note" />
            </div>
            <Link to="/remediation" className="panel block p-4 transition-colors hover:border-line-strong">
              <Stat label="Remediation" value={fmtInt(d.remediation.proposed ?? 0)} hint={`awaiting a decision · ${d.remediation.verified ?? 0} verified`} />
            </Link>
          </motion.div>

          <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
            <motion.div variants={fadeUp}>
              <Panel
                title="Highest-priority incidents"
                description="Ranked by severity, downstream reach and criticality"
                actions={
                  <ButtonLink to="/incidents" size="sm" variant="ghost">
                    All incidents <ArrowRight className="h-3.5 w-3.5" />
                  </ButtonLink>
                }
                bodyClassName="p-0"
              >
                {d.top_incidents.length === 0 ? (
                  <EmptyState icon={<ShieldAlert className="h-5 w-5" />} title="No open incidents">
                    Every monitored dataset and model passed its latest checks.
                  </EmptyState>
                ) : (
                  <ul className="divide-y divide-line">
                    {d.top_incidents.map((i) => (
                      <li key={i.id}>
                        <Link to={`/incidents/${i.id}`} className="flex flex-col gap-2 px-4 py-3 transition-colors hover:bg-raised sm:flex-row sm:items-center sm:gap-4">
                          <div className="flex items-center gap-2">
                            <UrgencyTag urgency={i.priority.urgency} score={i.priority.score} />
                            <SeverityBadge severity={i.severity} />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-base font-medium text-fg">{i.title}</div>
                            <div className="mt-0.5 text-sm text-muted">
                              {i.findings.length} finding{i.findings.length === 1 ? "" : "s"} · {i.impact.counts.total} downstream ({i.impact.counts.confirmed} confirmed) · {fmtRelative(i.last_seen_at)}
                            </div>
                          </div>
                          <StatusBadge status={i.status} className="self-start sm:self-auto" />
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            </motion.div>

            <motion.div variants={fadeUp}>
              <Panel title="Incidents opened" description="Last 14 days, by severity">
                <StackedTrend
                  ariaLabel="Incidents opened per day by severity"
                  data={dailyPivot(d.incident_trend, "severity")}
                  series={[
                    { key: "critical", label: "Critical", tone: "crit" },
                    { key: "warning", label: "Warning", tone: "warn" },
                    { key: "info", label: "Info", tone: "info" },
                  ]}
                />
                <div className="mt-5">
                  <div className="label mb-2">Rule results, last 14 days</div>
                  <StackedTrend
                    height={120}
                    ariaLabel="Rule results per day"
                    data={dailyPivot(d.check_trend, "status")}
                    series={[
                      { key: "pass", label: "Passed", tone: "ref" },
                      { key: "fail", label: "Failed", tone: "crit" },
                      { key: "error", label: "Errored", tone: "warn" },
                    ]}
                  />
                </div>
              </Panel>
            </motion.div>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <motion.div variants={fadeUp}>
              <Panel title="Recent drift" actions={<ButtonLink to="/drift" size="sm" variant="ghost">View all</ButtonLink>} bodyClassName="p-0">
                {d.recent_drift.length === 0 ? (
                  <EmptyState icon={<Waves className="h-5 w-5" />} title="No drift evaluations yet">
                    Drift runs automatically when a second version is uploaded.
                  </EmptyState>
                ) : (
                  <ul className="divide-y divide-line">
                    {d.recent_drift.map((r) => (
                      <li key={r.id}>
                        <Link to={`/drift/${r.id}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-raised">
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-base text-fg">{r.dataset_name}</div>
                            <div className="text-sm text-muted">
                              {r.features_drifted} feature{r.features_drifted === 1 ? "" : "s"} drifted · {fmtRelative(r.created_at)}
                            </div>
                          </div>
                          <SeverityBadge severity={r.severity} />
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            </motion.div>
            <motion.div variants={fadeUp}>
              <Panel title="Models" actions={<ButtonLink to="/models" size="sm" variant="ghost">Registry</ButtonLink>} bodyClassName="p-0">
                {d.models.length === 0 ? (
                  <EmptyState icon={<Boxes className="h-5 w-5" />} title="No models registered">
                    Register a model with the SDK to monitor predictions, drift and delayed labels.
                  </EmptyState>
                ) : (
                  <ul className="divide-y divide-line">
                    {d.models.map((m) => (
                      <li key={m.model_id}>
                        <Link to={`/models/${m.model_id}`} className="block px-4 py-2.5 hover:bg-raised">
                          <div className="flex items-center gap-2">
                            <span className="min-w-0 flex-1 truncate text-base text-fg">{m.name}</span>
                            <StatusBadge status={m.status} label={m.status === "ok" ? "latest window ok" : undefined} />
                          </div>
                          <div className="mt-1.5 flex items-center gap-3 text-sm text-muted">
                            <span className="w-28 shrink-0">labels {fmtFrac(m.label_coverage)}</span>
                            <Meter value={m.label_coverage ?? 0} tone="info" label="Label coverage" />
                          </div>
                          <div className="mt-1 text-sm text-faint">
                            performance {humanize(m.performance ?? "unknown")} · input drift in {m.input_drift_features ?? 0} feature(s)
                          </div>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            </motion.div>
            <motion.div variants={fadeUp}>
              <Panel title="Recent job failures" actions={<ButtonLink to="/jobs" size="sm" variant="ghost">Jobs</ButtonLink>} bodyClassName="p-0">
                {d.recent_job_failures.length === 0 ? (
                  <EmptyState title="No failed jobs">Scheduled profiling, validation, drift and evaluation jobs have not failed recently.</EmptyState>
                ) : (
                  <ul className="divide-y divide-line">
                    {d.recent_job_failures.map((j) => (
                      <li key={j.id} className="px-4 py-2.5">
                        <div className="flex items-center gap-2">
                          <span className="flex-1 text-base text-fg">{humanize(j.job_type)}</span>
                          <StatusBadge status={j.status} />
                        </div>
                        <div className="mt-0.5 line-clamp-2 text-sm text-muted">{j.error ?? "No error message recorded."}</div>
                        <div className="text-2xs text-faint">{fmtRelative(j.finished_at ?? j.started_at)}</div>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            </motion.div>
          </div>
          <motion.div variants={fadeUp}>
            <DatasetHealthStrip />
          </motion.div>
        </motion.div>
      )}
    </>
  );
}

function DatasetHealthStrip() {
  const q = useQuery({ queryKey: ["datasets", "strip"], queryFn: () => get<{ items: any[] }>("/datasets?page_size=12&sort=health") });
  if (q.isLoading) return <LoadingBlock rows={2} />;
  if (!q.data?.items.length) return null;
  return (
    <Panel title="Dataset health" actions={<ButtonLink to="/datasets" size="sm" variant="ghost">All datasets</ButtonLink>} bodyClassName="p-0">
      <ul className="grid divide-y divide-line sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-3">
        {q.data.items.map((d) => (
          <li key={d.id} className="sm:border-b sm:border-line">
            <Link to={`/datasets/${d.id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-raised">
              <HealthIndicator health={d.health} pulse />
              <span className="min-w-0 flex-1 truncate text-base text-fg">{d.name}</span>
              <span className="font-mono text-xs text-faint">v{d.current_version?.version_number ?? "–"}</span>
            </Link>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
