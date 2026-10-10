import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, GitCompare, X } from "lucide-react";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge, SeverityBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Callout, EmptyState, ErrorState, Field, LoadingBlock, Meter, Panel, Select } from "@/components/ui/primitives";
import { ApiError, get, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtNum, humanize } from "@/lib/format";
import type { Comparison, Dataset, Paged, Version } from "@/lib/types";

interface RenameDecision {
  id: number;
  from_column: string;
  to_column: string;
  decision: "confirmed" | "rejected";
  created_at: string;
}

export default function Compare() {
  const { id } = useParams();
  const dsId = Number(id);
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const { can } = useAuth();
  const ds = useQuery({ queryKey: ["dataset", dsId], queryFn: () => get<Dataset>(`/datasets/${dsId}`) });
  const versions = useQuery({ queryKey: ["versions", dsId, "all"], queryFn: () => get<Paged<Version>>(`/datasets/${dsId}/versions?page_size=100`) });
  const comps = useQuery({ queryKey: ["comparisons", dsId], queryFn: () => get<Paged<Comparison>>(`/datasets/${dsId}/comparisons?page_size=50`) });
  const decisions = useQuery({ queryKey: ["rename-decisions", dsId], queryFn: () => get<{ items: RenameDecision[] }>(`/datasets/${dsId}/rename-decisions`) });
  const ok = (versions.data?.items ?? []).filter((v) => v.ingestion_status === "succeeded");
  const [base, setBase] = useState("");
  const [target, setTarget] = useState("");
  const baseId = base || String(ok[1]?.id ?? "");
  const targetId = target || String(ok[0]?.id ?? "");

  const selectedId = Number(params.get("comparison")) || comps.data?.items[0]?.id;
  const selected = comps.data?.items.find((c) => c.id === selectedId);
  const vnum = (vid: number) => ok.find((v) => v.id === vid)?.version_number;

  const run = useMutation({
    mutationFn: () => post<Comparison>(`/datasets/${dsId}/compare`, { base_version_id: Number(baseId), target_version_id: Number(targetId) }),
    onSuccess: (c) => {
      void qc.invalidateQueries({ queryKey: ["comparisons", dsId] });
      setParams({ comparison: String(c.id) }, { replace: true });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Comparison failed."),
  });
  const decide = useMutation({
    mutationFn: (b: { from_column: string; to_column: string; decision: "confirmed" | "rejected" }) => post(`/datasets/${dsId}/rename-decisions`, b),
    onSuccess: (_, b) => {
      toast.success(b.decision === "confirmed" ? `Recorded: ${b.from_column} was renamed to ${b.to_column}.` : "Recorded: not a rename.");
      void qc.invalidateQueries({ queryKey: ["rename-decisions", dsId] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not record the decision."),
  });
  const decisionFor = (from: string, to: string) => decisions.data?.items.find((d) => d.from_column === from && d.to_column === to);

  if (ds.isError) return <ErrorState error={ds.error} />;
  return (
    <>
      <PageHeader
        title="Compare versions"
        crumbs={[{ label: "Datasets", to: "/datasets" }, { label: ds.data?.name ?? "…", to: `/datasets/${dsId}` }, { label: "Compare" }]}
        description="Schema, missing values, categories, duplicates and row count between two versions. Possible renames are listed for a person to confirm; they are never applied automatically."
      />
      <div className="grid gap-4 lg:grid-cols-[minmax(240px,300px)_1fr]">
        <div className="space-y-4">
          {can("editor") && ok.length >= 2 && (
            <Panel title="New comparison">
              <div className="space-y-3">
                <Field label="Base" htmlFor="c_base">
                  <Select id="c_base" value={baseId} onChange={(e) => setBase(e.target.value)}>
                    {ok.map((v) => (
                      <option key={v.id} value={v.id}>
                        v{v.version_number} · {fmtDate(v.created_at)}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Target" htmlFor="c_target">
                  <Select id="c_target" value={targetId} onChange={(e) => setTarget(e.target.value)}>
                    {ok.map((v) => (
                      <option key={v.id} value={v.id}>
                        v{v.version_number} · {fmtDate(v.created_at)}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Button className="w-full" variant="primary" icon={<GitCompare className="h-4 w-4" />} disabled={baseId === targetId} loading={run.isPending} onClick={() => run.mutate()}>
                  Compare
                </Button>
              </div>
            </Panel>
          )}
          <Panel title="History" bodyClassName="p-0">
            {!comps.data ? (
              <div className="p-4">
                <LoadingBlock rows={3} />
              </div>
            ) : comps.data.items.length === 0 ? (
              <EmptyState title="No comparisons yet" className="py-8" />
            ) : (
              <ul className="divide-y divide-line">
                {comps.data.items.map((c) => (
                  <li key={c.id}>
                    <button onClick={() => setParams({ comparison: String(c.id) }, { replace: true })} aria-current={c.id === selectedId} className={`flex w-full items-center gap-2 px-4 py-2.5 text-left ${c.id === selectedId ? "bg-overlay" : "hover:bg-raised"}`}>
                      <span className="font-mono text-sm">
                        v{vnum(c.base_version_id) ?? "?"} <ArrowRight className="inline h-3 w-3 text-faint" /> v{vnum(c.target_version_id) ?? "?"}
                      </span>
                      <span className="ml-auto">
                        <SeverityBadge severity={c.overall_severity} />
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
        <div className="space-y-4">
          {!selected ? (
            <Panel>
              <EmptyState icon={<GitCompare className="h-5 w-5" />} title="Select or run a comparison" />
            </Panel>
          ) : (
            <>
              <Panel
                title={
                  <span className="font-mono">
                    v{vnum(selected.base_version_id)} → v{vnum(selected.target_version_id)}
                  </span>
                }
                description={`${selected.result.summary.changes} change(s) · schema ${selected.result.summary.schema_changed ? "changed" : "unchanged"} · ${fmtDate(selected.created_at)}`}
                actions={<SeverityBadge severity={selected.overall_severity} />}
                bodyClassName="p-0"
              >
                {selected.result.changes.length === 0 ? (
                  <EmptyState title="No differences beyond normal variation" className="py-8" />
                ) : (
                  <ul className="divide-y divide-line">
                    {selected.result.changes.map((ch, i) => (
                      <li key={i} className="flex flex-wrap items-start gap-3 px-4 py-3">
                        <SeverityBadge severity={ch.severity} />
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium">
                            {humanize(ch.kind)} {ch.column && <code className="ml-1 rounded-sm bg-overlay px-1 font-mono text-xs text-muted">{ch.column}</code>}
                          </div>
                          <p className="mt-0.5 text-sm text-muted">{ch.message}</p>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
              {selected.result.rename_candidates.length > 0 && (
                <Panel title="Possible renames" description="Scored on name similarity (35%), profile similarity (50%) and position (15%). Confirming records a decision; it does not rewrite data.">
                  <ul className="space-y-3">
                    {selected.result.rename_candidates.map((r) => {
                      const d = decisionFor(r.from, r.to);
                      return (
                        <li key={`${r.from}-${r.to}`} className="rounded-md border border-line p-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <code className="font-mono text-sm text-crit line-through decoration-crit/50">{r.from}</code>
                            <ArrowRight className="h-3.5 w-3.5 text-faint" />
                            <code className="font-mono text-sm text-ok">{r.to}</code>
                            {r.ambiguous && <Badge tone="warn">ambiguous</Badge>}
                            <span className="ml-auto font-mono text-sm text-muted">{fmtNum(r.confidence * 100, 0)}% confidence</span>
                          </div>
                          <Meter className="mt-2" value={r.confidence} tone={r.confidence >= 0.75 ? "ok" : "warn"} label="Rename confidence" />
                          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-faint">
                            {Object.entries(r.evidence).map(([k, v]) => (
                              <span key={k}>
                                {humanize(k)} {fmtNum(v, 2)}
                              </span>
                            ))}
                          </div>
                          <div className="mt-3 flex flex-wrap items-center gap-2">
                            {d ? (
                              <Badge tone={d.decision === "confirmed" ? "ok" : "neutral"}>{d.decision === "confirmed" ? "Confirmed as rename" : "Rejected"}</Badge>
                            ) : can("editor") ? (
                              <>
                                <Button size="sm" icon={<Check className="h-3.5 w-3.5" />} loading={decide.isPending && decide.variables?.decision === "confirmed"} onClick={() => decide.mutate({ from_column: r.from, to_column: r.to, decision: "confirmed" })}>
                                  Confirm rename
                                </Button>
                                <Button size="sm" variant="ghost" icon={<X className="h-3.5 w-3.5" />} onClick={() => decide.mutate({ from_column: r.from, to_column: r.to, decision: "rejected" })}>
                                  Not a rename
                                </Button>
                              </>
                            ) : (
                              <span className="text-sm text-faint">Awaiting an editor's decision</span>
                            )}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                  <Callout tone="neutral" className="mt-3">
                    Later comparisons report a confirmed rename as one renamed column instead of a removal plus an addition. Rules that name the old column still need to be edited.
                  </Callout>
                </Panel>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
