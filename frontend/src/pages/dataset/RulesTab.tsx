import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ListChecks, Pencil, Play, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { CodeBlock } from "@/components/common/Json";
import { SeverityBadge, StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Callout, EmptyState, ErrorState, Field, Input, LoadingBlock, Panel, Select, Switch, Textarea } from "@/components/ui/primitives";
import { Table, Td, Th, Tr } from "@/components/ui/Table";
import { ApiError, del, get, patch, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtPct, fmtRelative, humanize } from "@/lib/format";
import type { Dataset, Rule, Version } from "@/lib/types";

interface RuleType {
  rule_type: string;
  config_schema: { properties: Record<string, any>; required?: string[] };
}

const DATASET_LEVEL = new Set(["row_count", "duplicate_rows", "schema", "expectation"]);
const COMPLEX_EXAMPLE: Record<string, string> = {
  expected_columns: JSON.stringify([{ name: "transaction_id", semantic_type: "text", required: true }], null, 2),
  expect: JSON.stringify({ column: "amount", op: "gt", value: 0 }, null, 2),
  when: JSON.stringify({ column: "currency", op: "in", value: ["USD", "EUR"] }, null, 2),
};
const HELP: Record<string, string> = {
  not_null: "Fails rows where any selected column is null.",
  unique: "Fails rows whose value (or combination of values) appears more than once.",
  allowed_values: "Fails non-null values outside an allowed set.",
  range: "Fails numeric values below min or above max.",
  regex: "Fails text values that do not match a pattern. Patterns with nested quantifiers or back-references are rejected to prevent catastrophic backtracking.",
  referential_integrity: "Fails values missing from a column of another dataset's active version.",
  freshness: "Fails when the newest timestamp is older than the allowed age.",
  row_count: "Fails when the number of rows is outside the bounds.",
  duplicate_rows: "Fails exact duplicate rows.",
  schema: "Fails when expected columns are missing or have the wrong type.",
  expectation: "A structured condition evaluated per row (no code execution): comparisons combined with all / any / not.",
};

function scalarKind(p: any): "number" | "integer" | "boolean" | "string" | "list" | "json" {
  const t = p.type ?? p.anyOf?.find((x: any) => x.type && x.type !== "null")?.type;
  if (p.anyOf && p.anyOf.some((x: any) => x.$ref)) return "json";
  if (t === "array") return p.items?.$ref ? "json" : "list";
  if (t === "number" || t === "integer" || t === "boolean" || t === "string") return t;
  return "json";
}

