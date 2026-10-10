import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Pause, Play, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge, StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Callout, EmptyState, ErrorState, Field, Input, LoadingBlock, Panel, Select } from "@/components/ui/primitives";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/Table";
import { ApiError, del, get, patch, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtDuration, fmtRelative, fmtSeconds, humanize } from "@/lib/format";
import type { Dataset, Job, JobExecution, MLModel, Paged } from "@/lib/types";

const INTERVALS: [number, string][] = [
  [900, "Every 15 minutes"],
  [3600, "Hourly"],
  [6 * 3600, "Every 6 hours"],
  [86400, "Daily"],
  [7 * 86400, "Weekly"],
];
const MODE_TEXT: Record<string, string> = {
  embedded: "The scheduler runs inside the API process.",
  worker: "A separate worker process runs due jobs.",
  external: "An external cron calls /api/v1/jobs/run-due. Jobs only run when it fires.",
  off: "Scheduling is disabled on this deployment. Jobs can still be run manually.",
};

function NewJobDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const datasets = useQuery({ queryKey: ["datasets", "all-min"], queryFn: () => get<Paged<Dataset>>("/datasets?page_size=100&sort=name"), enabled: open });
  const models = useQuery({ queryKey: ["models"], queryFn: () => get<{ items: MLModel[] }>("/models"), enabled: open });
  const [type, setType] = useState("monitor");
  const [target, setTarget] = useState("");
  const [interval, setInterval] = useState(86400);
  const [name, setName] = useState("");
  const [retries, setRetries] = useState(2);
  const [error, setError] = useState<string | null>(null);
  const targets: { id: number; label: string }[] =
    type === "model_eval" ? (models.data?.items ?? []).flatMap((m) => m.versions.map((v) => ({ id: v.id, label: `${m.name} v${v.version}` }))) : (datasets.data?.items ?? []).map((d) => ({ id: d.id, label: d.name }));
  const save = useMutation({
    mutationFn: () => {
      const t = targets.find((x) => String(x.id) === target);
      return post("/jobs", { name: name.trim() || `${humanize(type)} · ${t?.label ?? target}`, job_type: type, target_id: Number(target), interval_seconds: interval, max_retries: retries });
    },
    onSuccess: () => {
      toast.success("Job scheduled.");
      void qc.invalidateQueries({ queryKey: ["jobs"] });
      setTarget("");
      setName("");
      onClose();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not create the job."),
  });
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Schedule a job"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!target} loading={save.isPending} onClick={() => save.mutate()}>
            Schedule
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {error && <Callout tone="crit" className="sm:col-span-2">{error}</Callout>}
        <Field label="Job" htmlFor="j_type" className="sm:col-span-2" hint={type === "monitor" ? "Profile, validate, compare and test drift on the active version; opens incidents." : type === "model_eval" ? "Evaluate the last 24 hours of predictions." : undefined}>
          <Select
            id="j_type"
            value={type}
            onChange={(e) => {
              setType(e.target.value);
              setTarget("");
            }}
          >
            <option value="monitor">Full monitoring run</option>
            <option value="validate">Run quality rules</option>
            <option value="profile">Recompute profile</option>
            <option value="drift">Drift against reference</option>
            <option value="model_eval">Model evaluation</option>
          </Select>
        </Field>
        <Field label={type === "model_eval" ? "Model version" : "Dataset"} htmlFor="j_target" className="sm:col-span-2">
          <Select id="j_target" value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">Choose…</option>
            {targets.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Frequency" htmlFor="j_int">
          <Select id="j_int" value={interval} onChange={(e) => setInterval(Number(e.target.value))}>
            {INTERVALS.map(([s, l]) => (
              <option key={s} value={s}>
                {l}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Retries on failure" htmlFor="j_ret" hint="Exponential backoff">
          <Input id="j_ret" type="number" min={0} max={10} value={retries} onChange={(e) => setRetries(Number(e.target.value))} />
        </Field>
        <Field label="Name (optional)" htmlFor="j_name" className="sm:col-span-2">
          <Input id="j_name" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
      </div>
    </Dialog>
  );
}

export default function Jobs() {
  const qc = useQueryClient();
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(1);
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: () => get<{ items: Job[]; scheduler_mode: string }>("/jobs"), refetchInterval: 20_000 });
  const execs = useQuery({ queryKey: ["jobs", "executions", page], queryFn: () => get<Paged<JobExecution>>(`/jobs/executions?page=${page}&page_size=20`), placeholderData: keepPreviousData, refetchInterval: 20_000 });
  const inv = () => void qc.invalidateQueries({ queryKey: ["jobs"] });
  const run = useMutation({
    mutationFn: (j: Job) => post<JobExecution>(`/jobs/${j.id}/run`),
    onSuccess: (x) => {
      if (x.status === "succeeded") toast.success(`Finished in ${fmtDuration(x.duration_ms)}.`);
      else toast.error(`Job ${x.status}: ${x.error ?? ""}`);
      inv();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not run the job."),
  });
  const toggle = useMutation({ mutationFn: (j: Job) => patch(`/jobs/${j.id}`, { enabled: !j.enabled }), onSuccess: inv, onError: (e) => toast.error(e instanceof ApiError ? e.message : "Update failed.") });
  const remove = useMutation({ mutationFn: (j: Job) => del(`/jobs/${j.id}`), onSuccess: () => { toast.success("Job deleted."); inv(); }, onError: (e) => toast.error(e instanceof ApiError ? e.message : "Delete failed.") });
  const mode = jobs.data?.scheduler_mode;

  return (
    <>
      <PageHeader
        title="Jobs"
        description="Scheduled profiling, validation, drift and model evaluation. Each run is locked so it never overlaps itself, and failures retry with backoff."
        actions={
          can("editor") && (
            <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setOpen(true)}>
              Schedule job
            </Button>
          )
        }
      />
      {mode && (
        <Callout tone={mode === "off" || mode === "external" ? "warn" : "neutral"} className="mb-4" icon={<CalendarClock className="h-4 w-4" />}>
          <span className="text-fg">Scheduler mode: {mode}.</span> {MODE_TEXT[mode]}
        </Callout>
      )}
      <div className="space-y-4">
        <Panel title="Scheduled" bodyClassName="p-0">
          {jobs.isError ? (
            <ErrorState error={jobs.error} retry={() => jobs.refetch()} />
          ) : !jobs.data ? (
            <div className="p-4">
              <LoadingBlock />
            </div>
          ) : jobs.data.items.length === 0 ? (
            <EmptyState icon={<CalendarClock className="h-5 w-5" />} title="No scheduled jobs">
              Schedule a daily monitoring run for a dataset, or an evaluation for a model version.
            </EmptyState>
          ) : (
            <Table label="Scheduled jobs">
              <thead>
                <tr>
                  <Th>Job</Th>
                  <Th>Every</Th>
                  <Th>Last run</Th>
                  <Th>Next run</Th>
                  <Th align="right">Failures in a row</Th>
                  {can("editor") && <Th />}
                </tr>
              </thead>
              <tbody>
                {jobs.data.items.map((j) => (
                  <Tr key={j.id}>
                    <Td>
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{j.name}</span>
                        {!j.enabled && <Badge>paused</Badge>}
                        {j.running && <Badge tone="info">running</Badge>}
                      </div>
                      <div className="text-xs text-faint">{humanize(j.job_type)}</div>
                    </Td>
                    <Td className="whitespace-nowrap text-sm">{fmtSeconds(j.interval_seconds)}</Td>
                    <Td className="whitespace-nowrap">
                      {j.last_status ? <StatusBadge status={j.last_status} /> : <span className="text-sm text-faint">never</span>}
                      {j.last_run_at && <div className="text-xs text-faint">{fmtRelative(j.last_run_at)}</div>}
                    </Td>
                    <Td className="whitespace-nowrap text-sm text-muted">
                      {j.enabled ? fmtRelative(j.next_run_at) : "—"}
                      {j.pending_retry_attempt && <div className="text-xs text-warn">retry {j.pending_retry_attempt} pending</div>}
                    </Td>
                    <Td align="right" mono className={j.consecutive_failures ? "text-crit" : "text-faint"}>
                      {j.consecutive_failures}
                    </Td>
                    {can("editor") && (
                      <Td align="right" className="whitespace-nowrap">
                        <Button size="icon" variant="ghost" aria-label={`Run ${j.name} now`} title="Run now" disabled={j.running} loading={run.isPending && run.variables?.id === j.id} onClick={() => run.mutate(j)}>
                          {!(run.isPending && run.variables?.id === j.id) && <Play className="h-3.5 w-3.5" />}
                        </Button>
                        <Button size="icon" variant="ghost" aria-label={j.enabled ? `Pause ${j.name}` : `Resume ${j.name}`} title={j.enabled ? "Pause" : "Resume"} onClick={() => toggle.mutate(j)}>
                          {j.enabled ? <Pause className="h-3.5 w-3.5" /> : <CalendarClock className="h-3.5 w-3.5" />}
                        </Button>
                        <Button size="icon" variant="ghost" aria-label={`Delete ${j.name}`} title="Delete" onClick={() => remove.mutate(j)}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </Td>
                    )}
                  </Tr>
                ))}
              </tbody>
            </Table>
          )}
        </Panel>
        <Panel title="Recent executions" bodyClassName="p-0">
          {!execs.data ? (
            <div className="p-4">
              <LoadingBlock />
            </div>
          ) : execs.data.items.length === 0 ? (
            <EmptyState title="No executions yet" className="py-8" />
          ) : (
            <>
              <Table label="Job executions">
                <thead>
                  <tr>
                    <Th>Job</Th>
                    <Th>Status</Th>
                    <Th>Trigger</Th>
                    <Th align="right">Attempt</Th>
                    <Th align="right">Duration</Th>
                    <Th>Started</Th>
                    <Th>Result</Th>
                  </tr>
                </thead>
                <tbody>
                  {execs.data.items.map((x) => (
                    <Tr key={x.id}>
                      <Td className="text-sm">{humanize(x.job_type)}</Td>
                      <Td>
                        <StatusBadge status={x.status} />
                      </Td>
                      <Td className="text-sm text-muted">{x.trigger}</Td>
                      <Td align="right" mono>
                        {x.attempt}
                      </Td>
                      <Td align="right" mono>
                        {fmtDuration(x.duration_ms)}
                      </Td>
                      <Td className="whitespace-nowrap text-sm text-muted">{fmtDate(x.started_at)}</Td>
                      <Td className="max-w-[320px] truncate font-mono text-xs text-muted" title={x.error ?? JSON.stringify(x.result)}>
                        {x.error ? <span className="text-crit">{x.error}</span> : JSON.stringify(x.result)}
                      </Td>
                    </Tr>
                  ))}
                </tbody>
              </Table>
              <div className="border-t border-line">
                <Pagination page={execs.data.page} pages={execs.data.pages} total={execs.data.total} onPage={setPage} />
              </div>
            </>
          )}
        </Panel>
      </div>
      <NewJobDialog open={open} onClose={() => setOpen(false)} />
    </>
  );
}
