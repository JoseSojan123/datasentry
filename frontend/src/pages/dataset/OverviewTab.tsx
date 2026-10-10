import { useQuery } from "@tanstack/react-query";
import { GitBranch, ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge, SeverityBadge, StatusBadge, UrgencyTag } from "@/components/ui/Badge";
import { ButtonLink } from "@/components/ui/Button";
import { EmptyState, KV, LoadingBlock, Panel, Stat } from "@/components/ui/primitives";
import { get } from "@/lib/api";
import { fmtBytes, fmtDate, fmtDuration, fmtInt, fmtPct, fmtRelative, fmtSeconds } from "@/lib/format";
import type { Dataset, Impact, Incident, Paged, Profile } from "@/lib/types";
import { NODE_TYPE } from "@/components/lineage/meta";

export function OverviewTab({ ds }: { ds: Dataset }) {
  const v = ds.current_version;
  const profile = useQuery({ queryKey: ["profile", v?.id], queryFn: () => get<Profile>(`/versions/${v!.id}/profile`), enabled: !!v && v.ingestion_status === "succeeded" });
  const impact = useQuery({ queryKey: ["dataset-impact", ds.id], queryFn: () => get<Impact>(`/datasets/${ds.id}/lineage-impact`) });
  const incidents = useQuery({ queryKey: ["incidents", { dataset: ds.id }], queryFn: () => get<Paged<Incident>>(`/incidents?dataset_id=${ds.id}&status=open,acknowledged,investigating,reopened&page_size=5`) });
  const s = profile.data?.summary;

  return (
    <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
      <div className="space-y-4">
        <Panel title="Active version" description={v ? `v${v.version_number} · ${v.original_filename ?? v.origin}` : undefined}>
          {!v ? (
            <EmptyState title="No versions yet">Upload a file to create the first version.</EmptyState>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <Stat label="Rows" value={fmtInt(v.row_count)} />
                <Stat label="Columns" value={fmtInt(v.column_count)} />
                <Stat label="Missing cells" value={s ? fmtPct(s.missing_cell_pct) : "—"} tone={s && s.missing_cell_pct > 5 ? "warn" : undefined} />
                <Stat label="Duplicate rows" value={s ? fmtPct(s.duplicate_row_pct) : "—"} tone={s && s.duplicate_row_pct > 1 ? "warn" : undefined} />
              </div>
              <div className="mt-5 border-t border-line pt-4">
                <KV
                  cols={3}
                  items={[
                    ["Status", <StatusBadge key="s" status={v.status} />],
                    ["Ingested", fmtDate(v.created_at)],
                    ["Size", fmtBytes(v.size_bytes)],
                    ["Malformed rows", <span key="m" className={v.malformed_rows ? "text-warn" : ""}>{fmtInt(v.malformed_rows)}</span>],
                    ["Ingestion time", fmtDuration(v.ingestion_duration_ms)],
                    ["Freshness", s?.freshness_seconds !== undefined && s?.freshness_seconds !== null ? `${fmtSeconds(s.freshness_seconds)} old` : ds.freshness_column ? "—" : "no freshness column"],
                    ["Checksum", <code key="c" className="font-mono text-xs text-muted" title={v.checksum ?? ""}>{v.checksum?.slice(0, 16)}…</code>],
                    ["Schema fingerprint", <code key="f" className="font-mono text-xs text-muted">{v.schema_fingerprint}</code>],
                    ["Known good", v.is_known_good ? "yes" : "no"],
                  ]}
                />
              </div>
              {v.parse_warnings.length > 0 && (
                <ul className="mt-4 space-y-1 rounded-md border border-warn/30 bg-warn/[0.05] p-3 text-sm text-muted">
                  {v.parse_warnings.map((w, i) => (
                    <li key={i}>⚠ {w}</li>
                  ))}
                </ul>
              )}
            </>
          )}
        </Panel>
        <Panel title="Open incidents" bodyClassName="p-0">
          {incidents.isLoading ? (
            <div className="p-4">
              <LoadingBlock rows={2} />
            </div>
          ) : !incidents.data?.items.length ? (
            <EmptyState icon={<ShieldAlert className="h-5 w-5" />} title="No open incidents" className="py-8" />
          ) : (
            <ul className="divide-y divide-line">
              {incidents.data.items.map((i) => (
                <li key={i.id}>
                  <Link to={`/incidents/${i.id}`} className="flex flex-wrap items-center gap-2 px-4 py-3 hover:bg-raised">
                    <UrgencyTag urgency={i.priority.urgency} />
                    <SeverityBadge severity={i.severity} />
                    <span className="min-w-0 flex-1 truncate text-base text-fg">{i.title}</span>
                    <span className="text-sm text-faint">{fmtRelative(i.last_seen_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
      <div className="space-y-4">
        <Panel title="About">
          <KV
            cols={1}
            items={[
              ["Description", ds.description || <span className="text-faint">No description</span>],
              ["Owner", ds.owner || <span className="text-faint">Unassigned</span>],
              ["Criticality", <Badge key="c" tone={ds.criticality === "critical" ? "crit" : ds.criticality === "high" ? "warn" : "neutral"}>{ds.criticality}</Badge>],
              ["Primary key", ds.primary_key.length ? <code key="pk" className="font-mono text-sm">{ds.primary_key.join(", ")}</code> : <span className="text-faint">Not set</span>],
              ["Freshness column", ds.freshness_column ? <code key="fc" className="font-mono text-sm">{ds.freshness_column}</code> : <span className="text-faint">Not set</span>],
              ["Tags", ds.tags.length ? <span key="t" className="flex flex-wrap gap-1">{ds.tags.map((t) => <Badge key={t}>{t}</Badge>)}</span> : <span className="text-faint">None</span>],
            ]}
          />
        </Panel>
        <Panel
          title="Downstream impact"
          description="What depends on this dataset in the lineage graph"
          actions={
            <ButtonLink to={`/lineage?node=${impact.data?.sources?.[0] ?? ""}`} size="sm" variant="ghost" icon={<GitBranch className="h-3.5 w-3.5" />}>
              Lineage
            </ButtonLink>
          }
          bodyClassName="p-0"
        >
          {impact.isLoading ? (
            <div className="p-4">
              <LoadingBlock rows={3} />
            </div>
          ) : !impact.data?.affected.length ? (
            <EmptyState title="No registered dependents" className="py-8">
              Declare transformations, reports or consumers in the lineage view so incidents can show their reach.
            </EmptyState>
          ) : (
            <ul className="divide-y divide-line">
              {impact.data.affected.map((a) => {
                const T = NODE_TYPE[a.type] ?? NODE_TYPE.dataset;
                return (
                  <li key={a.node_id} className="flex items-center gap-3 px-4 py-2.5">
                    <T.icon className="h-4 w-4 shrink-0 text-faint" aria-hidden />
                    <span className="min-w-0 flex-1 truncate text-base">{a.name}</span>
                    <span className="font-mono text-2xs text-faint">depth {a.depth}</span>
                    <Badge tone={a.impact === "confirmed" ? "crit" : "warn"}>{a.impact}</Badge>
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
