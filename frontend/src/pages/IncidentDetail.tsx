import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, CheckCircle2, GitBranch, ListChecks, MessageSquare, RotateCcw, ShieldCheck, UserRound } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { FindingList } from "@/components/common/Findings";
import { RemediationCard } from "@/components/common/RemediationCard";
import { PageHeader } from "@/components/layout/PageHeader";
import { LineageGraph, LineageLegend } from "@/components/lineage/LineageGraph";
import { NODE_TYPE } from "@/components/lineage/meta";
import { Badge, SeverityBadge, StatusBadge, UrgencyTag } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Callout, EmptyState, ErrorState, Field, LoadingBlock, Panel, Select, Textarea } from "@/components/ui/primitives";
import { ApiError, get, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { fmtDate, fmtRelative, fmtSeconds, humanize } from "@/lib/format";
import { useMediaQuery } from "@/lib/hooks";
import { useMotion } from "@/lib/motion";
import type { Finding, IncidentDetail as IncidentT, LineageEdge, LineageNode } from "@/lib/types";

interface Investigation {
  source_node_id: number | null;
  state: string;
  contained: boolean;
  verified_remediation_id: number | null;
  nodes: LineageNode[];
  edges: LineageEdge[];
  findings: Finding[];
  counts: Record<string, number>;
}

const COMPONENT_LABEL: Record<string, string> = {
  severity: "Severity",
  downstream: "Downstream reach",
  models_reports: "Models and reports affected",
  source_criticality: "Source criticality",
};
const COMPONENT_TONE: Record<string, string> = { severity: "bg-crit", downstream: "bg-warn", models_reports: "bg-accent", source_criticality: "bg-info" };

function PriorityBreakdown({ inc }: { inc: IncidentT }) {
  const comps = Object.entries(inc.priority.components ?? {});
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="label">Priority score</span>
        <span className="font-mono text-sm text-fg">{inc.priority.score.toFixed(1)} / 100</span>
      </div>
      <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-overlay" role="img" aria-label={`Priority ${inc.priority.score.toFixed(1)} of 100`}>
        {comps.map(([k, v]) => (
          <div key={k} className={cn("h-full", COMPONENT_TONE[k] ?? "bg-faint")} style={{ width: `${v}%` }} title={`${COMPONENT_LABEL[k] ?? k}: ${v}`} />
        ))}
      </div>
      <ul className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted">
        {comps.map(([k, v]) => (
          <li key={k} className="flex items-center gap-1.5">
            <span className={cn("h-2 w-2 rounded-sm", COMPONENT_TONE[k] ?? "bg-faint")} />
            {COMPONENT_LABEL[k] ?? humanize(k)} <span className="ml-auto font-mono">{Number(v).toFixed(1)}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-2xs text-faint">{inc.priority.method}</p>
    </div>
  );
}

function NodeInspector({ node, nodes, onClose }: { node: LineageNode; nodes: LineageNode[]; onClose: () => void }) {
  const T = NODE_TYPE[node.node_type] ?? NODE_TYPE.dataset;
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const link = node.dataset_id ? `/datasets/${node.dataset_id}` : node.model_id ? `/models/${node.model_id}` : `/lineage?node=${node.id}`;
  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-line bg-raised text-muted">
          <T.icon className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="break-words text-md font-medium">{node.name}</div>
          <div className="text-sm text-muted">
            {T.label} · {node.criticality} criticality{node.owner ? ` · ${node.owner}` : ""}
          </div>
        </div>
        <button onClick={onClose} className="text-sm text-faint hover:text-fg">
          Close
        </button>
      </div>
      {node.description && <p className="text-sm text-muted">{node.description}</p>}
      <div className="flex flex-wrap gap-2">
        {node.role === "source" && <Badge tone="crit">source of this incident</Badge>}
        {node.role === "affected" && <Badge tone={node.impact === "confirmed" ? "crit" : "warn"}>{node.impact} impact · depth {node.depth}</Badge>}
        {node.role === "upstream" && <Badge>upstream</Badge>}
      </div>
      {node.path && node.path.length > 1 && (
        <div>
          <div className="label mb-1.5">Path from the source</div>
          <ol className="flex flex-wrap items-center gap-1 text-sm">
            {node.path.map((id, i) => (
              <li key={id} className="flex items-center gap-1">
                {i > 0 && <ArrowRight className="h-3 w-3 text-faint" aria-hidden />}
                <span className={cn("rounded-sm px-1.5 py-0.5", id === node.id ? "bg-overlay text-fg" : "text-muted")}>{byId[id]?.name ?? `#${id}`}</span>
              </li>
            ))}
          </ol>
          <p className="mt-2 text-xs text-faint">
            {node.impact === "confirmed" ? "Every edge on this path was observed by DataSentry." : "At least one edge on this path is declared or inferred, so the impact is possible but not confirmed."}
          </p>
        </div>
      )}
      <Link to={link} className="link text-sm">
        Open {T.label.toLowerCase()}
      </Link>
    </div>
  );
}

function Timeline({ inc }: { inc: IncidentT }) {
  const items = useMemo(
    () =>
      [
        ...inc.events.filter((e) => e.event_type !== "commented").map((e) => ({ kind: "event" as const, at: e.created_at, id: `e${e.id}`, e })),
        ...inc.comments.map((c) => ({ kind: "comment" as const, at: c.created_at, id: `c${c.id}`, c })),
      ].sort((a, b) => a.at.localeCompare(b.at) || a.id.localeCompare(b.id)),
    [inc],
  );
  const dot = (t: string) => (t.includes("verified") || t === "resolved" ? "bg-ok" : t.includes("failed") || t === "detected" || t === "reopened" ? "bg-crit" : t.includes("remediation") ? "bg-accent" : "bg-faint");
  return (
    <ol className="relative space-y-4 before:absolute before:bottom-2 before:left-[5px] before:top-2 before:w-px before:bg-line">
      {items.map((it) => (
        <li key={it.id} className="relative pl-6">
          <span className={cn("absolute left-0 top-1.5 h-[11px] w-[11px] rounded-full border-2 border-surface", it.kind === "comment" ? "bg-info" : dot(it.e.event_type))} aria-hidden />
          {it.kind === "event" ? (
            <>
              <div className="flex flex-wrap items-center gap-x-2 text-sm">
                <span className="font-medium text-fg">{humanize(it.e.event_type)}</span>
                <span className="text-xs text-faint">
                  {it.e.actor} · <time dateTime={it.at} title={fmtDate(it.at)}>{fmtRelative(it.at)}</time>
                </span>
              </div>
              <p className="mt-0.5 break-words text-sm text-muted">{it.e.message}</p>
            </>
          ) : (
            <div className="rounded-md border border-line bg-raised px-3 py-2">
              <div className="flex items-center gap-2 text-xs text-faint">
                <MessageSquare className="h-3 w-3" /> {it.c.author ?? "someone"} · {fmtRelative(it.at)}
              </div>
              <p className="mt-1 whitespace-pre-wrap break-words text-sm text-fg">{it.c.body}</p>
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}

export default function IncidentDetail() {
  const { id } = useParams();
  const incId = Number(id);
  const qc = useQueryClient();
  const { can } = useAuth();
  const { reduced, fadeUp, stagger } = useMotion();
  const narrow = useMediaQuery("(max-width: 640px)");
  const inc = useQuery({ queryKey: ["incident", incId], queryFn: () => get<IncidentT>(`/incidents/${incId}`) });
  const inv = useQuery({ queryKey: ["investigation", incId], queryFn: () => get<Investigation>(`/incidents/${incId}/investigation`) });
  const users = useQuery({ queryKey: ["users"], queryFn: () => get<{ items: { id: number; display_name: string }[] }>("/users"), enabled: can("editor") });
  const [selected, setSelected] = useState<number | null>(null);
  const [replay, setReplay] = useState(0);
  const [confirmedOnly, setConfirmedOnly] = useState(false);
  const [resolveOpen, setResolveOpen] = useState(false);
  const [resolveNote, setResolveNote] = useState("");
  const [comment, setComment] = useState("");

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["incident", incId] });
    void qc.invalidateQueries({ queryKey: ["investigation", incId] });
    void qc.invalidateQueries({ queryKey: ["incidents"] });
    void qc.invalidateQueries({ queryKey: ["overview"] });
  };
  const status = useMutation({
    mutationFn: (b: { status: string; note?: string }) => post(`/incidents/${incId}/status`, b),
    onSuccess: (_, b) => {
      toast.success(b.status === "resolved" ? "Incident resolved with your note." : `Marked ${b.status}.`);
      setResolveOpen(false);
      setResolveNote("");
      refresh();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not change status."),
  });
  const assign = useMutation({
    mutationFn: (uid: number | null) => post(`/incidents/${incId}/assign`, { user_id: uid }),
    onSuccess: refresh,
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not assign."),
  });
  const addComment = useMutation({
    mutationFn: () => post(`/incidents/${incId}/comments`, { body: comment.trim() }),
    onSuccess: () => {
      setComment("");
      refresh();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not post the comment."),
  });

  const highlight = useMemo(() => {
    if (!inv.data || !confirmedOnly) return null;
    return new Set(inv.data.nodes.filter((n) => n.role === "source" || n.impact === "confirmed").map((n) => n.id));
  }, [inv.data, confirmedOnly]);

  if (inc.isError) return <Panel><ErrorState error={inc.error} retry={() => inc.refetch()} /></Panel>;
  if (!inc.data) return <LoadingBlock rows={10} label="Loading incident" />;
  const i = inc.data;
  const open = i.status !== "resolved";
  const contained = !!inv.data?.contained;
  const selNode = inv.data?.nodes.find((n) => n.id === selected) ?? null;
  const counts = inv.data?.counts ?? i.impact.counts;
  const subject = i.dataset_name ? { label: i.dataset_name, to: `/datasets/${i.dataset_id}` } : i.model_name ? { label: i.model_name, to: `/models/${i.model_id}` } : null;
  const active = i.proposals.filter((p) => ["proposed", "approved", "failed", "verification_failed", "executing", "recommended_only"].includes(p.status));
  const past = i.proposals.filter((p) => !active.includes(p));

  return (
    <>
      <PageHeader
        title={i.title}
        docTitle={`Incident #${i.id}`}
        crumbs={[{ label: "Incidents", to: "/incidents" }, { label: `#${i.id}` }]}
        meta={
          <>
            <UrgencyTag urgency={i.priority.urgency} score={i.priority.score} />
            <SeverityBadge severity={i.severity} />
            <StatusBadge status={i.status} />
            {subject && (
              <Link to={subject.to} className="text-sm text-muted hover:text-fg">
                {subject.label}
                {i.version_number ? <span className="font-mono"> · v{i.version_number}</span> : null}
                {i.version_status && i.version_status !== "active" ? <span className="text-faint"> ({i.version_status})</span> : null}
              </Link>
            )}
            <span className="text-sm text-faint">
              first seen {fmtRelative(i.first_seen_at)}
              {i.occurrence_count > 1 ? ` · seen ${i.occurrence_count} times` : ""}
            </span>
          </>
        }
        actions={
          can("editor") && (
            <>
              {(i.status === "open" || i.status === "reopened") && (
                <Button size="sm" onClick={() => status.mutate({ status: "acknowledged" })} loading={status.isPending && status.variables?.status === "acknowledged"}>
                  Acknowledge
                </Button>
              )}
              {open && i.status !== "investigating" && (
                <Button size="sm" onClick={() => status.mutate({ status: "investigating" })} loading={status.isPending && status.variables?.status === "investigating"}>
                  Start investigating
                </Button>
              )}
              {open && (
                <Button size="sm" variant="outline" onClick={() => setResolveOpen(true)}>
                  Resolve manually
                </Button>
              )}
              {!open && (
                <Button size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => status.mutate({ status: "reopened" })}>
                  Reopen
                </Button>
              )}
            </>
          )
        }
      />

      {i.status === "resolved" && i.resolution && (
        <Callout tone={i.resolution.type === "verified" ? "ok" : "neutral"} icon={i.resolution.type === "verified" ? <ShieldCheck className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />} title={i.resolution.type === "verified" ? "Resolved after verification" : "Resolved manually"} className="mb-4">
          {i.resolution.message ?? i.resolution.note} {i.resolution_seconds ? <span className="text-faint">Time to resolve: {fmtSeconds(i.resolution_seconds)}.</span> : null}
        </Callout>
      )}

      <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-4">
        {/* Signature: investigation graph */}
        <motion.section variants={fadeUp} aria-labelledby="inv-title" className="panel overflow-hidden">
          <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
            <div className="flex items-center gap-2">
              <GitBranch className="h-4 w-4 text-accent" aria-hidden />
              <h2 id="inv-title" className="text-md font-medium">
                Investigation
              </h2>
              {contained ? <Badge tone="ok">contained</Badge> : <Badge tone="crit">propagating</Badge>}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-1.5 text-sm text-muted">
                <input type="checkbox" checked={confirmedOnly} onChange={(e) => setConfirmedOnly(e.target.checked)} className="accent-[rgb(var(--accent))]" />
                Confirmed paths only
              </label>
              {!reduced && (
                <Button size="sm" variant="ghost" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => setReplay((r) => r + 1)}>
                  Replay
                </Button>
              )}
            </div>
          </header>
          <div className="grid lg:grid-cols-[minmax(0,1fr)_300px]">
            <div className="relative min-w-0 p-3">
              {inv.isError ? (
                <ErrorState error={inv.error} />
              ) : !inv.data ? (
                <div className="h-[420px] animate-pulse rounded-lg bg-raised" />
              ) : inv.data.nodes.length <= 1 ? (
                <EmptyState icon={<GitBranch className="h-5 w-5" />} title="No downstream dependencies registered" className="h-[300px]">
                  The blast radius beyond {subject?.label ?? "the source"} is unknown. Declare transformations, reports and consumers on the{" "}
                  <Link to="/lineage" className="link">
                    lineage
                  </Link>{" "}
                  page to see impact here.
                </EmptyState>
              ) : (
                <LineageGraph key={replay} nodes={inv.data.nodes} edges={inv.data.edges} mode="investigation" selectedId={selected} onSelect={setSelected} highlight={highlight} contained={contained} height={narrow ? 460 : 440} />
              )}
              <LineageLegend mode="investigation" className="mt-3 px-1" />
            </div>
            <aside className="border-t border-line p-4 lg:border-l lg:border-t-0" aria-live="polite">
              <AnimatePresence mode="wait" initial={false}>
                {selNode && inv.data ? (
                  <motion.div key={`n${selNode.id}`} initial={reduced ? false : { opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }} transition={{ duration: reduced ? 0 : 0.18 }}>
                    <NodeInspector node={selNode} nodes={inv.data.nodes} onClose={() => setSelected(null)} />
                  </motion.div>
                ) : (
                  <motion.div key="summary" initial={reduced ? false : { opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduced ? 0 : 0.15 }} className="space-y-5">
                    <div>
                      <div className="label">Blast radius</div>
                      <div className="mt-2 grid grid-cols-3 gap-2 text-center">
                        <div className="rounded-md border border-line bg-raised py-2">
                          <div className="font-mono text-xl">{counts.total ?? 0}</div>
                          <div className="text-2xs text-faint">downstream</div>
                        </div>
                        <div className="rounded-md border border-crit/30 bg-crit/[0.06] py-2">
                          <div className="font-mono text-xl text-crit">{counts.confirmed ?? 0}</div>
                          <div className="text-2xs text-faint">confirmed</div>
                        </div>
                        <div className="rounded-md border border-warn/30 bg-warn/[0.06] py-2">
                          <div className="font-mono text-xl text-warn">{counts.potential ?? 0}</div>
                          <div className="text-2xs text-faint">potential</div>
                        </div>
                      </div>
                    </div>
                    <PriorityBreakdown inc={i} />
                    {i.impact.consequences && i.impact.consequences.length > 0 && (
                      <div>
                        <div className="label mb-1.5">Likely consequences</div>
                        <ul className="space-y-1.5 text-sm text-muted">
                          {i.impact.consequences.map((c, k) => (
                            <li key={k} className="flex gap-2">
                              <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-faint" />
                              {c}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {i.impact.cost_estimate ? (
                      <div className="rounded-md border border-line p-2.5 text-sm">
                        <div className="label">{i.impact.cost_estimate.label}</div>
                        <div className="mt-1 font-mono text-fg">{i.impact.cost_estimate.estimated_cost.toLocaleString()}</div>
                        <div className="mt-0.5 text-xs text-faint">{i.impact.cost_estimate.assumptions}</div>
                      </div>
                    ) : (
                      <p className="text-xs text-faint">No monetary estimate: no cost assumptions are configured for the affected consumers.</p>
                    )}
                    <p className="text-xs text-faint">Select a node to see its path from the source.</p>
                  </motion.div>
                )}
              </AnimatePresence>
            </aside>
          </div>
          {inv.data && inv.data.nodes.length > 1 && (
            <details className="border-t border-line px-4 py-2.5 text-sm">
              <summary className="cursor-pointer text-muted hover:text-fg">Impact as a list</summary>
              <ul className="mt-2 space-y-1">
                {inv.data.nodes
                  .filter((n) => n.role === "affected")
                  .sort((a, b) => (a.depth ?? 0) - (b.depth ?? 0))
                  .map((n) => (
                    <li key={n.id} className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs text-faint">depth {n.depth}</span>
                      <span className="text-fg">{n.name}</span>
                      <span className="text-faint">({NODE_TYPE[n.node_type]?.label ?? n.node_type})</span>
                      <Badge tone={n.impact === "confirmed" ? "crit" : "warn"}>{n.impact}</Badge>
                    </li>
                  ))}
              </ul>
            </details>
          )}
        </motion.section>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
          <div className="space-y-4">
            <motion.div variants={fadeUp}>
              <Panel title="Evidence" description={`${i.findings.length} finding${i.findings.length === 1 ? "" : "s"} from rules, profiling, schema comparison, drift or model monitoring`} bodyClassName="p-0">
                <FindingList findings={i.findings} datasetId={i.dataset_id} />
              </Panel>
            </motion.div>
            <motion.div variants={fadeUp}>
              <Panel title="Remediation" description="Safe, reversible actions. Data changes write a new version; an action counts as a fix only after the original checks pass again.">
                {i.proposals.length === 0 ? (
                  <EmptyState title="No remediation proposed" className="py-6">
                    No catalogued action applies to these findings. Investigate the source and resolve manually with a note.
                  </EmptyState>
                ) : (
                  <div className="space-y-3">
                    {active.map((p, k) => (
                      <RemediationCard key={p.id} p={p} defaultOpen={k === 0} />
                    ))}
                    {past.length > 0 && (
                      <>
                        {active.length > 0 && <div className="label pt-2">History</div>}
                        {past.map((p) => (
                          <RemediationCard key={p.id} p={p} defaultOpen={false} />
                        ))}
                      </>
                    )}
                  </div>
                )}
              </Panel>
            </motion.div>
          </div>
          <div className="space-y-4">
            <motion.div variants={fadeUp}>
              <Panel title="Ownership">
                <div className="flex items-center gap-3">
                  <UserRound className="h-4 w-4 text-faint" aria-hidden />
                  {can("editor") ? (
                    <Select aria-label="Assignee" value={i.assigned_to ?? ""} onChange={(e) => assign.mutate(e.target.value ? Number(e.target.value) : null)} className="flex-1">
                      <option value="">Unassigned</option>
                      {users.data?.items.map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.display_name}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <span className="text-sm">{i.assignee_name ?? "Unassigned"}</span>
                  )}
                </div>
                {i.impact.investigation_steps && i.impact.investigation_steps.length > 0 && (
                  <div className="mt-4">
                    <div className="label mb-1.5 flex items-center gap-1.5">
                      <ListChecks className="h-3.5 w-3.5" /> Suggested investigation steps
                    </div>
                    <ol className="list-decimal space-y-1 pl-5 text-sm text-muted">
                      {i.impact.investigation_steps.map((s, k) => (
                        <li key={k}>{s}</li>
                      ))}
                    </ol>
                  </div>
                )}
              </Panel>
            </motion.div>
            <motion.div variants={fadeUp}>
              <Panel title="Timeline">
                <Timeline inc={i} />
                {can("editor") && (
                  <form
                    className="mt-5 space-y-2"
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (comment.trim()) addComment.mutate();
                    }}
                  >
                    <label htmlFor="comment" className="sr-only">
                      Add a comment
                    </label>
                    <Textarea id="comment" rows={2} placeholder="Add a comment or finding from your investigation" value={comment} onChange={(e) => setComment(e.target.value)} maxLength={5000} />
                    <div className="flex justify-end">
                      <Button type="submit" size="sm" disabled={!comment.trim()} loading={addComment.isPending}>
                        Comment
                      </Button>
                    </div>
                  </form>
                )}
              </Panel>
            </motion.div>
          </div>
        </div>
      </motion.div>

      <Dialog
        open={resolveOpen}
        onClose={() => setResolveOpen(false)}
        title="Resolve without verification?"
        description="Use this when the cause is handled outside DataSentry or the findings are expected. The note is kept in the timeline; the incident is not marked as verified."
        footer={
          <>
            <Button variant="ghost" onClick={() => setResolveOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" disabled={resolveNote.trim().length < 5} loading={status.isPending} onClick={() => status.mutate({ status: "resolved", note: resolveNote.trim() })}>
              Resolve
            </Button>
          </>
        }
      >
        <Field label="Resolution note" htmlFor="res_note" hint="At least 5 characters. Explain what was done or why no action is needed.">
          <Textarea id="res_note" rows={3} value={resolveNote} onChange={(e) => setResolveNote(e.target.value)} data-autofocus />
        </Field>
      </Dialog>
    </>
  );
}
