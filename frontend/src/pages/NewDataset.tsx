import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Upload } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { Dropzone } from "@/components/common/Dropzone";
import { MonitoringResult, type MonitoringOutcome } from "@/components/common/MonitoringResult";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Callout, ErrorState, Field, Input, LoadingBlock, Panel, Select, Tabs, Textarea } from "@/components/ui/primitives";
import { ApiError, get, post, upload } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Dataset } from "@/lib/types";

const csvList = (s: string | undefined) =>
  (s ?? "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

const schema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Name the dataset.")
    .max(120)
    .regex(/^[A-Za-z0-9][A-Za-z0-9_.\- ]*$/, "Use letters, numbers, spaces, dots, dashes or underscores; start with a letter or number."),
  description: z.string().max(2000).optional(),
  owner: z.string().max(120).optional(),
  domain: z.string().max(80).optional(),
  tags: z.string().optional(),
  criticality: z.enum(["low", "medium", "high", "critical"]),
  primary_key: z.string().optional(),
  freshness_column: z.string().max(128).optional(),
  encoding: z.string().min(1),
});
type Values = z.infer<typeof schema>;

function UploadForm() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const [result, setResult] = useState<{ dataset: Dataset; monitoring: MonitoringOutcome } | null>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { criticality: "medium", encoding: "utf-8" } });
  const { errors, isSubmitting } = form.formState;

  const onSubmit = form.handleSubmit(async (v) => {
    setServerError(null);
    if (!file) {
      setFileError("Choose a file to upload.");
      return;
    }
    const meta = {
      name: v.name.trim(),
      description: v.description || null,
      owner: v.owner || null,
      domain: v.domain || null,
      tags: csvList(v.tags),
      criticality: v.criticality,
      primary_key: csvList(v.primary_key),
      freshness_column: v.freshness_column || null,
    };
    const fd = new FormData();
    fd.append("file", file);
    fd.append("metadata", JSON.stringify(meta));
    fd.append("encoding", v.encoding);
    setProgress(0);
    try {
      const res = await upload<{ dataset: Dataset; monitoring: MonitoringOutcome }>("/datasets/upload", fd, setProgress);
      setResult(res);
      void qc.invalidateQueries({ queryKey: ["datasets"] });
      void qc.invalidateQueries({ queryKey: ["overview"] });
      toast.success(`${res.dataset.name} ingested and profiled.`);
    } catch (e) {
      setServerError(e instanceof ApiError ? e.message : "Upload failed.");
    } finally {
      setProgress(null);
    }
  });

  if (result) {
    return (
      <Panel title={`${result.dataset.name} · version 1`} description={`${result.dataset.current_version?.row_count?.toLocaleString() ?? "?"} rows, ${result.dataset.current_version?.column_count ?? "?"} columns`}>
        <MonitoringResult result={result.monitoring} datasetId={result.dataset.id} />
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => navigate(`/datasets/${result.dataset.id}`)}>
            Open dataset
          </Button>
          <Button onClick={() => navigate(`/datasets/${result.dataset.id}?tab=rules`)}>Add quality rules</Button>
        </div>
      </Panel>
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="grid gap-4 lg:grid-cols-[1fr_1.1fr]">
      <Panel title="File">
        <Dropzone
          file={file}
          onFile={(f) => {
            setFile(f);
            setFileError(null);
            if (f && !form.getValues("name")) form.setValue("name", f.name.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_.\- ]/g, "_").slice(0, 120));
          }}
          progress={progress}
          disabled={isSubmitting}
        />
        {fileError && (
          <p role="alert" className="mt-1.5 text-sm text-crit">
            {fileError}
          </p>
        )}
        <Field label="Text encoding" htmlFor="encoding" className="mt-4" hint="Used for CSV files. Invalid bytes are reported, not silently dropped.">
          <Select id="encoding" {...form.register("encoding")}>
            <option value="utf-8">UTF-8</option>
            <option value="latin-1">Latin-1 (ISO-8859-1)</option>
          </Select>
        </Field>
        <Callout tone="neutral" className="mt-4">
          The first upload becomes the reference version that later versions are compared and tested for drift against. Do not upload personal data you are not permitted to process.
        </Callout>
      </Panel>
      <Panel title="Details">
        {serverError && (
          <Callout tone="crit" className="mb-4">
            <span role="alert">{serverError}</span>
          </Callout>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" htmlFor="name" error={errors.name?.message} className="sm:col-span-2" required>
            <Input id="name" aria-invalid={!!errors.name} {...form.register("name")} />
          </Field>
          <Field label="Description" htmlFor="description" className="sm:col-span-2">
            <Textarea id="description" rows={2} {...form.register("description")} />
          </Field>
          <Field label="Owner" htmlFor="owner" hint="Team or person accountable">
            <Input id="owner" {...form.register("owner")} />
          </Field>
          <Field label="Criticality" htmlFor="criticality" hint="Weights incident priority">
            <Select id="criticality" {...form.register("criticality")}>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </Select>
          </Field>
          <Field label="Primary key columns" htmlFor="primary_key" hint="Comma-separated; enables key uniqueness checks">
            <Input id="primary_key" placeholder="e.g. transaction_id" {...form.register("primary_key")} />
          </Field>
          <Field label="Freshness column" htmlFor="freshness_column" hint="Timestamp column used to measure staleness">
            <Input id="freshness_column" placeholder="e.g. event_time" {...form.register("freshness_column")} />
          </Field>
          <Field label="Domain" htmlFor="domain">
            <Input id="domain" placeholder="e.g. payments" {...form.register("domain")} />
          </Field>
          <Field label="Tags" htmlFor="tags" hint="Comma-separated">
            <Input id="tags" {...form.register("tags")} />
          </Field>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => navigate("/datasets")}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={isSubmitting} icon={<Upload className="h-4 w-4" />}>
            Upload and profile
          </Button>
        </div>
      </Panel>
    </form>
  );
}

