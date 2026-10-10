import { cn } from "@/lib/cn";

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("h-6 w-6", className)} aria-hidden>
      <path d="M16 4.5 6.5 8.7v6.8c0 5.9 4 10.5 9.5 12 5.5-1.5 9.5-6.1 9.5-12V8.7L16 4.5Z" fill="rgb(var(--accent) / 0.12)" stroke="rgb(var(--accent))" strokeWidth="2" strokeLinejoin="round" />
      <path d="M10.5 17.2h3.2l1.6-4.2 2.6 7.2 1.6-3H22" fill="none" stroke="rgb(var(--text))" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Logo({ className, compact }: { className?: string; compact?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <LogoMark />
      {!compact && (
        <span className="text-lg font-semibold tracking-tight">
          Data<span className="text-accent">Sentry</span>
        </span>
      )}
    </span>
  );
}
