import type { ReactNode } from "react";

export function TooltipBox({ title, rows }: { title?: ReactNode; rows: { label: ReactNode; value: ReactNode; color?: string }[] }) {
  return (
    <div className="min-w-[140px] rounded-md border border-line-strong bg-surface px-3 py-2 text-sm shadow-pop">
      {title && <div className="mb-1 font-medium text-fg">{title}</div>}
      {rows.map((r, i) => (
        <div key={i} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-muted">
            {r.color && <span className="h-2 w-2 rounded-sm" style={{ background: r.color }} />}
            {r.label}
          </span>
          <span className="font-mono text-fg">{r.value}</span>
        </div>
      ))}
    </div>
  );
}
