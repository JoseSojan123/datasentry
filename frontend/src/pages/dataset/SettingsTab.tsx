import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Callout, Field, Input, Panel, Select, Textarea } from "@/components/ui/primitives";
import { ApiError, del, get, patch, put } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Dataset, Version } from "@/lib/types";

const DRIFT_FIELDS: { key: string; label: string; hint: string; def: number }[] = [
  { key: "psi_warning", label: "PSI warning", hint: "Numeric effect size; 0.1 is a common convention", def: 0.1 },
  { key: "psi_critical", label: "PSI critical", hint: "0.25 is a common convention", def: 0.25 },
  { key: "js_warning", label: "JS distance warning", hint: "Categorical effect size (base 2, 0–1)", def: 0.1 },
  { key: "js_critical", label: "JS distance critical", hint: "", def: 0.2 },
  { key: "alpha", label: "Significance level", hint: "After multiple-testing correction", def: 0.05 },
  { key: "min_samples", label: "Minimum samples", hint: "Below this a feature is reported as insufficient data", def: 30 },
  { key: "missing_warning_pp", label: "Missingness warning (pp)", hint: "Increase in missing %, percentage points", def: 5 },
  { key: "missing_critical_pp", label: "Missingness critical (pp)", hint: "", def: 20 },
];

const csv = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

