import { AlertTriangle, Inbox, RotateCw } from "lucide-react";
import { motion } from "framer-motion";
import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/cn";
import { ApiError } from "@/lib/api";
import { useMotion } from "@/lib/motion";
import { Button } from "./Button";

export function Panel({ title, actions, children, className, bodyClassName, description, id }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClassName?: string; description?: ReactNode; id?: string }) {
  return (
    <section className={cn("panel min-w-0", className)} aria-labelledby={title && id ? `${id}-title` : undefined}>
      {(title || actions) && (
        <header className="flex min-h-[44px] flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
          <div className="min-w-0">
            {title && (
              <h2 id={id ? `${id}-title` : undefined} className="text-md font-medium text-fg">
                {title}
              </h2>
            )}
            {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div className={cn("relative overflow-hidden rounded bg-raised", className)} aria-hidden>
      <div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-overlay/80 to-transparent" />
    </div>
  );
}

export function LoadingBlock({ rows = 4, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="space-y-2.5">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className={cn("h-9", i % 3 === 2 && "w-2/3")} />
      ))}
      <span className="sr-only">{label}…</span>
    </div>
  );
}

export function EmptyState({ icon, title, children, action, className }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-12 text-center", className)}>
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg border border-line bg-raised text-faint">{icon ?? <Inbox className="h-5 w-5" />}</div>
      <h3 className="text-md font-medium text-fg">{title}</h3>
      {children && <div className="mt-1 max-w-md text-sm text-muted">{children}</div>}
      {action && <div className="mt-4 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, retry, className }: { error: unknown; retry?: () => void; className?: string }) {
  const e = error instanceof ApiError ? error : null;
  const message = e?.message ?? (error instanceof Error ? error.message : "Something went wrong.");
  return (
    <div role="alert" className={cn("flex flex-col items-center px-6 py-10 text-center", className)}>
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg border border-crit/30 bg-crit/10 text-crit">
        <AlertTriangle className="h-5 w-5" aria-hidden />
      </div>
      <h3 className="text-md font-medium">{e?.status === 404 ? "Not found" : "Could not load this"}</h3>
      <p className="mt-1 max-w-md text-sm text-muted">{message}</p>
      {e?.requestId && <p className="mt-2 font-mono text-2xs text-faint">request {e.requestId}</p>}
      {retry && (
        <Button className="mt-4" size="sm" onClick={retry} icon={<RotateCw className="h-3.5 w-3.5" />}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function Stat({ label, value, hint, tone, className, children }: { label: ReactNode; value: ReactNode; hint?: ReactNode; tone?: "crit" | "warn" | "ok" | "info"; className?: string; children?: ReactNode }) {
  const toneCls = tone ? { crit: "text-crit", warn: "text-warn", ok: "text-ok", info: "text-info" }[tone] : "text-fg";
  return (
    <div className={cn("min-w-0", className)}>
      <div className="label">{label}</div>
      <div className={cn("mt-1.5 font-mono text-2xl font-medium tracking-tight tabular", toneCls)}>{value}</div>
      {hint && <div className="mt-0.5 text-sm text-muted">{hint}</div>}
      {children}
    </div>
  );
}

export function KV({ items, className, cols = 2 }: { items: [ReactNode, ReactNode][]; className?: string; cols?: 1 | 2 | 3 }) {
  return (
    <dl className={cn("grid gap-x-6 gap-y-3", cols === 1 ? "grid-cols-1" : cols === 2 ? "grid-cols-1 sm:grid-cols-2" : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3", className)}>
      {items.map(([k, v], i) => (
        <div key={i} className="min-w-0">
          <dt className="label">{k}</dt>
          <dd className="mt-1 break-words text-base text-fg">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange, className }: { tabs: { id: T; label: ReactNode; count?: number }[]; value: T; onChange: (v: T) => void; className?: string }) {
  const { reduced } = useMotion();
  const id = useId();
  return (
    <div role="tablist" aria-orientation="horizontal" className={cn("-mb-px flex gap-1 overflow-x-auto border-b border-line", className)}>
      {tabs.map((t) => {
        const active = t.id === value;
        return (
          <button
            key={t.id}
            role="tab"
            aria-selected={active}
            id={`${id}-${t.id}`}
            onClick={() => onChange(t.id)}
            onKeyDown={(e) => {
              const i = tabs.findIndex((x) => x.id === value);
              if (e.key === "ArrowRight") onChange(tabs[(i + 1) % tabs.length].id);
              if (e.key === "ArrowLeft") onChange(tabs[(i - 1 + tabs.length) % tabs.length].id);
            }}
            tabIndex={active ? 0 : -1}
            className={cn("relative flex h-10 shrink-0 items-center gap-1.5 px-3 text-base transition-colors", active ? "text-fg" : "text-muted hover:text-fg")}
          >
            {t.label}
            {t.count !== undefined && <span className="rounded-sm bg-overlay px-1 font-mono text-2xs text-muted">{t.count}</span>}
            {active && <motion.span layoutId={`${id}-ind`} transition={reduced ? { duration: 0 } : { type: "spring", stiffness: 500, damping: 40 }} className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-accent" />}
          </button>
        );
      })}
    </div>
  );
}

const fieldCls =
  "w-full rounded border border-line bg-bg px-2.5 text-base text-fg placeholder:text-faint transition-colors hover:border-line-strong focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/25 disabled:opacity-60 aria-[invalid=true]:border-crit";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={cn(fieldCls, "h-8", className)} {...rest} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={cn(fieldCls, "min-h-[80px] py-2", className)} {...rest} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, children, ...rest }, ref) {
  return (
    <select ref={ref} className={cn(fieldCls, "h-8 appearance-none pr-7", className)} style={{ backgroundRepeat: "no-repeat", backgroundSize: "12px", backgroundPosition: "right 8px center", backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")" }} {...rest}>
      {children}
    </select>
  );
});

export function Field({ label, hint, error, children, htmlFor, className, required }: { label: ReactNode; hint?: ReactNode; error?: string; children: ReactNode; htmlFor?: string; className?: string; required?: boolean }) {
  return (
    <div className={cn("min-w-0", className)}>
      <label htmlFor={htmlFor} className="mb-1.5 block text-sm font-medium text-fg">
        {label}
        {required && <span className="ml-0.5 text-crit" aria-hidden>*</span>}
      </label>
      {children}
      {error ? (
        <p role="alert" className="mt-1 text-sm text-crit">
          {error}
        </p>
      ) : (
        hint && <p className="mt-1 text-sm text-muted">{hint}</p>
      )}
    </div>
  );
}

export function Switch({ checked, onChange, label, disabled, id }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean; id?: string }) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn("relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors disabled:opacity-50", checked ? "border-accent bg-accent" : "border-line-strong bg-overlay")}
    >
      <span className={cn("inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform", checked ? "translate-x-[18px]" : "translate-x-[2px]")} />
    </button>
  );
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("font-mono text-sm", className)}>{children}</span>;
}

export function Callout({ tone = "info", title, children, className, icon }: { tone?: "info" | "warn" | "crit" | "ok" | "neutral"; title?: ReactNode; children?: ReactNode; className?: string; icon?: ReactNode }) {
  const t = { info: "border-info/30 bg-info/[0.06]", warn: "border-warn/30 bg-warn/[0.06]", crit: "border-crit/30 bg-crit/[0.06]", ok: "border-ok/30 bg-ok/[0.06]", neutral: "border-line bg-raised" }[tone];
  const ic = { info: "text-info", warn: "text-warn", crit: "text-crit", ok: "text-ok", neutral: "text-muted" }[tone];
  return (
    <div className={cn("flex gap-3 rounded-md border px-3.5 py-3", t, className)}>
      {icon && <div className={cn("mt-0.5 shrink-0", ic)}>{icon}</div>}
      <div className="min-w-0 text-sm text-muted">
        {title && <div className="mb-0.5 text-base font-medium text-fg">{title}</div>}
        {children}
      </div>
    </div>
  );
}

export function Meter({ value, tone = "accent", className, label }: { value: number; tone?: "accent" | "crit" | "warn" | "ok" | "info"; className?: string; label?: string }) {
  const v = Math.max(0, Math.min(1, value));
  const bg = { accent: "bg-accent", crit: "bg-crit", warn: "bg-warn", ok: "bg-ok", info: "bg-info" }[tone];
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-overlay", className)} role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(v * 100)} aria-label={label}>
      <div className={cn("h-full rounded-full", bg)} style={{ width: `${v * 100}%` }} />
    </div>
  );
}
