import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, GitBranch, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { LineageGraph, LineageLegend } from "@/components/lineage/LineageGraph";
import { NODE_TYPE, PROVENANCE } from "@/components/lineage/meta";
import { Badge, HealthIndicator } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Callout, EmptyState, ErrorState, Field, Input, LoadingBlock, Panel, Select, Textarea } from "@/components/ui/primitives";
import { ApiError, del, get, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useMediaQuery } from "@/lib/hooks";
import type { Impact, LineageEdge, LineageNode } from "@/lib/types";

interface Graph {
  nodes: LineageNode[];
  edges: LineageEdge[];
  validation: { valid: boolean; issues: { kind: string; severity: string; node?: number; message: string }[] };
}

function AddNodeDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ node_type: "transformation", name: "", description: "", criticality: "medium", owner: "" });
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => post<LineageNode>("/lineage/nodes", { ...f, name: f.name.trim(), description: f.description || null, owner: f.owner || null }),
    onSuccess: () => {
      toast.success("Node added.");
      void qc.invalidateQueries({ queryKey: ["lineage"] });
      setF({ ...f, name: "", description: "" });
      onClose();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not add the node."),
  });
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Declare a node"
      description="Datasets and models appear automatically. Declare what consumes them: transformations, feature tables, reports and downstream consumers."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!f.name.trim()} loading={save.isPending} onClick={() => save.mutate()}>
            Add node
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {error && <Callout tone="crit" className="sm:col-span-2">{error}</Callout>}
        <Field label="Type" htmlFor="n_type">
          <Select id="n_type" value={f.node_type} onChange={(e) => setF({ ...f, node_type: e.target.value })}>
            {["transformation", "feature_table", "report", "consumer"].map((t) => (
              <option key={t} value={t}>
                {NODE_TYPE[t].label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Criticality" htmlFor="n_crit">
          <Select id="n_crit" value={f.criticality} onChange={(e) => setF({ ...f, criticality: e.target.value })}>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="critical">Critical</option>
          </Select>
        </Field>
        <Field label="Name" htmlFor="n_name" className="sm:col-span-2">
          <Input id="n_name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} data-autofocus />
        </Field>
        <Field label="Owner" htmlFor="n_owner">
          <Input id="n_owner" value={f.owner} onChange={(e) => setF({ ...f, owner: e.target.value })} />
        </Field>
        <Field label="Description" htmlFor="n_desc" className="sm:col-span-2">
          <Textarea id="n_desc" rows={2} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
        </Field>
      </div>
    </Dialog>
  );
}

function AddEdgeDialog({ open, onClose, nodes, defaultSource }: { open: boolean; onClose: () => void; nodes: LineageNode[]; defaultSource?: number | null }) {
  const qc = useQueryClient();
  const [src, setSrc] = useState<string>("");
  const [tgt, setTgt] = useState<string>("");
  const [dep, setDep] = useState("reads");
  const [prov, setProv] = useState<"declared" | "inferred">("declared");
  const [error, setError] = useState<string | null>(null);
  const source = src || String(defaultSource ?? "");
  const save = useMutation({
    mutationFn: () => post("/lineage/edges", { source_id: Number(source), target_id: Number(tgt), dependency_type: dep, provenance: prov }),
    onSuccess: () => {
      toast.success("Dependency added.");
      void qc.invalidateQueries({ queryKey: ["lineage"] });
      setTgt("");
      onClose();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not add the dependency."),
  });
  const sorted = [...nodes].sort((a, b) => a.name.localeCompare(b.name));
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Declare a dependency"
      description="Edges you add are declared or inferred. Only DataSentry creates confirmed edges, when it observes the dependency itself."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!source || !tgt || source === tgt} loading={save.isPending} onClick={() => save.mutate()}>
            Add dependency
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {error && <Callout tone="crit" className="sm:col-span-2">{error}</Callout>}
        <Field label="Upstream (source)" htmlFor="e_src">
          <Select id="e_src" value={source} onChange={(e) => setSrc(e.target.value)}>
            <option value="">Choose…</option>
            {sorted.map((n) => (
              <option key={n.id} value={n.id}>
                {n.name} ({NODE_TYPE[n.node_type]?.label})
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Downstream (target)" htmlFor="e_tgt">
          <Select id="e_tgt" value={tgt} onChange={(e) => setTgt(e.target.value)}>
            <option value="">Choose…</option>
            {sorted.filter((n) => String(n.id) !== source).map((n) => (
              <option key={n.id} value={n.id}>
                {n.name} ({NODE_TYPE[n.node_type]?.label})
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Dependency type" htmlFor="e_dep">
          <Select id="e_dep" value={dep} onChange={(e) => setDep(e.target.value)}>
            {["reads", "writes", "feeds", "features", "trains", "exports", "joins"].map((d) => (
              <option key={d}>{d}</option>
            ))}
          </Select>
        </Field>
        <Field label="Provenance" htmlFor="e_prov" hint={PROVENANCE[prov].description}>
          <Select id="e_prov" value={prov} onChange={(e) => setProv(e.target.value as "declared" | "inferred")}>
            <option value="declared">Declared</option>
            <option value="inferred">Inferred</option>
          </Select>
        </Field>
        <p className="text-sm text-muted sm:col-span-2">A dependency that would create a cycle is rejected.</p>
      </div>
    </Dialog>
  );
}

export default function Lineage() {
  const qc = useQueryClient();
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const narrow = useMediaQuery("(max-width: 640px)");
  const graph = useQuery({ queryKey: ["lineage", "graph"], queryFn: () => get<Graph>("/lineage/graph") });
  const selected = Number(params.get("node")) || null;
  const impact = useQuery({ queryKey: ["lineage", "impact", selected], queryFn: () => get<Impact>(`/lineage/nodes/${selected}/impact`), enabled: !!selected });
  const [addNode, setAddNode] = useState(false);
  const [addEdge, setAddEdge] = useState(false);

  const select = (id: number | null) => {
    const p = new URLSearchParams(params);
    if (id) p.set("node", String(id));
    else p.delete("node");
    setParams(p, { replace: true });
  };

  const highlight = useMemo(() => {
    if (!selected || !impact.data) return null;
    return new Set<number>([selected, ...impact.data.affected.map((a) => a.node_id)]);
  }, [selected, impact.data]);

  const removeEdge = useMutation({
    mutationFn: (id: number) => del(`/lineage/edges/${id}`),
    onSuccess: () => {
      toast.success("Dependency removed.");
      void qc.invalidateQueries({ queryKey: ["lineage"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not remove."),
  });
  const removeNode = useMutation({
    mutationFn: (id: number) => del(`/lineage/nodes/${id}`),
    onSuccess: () => {
      toast.success("Node removed.");
      select(null);
      void qc.invalidateQueries({ queryKey: ["lineage"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not remove."),
  });

  const g = graph.data;
  const node = g?.nodes.find((n) => n.id === selected);
  const byId = Object.fromEntries((g?.nodes ?? []).map((n) => [n.id, n]));
  const edgesOf = (id: number) => (g?.edges ?? []).filter((e) => e.source_id === id || e.target_id === id);
  const issues = g?.validation.issues.filter((x) => x.severity !== "info") ?? [];

  return (
    <>
      <PageHeader
        title="Lineage"
        description="How datasets flow into transformations, feature tables, models, reports and consumers. Select a node to highlight everything downstream of it."
        actions={
          can("editor") && (
            <>
              <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setAddNode(true)}>
                Node
              </Button>
              <Button size="sm" variant="primary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setAddEdge(true)} disabled={(g?.nodes.length ?? 0) < 2}>
                Dependency
              </Button>
            </>
          )
        }
      />
      {graph.isError ? (
        <Panel>
          <ErrorState error={graph.error} retry={() => graph.refetch()} />
        </Panel>
      ) : !g ? (
        <LoadingBlock rows={8} />
      ) : g.nodes.length === 0 ? (
        <Panel>
          <EmptyState icon={<GitBranch className="h-5 w-5" />} title="The lineage graph is empty">
            Datasets and models are added automatically when you register them. Then declare the transformations and reports that use them.
          </EmptyState>
        </Panel>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
          <div className="min-w-0">
            <LineageGraph nodes={g.nodes} edges={g.edges} selectedId={selected} onSelect={select} highlight={highlight} height={narrow ? 480 : 600} />
            <LineageLegend className="mt-3" />
            {issues.length > 0 && (
              <Callout tone="warn" icon={<AlertTriangle className="h-4 w-4" />} title="Graph validation" className="mt-4">
                <ul className="list-disc pl-4">
                  {issues.map((x, k) => (
                    <li key={k}>{x.message}</li>
                  ))}
                </ul>
              </Callout>
            )}
          </div>
          <Panel title={node ? node.name : "Details"} bodyClassName="space-y-4">
            {!node ? (
              <div className="space-y-3 text-sm text-muted">
                <p>Select a node to see what depends on it.</p>
                <dl className="grid grid-cols-2 gap-2">
                  {Object.entries(NODE_TYPE).map(([k, t]) => (
                    <div key={k} className="flex items-center gap-2 rounded border border-line px-2 py-1.5">
                      <t.icon className="h-3.5 w-3.5 text-faint" />
                      <dt className="text-xs">{t.label}</dt>
                      <dd className="ml-auto font-mono text-xs text-fg">{g.nodes.filter((n) => n.node_type === k).length}</dd>
                    </div>
                  ))}
                </dl>
                <p className="text-xs text-faint">{g.edges.length} dependencies · {g.edges.filter((e) => e.provenance === "confirmed").length} confirmed</p>
              </div>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge>{NODE_TYPE[node.node_type]?.label}</Badge>
                  <Badge tone={node.criticality === "critical" ? "crit" : node.criticality === "high" ? "warn" : "neutral"}>{node.criticality}</Badge>
                  {node.health && <HealthIndicator health={node.health} />}
                </div>
                {node.description && <p className="text-sm text-muted">{node.description}</p>}
                {node.owner && <p className="text-sm text-muted">Owner: {node.owner}</p>}
                {(node.dataset_id || node.model_id) && (
                  <Link to={node.dataset_id ? `/datasets/${node.dataset_id}` : `/models/${node.model_id}`} className="link text-sm">
                    Open {node.dataset_id ? "dataset" : "model"}
                  </Link>
                )}
                <div>
                  <div className="label mb-1.5">Downstream impact</div>
                  {impact.isLoading ? (
                    <LoadingBlock rows={2} />
                  ) : !impact.data?.affected.length ? (
                    <p className="text-sm text-faint">Nothing depends on this node.</p>
                  ) : (
                    <>
                      <p className="mb-2 text-sm text-muted">
                        {impact.data.counts.total} node(s): {impact.data.counts.confirmed} confirmed, {impact.data.counts.potential} potential.
                      </p>
                      <ul className="space-y-1">
                        {impact.data.affected.map((a) => (
                          <li key={a.node_id}>
                            <button onClick={() => select(a.node_id)} className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-sm hover:bg-raised">
                              <span className="font-mono text-2xs text-faint">{a.depth}</span>
                              <span className="min-w-0 flex-1 truncate">{a.name}</span>
                              <Badge tone={a.impact === "confirmed" ? "crit" : "warn"}>{a.impact}</Badge>
                            </button>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                </div>
                <div>
                  <div className="label mb-1.5">Dependencies</div>
                  <ul className="space-y-1">
                    {edgesOf(node.id).map((e) => (
                      <li key={e.id} className="flex items-center gap-1.5 text-sm">
                        <span className="min-w-0 truncate">{byId[e.source_id]?.name}</span>
                        <ArrowRight className="h-3 w-3 shrink-0 text-faint" />
                        <span className="min-w-0 truncate">{byId[e.target_id]?.name}</span>
                        <Badge className="ml-auto shrink-0" tone={e.provenance === "confirmed" ? "ok" : e.provenance === "declared" ? "info" : "neutral"}>
                          {e.provenance}
                        </Badge>
                        {can("editor") && e.provenance !== "confirmed" && (
                          <button aria-label={`Remove dependency ${byId[e.source_id]?.name} to ${byId[e.target_id]?.name}`} onClick={() => removeEdge.mutate(e.id)} className="shrink-0 rounded p-1 text-faint hover:bg-overlay hover:text-crit">
                            <Trash2 className="h-3 w-3" />
                          </button>
                        )}
                      </li>
                    ))}
                    {edgesOf(node.id).length === 0 && <li className="text-sm text-faint">None</li>}
                  </ul>
                </div>
                {can("editor") && (
                  <div className="flex flex-wrap gap-2 border-t border-line pt-3">
                    <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setAddEdge(true)}>
                      Add downstream
                    </Button>
                    {node.node_type !== "dataset" && !node.model_id && (
                      <Button size="sm" variant="danger" icon={<Trash2 className="h-3.5 w-3.5" />} loading={removeNode.isPending} onClick={() => removeNode.mutate(node.id)}>
                        Remove node
                      </Button>
                    )}
                  </div>
                )}
              </>
            )}
          </Panel>
        </div>
      )}
      <AddNodeDialog open={addNode} onClose={() => setAddNode(false)} />
      {g && <AddEdgeDialog open={addEdge} onClose={() => setAddEdge(false)} nodes={g.nodes} defaultSource={selected} />}
    </>
  );
}
