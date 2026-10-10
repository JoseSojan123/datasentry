import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { CodeBlock } from "@/components/common/Json";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge, StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Callout, EmptyState, ErrorState, Field, Input, LoadingBlock, Meter, Panel, Select, Textarea } from "@/components/ui/primitives";
import { ApiError, get, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtFrac, fmtInt, fmtNum, fmtRelative, humanize } from "@/lib/format";
import type { Dataset, MLModel, Paged } from "@/lib/types";

const SNIPPET = `from datasentry import DataSentry

client = DataSentry(api_url="http://localhost:8000", api_key="dsk_...")
model = client.register_model("credit_default_lr", task="classification", positive_label=1)
client.create_model_version(model.id, "1.0.0",
    input_schema=[{"name": "income", "type": "numeric"}],
    baseline_metrics={"f1": 0.64}, feature_logging="aggregate")
client.log_predictions(model.id, "1.0.0", records)  # record_id, features, prediction, score
client.log_labels(model.id, "1.0.0", labels)        # labels can arrive days later
client.evaluate_model(model.id, "1.0.0")`;

function RegisterDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const datasets = useQuery({ queryKey: ["datasets", "all-min"], queryFn: () => get<Paged<Dataset>>("/datasets?page_size=100&sort=name"), enabled: open });
  const [f, setF] = useState({ name: "", task: "classification", target: "", positive_label: "1", reference_dataset_id: "", criticality: "medium", owner: "", description: "" });
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () =>
      post<MLModel>("/models", {
        name: f.name.trim(),
        task: f.task,
        target: f.target || null,
        positive_label: f.task === "classification" ? f.positive_label || null : null,
        reference_dataset_id: f.reference_dataset_id ? Number(f.reference_dataset_id) : null,
        criticality: f.criticality,
        owner: f.owner || null,
        description: f.description || null,
      }),
    onSuccess: (m) => {
      void qc.invalidateQueries({ queryKey: ["models"] });
      toast.success(`${m.name} registered. Add a version with the SDK to start monitoring.`);
      onClose();
      navigate(`/models/${m.id}`);
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not register the model."),
  });
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Register a model"
      description="Registration records metadata. Versions, predictions and labels are sent from your serving code with the SDK or REST API."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={save.isPending} disabled={!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$/.test(f.name)} onClick={() => save.mutate()}>
            Register
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {error && (
          <Callout tone="crit" className="sm:col-span-2">
            <span role="alert">{error}</span>
          </Callout>
        )}
        <Field label="Name" htmlFor="m_name" hint="Letters, numbers, dot, dash, underscore" className="sm:col-span-2">
          <Input id="m_name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} data-autofocus />
        </Field>
        <Field label="Task" htmlFor="m_task">
          <Select id="m_task" value={f.task} onChange={(e) => setF({ ...f, task: e.target.value })}>
            <option value="classification">Classification</option>
            <option value="regression">Regression</option>
          </Select>
        </Field>
        {f.task === "classification" && (
          <Field label="Positive label" htmlFor="m_pos">
            <Input id="m_pos" value={f.positive_label} onChange={(e) => setF({ ...f, positive_label: e.target.value })} />
          </Field>
        )}
        <Field label="Target" htmlFor="m_target" hint="What the model predicts">
          <Input id="m_target" value={f.target} onChange={(e) => setF({ ...f, target: e.target.value })} />
        </Field>
        <Field label="Training reference dataset" htmlFor="m_ref" hint="Used as the input-drift baseline">
          <Select id="m_ref" value={f.reference_dataset_id} onChange={(e) => setF({ ...f, reference_dataset_id: e.target.value })}>
            <option value="">None</option>
            {datasets.data?.items.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Criticality" htmlFor="m_crit">
          <Select id="m_crit" value={f.criticality} onChange={(e) => setF({ ...f, criticality: e.target.value })}>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="critical">Critical</option>
          </Select>
        </Field>
        <Field label="Owner" htmlFor="m_owner">
          <Input id="m_owner" value={f.owner} onChange={(e) => setF({ ...f, owner: e.target.value })} />
        </Field>
        <Field label="Description" htmlFor="m_desc" className="sm:col-span-2">
          <Textarea id="m_desc" rows={2} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
        </Field>
      </div>
    </Dialog>
  );
}

export default function Models() {
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const q = useQuery({ queryKey: ["models"], queryFn: () => get<{ items: MLModel[] }>("/models") });
  return (
    <>
      <PageHeader
        title="Models"
        description="Input drift, prediction drift and measured performance are tracked separately. Performance needs ground-truth labels, which often arrive days after the prediction."
        actions={
          can("editor") && (
            <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setOpen(true)}>
              Register model
            </Button>
          )
        }
      />
      {q.isError ? (
        <Panel>
          <ErrorState error={q.error} retry={() => q.refetch()} />
        </Panel>
      ) : !q.data ? (
        <LoadingBlock rows={4} />
      ) : q.data.items.length === 0 ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel>
            <EmptyState icon={<Boxes className="h-5 w-5" />} title="No models registered">
              Register a model, then log predictions and labels from your serving code. The SDK example trains a scikit-learn model on the public Breast Cancer Wisconsin dataset and monitors it.
            </EmptyState>
          </Panel>
          <Panel title="Python SDK">
            <CodeBlock code={SNIPPET} language="python" />
          </Panel>
        </div>
      ) : (
        <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {q.data.items.map((m) => {
            const e = m.latest_evaluation;
            const v = m.versions[m.versions.length - 1];
            return (
              <li key={m.id}>
                <Link to={`/models/${m.id}`} className="panel block h-full p-4 transition-colors hover:border-line-strong">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-md font-medium">{m.name}</div>
                      <div className="mt-0.5 text-sm text-muted">
                        {m.task} · {m.versions.length} version{m.versions.length === 1 ? "" : "s"}
                        {v && <span className="font-mono"> · latest {v.version}</span>}
                      </div>
                    </div>
                    {m.open_incidents > 0 ? <Badge tone="crit">{m.open_incidents} open</Badge> : <Badge tone="ok">no incidents</Badge>}
                  </div>
                  <div className="mt-4 grid grid-cols-3 gap-3">
                    <div>
                      <div className="label">Predictions</div>
                      <div className="mt-1 font-mono text-lg">{fmtInt(m.prediction_count)}</div>
                    </div>
                    <div>
                      <div className="label">Latest {e?.metrics?.f1 !== undefined ? "F1" : "metric"}</div>
                      <div className="mt-1 font-mono text-lg">{e?.metrics?.f1 != null ? fmtNum(e.metrics.f1, 3) : e?.metrics?.rmse != null ? fmtNum(e.metrics.rmse) : "—"}</div>
                    </div>
                    <div>
                      <div className="label">Window</div>
                      <div className="mt-1">{e ? <StatusBadge status={e.status} /> : <span className="text-sm text-faint">not evaluated</span>}</div>
                    </div>
                  </div>
                  {e && (
                    <>
                      <div className="mt-4 flex items-center gap-3 text-sm text-muted">
                        <span className="w-24 shrink-0">labels {fmtFrac(e.label_coverage)}</span>
                        <Meter value={e.label_coverage} tone="info" label="Label coverage" />
                      </div>
                      <div className="mt-1.5 text-sm text-faint">
                        performance {humanize(e.performance?.status ?? "unknown")} · input drift in {e.input_drift?.features_drifted ?? 0} feature(s) · {fmtRelative(e.created_at)}
                      </div>
                    </>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
      <RegisterDialog open={open} onClose={() => setOpen(false)} />
    </>
  );
}
