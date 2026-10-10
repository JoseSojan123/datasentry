import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Bell, CheckCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { get, post } from "@/lib/api";
import { cn } from "@/lib/cn";
import { fmtRelative } from "@/lib/format";
import { useMotion } from "@/lib/motion";
import type { Notification, Paged } from "@/lib/types";

export function NotificationsButton() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { reduced } = useMotion();
  const q = useQuery({ queryKey: ["notifications"], queryFn: () => get<Paged<Notification> & { unread: number }>("/notifications?page_size=15"), refetchInterval: 30_000 });
  const readAll = useMutation({ mutationFn: () => post("/notifications/read-all"), onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }) });
  const readOne = useMutation({ mutationFn: (id: number) => post(`/notifications/${id}/read`), onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }) });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const unread = q.data?.unread ?? 0;
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen((v) => !v)} aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`} aria-expanded={open} className="relative flex h-8 w-8 items-center justify-center rounded text-muted hover:bg-overlay hover:text-fg">
        <Bell className="h-4 w-4" />
        {unread > 0 && <span className="absolute right-1 top-1 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-crit px-0.5 font-mono text-[9px] font-semibold text-white">{unread > 9 ? "9+" : unread}</span>}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div initial={reduced ? false : { opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: reduced ? 0 : 0.14 }} className="fixed inset-x-2 top-14 z-40 rounded-lg border border-line-strong bg-surface shadow-pop sm:absolute sm:inset-x-auto sm:right-0 sm:top-10 sm:w-96">
            <div className="flex items-center justify-between border-b border-line px-3.5 py-2.5">
              <span className="text-base font-medium">Notifications</span>
              <button disabled={!unread} onClick={() => readAll.mutate()} className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg disabled:opacity-40">
                <CheckCheck className="h-3.5 w-3.5" /> Mark all read
              </button>
            </div>
            <ul className="max-h-[60vh] overflow-y-auto py-1">
              {q.data?.items.length === 0 && <li className="px-4 py-8 text-center text-sm text-muted">No notifications yet. Incidents and job failures appear here.</li>}
              {q.data?.items.map((n) => (
                <li key={n.id}>
                  <button
                    onClick={() => {
                      if (!n.read) readOne.mutate(n.id);
                      setOpen(false);
                      if (n.link) navigate(n.link);
                    }}
                    className="flex w-full gap-3 px-3.5 py-2.5 text-left hover:bg-raised"
                  >
                    <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", n.read ? "bg-transparent" : n.severity === "critical" ? "bg-crit" : n.severity === "warning" ? "bg-warn" : "bg-info")} aria-hidden />
                    <span className="min-w-0">
                      <span className={cn("block truncate text-base", n.read ? "text-muted" : "text-fg")}>{n.title}</span>
                      <span className="line-clamp-2 text-sm text-faint">{n.body}</span>
                      <span className="mt-0.5 block text-2xs text-faint">{fmtRelative(n.created_at)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
