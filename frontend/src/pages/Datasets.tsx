import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Database, Plus, Search } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge, HealthIndicator, toneFor } from "@/components/ui/Badge";
import { ButtonLink } from "@/components/ui/Button";
import { EmptyState, ErrorState, Input, LoadingBlock, Panel, Select } from "@/components/ui/primitives";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/Table";
import { get, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtInt, fmtRelative } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import type { Dataset, Paged } from "@/lib/types";

export default function Datasets() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { can } = useAuth();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const q = useDebounced(search.trim(), 250);
  const health = params.get("health") ?? "";
  const sort = params.get("sort") ?? "updated";
  const page = Number(params.get("page") ?? 1);

  const set = (k: string, v: string) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v);
    else p.delete(k);
    if (k !== "page") p.delete("page");
    setParams(p, { replace: true });
  };

  const query = useQuery({
    queryKey: ["datasets", { q, health, sort, page }],
    queryFn: () => get<Paged<Dataset>>(`/datasets${qs({ q, health, sort, page, page_size: 20 })}`),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader
        title="Datasets"
        description="Every registered dataset with its active version, health from the latest monitoring run, and open incidents."
        actions={
          can("editor") && (
            <ButtonLink to="/datasets/new" variant="primary" icon={<Plus className="h-4 w-4" />}>
              Add dataset
            </ButtonLink>
          )
        }
      />
      <Panel bodyClassName="p-0">
        <div className="flex flex-col gap-2 border-b border-line p-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint" aria-hidden />
            <Input aria-label="Search datasets" placeholder="Search by name, description or owner" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-8" />
          </div>
          <div className="flex gap-2">
            <Select aria-label="Filter by health" value={health} onChange={(e) => set("health", e.target.value)} className="sm:w-40">
              <option value="">All health states</option>
              <option value="failing">Failing</option>
              <option value="warning">Warning</option>
              <option value="healthy">Healthy</option>
              <option value="unknown">Not checked</option>
            </Select>
            <Select aria-label="Sort" value={sort} onChange={(e) => set("sort", e.target.value)} className="sm:w-40">
              <option value="updated">Recently updated</option>
              <option value="name">Name</option>
              <option value="health">Health</option>
              <option value="criticality">Criticality</option>
            </Select>
          </div>
        </div>
        {query.isError ? (
          <ErrorState error={query.error} retry={() => query.refetch()} />
        ) : !query.data ? (
          <div className="p-4">
            <LoadingBlock rows={6} />
          </div>
        ) : query.data.items.length === 0 ? (
          <EmptyState
            icon={<Database className="h-5 w-5" />}
            title={q || health ? "No datasets match these filters" : "No datasets yet"}
            action={can("editor") && !q && !health ? <ButtonLink to="/datasets/new" variant="primary">Add a dataset</ButtonLink> : undefined}
          >
            {q || health ? "Try a different search or clear the health filter." : "Upload a file, push records with the SDK, or load a synthetic scenario."}
          </EmptyState>
        ) : (
          <>
            {/* Mobile cards */}
            <ul className="divide-y divide-line md:hidden">
              {query.data.items.map((d) => (
                <li key={d.id}>
                  <Link to={`/datasets/${d.id}`} className="block px-4 py-3 hover:bg-raised">
                    <div className="flex items-center gap-2">
                      <span className="min-w-0 flex-1 truncate text-base font-medium text-fg">{d.name}</span>
                      <HealthIndicator health={d.health} />
                    </div>
                    <div className="mt-1 text-sm text-muted">
                      v{d.current_version?.version_number ?? "–"} · {fmtInt(d.current_version?.row_count)} rows · {d.rule_count} rules
                      {d.open_incidents > 0 && <span className="text-crit"> · {d.open_incidents} open</span>}
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
            <Table className="hidden md:block" label="Datasets">
              <thead>
                <tr>
                  <Th>Dataset</Th>
                  <Th>Health</Th>
                  <Th>Criticality</Th>
                  <Th align="right">Active version</Th>
                  <Th align="right">Rows</Th>
                  <Th align="right">Rules</Th>
                  <Th align="right">Incidents</Th>
                  <Th align="right">Updated</Th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((d) => (
                  <Tr key={d.id} onClick={() => navigate(`/datasets/${d.id}`)}>
                    <Td className="max-w-[340px]">
                      <Link to={`/datasets/${d.id}`} className="block truncate font-medium text-fg hover:text-accent" onClick={(e) => e.stopPropagation()}>
                        {d.name}
                      </Link>
                      <div className="truncate text-sm text-faint">{d.description || d.owner || d.source_type}</div>
                    </Td>
                    <Td>
                      <HealthIndicator health={d.health} />
                    </Td>
                    <Td>
                      <Badge tone={d.criticality === "critical" ? "crit" : d.criticality === "high" ? "warn" : "neutral"}>{d.criticality}</Badge>
                    </Td>
                    <Td align="right" mono>
                      {d.current_version ? `v${d.current_version.version_number}` : "—"}
                      {d.current_version && d.current_version.status !== "active" && <Badge tone={toneFor(d.current_version.status)} className="ml-2">{d.current_version.status}</Badge>}
                    </Td>
                    <Td align="right" mono>
                      {fmtInt(d.current_version?.row_count)}
                    </Td>
                    <Td align="right" mono>
                      {d.rule_count}
                    </Td>
                    <Td align="right" mono className={d.open_incidents ? "text-crit" : "text-faint"}>
                      {d.open_incidents}
                    </Td>
                    <Td align="right" className="whitespace-nowrap text-sm text-muted">
                      {fmtRelative(d.updated_at)}
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <div className="border-t border-line">
              <Pagination page={query.data.page} pages={query.data.pages} total={query.data.total} onPage={(p) => set("page", String(p))} />
            </div>
          </>
        )}
      </Panel>
    </>
  );
}