function RuleDialog({ open, onClose, ds, columns, rule }: { open: boolean; onClose: () => void; ds: Dataset; columns: string[]; rule?: Rule | null }) {
  const qc = useQueryClient();
  const types = useQuery({ queryKey: ["rule-types"], queryFn: () => get<{ items: RuleType[] }>("/rule-types"), staleTime: Infinity });
  const [ruleType, setRuleType] = useState(rule?.rule_type ?? "not_null");
  const [name, setName] = useState(rule?.name ?? "");
  const [severity, setSeverity] = useState<string>(rule?.severity ?? "warning");
  const [cols, setCols] = useState<string[]>(rule?.columns ?? []);
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const schema = useMemo(() => types.data?.items.find((t) => t.rule_type === ruleType)?.config_schema, [types.data, ruleType]);

  useEffect(() => {
    if (!open) return;
    setRuleType(rule?.rule_type ?? "not_null");
    setName(rule?.name ?? "");
    setSeverity(rule?.severity ?? "warning");
    setCols(rule?.columns ?? []);
    setError(null);
  }, [open, rule]);

  useEffect(() => {
    if (!schema) return;
    const init: Record<string, string> = {};
    for (const [k, p] of Object.entries(schema.properties)) {
      const existing = rule && rule.rule_type === ruleType ? rule.config[k] : undefined;
      const kind = scalarKind(p);
      const val = existing !== undefined ? existing : p.default;
      if (kind === "json") init[k] = val !== undefined && val !== null ? JSON.stringify(val, null, 2) : schema.required?.includes(k) ? (COMPLEX_EXAMPLE[k] ?? "") : "";
      else if (kind === "list") init[k] = Array.isArray(val) ? val.join(", ") : "";
      else init[k] = val === undefined || val === null ? "" : String(val);
    }
    setValues(init);
  }, [schema, ruleType, rule]);

  const save = useMutation({
    mutationFn: (body: any) => (rule ? patch(`/rules/${rule.id}`, body) : post(`/datasets/${ds.id}/rules`, body)),
    onSuccess: () => {
      toast.success(rule ? "Rule updated." : "Rule created. It runs on the next validation.");
      void qc.invalidateQueries({ queryKey: ["rules", ds.id] });
      void qc.invalidateQueries({ queryKey: ["dataset", ds.id] });
      onClose();
    },
    onError: (e) => setError(e instanceof ApiError ? `${e.message}${Array.isArray(e.details) ? " " + (e.details as any[]).map((d) => `${d.field}: ${d.message}`).join("; ") : ""}` : "Could not save the rule."),
  });

  const submit = () => {
    setError(null);
    if (!schema) return;
    if (!name.trim()) return setError("Give the rule a name.");
    if (!DATASET_LEVEL.has(ruleType) && cols.length === 0) return setError("Select at least one column.");
    const config: Record<string, any> = {};
    for (const [k, p] of Object.entries(schema.properties)) {
      const raw = (values[k] ?? "").trim();
      const kind = scalarKind(p);
      if (raw === "") {
        if (schema.required?.includes(k)) return setError(`${p.title ?? k} is required.`);
        continue;
      }
      if (kind === "number" || kind === "integer") {
        const n = Number(raw);
        if (Number.isNaN(n)) return setError(`${p.title ?? k} must be a number.`);
        config[k] = kind === "integer" ? Math.round(n) : n;
      } else if (kind === "boolean") config[k] = raw === "true";
      else if (kind === "list") config[k] = raw.split(",").map((s) => s.trim()).filter(Boolean);
      else if (kind === "json") {
        try {
          config[k] = JSON.parse(raw);
        } catch {
          return setError(`${p.title ?? k} must be valid JSON.`);
        }
      } else config[k] = raw;
    }
    const body: any = { name: name.trim(), severity, columns: cols, config };
    if (!rule) body.rule_type = ruleType;
    save.mutate(body);
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={rule ? "Edit rule" : "New quality rule"}
      description="Rules are validated against a typed configuration on the server. Nothing you enter is executed as code."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} loading={save.isPending}>
            {rule ? "Save changes" : "Create rule"}
          </Button>
        </>
      }
    >
      {!types.data ? (
        <LoadingBlock rows={4} />
      ) : (
        <div className="space-y-4">
          {error && (
            <Callout tone="crit" className="py-2">
              <span role="alert">{error}</span>
            </Callout>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Rule type" htmlFor="rule_type" hint={HELP[ruleType]} className="sm:col-span-2">
              <Select id="rule_type" value={ruleType} disabled={!!rule} onChange={(e) => setRuleType(e.target.value)}>
                {types.data.items.map((t) => (
                  <option key={t.rule_type} value={t.rule_type}>
                    {humanize(t.rule_type)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Name" htmlFor="rule_name">
              <Input id="rule_name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. amount is positive" data-autofocus />
            </Field>
            <Field label="Severity when it fails" htmlFor="rule_sev">
              <Select id="rule_sev" value={severity} onChange={(e) => setSeverity(e.target.value)}>
                <option value="info">Info</option>
                <option value="warning">Warning</option>
                <option value="critical">Critical</option>
              </Select>
            </Field>
          </div>
          <fieldset>
            <legend className="mb-1.5 text-sm font-medium">Columns {DATASET_LEVEL.has(ruleType) && <span className="font-normal text-faint">(optional for this rule type)</span>}</legend>
            <div className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto rounded border border-line bg-bg p-2">
              {columns.map((c) => {
                const on = cols.includes(c);
                return (
                  <button key={c} type="button" aria-pressed={on} onClick={() => setCols(on ? cols.filter((x) => x !== c) : [...cols, c])} className={`rounded-sm border px-2 py-0.5 font-mono text-xs transition-colors ${on ? "border-accent bg-accent/15 text-fg" : "border-line text-muted hover:border-line-strong"}`}>
                    {c}
                  </button>
                );
              })}
            </div>
          </fieldset>
          {schema && (
            <div className="grid gap-4 sm:grid-cols-2">
              {Object.entries(schema.properties).map(([k, p]) => {
                const kind = scalarKind(p);
                const id = `cfg_${k}`;
                const label = (
                  <>
                    {p.title ?? humanize(k)}
                    {schema.required?.includes(k) && <span className="ml-0.5 text-crit">*</span>}
                  </>
                );
                if (kind === "boolean")
                  return (
                    <div key={k} className="flex items-center justify-between gap-3 rounded border border-line px-3 py-2">
                      <label htmlFor={id} className="text-sm">
                        {label}
                      </label>
                      <Switch id={id} label={p.title ?? k} checked={values[k] === "true"} onChange={(v) => setValues({ ...values, [k]: String(v) })} />
                    </div>
                  );
                if (kind === "json")
                  return (
                    <Field key={k} label={label} htmlFor={id} className="sm:col-span-2" hint={k === "expect" || k === "when" ? 'Operators: eq, ne, lt, le, gt, ge, in, not_in, is_null, not_null, matches. Combine with {"all": [...]}, {"any": [...]} or {"not": {...}}.' : "JSON"}>
                      <Textarea id={id} rows={5} className="font-mono text-sm" value={values[k] ?? ""} onChange={(e) => setValues({ ...values, [k]: e.target.value })} spellCheck={false} />
                    </Field>
                  );
                return (
                  <Field key={k} label={label} htmlFor={id} hint={kind === "list" ? "Comma-separated" : p.description}>
                    <Input id={id} inputMode={kind === "number" || kind === "integer" ? "decimal" : undefined} value={values[k] ?? ""} onChange={(e) => setValues({ ...values, [k]: e.target.value })} className={kind === "string" ? "font-mono" : undefined} />
                  </Field>
                );
              })}
            </div>
          )}
        </div>
      )}
    </Dialog>
  );
}

export function RulesTab({ ds }: { ds: Dataset }) {
  const qc = useQueryClient();
  const { can } = useAuth();
  const rules = useQuery({ queryKey: ["rules", ds.id], queryFn: () => get<{ items: Rule[] }>(`/datasets/${ds.id}/rules`) });
  const version = useQuery({ queryKey: ["version", ds.current_version_id], queryFn: () => get<Version>(`/versions/${ds.current_version_id}`), enabled: !!ds.current_version_id });
  const [dialog, setDialog] = useState<{ open: boolean; rule: Rule | null }>({ open: false, rule: null });
  const [confirmDelete, setConfirmDelete] = useState<Rule | null>(null);

  const toggle = useMutation({
    mutationFn: (r: Rule) => patch(`/rules/${r.id}`, { enabled: !r.enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["rules", ds.id] }),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not update the rule."),
  });
  const remove = useMutation({
    mutationFn: (r: Rule) => del(`/rules/${r.id}`),
    onSuccess: () => {
      toast.success("Rule deleted.");
      setConfirmDelete(null);
      void qc.invalidateQueries({ queryKey: ["rules", ds.id] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not delete the rule."),
  });
  const run = useMutation({
    mutationFn: () => post<{ summary: { passed: number; failed: number; errored: number } }>(`/datasets/${ds.id}/validate`, {}),
    onSuccess: (r) => {
      toast.success(`Validation finished: ${r.summary.passed} passed, ${r.summary.failed} failed, ${r.summary.errored} errored.`);
      void qc.invalidateQueries({ queryKey: ["rules", ds.id] });
      void qc.invalidateQueries({ queryKey: ["check-runs", ds.id] });
      void qc.invalidateQueries({ queryKey: ["dataset", ds.id] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Validation failed to run."),
  });

  const columns = (version.data?.columns ?? []).map((c) => c.name);

  return (
    <>
      <Panel
        title="Quality rules"
        description="Evaluated on every new version and on demand. A failing rule contributes a finding to the incident for that version."
        actions={
          can("editor") && (
            <>
              <Button size="sm" icon={<Play className="h-3.5 w-3.5" />} loading={run.isPending} disabled={!ds.current_version_id || !rules.data?.items.length} onClick={() => run.mutate()}>
                Run now
              </Button>
              <Button size="sm" variant="primary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setDialog({ open: true, rule: null })} disabled={!ds.current_version_id}>
                Add rule
              </Button>
            </>
          )
        }
        bodyClassName="p-0"
      >
        {rules.isError ? (
          <ErrorState error={rules.error} retry={() => rules.refetch()} />
        ) : !rules.data ? (
          <div className="p-4">
            <LoadingBlock />
          </div>
        ) : rules.data.items.length === 0 ? (
          <EmptyState icon={<ListChecks className="h-5 w-5" />} title="No rules yet">
            Profiling still runs on every version. Add rules for the guarantees your consumers rely on, such as keys being unique or amounts being positive.
          </EmptyState>
        ) : (
          <Table label="Rules">
            <thead>
              <tr>
                <Th>Rule</Th>
                <Th>Type</Th>
                <Th>Columns</Th>
                <Th>Severity</Th>
                <Th>Last result</Th>
                <Th align="right">Failing</Th>
                <Th align="center">Enabled</Th>
                {can("editor") && <Th />}
              </tr>
            </thead>
            <tbody>
              {rules.data.items.map((r) => (
                <Tr key={r.id}>
                  <Td className="min-w-[180px]">
                    <div className="font-medium text-fg">{r.name}</div>
                    {r.last_result && <div className="line-clamp-2 max-w-md text-sm text-muted">{r.last_result.explanation}</div>}
                  </Td>
                  <Td className="whitespace-nowrap text-sm text-muted">{humanize(r.rule_type)}</Td>
                  <Td className="font-mono text-xs text-muted">{r.columns.join(", ") || "—"}</Td>
                  <Td>
                    <SeverityBadge severity={r.severity} />
                  </Td>
                  <Td className="whitespace-nowrap">
                    {r.last_result ? (
                      <span className="flex items-center gap-2">
                        <StatusBadge status={r.last_result.status} />
                        <span className="text-xs text-faint">{fmtRelative(r.last_result.created_at)}</span>
                      </span>
                    ) : (
                      <span className="text-sm text-faint">not run</span>
                    )}
                  </Td>
                  <Td align="right" mono className={r.last_result?.status === "fail" ? "text-crit" : "text-muted"}>
                    {fmtPct(r.last_result?.failure_pct)}
                  </Td>
                  <Td align="center">
                    <Switch label={`Enable ${r.name}`} checked={r.enabled} disabled={!can("editor")} onChange={() => toggle.mutate(r)} />
                  </Td>
                  {can("editor") && (
                    <Td align="right" className="whitespace-nowrap">
                      <Button size="icon" variant="ghost" aria-label={`Edit ${r.name}`} onClick={() => setDialog({ open: true, rule: r })}>
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button size="icon" variant="ghost" aria-label={`Delete ${r.name}`} onClick={() => setConfirmDelete(r)}>
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
      <RuleDialog open={dialog.open} rule={dialog.rule} onClose={() => setDialog({ open: false, rule: null })} ds={ds} columns={columns} />
      <Dialog
        open={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        size="sm"
        title="Delete this rule?"
        description={`“${confirmDelete?.name}” and its execution history will be removed. Past incidents keep their findings.`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmDelete(null)}>
              Cancel
            </Button>
            <Button variant="danger" loading={remove.isPending} onClick={() => confirmDelete && remove.mutate(confirmDelete)}>
              Delete rule
            </Button>
          </>
        }
      >
        <CodeBlock code={JSON.stringify(confirmDelete?.config ?? {}, null, 2)} copy={false} />
      </Dialog>
    </>
  );
}
