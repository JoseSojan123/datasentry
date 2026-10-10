import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Waves } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { SeverityBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState, ErrorState, Field, LoadingBlock, Panel, Select } from "@/components/ui/primitives";
import { Table, Td, Th, Tr } from "@/components/ui/Table";
import { ApiError, get, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtFrac } from "@/lib/format";
import type { Dataset, DriftEvaluation, Paged, Version } from "@/lib/types";

export function DriftTab({ ds }: { ds: Dataset }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { can } = useAuth();
  const evals = useQuery({ queryKey: ["drift", { dataset: ds.id }], queryFn: () => get<Paged<DriftEvaluation>>(`/datasets/${ds.id}/drift?page_size=50`) });
  const versions = useQuery({ queryKey: ["versions", ds.id, "all"], queryFn: () => get<Paged<Version>>(`/datasets/${ds.id}/versions?page_size=100`) });
  const ok = (versions.data?.items ?? []).filter((v) => v.ingestion_status === "succeeded");
  const [ref, setRef] = useState<string>("");
  const [cur, setCur] = useState<string>("");
  const refId = ref || String(ds.reference_version_id ?? ok[ok.length - 1]?.id ?? "");
  const curId = cur || String(ds.current_version_id ?? ok[0]?.id ?? "");

  const run = useMutation({
    mutationFn: () => post<DriftEvaluation>(`/datasets/${ds.id}/drift`, { reference_version_id: Number(refId), current_version_id: Number(curId) }),
    onSuccess: (e) => {
      void qc.invalidateQueries({ queryKey: ["drift"] });
      toast.success(`Drift evaluated: ${e.summary.features_drifted} of ${e.summary.features_evaluated} features drifted.`);
      navigate(`/drift/${e.id}`);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Drift evaluation failed."),
  });

  return (
    <div className="space-y-4">
      {can("editor") && ok.length >= 2 && (
        <Panel title="Run a drift evaluation" description="Compares the distributions of every shared column. Uses the dataset's drift settings.">
          <div className="grid items-end gap-3 sm:grid-cols-[1fr_1fr_auto]">
            <Field label="Reference" htmlFor="ref_v">
              <Select id="ref_v" value={refId} onChange={(e) => setRef(e.target.value)}>
                {ok.map((v) => (
                  <option key={v.id} value={v.id}>
                    v{v.version_number} · {v.row_count?.toLocaleString()} rows{v.id === ds.reference_version_id ? " (reference)" : ""}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Current" htmlFor="cur_v">
              <Select id="cur_v" value={curId} onChange={(e) => setCur(e.target.value)}>
                {ok.map((v) => (
                  <option key={v.id} value={v.id}>
                    v{v.version_number} · {v.row_count?.toLocaleString()} rows{v.id === ds.current_version_id ? " (active)" : ""}
                  </option>
                ))}
              </Select>
            </Field>
            <Button variant="primary" loading={run.isPending} disabled={refId === curId} onClick={() => run.mutate()} icon={<Waves className="h-4 w-4" />}>
              Evaluate
            </Button>
          </div>
        </Panel>
      )}
      <Panel title="Drift history" bodyClassName="p-0">
        {evals.isError ? (
          <ErrorState error={evals.error} retry={() => evals.refetch()} />
        ) : !evals.data ? (
          <div className="p-4">
            <LoadingBlock />
          </div>
        ) : evals.data.items.length === 0 ? (
          <EmptyState icon={<Waves className="h-5 w-5" />} title="No drift evaluations">
            Drift is evaluated automatically when a new version arrives, against the reference version.
          </EmptyState>
        ) : (
          <Table label="Drift evaluations">
            <thead>
              <tr>
                <Th>Evaluation</Th>
                <Th>Severity</Th>
                <Th align="right">Drifted</Th>
                <Th align="right">Inconclusive</Th>
                <Th align="right">Drift share</Th>
                <Th>Trigger</Th>
                <Th>When</Th>
              </tr>
            </thead>
            <tbody>
              {evals.data.items.map((e) => (
                <Tr key={e.id} onClick={() => navigate(`/drift/${e.id}`)}>
                  <Td>
                    <Link to={`/drift/${e.id}`} className="font-mono text-fg hover:text-accent" onClick={(x) => x.stopPropagation()}>
                      #{e.id}
                    </Link>
                    <span className="ml-2 text-xs text-faint">
                      #{e.reference_version_id} → #{e.current_version_id}
                    </span>
                  </Td>
                  <Td>
                    <SeverityBadge severity={e.overall_severity} />
                  </Td>
                  <Td align="right" mono>
                    {e.summary.features_drifted}/{e.summary.features_evaluated}
                  </Td>
                  <Td align="right" mono className="text-muted">
                    {e.summary.features_inconclusive}
                  </Td>
                  <Td align="right" mono>
                    {fmtFrac(e.summary.drift_share)}
                  </Td>
                  <Td className="text-sm text-muted">{e.trigger}</Td>
                  <Td className="whitespace-nowrap text-sm text-muted">{fmtDate(e.created_at)}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Panel>
    </div>
  );
}
