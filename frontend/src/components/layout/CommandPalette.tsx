import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import { AnimatePresence, motion } from "framer-motion";
import { Boxes, Database, GitBranch, Moon, Plus, Search, ShieldAlert, Sun, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { get, qs } from "@/lib/api";
import { useDebounced } from "@/lib/hooks";
import { useMotion } from "@/lib/motion";
import { useTheme } from "@/lib/theme";
import { NAV } from "./nav";

interface SearchResult {
  datasets: { id: number; name: string; health: string }[];
  models: { id: number; name: string; task: string }[];
  incidents: { id: number; title: string; severity: string; status: string }[];
  lineage_nodes: { id: number; name: string; node_type: string }[];
}

const itemCls = "flex h-9 cursor-pointer items-center gap-2.5 rounded px-2.5 text-base text-muted aria-selected:bg-overlay aria-selected:text-fg";
const groupCls = "[&_[cmdk-group-heading]]:label [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-3";

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const navigate = useNavigate();
  const { resolved, setPref } = useTheme();
  const { reduced } = useMotion();
  const [q, setQ] = useState("");
  const dq = useDebounced(q.trim(), 180);
  const search = useQuery({ queryKey: ["search", dq], queryFn: () => get<SearchResult>(`/search${qs({ q: dq })}`), enabled: open && dq.length >= 2 });

  useEffect(() => {
    if (!open) setQ("");
  }, [open]);

  const go = (to: string) => {
    onOpenChange(false);
    navigate(to);
  };
  const r = search.data;

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-start justify-center px-3 pt-[12vh]">
          <motion.div className="absolute inset-0 bg-black/55" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduced ? 0 : 0.12 }} onClick={() => onOpenChange(false)} />
          <motion.div initial={reduced ? false : { opacity: 0, y: -8, scale: 0.985 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: reduced ? 0 : 0.16 }} className="relative w-full max-w-xl">
            <Command label="Command palette" shouldFilter={!dq || dq.length < 2} className="overflow-hidden rounded-xl border border-line-strong bg-surface shadow-pop" onKeyDown={(e) => e.key === "Escape" && onOpenChange(false)}>
              <div className="flex items-center gap-2 border-b border-line px-3.5">
                <Search className="h-4 w-4 text-faint" aria-hidden />
                <Command.Input autoFocus value={q} onValueChange={setQ} placeholder="Search datasets, incidents, models… or jump to a page" className="h-12 flex-1 bg-transparent text-md text-fg placeholder:text-faint focus:outline-none" />
                <span className="kbd">esc</span>
              </div>
              <Command.List className="max-h-[min(60vh,420px)] overflow-y-auto p-1.5">
                <Command.Empty className="px-3 py-8 text-center text-sm text-muted">{search.isFetching ? "Searching…" : "No matches."}</Command.Empty>
                {r && r.incidents.length > 0 && (
                  <Command.Group heading="Incidents" className={groupCls}>
                    {r.incidents.map((i) => (
                      <Command.Item key={`i${i.id}`} value={`incident ${i.id} ${i.title}`} onSelect={() => go(`/incidents/${i.id}`)} className={itemCls}>
                        <ShieldAlert className={`h-4 w-4 ${i.severity === "critical" ? "text-crit" : "text-warn"}`} />
                        <span className="truncate">{i.title}</span>
                        <span className="ml-auto text-xs text-faint">{i.status}</span>
                      </Command.Item>
                    ))}
                  </Command.Group>
                )}
                {r && r.datasets.length > 0 && (
                  <Command.Group heading="Datasets" className={groupCls}>
                    {r.datasets.map((d) => (
                      <Command.Item key={`d${d.id}`} value={`dataset ${d.id} ${d.name}`} onSelect={() => go(`/datasets/${d.id}`)} className={itemCls}>
                        <Database className="h-4 w-4" />
                        <span className="truncate">{d.name}</span>
                        <span className="ml-auto text-xs text-faint">{d.health}</span>
                      </Command.Item>
                    ))}
                  </Command.Group>
                )}
                {r && r.models.length > 0 && (
                  <Command.Group heading="Models" className={groupCls}>
                    {r.models.map((m) => (
                      <Command.Item key={`m${m.id}`} value={`model ${m.id} ${m.name}`} onSelect={() => go(`/models/${m.id}`)} className={itemCls}>
                        <Boxes className="h-4 w-4" />
                        <span className="truncate">{m.name}</span>
                      </Command.Item>
                    ))}
                  </Command.Group>
                )}
                {r && r.lineage_nodes.length > 0 && (
                  <Command.Group heading="Lineage" className={groupCls}>
                    {r.lineage_nodes.map((n) => (
                      <Command.Item key={`n${n.id}`} value={`node ${n.id} ${n.name}`} onSelect={() => go(`/lineage?node=${n.id}`)} className={itemCls}>
                        <GitBranch className="h-4 w-4" />
                        <span className="truncate">{n.name}</span>
                        <span className="ml-auto text-xs text-faint">{n.node_type.replace("_", " ")}</span>
                      </Command.Item>
                    ))}
                  </Command.Group>
                )}
                <Command.Group heading="Actions" className={groupCls}>
                  <Command.Item value="upload dataset new" onSelect={() => go("/datasets/new")} className={itemCls}>
                    <Upload className="h-4 w-4" /> Upload a dataset
                  </Command.Item>
                  <Command.Item value="load synthetic scenario demo" onSelect={() => go("/datasets/new?tab=scenario")} className={itemCls}>
                    <Plus className="h-4 w-4" /> Load a synthetic anomaly scenario
                  </Command.Item>
                  <Command.Item
                    value="toggle theme dark light"
                    onSelect={() => {
                      setPref(resolved === "dark" ? "light" : "dark");
                      onOpenChange(false);
                    }}
                    className={itemCls}
                  >
                    {resolved === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />} Switch to {resolved === "dark" ? "light" : "dark"} theme
                  </Command.Item>
                </Command.Group>
                <Command.Group heading="Go to" className={groupCls}>
                  {NAV.flatMap((g) => g.items).map((n) => (
                    <Command.Item key={n.to} value={`go ${n.label}`} onSelect={() => go(n.to)} className={itemCls}>
                      <n.icon className="h-4 w-4" />
                      {n.label}
                      <span className="ml-auto flex gap-1">
                        {n.key.split(" ").map((k) => (
                          <span key={k} className="kbd">
                            {k}
                          </span>
                        ))}
                      </span>
                    </Command.Item>
                  ))}
                </Command.Group>
              </Command.List>
            </Command>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
