import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { SeverityBadge, StatusBadge } from "@/components/ui/Badge";
import { EmptyState, ErrorState, LoadingBlock, Meter, Panel } from "@/components/ui/primitives";
import { Pagination } from "@/components/ui/Table";
import { get } from "@/lib/api";
import { cn } from "@/lib/cn";
import { fmtDate, fmtDuration, fmtInt, fmtPct, fmtRelative, humanize } from "@/lib/format";
import type { CheckResult, CheckRun, Dataset, Paged } from "@/lib/types";

function ResultRow({ r }: { r: CheckResult }) {
  const [open, setOpen] = useState(r.status !== "pass");
  return (
    <li>
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-raised">
        <StatusBadge status={r.status} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-base text-fg">{r.rule.name}</span>
          <span className="text-xs text-faint">
            {humanize(r.rule.rule_type)}
            {r.rule.columns.length > 0 && ` · ${r.rule.columns.join(", ")}`}
          </span>
        </span>
        <SeverityBadge severity={r.rule.severity} className="hidden sm:inline-flex" />
        <span className={cn("w-16 text-right font-mono text-sm", r.status === "fail" ? "text-crit" : "text-muted")}>{fmtPct(r.failure_pct)}</span>
        <ChevronDown className={cn("h-4 w-4 text-faint transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open && (
        <div className="space-y-3 border-t border-line/60 bg-bg/40 px-4 py-3">
          <p className="text-sm text-fg">{r.explanation}</p>
          <div className="grid gap-3 text-sm sm:grid-cols-3">
            <div>
              <div className="label">Rows evaluated</div>
              <div className="mt-0.5 font-mono">{fmtInt(r.rows_evaluated)}</div>
            </div>
            <div>
              <div className="label">Failing rows</div>
              <div className="mt-0.5 font-mono">{fmtInt(r.failed_rows)}</div>
            </div>
            <div>
              <div className="label">Duration</div>
              <div className="mt-0.5 font-mono">{fmtDuration(r.duration_ms)}</div>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <div className="label mb-1">Observed</div>
              <pre className="overflow-x-auto rounded border border-line bg-bg p-2 font-mono text-xs text-muted">{JSON.stringify(r.observed, null, 2)}</pre>
            </div>
            <div>
              <div className="label mb-1">Expected</div>
              <pre className="overflow-x-auto rounded border border-line bg-bg p-2 font-mono text-xs text-muted">{JSON.stringify(r.expected, null, 2)}</pre>
            </div>
          </div>
          {r.sample_failures.length > 0 && (
            <div>
              <div className="label mb-1">Sample of failing rows (row index is 0-based)</div>
              <div className="overflow-x-auto rounded border border-line">
                <table className="w-full text-left font-mono text-xs">
                  <thead>
                    <tr className="border-b border-line text-faint">
                      {Object.keys(r.sample_failures[0]).map((k) => (
                        <th key={k} className="px-2 py-1.5 font-normal">
                          {k}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {r.sample_failures.map((row, i) => (
                      <tr key={i} className="border-b border-line/50 last:border-0">
                        {Object.values(row).map((v, j) => (
                          <td key={j} className="px-2 py-1 text-muted">
                            {v === null ? <span className="text-faint">null</span> : String(v)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

export function ChecksTab({ ds }: { ds: Dataset }) {
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState(1);
  const runs = useQuery({ queryKey: ["check-runs", ds.id, page], queryFn: () => get<Paged<CheckRun>>(`/datasets/${ds.id}/check-runs?page=${page}&page_size=15`) });
  const runId = Number(params.get("run")) || runs.data?.items[0]?.id;
  const run = useQuery({ queryKey: ["check-run", runId], queryFn: () => get<CheckRun>(`/check-runs/${runId}`), enabled: !!runId });

  if (runs.isError) return <ErrorState error={runs.error} retry={() => runs.refetch()} />;
  if (!runs.data) return <LoadingBlock />;
  if (runs.data.items.length === 0) return <Panel><EmptyState title="No rule runs yet">Rules run on every new version and when you press Run now on the Rules tab.</EmptyState></Panel>;

  const sorted = run.data?.results ? [...run.data.results].sort((a, b) => ({ fail: 0, error: 1, pass: 2 })[a.status] - ({ fail: 0, error: 1, pass: 2 })[b.status]) : [];

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(240px,320px)_1fr]">
      <Panel title="Runs" bodyClassName="p-0">
        <ul className="divide-y divide-line">
          {runs.data.items.map((r) => (
            <li key={r.id}>
              <button
                onClick={() => {
                  const p = new URLSearchParams(params);
                  p.set("run", String(r.id));
                  setParams(p, { replace: true });
                }}
                aria-current={r.id === runId}
                className={cn("block w-full px-4 py-2.5 text-left transition-colors", r.id === runId ? "bg-overlay" : "hover:bg-raised")}
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm text-fg">#{r.id}</span>
                  <span className="text-xs text-faint">{humanize(r.trigger)}</span>
                  <span className={cn("ml-auto font-mono text-sm", r.summary.failed ? "text-crit" : "text-ok")}>
                    {r.summary.passed}/{r.summary.total}
                  </span>
                </div>
                <Meter className="mt-1.5" value={(r.summary.pass_rate ?? 0) / 100} tone={r.summary.failed ? "warn" : "ok"} label="Pass rate" />
                <div className="mt-1 text-xs text-faint">{fmtRelative(r.created_at)}</div>
              </button>
            </li>
          ))}
        </ul>
        <div className="border-t border-line">
          <Pagination page={runs.data.page} pages={runs.data.pages} total={runs.data.total} onPage={setPage} />
        </div>
      </Panel>
      <Panel title={run.data ? `Run #${run.data.id}` : "Run"} description={run.data ? `${fmtDate(run.data.created_at)} · ${run.data.summary.passed} passed, ${run.data.summary.failed} failed, ${run.data.summary.errored} errored · ${fmtDuration(run.data.duration_ms)}` : undefined} bodyClassName="p-0">
        {run.isError ? <ErrorState error={run.error} /> : !run.data ? <div className="p-4"><LoadingBlock /></div> : (
          <ul className="divide-y divide-line">
            {sorted.map((r) => (
              <ResultRow key={r.id} r={r} />
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
