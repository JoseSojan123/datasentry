import { ChevronRight } from "lucide-react";
import { Fragment, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useDocumentTitle } from "@/lib/hooks";

export function PageHeader({ title, docTitle, description, crumbs, actions, meta }: { title: ReactNode; docTitle?: string; description?: ReactNode; crumbs?: { label: string; to?: string }[]; actions?: ReactNode; meta?: ReactNode }) {
  useDocumentTitle(docTitle ?? (typeof title === "string" ? title : undefined));
  return (
    <header className="mb-5 flex flex-col gap-3 sm:mb-6 lg:flex-row lg:items-end lg:justify-between">
      <div className="min-w-0">
        {crumbs && crumbs.length > 0 && (
          <nav aria-label="Breadcrumb" className="mb-2 flex flex-wrap items-center gap-1 text-sm text-faint">
            {crumbs.map((c, i) => (
              <Fragment key={i}>
                {i > 0 && <ChevronRight className="h-3 w-3" aria-hidden />}
                {c.to ? (
                  <Link to={c.to} className="hover:text-fg">
                    {c.label}
                  </Link>
                ) : (
                  <span aria-current="page">{c.label}</span>
                )}
              </Fragment>
            ))}
          </nav>
        )}
        <h1 className="break-words text-2xl font-semibold tracking-tight text-fg">{title}</h1>
        {description && <p className="mt-1.5 max-w-3xl text-base text-muted">{description}</p>}
        {meta && <div className="mt-2.5 flex flex-wrap items-center gap-2">{meta}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