export function SettingsTab({ ds }: { ds: Dataset }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { can } = useAuth();
  const editable = can("editor");
  const version = useQuery({ queryKey: ["version", ds.current_version_id], queryFn: () => get<Version>(`/versions/${ds.current_version_id}`), enabled: !!ds.current_version_id });
  const columns = (version.data?.columns ?? []).map((c) => c.name);

  const [meta, setMeta] = useState({ description: ds.description ?? "", owner: ds.owner ?? "", domain: ds.domain ?? "", criticality: ds.criticality, tags: ds.tags.join(", "), primary_key: ds.primary_key.join(", "), freshness_column: ds.freshness_column ?? "" });
  const [gate, setGate] = useState<string>(ds.settings?.gate_mode ?? "warn");
  const [drift, setDrift] = useState<Record<string, string>>(() => Object.fromEntries(DRIFT_FIELDS.map((f) => [f.key, String(ds.settings?.drift?.[f.key] ?? f.def)])));
  const [correction, setCorrection] = useState<string>(ds.settings?.drift?.correction ?? "benjamini_hochberg");
  const [policies, setPolicies] = useState<{ column: string; strategy: string; value: string; max_affected_pct: string }[]>(() =>
    Object.entries((ds.settings?.remediation?.missing_value_policies ?? {}) as Record<string, any>).map(([column, p]) => ({ column, strategy: p.strategy, value: p.value ?? "", max_affected_pct: String(p.max_affected_pct ?? 20) })),
  );
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [typed, setTyped] = useState("");

  const done = (msg: string) => {
    toast.success(msg);
    void qc.invalidateQueries({ queryKey: ["dataset", ds.id] });
  };
  const err = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Could not save.");

  const saveMeta = useMutation({
    mutationFn: () =>
      patch(`/datasets/${ds.id}`, {
        description: meta.description || null,
        owner: meta.owner || null,
        domain: meta.domain || null,
        criticality: meta.criticality,
        tags: csv(meta.tags),
        primary_key: csv(meta.primary_key),
        freshness_column: meta.freshness_column || null,
      }),
    onSuccess: () => done("Details saved."),
    onError: err,
  });
  const saveMonitoring = useMutation({
    mutationFn: () => {
      const d: Record<string, any> = { correction };
      for (const f of DRIFT_FIELDS) {
        const n = Number(drift[f.key]);
        if (Number.isNaN(n)) throw new ApiError(400, "invalid", `${f.label} must be a number.`);
        d[f.key] = f.key === "min_samples" ? Math.round(n) : n;
      }
      const mvp: Record<string, any> = {};
      for (const p of policies) {
        if (!p.column) continue;
        mvp[p.column] = { strategy: p.strategy, max_affected_pct: Number(p.max_affected_pct) || 20, ...(p.strategy === "constant" ? { value: p.value } : {}) };
      }
      return put(`/datasets/${ds.id}/settings`, { gate_mode: gate, drift: d, remediation: { ...(ds.settings?.remediation ?? {}), missing_value_policies: mvp } });
    },
    onSuccess: () => done("Monitoring settings saved. They apply from the next evaluation."),
    onError: err,
  });
  const remove = useMutation({
    mutationFn: () => del(`/datasets/${ds.id}?confirm=${encodeURIComponent(ds.name)}`),
    onSuccess: () => {
      toast.success(`${ds.name} deleted.`);
      void qc.invalidateQueries();
      navigate("/datasets");
    },
    onError: err,
  });

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel title="Details">
        <fieldset disabled={!editable} className="grid gap-4 sm:grid-cols-2">
          <Field label="Description" htmlFor="s_desc" className="sm:col-span-2">
            <Textarea id="s_desc" rows={2} value={meta.description} onChange={(e) => setMeta({ ...meta, description: e.target.value })} />
          </Field>
          <Field label="Owner" htmlFor="s_owner">
            <Input id="s_owner" value={meta.owner} onChange={(e) => setMeta({ ...meta, owner: e.target.value })} />
          </Field>
          <Field label="Criticality" htmlFor="s_crit">
            <Select id="s_crit" value={meta.criticality} onChange={(e) => setMeta({ ...meta, criticality: e.target.value as Dataset["criticality"] })}>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </Select>
          </Field>
          <Field label="Primary key" htmlFor="s_pk" hint="Comma-separated columns">
            <Input id="s_pk" value={meta.primary_key} onChange={(e) => setMeta({ ...meta, primary_key: e.target.value })} />
          </Field>
          <Field label="Freshness column" htmlFor="s_fc">
            <Input id="s_fc" list="s_cols" value={meta.freshness_column} onChange={(e) => setMeta({ ...meta, freshness_column: e.target.value })} />
          </Field>
          <Field label="Domain" htmlFor="s_dom">
            <Input id="s_dom" value={meta.domain} onChange={(e) => setMeta({ ...meta, domain: e.target.value })} />
          </Field>
          <Field label="Tags" htmlFor="s_tags">
            <Input id="s_tags" value={meta.tags} onChange={(e) => setMeta({ ...meta, tags: e.target.value })} />
          </Field>
          <datalist id="s_cols">
            {columns.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </fieldset>
        {editable && (
          <div className="mt-4 flex justify-end">
            <Button variant="primary" loading={saveMeta.isPending} onClick={() => saveMeta.mutate()}>
              Save details
            </Button>
          </div>
        )}
      </Panel>

      <Panel title="Monitoring policy">
        <fieldset disabled={!editable} className="space-y-5">
          <Field label="Validation gate" htmlFor="s_gate" hint={gate === "block" ? "A new version with critical findings is quarantined; the previous version stays active." : "New versions become active; findings open incidents but do not block."}>
            <Select id="s_gate" value={gate} onChange={(e) => setGate(e.target.value)}>
              <option value="warn">Warn only</option>
              <option value="block">Block on critical findings</option>
            </Select>
          </Field>
          <div>
            <div className="label mb-2">Drift thresholds</div>
            <div className="grid gap-3 sm:grid-cols-2">
              {DRIFT_FIELDS.map((f) => (
                <Field key={f.key} label={f.label} htmlFor={`d_${f.key}`} hint={f.hint || undefined}>
                  <Input id={`d_${f.key}`} inputMode="decimal" value={drift[f.key]} onChange={(e) => setDrift({ ...drift, [f.key]: e.target.value })} />
                </Field>
              ))}
              <Field label="Multiple-testing correction" htmlFor="d_corr">
                <Select id="d_corr" value={correction} onChange={(e) => setCorrection(e.target.value)}>
                  <option value="benjamini_hochberg">Benjamini–Hochberg (FDR)</option>
                  <option value="bonferroni">Bonferroni (FWER)</option>
                  <option value="none">None</option>
                </Select>
              </Field>
            </div>
          </div>
          <div>
            <div className="label mb-1">Missing-value policies</div>
            <p className="mb-2 text-sm text-muted">Used by the “apply missing-value policy” remediation. It always writes a new version, and refuses when more rows than the limit would change.</p>
            <div className="space-y-2">
              {policies.map((p, i) => (
                <div key={i} className="grid grid-cols-2 gap-2 rounded border border-line p-2 sm:grid-cols-[1fr_1fr_90px_32px]">
                  <Select aria-label="Column" value={p.column} onChange={(e) => setPolicies(policies.map((x, j) => (j === i ? { ...x, column: e.target.value } : x)))}>
                    <option value="">Column…</option>
                    {columns.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </Select>
                  <Select aria-label="Strategy" value={p.strategy} onChange={(e) => setPolicies(policies.map((x, j) => (j === i ? { ...x, strategy: e.target.value } : x)))}>
                    <option value="mode">Most frequent</option>
                    <option value="median">Median</option>
                    <option value="mean">Mean</option>
                    <option value="constant">Constant</option>
                    <option value="drop_rows">Drop rows</option>
                  </Select>
                  <Input aria-label="Max affected %" title="Maximum % of rows the policy may change" value={p.max_affected_pct} onChange={(e) => setPolicies(policies.map((x, j) => (j === i ? { ...x, max_affected_pct: e.target.value } : x)))} />
                  <Button size="icon" variant="ghost" aria-label="Remove policy" onClick={() => setPolicies(policies.filter((_, j) => j !== i))}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                  {p.strategy === "constant" && <Input aria-label="Constant value" placeholder="Fill value" className="col-span-2 sm:col-span-4" value={p.value} onChange={(e) => setPolicies(policies.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />}
                </div>
              ))}
              {editable && (
                <Button size="sm" variant="ghost" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setPolicies([...policies, { column: "", strategy: "mode", value: "", max_affected_pct: "20" }])}>
                  Add policy
                </Button>
              )}
            </div>
          </div>
        </fieldset>
        {editable && (
          <div className="mt-4 flex justify-end">
            <Button variant="primary" loading={saveMonitoring.isPending} onClick={() => saveMonitoring.mutate()}>
              Save policy
            </Button>
          </div>
        )}
      </Panel>

      {can("admin") && (
        <Panel title="Danger zone" className="border-crit/30 xl:col-span-2">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-muted">Deleting removes the dataset with its versions, profiles, rules, drift evaluations, incidents and its lineage node. The deletion itself is recorded in the audit log.</p>
            <Button variant="danger" icon={<Trash2 className="h-4 w-4" />} onClick={() => setConfirmDelete(true)}>
              Delete dataset
            </Button>
          </div>
        </Panel>
      )}
      <Dialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        size="sm"
        title={`Delete ${ds.name}?`}
        description="This cannot be undone."
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
              Cancel
            </Button>
            <Button variant="danger" disabled={typed !== ds.name} loading={remove.isPending} onClick={() => remove.mutate()}>
              Delete permanently
            </Button>
          </>
        }
      >
        <Callout tone="crit" className="mb-3">
          Type the dataset name to confirm.
        </Callout>
        <Input aria-label="Dataset name" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={ds.name} data-autofocus />
      </Dialog>
    </div>
  );
}
