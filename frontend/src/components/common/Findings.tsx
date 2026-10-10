import { Boxes, Columns3, FileWarning, ListChecks, Waves } from "lucide-react";
import { Link } from "react-router-dom";
import { SeverityBadge } from "@/components/ui/Badge";
import { cn } from "@/lib/cn";
import { humanize } from "@/lib/format";
import type { Finding } from "@/lib/types";

const SRC: Record<string, { icon: typeof Waves; label: string }> = {
  rule: { icon: ListChecks, label: "Rule" },
  drift: { icon: Waves, label: "Drift" },
  schema: { icon: Columns3, label: "Schema / profile" },
  model: { icon: Boxes, label: "Model" },
  ingestion: { icon: FileWarning, label: "Ingestion" },
  freshness: { icon: FileWarning, label: "Freshness" },
};

export function evidenceLink(f: Finding & Record<string, any>, datasetId?: number | null): string | null {
  if (f.drift_evaluation_id) return `/drift/${f.drift_evaluation_id}${f.column ? `?feature=${encodeURIComponent(f.column)}` : ""}`;
  if (f.comparison_id && datasetId) return `/datasets/${datasetId}/compare?comparison=${f.comparison_id}`;
  if (f.check_run_id && datasetId) return `/datasets/${datasetId}?tab=checks&run=${f.check_run_id}`;
  return null;
}

export function FindingRow({ f, datasetId, className }: { f: Finding & Record<string, any>; datasetId?: number | null; className?: string }) {
  const s = SRC[f.source] ?? SRC.schema;
  const link = evidenceLink(f, datasetId);
  return (
    <li className={cn("flex gap-3 px-4 py-3", className)}>
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded border border-line bg-raised text-muted" title={s.label}>
        <s.icon className="h-3.5 w-3.5" aria-hidden />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={f.severity} />
          <span className="text-sm font-medium text-fg">{humanize(f.kind)}</span>
          {f.column && <code className="rounded-sm bg-overlay px-1 font-mono text-xs text-muted">{f.column}</code>}
          {f.rule_name && <span className="text-xs text-faint">rule “{f.rule_name}”</span>}
        </div>
        <p className="mt-1 text-sm leading-relaxed text-muted">{f.message}</p>
      </div>
      {link && (
        <Link to={link} className="link shrink-0 self-start text-sm">
          Evidence
        </Link>
      )}
    </li>
  );
}

export function FindingList({ findings, datasetId, className }: { findings: Finding[]; datasetId?: number | null; className?: string }) {
  return (
    <ul className={cn("divide-y divide-line", className)}>
      {findings.map((f, i) => (
        <FindingRow key={f.id ?? i} f={f} datasetId={datasetId} />
      ))}
    </ul>
  );
}
