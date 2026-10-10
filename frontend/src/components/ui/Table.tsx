import { ChevronLeft, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { fmtInt } from "@/lib/format";
import { Button } from "./Button";

export function Table({ children, className, label }: { children: ReactNode; className?: string; label?: string }) {
  return (
    <div className={cn("-mx-px overflow-x-auto", className)}>
      <table aria-label={label} className="w-full border-collapse text-left text-base">
        {children}
      </table>
    </div>
  );
}

export function Th({ children, className, align }: { children?: ReactNode; className?: string; align?: "right" | "left" | "center" }) {
  return <th scope="col" className={cn("h-9 whitespace-nowrap border-b border-line px-3 text-2xs font-medium uppercase tracking-[0.08em] text-faint first:pl-4 last:pr-4", align === "right" && "text-right", align === "center" && "text-center", className)}>{children}</th>;
}

export function Td({ children, className, align, mono, title }: { children?: ReactNode; className?: string; align?: "right" | "left" | "center"; mono?: boolean; title?: string }) {
  return <td title={title} className={cn("border-b border-line/70 px-3 py-2.5 align-middle first:pl-4 last:pr-4", align === "right" && "text-right", align === "center" && "text-center", mono && "font-mono text-sm", className)}>{children}</td>;
}

export function Tr({ children, className, onClick }: { children: ReactNode; className?: string; onClick?: () => void }) {
  return <tr onClick={onClick} className={cn("transition-colors last:[&>td]:border-b-0", onClick && "cursor-pointer hover:bg-raised", className)}>{children}</tr>;
}

export function Pagination({ page, pages, total, onPage, className }: { page: number; pages: number; total: number; onPage: (p: number) => void; className?: string }) {
  if (pages <= 1) return <div className={cn("px-4 py-2.5 text-sm text-faint", className)}>{fmtInt(total)} {total === 1 ? "item" : "items"}</div>;
  return (
    <nav aria-label="Pagination" className={cn("flex items-center justify-between gap-2 px-4 py-2.5", className)}>
      <span className="text-sm text-faint">
        Page {page} of {pages} · {fmtInt(total)} items
      </span>
      <div className="flex gap-1">
        <Button size="icon" variant="ghost" aria-label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <Button size="icon" variant="ghost" aria-label="Next page" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </nav>
  );
}
