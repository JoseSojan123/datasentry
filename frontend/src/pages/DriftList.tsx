import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Waves } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { SeverityBadge } from "@/components/ui/Badge";
import { Callout, EmptyState, ErrorState, LoadingBlock, Meter, Panel } from "@/components/ui/primitives";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/Table";
import { get } from "@/lib/api";
import { fmtFrac, fmtRelative } from "@/lib/format";
import type { DriftEvaluation, Paged } from "@/lib/types";

export default function DriftList() {
  const [page, setPage] = useState(1);
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["drift", "all", page], queryFn: () => get<Paged<DriftEvaluation>>(`/drift?page=${page}&page_size=25`), placeholderData: keepPreviousData });
  return (
    <>
      <PageHeader title="Drift" description="Distribution changes between a reference and a current version, per column. Model input and prediction drift are on each model's page." />
      <Callout tone="neutral" className="mb-4">
        A feature is marked as drifted only when its effect size (PSI for numbers, Jensen–Shannon distance for categories) crosses the warning threshold and the corrected KS or chi-square test is significant. A large effect without significance is reported as inconclusive.
      </Callout>
      <Panel bodyClassName="p-0">
        {q.isError ? (
          <ErrorState error={q.error} retry={() => q.refetch()} />
        ) : !q.data ? (
          <div className="p-4">
            <LoadingBlock rows={6} />
          </div>
        ) : q.data.items.length === 0 ? (
          <EmptyState icon={<Waves className="h-5 w-5" />} title="No drift evaluations yet">
            Upload a second version of a dataset, or run an evaluation from a dataset's Drift tab.
          </EmptyState>
        ) : (
          <>
            <Table label="Drift evaluations">
              <thead>
                <tr>
                  <Th>Dataset</Th>
                  <Th>Severity</Th>
                  <Th>Drifted features</Th>
                  <Th align="right">Inconclusive</Th>
                  <Th align="right">Rows ref / cur</Th>
                  <Th>Trigger</Th>
                  <Th align="right">When</Th>
                </tr>
              </thead>
              <tbody>
                {q.data.items.map((e) => (
                  <Tr key={e.id} onClick={() => navigate(`/drift/${e.id}`)}>
                    <Td>
                      <Link to={`/drift/${e.id}`} className="font-medium text-fg hover:text-accent" onClick={(x) => x.stopPropagation()}>
                        {e.dataset_name}
                      </Link>
                      <div className="font-mono text-xs text-faint">#{e.id}</div>
                    </Td>
                    <Td>
                      <SeverityBadge severity={e.overall_severity} />
                    </Td>
                    <Td className="min-w-[160px]">
                      <div className="flex items-center gap-2">
                        <span className="w-12 font-mono text-sm">
                          {e.summary.features_drifted}/{e.summary.features_evaluated}
                        </span>
                        <Meter value={e.summary.drift_share ?? 0} tone={e.summary.features_drifted ? "crit" : "ok"} label="Drift share" className="max-w-[120px]" />
                        <span className="font-mono text-xs text-faint">{fmtFrac(e.summary.drift_share)}</span>
                      </div>
                    </Td>
                    <Td align="right" mono className="text-muted">
                      {e.summary.features_inconclusive}
                    </Td>
                    <Td align="right" mono className="text-muted">
                      {e.summary.n_reference?.toLocaleString()} / {e.summary.n_current?.toLocaleString()}
                    </Td>
                    <Td className="text-sm text-muted">{e.trigger}</Td>
                    <Td align="right" className="whitespace-nowrap text-sm text-muted">
                      {fmtRelative(e.created_at)}
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <div className="border-t border-line">
              <Pagination page={q.data.page} pages={q.data.pages} total={q.data.total} onPage={setPage} />
            </div>
          </>
        )}
      </Panel>
    </>
  );
}
