import { useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { CheckCircle2, ChevronDown, CircleDashed, Play, ShieldCheck, ThumbsDown, ThumbsUp, XCircle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Badge, StatusBadge, type Tone } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Callout, Field, Textarea } from "@/components/ui/primitives";
import { ApiError, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { fmtDate, humanize } from "@/lib/format";
import { useMotion } from "@/lib/motion";
import type { Incident, Proposal } from "@/lib/types";

const RISK: Record<string, Tone> = { low: "ok", medium: "warn", high: "crit" };
const STATUS_LABEL: Record<string, string> = {
  proposed: "awaiting approval",
  approved: "approved, not run",
  recommended_only: "recommendation only",
  executing: "executing",
  completed: "executed",
  verified: "executed and verified",
  verification_failed: "executed, verification failed",
  failed: "failed",
  rejected: "rejected",
};

export function RemediationCard({ p, showIncident, onExecuted, defaultOpen }: { p: Proposal; showIncident?: boolean; onExecuted?: (r: { incident: Incident }) => void; defaultOpen?: boolean }) {
  const qc = useQueryClient();
  const { can } = useAuth();
  const { reduced } = useMotion();
  const [open, setOpen] = useState(defaultOpen ?? p.status === "approved");
  const [decision, setDecision] = useState<"approve" | "reject" | null>(null);
  const [note, setNote] = useState("");
  const blocked = p.preconditions.some((c) => c.blocking && !c.passed);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["incident", p.incident_id] });
    void qc.invalidateQueries({ queryKey: ["investigation", p.incident_id] });
    void qc.invalidateQueries({ queryKey: ["remediations"] });
    void qc.invalidateQueries({ queryKey: ["overview"] });
    void qc.invalidateQueries({ queryKey: ["incidents"] });
  };
  const decide = useMutation({
    mutationFn: (kind: "approve" | "reject") => post(`/remediations/${p.id}/${kind}`, { note: note || null }),
    onSuccess: (_, kind) => {
      toast.success(kind === "approve" ? "Approved. You can run it now." : "Rejected.");
      setDecision(null);
      setNote("");
      refresh();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not record the decision."),
  });
  const run = useMutation({
    mutationFn: () => post<{ proposal: Proposal; execution: any; incident: Incident }>(`/remediations/${p.id}/execute`),
    onSuccess: (r) => {
      const v = r.execution.verification ?? {};
      if (r.execution.status !== "succeeded") toast.error(`Not completed: ${r.execution.error ?? r.execution.status}`);
      else if (r.incident.status === "resolved") toast.success("Executed and verified. The incident is resolved.");
      else if (v.applicable && !v.passed) toast.warning("Executed, but verification still finds problems. The incident stays open.");
      else toast.success("Executed.");
      refresh();
      onExecuted?.(r);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Execution failed."),
  });

  const lastExec = p.executions?.[p.executions.length - 1];
  return (
    <motion.article layout={!reduced} className={cn("rounded-lg border bg-surface", p.status === "verified" ? "border-ok/40" : p.status === "proposed" || p.status === "approved" ? "border-line-strong" : "border-line")}>
      <button className="flex w-full items-start gap-3 px-4 py-3 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
        <div className={cn("mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border", p.status === "verified" ? "border-ok/40 text-ok" : "border-line text-muted")}>
          {p.status === "verified" ? <ShieldCheck className="h-4 w-4" /> : p.status === "failed" || p.status === "verification_failed" ? <XCircle className="h-4 w-4 text-crit" /> : <CircleDashed className="h-4 w-4" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-base font-medium text-fg">{p.title}</span>
            <Badge tone={RISK[p.risk_level]}>{p.risk_level} risk</Badge>
            {p.changes_data ? <Badge tone="warn">writes a new version</Badge> : <Badge>no data change</Badge>}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
            <StatusBadge status={p.status} label={STATUS_LABEL[p.status] ?? humanize(p.status)} />
            <span className="text-faint">{p.execution_mode} mode</span>
            {showIncident && p.incident_title && (
              <Link to={`/incidents/${p.incident_id}`} onClick={(e) => e.stopPropagation()} className="link truncate">
                {p.incident_title}
              </Link>
            )}
          </div>
        </div>
        <ChevronDown className={cn("mt-1 h-4 w-4 shrink-0 text-faint transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open && (
        <div className="space-y-4 border-t border-line px-4 py-4">
          <p className="text-sm text-muted">{p.description}</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <div className="label mb-1">Why</div>
              <p className="text-sm text-fg">{p.reason}</p>
            </div>
            <div>
              <div className="label mb-1">Expected outcome</div>
              <p className="text-sm text-fg">{p.expected_outcome}</p>
            </div>
            <div>
              <div className="label mb-1">Rollback</div>
              <p className="text-sm text-fg">{p.rollback}</p>
            </div>
            {Object.keys(p.params).length > 0 && (
              <div>
                <div className="label mb-1">Parameters</div>
                <code className="block break-words font-mono text-xs text-muted">{JSON.stringify(p.params)}</code>
              </div>
            )}
          </div>
          {p.preconditions.length > 0 && (
            <div>
              <div className="label mb-1.5">Preconditions</div>
              <ul className="space-y-1.5">
                {p.preconditions.map((c) => (
                  <li key={c.name} className="flex items-start gap-2 text-sm">
                    {c.passed ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ok" aria-label="passed" /> : <XCircle className={cn("mt-0.5 h-4 w-4 shrink-0", c.blocking ? "text-crit" : "text-warn")} aria-label={c.blocking ? "failed, blocking" : "failed, not blocking"} />}
                    <span>
                      <span className="text-fg">{c.name}</span> <span className="text-muted">· {c.detail}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {blocked && (p.status === "proposed" || p.status === "approved") && (
            <Callout tone="warn" className="py-2">
              A blocking precondition fails, so this action will be refused if run. It is listed so you can see why it is not safe here.
            </Callout>
          )}
          {lastExec && (
            <div className="rounded-md border border-line bg-bg/50 p-3">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="label">Attempt {lastExec.attempt}</span>
                <StatusBadge status={lastExec.status} />
                <span className="text-xs text-faint">{fmtDate(lastExec.finished_at ?? lastExec.started_at)}</span>
              </div>
              {lastExec.error && <p className="mt-1.5 text-sm text-crit">{lastExec.error}</p>}
              {lastExec.verification?.note && (
                <p className={cn("mt-1.5 text-sm", lastExec.verification.passed ? "text-ok" : lastExec.verification.applicable ? "text-warn" : "text-muted")}>
                  {lastExec.verification.passed ? "✓ " : ""}
                  {lastExec.verification.note}
                </p>
              )}
            </div>
          )}
          {can("editor") && (
            <div className="flex flex-wrap gap-2">
              {p.status === "proposed" && (
                <>
                  <Button size="sm" variant="primary" icon={<ThumbsUp className="h-3.5 w-3.5" />} onClick={() => setDecision("approve")}>
                    Approve
                  </Button>
                  <Button size="sm" variant="ghost" icon={<ThumbsDown className="h-3.5 w-3.5" />} onClick={() => setDecision("reject")}>
                    Reject
                  </Button>
                </>
              )}
              {(p.status === "approved" || p.status === "failed" || p.status === "verification_failed") && (
                <Button size="sm" variant="primary" icon={<Play className="h-3.5 w-3.5" />} loading={run.isPending} onClick={() => run.mutate()}>
                  {p.status === "approved" ? "Run and verify" : "Retry"}
                </Button>
              )}
              {p.status === "approved" && (
                <Button size="sm" variant="ghost" onClick={() => setDecision("reject")}>
                  Reject
                </Button>
              )}
            </div>
          )}
        </div>
      )}
      <Dialog
        open={!!decision}
        onClose={() => setDecision(null)}
        size="sm"
        title={decision === "approve" ? `Approve “${p.title}”?` : `Reject “${p.title}”?`}
        description={decision === "approve" ? "Approval allows execution. Nothing runs until someone presses Run." : "The proposal stays in the incident history as rejected."}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDecision(null)}>
              Cancel
            </Button>
            <Button variant={decision === "approve" ? "primary" : "danger"} loading={decide.isPending} onClick={() => decision && decide.mutate(decision)}>
              {decision === "approve" ? "Approve" : "Reject"}
            </Button>
          </>
        }
      >
        <Field label="Note (optional)" htmlFor={`note-${p.id}`}>
          <Textarea id={`note-${p.id}`} rows={2} value={note} onChange={(e) => setNote(e.target.value)} data-autofocus />
        </Field>
      </Dialog>
    </motion.article>
  );
}
