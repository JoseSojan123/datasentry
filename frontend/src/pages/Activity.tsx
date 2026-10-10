import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Activity as ActivityIcon } from "lucide-react";
import { useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState, ErrorState, LoadingBlock, Panel, Tabs } from "@/components/ui/primitives";
import { Pagination } from "@/components/ui/Table";
import { get } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtRelative, humanize } from "@/lib/format";
import type { AuditEvent, Paged } from "@/lib/types";

function Feed({ path }: { path: string }) {
  const [page, setPage] = useState(1);
  const q = useQuery({ queryKey: ["feed", path, page], queryFn: () => get<Paged<AuditEvent>>(`${path}?page=${page}&page_size=30`), placeholderData: keepPreviousData });
  if (q.isError) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  if (!q.data) return <div className="p-4"><LoadingBlock rows={8} /></div>;
  if (!q.data.items.length) return <EmptyState icon={<ActivityIcon className="h-5 w-5" />} title="No activity yet" />;
  return (
    <>
      <ul className="divide-y divide-line">
        {q.data.items.map((e) => (
          <li key={e.id} className="flex flex-col gap-1 px-4 py-2.5 sm:flex-row sm:items-center sm:gap-4">
            <code className="w-56 shrink-0 font-mono text-xs text-accent">{e.action}</code>
            <span className="min-w-0 flex-1 truncate text-sm text-muted">
              {humanize(e.entity_type)} {e.entity_id && <span className="font-mono">#{e.entity_id}</span>}
              {Object.keys(e.data ?? {}).length > 0 && <span className="ml-2 font-mono text-xs text-faint">{JSON.stringify(e.data).slice(0, 140)}</span>}
            </span>
            <span className="shrink-0 text-xs text-faint">{e.actor}</span>
            <time className="shrink-0 text-xs text-faint" dateTime={e.created_at} title={fmtDate(e.created_at)}>
              {fmtRelative(e.created_at)}
            </time>
          </li>
        ))}
      </ul>
      <div className="border-t border-line">
        <Pagination page={q.data.page} pages={q.data.pages} total={q.data.total} onPage={setPage} />
      </div>
    </>
  );
}

export default function Activity() {
  const { can } = useAuth();
  const [tab, setTab] = useState<"activity" | "audit">("activity");
  return (
    <>
      <PageHeader title="Activity" description="What happened in this workspace: ingestion, monitoring, incidents and remediation. Admins also see the full audit log, including sign-ins, role changes and API key use." />
      {can("admin") && <Tabs className="mb-4" value={tab} onChange={setTab} tabs={[{ id: "activity", label: "Activity" }, { id: "audit", label: "Audit log" }]} />}
      <Panel bodyClassName="p-0">{tab === "activity" ? <Feed path="/activity" /> : <Feed path="/audit" />}</Panel>
    </>
  );
}