function ScenarioPicker() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["scenarios"], queryFn: () => get<{ items: { name: string; title: string; description: string; injected: { kind: string; column: string | null }[] }[]; label: string }>("/demo/scenarios") });
  const load = useMutation({
    mutationFn: (name: string) => post<{ dataset_id: number; incident_id: number | null; findings: unknown[] }>(`/demo/scenarios/${name}`),
    onSuccess: (r) => {
      void qc.invalidateQueries();
      toast.success(r.incident_id ? `Scenario loaded: ${r.findings.length} finding(s), incident opened.` : "Scenario loaded with no findings.");
      navigate(r.incident_id ? `/incidents/${r.incident_id}` : `/datasets/${r.dataset_id}`);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not load the scenario."),
  });
  if (q.isError) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  if (!q.data) return <LoadingBlock />;
  return (
    <div className="space-y-3">
      <Callout tone="info" icon={<FlaskConical className="h-4 w-4" />}>
        {q.data.label}. Each scenario creates a dataset with a clean reference version and a second version with the listed problem injected, then runs monitoring on it. Use the healthy control to check for false positives.
      </Callout>
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {q.data.items.map((s) => (
          <li key={s.name} className="panel flex flex-col p-4">
            <div className="flex items-start justify-between gap-2">
              <h3 className="text-md font-medium">{s.title}</h3>
              {s.injected.length === 0 && <Badge tone="ok">control</Badge>}
            </div>
            <p className="mt-1 flex-1 text-sm text-muted">{s.description}</p>
            <div className="mt-2 flex flex-wrap gap-1">
              {s.injected.map((i, k) => (
                <Badge key={k}>
                  {i.kind}
                  {i.column ? `: ${i.column}` : ""}
                </Badge>
              ))}
            </div>
            <Button className="mt-3" size="sm" loading={load.isPending && load.variables === s.name} disabled={load.isPending} onClick={() => load.mutate(s.name)}>
              Load scenario
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function NewDataset() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as "upload" | "scenario") ?? "upload";
  const { can } = useAuth();
  return (
    <>
      <PageHeader title="Add a dataset" crumbs={[{ label: "Datasets", to: "/datasets" }, { label: "New" }]} description="Upload a file to register a dataset, or load a labelled synthetic scenario to see detection end to end." />
      {!can("editor") ? (
        <Callout tone="warn">Your role is viewer. Ask an admin for editor access to add datasets.</Callout>
      ) : (
        <>
          <Tabs
            className="mb-5"
            value={tab}
            onChange={(t) => setParams({ tab: t }, { replace: true })}
            tabs={[
              { id: "upload", label: "Upload a file" },
              { id: "scenario", label: "Synthetic scenario" },
            ]}
          />
          {tab === "upload" ? <UploadForm /> : <ScenarioPicker />}
        </>
      )}
    </>
  );
}
