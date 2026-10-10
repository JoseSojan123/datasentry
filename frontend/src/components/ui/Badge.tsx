import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { humanize } from "@/lib/format";

export type Tone = "crit" | "warn" | "info" | "ok" | "neutral" | "accent";

const tones: Record<Tone, string> = {
  crit: "border-crit/35 bg-crit/10 text-crit",
  warn: "border-warn/35 bg-warn/10 text-warn",
  info: "border-info/35 bg-info/10 text-info",
  ok: "border-ok/35 bg-ok/10 text-ok",
  accent: "border-accent/35 bg-accent/10 text-accent",
  neutral: "border-line bg-raised text-muted",
};
const dots: Record<Tone, string> = { crit: "bg-crit", warn: "bg-warn", info: "bg-info", ok: "bg-ok", accent: "bg-accent", neutral: "bg-faint" };

export function Badge({ tone = "neutral", children, className, dot, title }: { tone?: Tone; children: ReactNode; className?: string; dot?: boolean; title?: string }) {
  return (
    <span title={title} className={cn("inline-flex h-5 items-center gap-1.5 whitespace-nowrap rounded-sm border px-1.5 text-xs font-medium", tones[tone], className)}>
      {dot && <span className={cn("h-1.5 w-1.5 rounded-full", dots[tone])} aria-hidden />}
      {children}
    </span>
  );
}

export function toneFor(value: string | null | undefined): Tone {
  switch (value) {
    case "critical":
    case "failing":
    case "failed":
    case "fail":
    case "error":
    case "degraded":
    case "drift":
    case "rejected":
    case "quarantined":
    case "verification_failed":
    case "high":
      return "crit";
    case "warning":
    case "inconclusive":
    case "acknowledged":
    case "investigating":
    case "reopened":
    case "proposed":
    case "medium":
    case "timeout":
    case "partial":
      return "warn";
    case "info":
    case "approved":
    case "running":
    case "executing":
    case "pending":
    case "insufficient_data":
    case "unknown_label":
      return "info";
    case "healthy":
    case "ok":
    case "pass":
    case "succeeded":
    case "success":
    case "resolved":
    case "verified":
    case "active":
    case "no_drift":
    case "low":
      return "ok";
    case "open":
      return "crit";
    default:
      return "neutral";
  }
}

const SEV_LABEL: Record<string, string> = { critical: "Critical", warning: "Warning", info: "Info", none: "None" };

export function SeverityBadge({ severity, className }: { severity: string; className?: string }) {
  return (
    <Badge tone={severity === "none" ? "neutral" : toneFor(severity)} dot className={className}>
      {SEV_LABEL[severity] ?? humanize(severity)}
    </Badge>
  );
}

export function StatusBadge({ status, className, label }: { status: string | null | undefined; className?: string; label?: string }) {
  if (!status) return <Badge className={className}>—</Badge>;
  return (
    <Badge tone={toneFor(status)} className={className}>
      {label ?? humanize(status)}
    </Badge>
  );
}

const HEALTH_LABEL: Record<string, string> = { healthy: "Healthy", warning: "Warning", failing: "Failing", unknown: "Not checked" };

export function HealthIndicator({ health, className, pulse }: { health: string | null | undefined; className?: string; pulse?: boolean }) {
  const h = health ?? "unknown";
  const tone = h === "unknown" ? "neutral" : toneFor(h);
  return (
    <span className={cn("inline-flex items-center gap-2 text-sm", className)}>
      <span className="relative inline-flex h-2 w-2">
        {pulse && h === "failing" && <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-full bg-crit" aria-hidden />}
        <span className={cn("relative inline-flex h-2 w-2 rounded-full", dots[tone])} aria-hidden />
      </span>
      <span className={cn(tone === "neutral" ? "text-muted" : "text-fg")}>{HEALTH_LABEL[h] ?? humanize(h)}</span>
    </span>
  );
}

export function UrgencyTag({ urgency, score }: { urgency: string; score?: number }) {
  const tone: Tone = urgency === "P1" ? "crit" : urgency === "P2" ? "warn" : urgency === "P3" ? "info" : "neutral";
  return (
    <Badge tone={tone} className="font-mono" title={score !== undefined ? `Priority score ${score.toFixed(1)} / 100` : undefined}>
      {urgency}
      {score !== undefined && <span className="opacity-70">{score.toFixed(0)}</span>}
    </Badge>
  );
}
