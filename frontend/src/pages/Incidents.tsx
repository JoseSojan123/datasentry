import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Search, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { SeverityBadge, StatusBadge, UrgencyTag } from "@/components/ui/Badge";
import { EmptyState, ErrorState, Input, LoadingBlock, Panel, Select } from "@/components/ui/primitives";
import { Pagination } from "@/components/ui/Table";
import { get, qs } from "@/lib/api";
import { cn } from "@/lib/cn";
import { fmtRelative, fmtSeconds } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import type { Incident, Paged } from "@/lib/types";

const STATUS_SETS: Record<string, string> = {
  active: "open,acknowledged,investigating,reopened",
  open: "open,reopened",
  investigating: "acknowledged,investigating",
  resolved: "resolved",
  all: "",
};

export default function Incidents() {
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const q = useDebounced(search.trim(), 250);
  const statusKey = params.get("status") ?? "active";
  const severity = params.get("severity") ?? "";
  const sort = params.get("sort") ?? "priority";
  const page = Number(params.get("page") ?? 1);
  const modelId = params.get("model_id");
  const datasetId = params.get("dataset_id");
  const set = (k: string, v: string) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v);
    else p.delete(k);
    if (k !== "page") p.delete("page");
    setParams(p, { replace: true });
  };
  const query = useQuery({
    queryKey: ["incidents", { q, statusKey, severity, sort, page, modelId, datasetId }],
    queryFn: () => get<Paged<Incident>>(`/incidents${qs({ q, status: STATUS_SETS[statusKey] ?? statusKey, severity, sort, page, page_size: 20, model_id: modelId, dataset_id: datasetId })}`),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader title="Incidents" description="Findings on the same dataset or model are grouped into one incident and re-opened if they come back within 7 days. Priority combines severity, downstream reach and criticality." />
      <div className="mb-3 flex flex-col gap-2 lg:flex-row lg:items-center">
        <div role="tablist" aria-label="Status" className="flex overflow-x-auto rounded-md border border-line bg-surface p-0.5">
          {[
            ["active", "Active"],
            ["open", "Open"],
            ["investigating", "In progress"],
            ["resolved", "Resolved"],
            ["all", "All"],
          ].map(([k, label]) => (
            <button key={k} role="tab" aria-selected={statusKey === k} onClick={() => set("status", k === "active" ? "" : k)} className={cn("h-7 shrink-0 rounded px-3 text-sm transition-colors", statusKey === k ? "bg-overlay text-fg" : "text-muted hover:text-fg")}>
              {label}
            </button>
          ))}
        </div>
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint" aria-hidden />
          <Input aria-label="Search incidents" placeholder="Search titles" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-8" />
        </div>
        <div className="flex gap-2">
          <Select aria-label="Severity" value={severity} onChange={(e) => set("severity", e.target.value)} className="lg:w-36">
            <option value="">Any severity</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </Select>
          <Select aria-label="Sort" value={sort} onChange={(e) => set("sort", e.target.value)} className="lg:w-36">
            <option value="priority">Priority</option>
            <option value="recent">Most recent</option>
            <option value="oldest">Oldest first</option>
          </Select>
        </div>
      </div>
      <Panel bodyClassName="p-0">
        {query.isError ? (
          <ErrorState error={query.error} retry={() => query.refetch()} />
        ) : !query.data ? (
          <div className="p-4">
            <LoadingBlock rows={6} />
          </div>
        ) : query.data.items.length === 0 ? (
          <EmptyState icon={<ShieldAlert className="h-5 w-5" />} title={statusKey === "active" && !q && !severity ? "No active incidents" : "No incidents match"}>
            {statusKey === "active" && !q && !severity ? "Every monitored dataset and model passed its latest checks." : "Try another status or clear the filters."}
          </EmptyState>
        ) : (
          <>
            <ul className="divide-y divide-line">
              {query.data.items.map((i) => (
                <li key={i.id}>
                  <Link to={`/incidents/${i.id}`} className="grid gap-2 px-4 py-3 transition-colors hover:bg-raised md:grid-cols-[110px_minmax(0,1fr)_auto] md:items-center md:gap-4">
                    <div className="flex items-center gap-1.5">
                      <UrgencyTag urgency={i.priority.urgency} score={i.priority.score} />
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <SeverityBadge severity={i.severity} />
                        <span className="min-w-0 truncate text-base font-medium text-fg">{i.title}</span>
                      </div>
                      <div className="mt-1 flex flex-wrap gap-x-3 text-sm text-muted">
                        <span className="font-mono text-xs text-faint">#{i.id}</span>
                        <span>
                          {i.findings.length} finding{i.findings.length === 1 ? "" : "s"}
                        </span>
                        <span>
                          {i.impact.counts.total} downstream · {i.impact.counts.confirmed} confirmed
                        </span>
                        {i.occurrence_count > 1 && <span>seen {i.occurrence_count}×</span>}
                        <span>{i.status === "resolved" ? `resolved in ${fmtSeconds(i.resolution_seconds)}` : `last seen ${fmtRelative(i.last_seen_at)}`}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 md:justify-end">
                      <StatusBadge status={i.status} />
                      {i.resolution?.type === "verified" && <span className="text-xs text-ok">verified</span>}
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
            <div className="border-t border-line">
              <Pagination page={query.data.page} pages={query.data.pages} total={query.data.total} onPage={(p) => set("page", String(p))} />
            </div>
          </>
        )}
      </Panel>
    </>
  );
}
