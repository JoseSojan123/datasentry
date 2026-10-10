import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { RemediationCard } from "@/components/common/RemediationCard";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Callout, EmptyState, ErrorState, Field, Input, LoadingBlock, Panel, Switch } from "@/components/ui/primitives";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/Table";
import { ApiError, get, put, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import type { Paged, Proposal } from "@/lib/types";

interface Policy {
  mode: "recommend" | "approval" | "auto";
  auto_allowlist: string[];
  timeout_seconds: number;
  auto_eligible: string[];
}
interface CatalogItem {
  action: string;
  title: string;
  risk: string;
  changes_data: boolean;
  reversible: boolean;
  description: string;
  expected_outcome: string;
  rollback: string;
  auto_eligible: boolean;
}

const MODES: { id: Policy["mode"]; title: string; body: string }[] = [
  { id: "recommend", title: "Recommend only", body: "Proposals are shown with their evidence. Nothing can be executed from DataSentry." },
  { id: "approval", title: "Require approval", body: "An editor approves each proposal, then runs it. Verification decides whether the incident resolves." },
  { id: "auto", title: "Automatic (allowlist)", body: "Low-risk, non-destructive actions you select run immediately when an incident opens. Everything else still needs approval." },
];

function PolicyPanel({ catalog }: { catalog: CatalogItem[] }) {
  const qc = useQueryClient();
  const { can } = useAuth();
  const q = useQuery({ queryKey: ["remediation-policy"], queryFn: () => get<Policy>("/settings/remediation") });
  const [draft, setDraft] = useState<Policy | null>(null);
  useEffect(() => {
    if (q.data) setDraft(q.data);
  }, [q.data]);
  const save = useMutation({
    mutationFn: () => put<Policy>("/settings/remediation", { mode: draft!.mode, auto_allowlist: draft!.auto_allowlist, timeout_seconds: draft!.timeout_seconds }),
    onSuccess: () => {
      toast.success("Remediation policy saved.");
      void qc.invalidateQueries({ queryKey: ["remediation-policy"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not save the policy."),
  });
  if (q.isError) return <ErrorState error={q.error} />;
  if (!draft) return <LoadingBlock rows={3} />;
  const admin = can("admin");
  const titleOf = (a: string) => catalog.find((c) => c.action === a)?.title ?? a;
  return (
    <Panel title="Workspace policy" description={admin ? "Applies to new proposals." : "Only admins can change the policy."}>
      <fieldset disabled={!admin}>
        <legend className="sr-only">Execution mode</legend>
        <div className="grid gap-2 md:grid-cols-3">
          {MODES.map((m) => (
            <label key={m.id} className={cn("cursor-pointer rounded-lg border p-3 transition-colors", draft.mode === m.id ? "border-accent bg-accent/[0.06]" : "border-line hover:border-line-strong")}>
              <input type="radio" name="mode" value={m.id} checked={draft.mode === m.id} onChange={() => setDraft({ ...draft, mode: m.id })} className="sr-only" />
              <div className="flex items-center gap-2 text-base font-medium">
                <span className={cn("h-3 w-3 rounded-full border-2", draft.mode === m.id ? "border-accent bg-accent" : "border-line-strong")} aria-hidden />
                {m.title}
              </div>
              <p className="mt-1 text-sm text-muted">{m.body}</p>
            </label>
          ))}
        </div>
        {draft.mode === "auto" && (
          <div className="mt-4">
            <div className="label mb-2">Actions allowed to run automatically</div>
            <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {draft.auto_eligible.map((a) => {
                const on = draft.auto_allowlist.includes(a);
                return (
                  <li key={a} className="flex items-center justify-between gap-3 rounded border border-line px-3 py-2">
                    <span className="text-sm">{titleOf(a)}</span>
                    <Switch label={`Allow ${titleOf(a)} automatically`} checked={on} onChange={(v) => setDraft({ ...draft, auto_allowlist: v ? [...draft.auto_allowlist, a] : draft.auto_allowlist.filter((x) => x !== a) })} />
                  </li>
                );
              })}
            </ul>
            <p className="mt-2 text-xs text-faint">Only actions that do not modify data are eligible. Data-changing actions always require approval.</p>
          </div>
        )}
        <Field label="Execution timeout (seconds)" htmlFor="rem_to" className="mt-4 max-w-xs">
          <Input id="rem_to" type="number" min={5} max={600} value={draft.timeout_seconds} onChange={(e) => setDraft({ ...draft, timeout_seconds: Number(e.target.value) })} />
        </Field>
      </fieldset>
      {admin && (
        <div className="mt-4 flex justify-end">
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>
            Save policy
          </Button>
        </div>
      )}
    </Panel>
  );
}

const FILTERS: [string, string][] = [
  ["proposed,approved", "Needs action"],
  ["verified,completed", "Done"],
  ["failed,verification_failed", "Failed"],
  ["rejected,recommended_only", "Rejected or advisory"],
  ["", "All"],
];

export default function Remediation() {
  const [filter, setFilter] = useState(FILTERS[0][0]);
  const [page, setPage] = useState(1);
  const catalog = useQuery({ queryKey: ["remediation-catalog"], queryFn: () => get<{ items: CatalogItem[] }>("/remediations/catalog"), staleTime: Infinity });
  const list = useQuery({ queryKey: ["remediations", filter, page], queryFn: () => get<Paged<Proposal>>(`/remediations${qs({ status: filter, page, page_size: 20 })}`), placeholderData: keepPreviousData });
  return (
    <>
      <PageHeader title="Remediation" description="Every action is reversible or writes a new version. An incident is resolved by remediation only when the checks that raised it pass again on the active version." />
      <div className="space-y-4">
        <PolicyPanel catalog={catalog.data?.items ?? []} />
        <Panel title="Proposals" bodyClassName="p-0">
          <div role="tablist" aria-label="Filter proposals" className="flex gap-1 overflow-x-auto border-b border-line px-3 py-2">
            {FILTERS.map(([v, l]) => (
              <button
                key={l}
                role="tab"
                aria-selected={filter === v}
                onClick={() => {
                  setFilter(v);
                  setPage(1);
                }}
                className={cn("h-7 shrink-0 rounded px-2.5 text-sm", filter === v ? "bg-overlay text-fg" : "text-muted hover:text-fg")}
              >
                {l}
              </button>
            ))}
          </div>
          <div className="p-4">
            {list.isError ? (
              <ErrorState error={list.error} retry={() => list.refetch()} />
            ) : !list.data ? (
              <LoadingBlock rows={4} />
            ) : list.data.items.length === 0 ? (
              <EmptyState icon={<Wrench className="h-5 w-5" />} title="Nothing here">
                Proposals are generated when an incident opens.
              </EmptyState>
            ) : (
              <div className="space-y-3">
                {list.data.items.map((p) => (
                  <RemediationCard key={p.id} p={p} showIncident />
                ))}
              </div>
            )}
          </div>
          {list.data && (
            <div className="border-t border-line">
              <Pagination page={list.data.page} pages={list.data.pages} total={list.data.total} onPage={setPage} />
            </div>
          )}
        </Panel>
        <Panel title="Action catalog" description="The only actions DataSentry can take. None deletes data." bodyClassName="p-0">
          {!catalog.data ? (
            <div className="p-4">
              <LoadingBlock rows={4} />
            </div>
          ) : (
            <Table label="Remediation actions">
              <thead>
                <tr>
                  <Th>Action</Th>
                  <Th>Risk</Th>
                  <Th>Data</Th>
                  <Th>Rollback</Th>
                  <Th align="center">Auto-eligible</Th>
                </tr>
              </thead>
              <tbody>
                {catalog.data.items.map((c) => (
                  <Tr key={c.action}>
                    <Td className="min-w-[220px]">
                      <div className="font-medium">{c.title}</div>
                      <div className="text-sm text-muted">{c.description}</div>
                    </Td>
                    <Td>
                      <Badge tone={c.risk === "low" ? "ok" : c.risk === "medium" ? "warn" : "crit"}>{c.risk}</Badge>
                    </Td>
                    <Td className="whitespace-nowrap text-sm text-muted">{c.changes_data ? "new version" : "unchanged"}</Td>
                    <Td className="min-w-[200px] text-sm text-muted">{c.rollback}</Td>
                    <Td align="center">{c.auto_eligible ? <Badge tone="ok">yes</Badge> : <span className="text-faint">no</span>}</Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          )}
        </Panel>
        <Callout tone="neutral">Arbitrary code, SQL or shell commands are never accepted as remediation. Actions come only from the catalog above and run with fixed, validated parameters.</Callout>
      </div>
    </>
  );
}
