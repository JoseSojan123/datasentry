import dagre from "@dagrejs/dagre";

export const NODE_W = 204;
export const NODE_H = 64;

export function layoutGraph(nodes: { id: number }[], edges: { source_id: number; target_id: number }[], dir: "LR" | "TB" = "LR") {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: dir, nodesep: dir === "LR" ? 22 : 36, ranksep: dir === "LR" ? 56 : 48, marginx: 10, marginy: 10 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of nodes) g.setNode(String(n.id), { width: NODE_W, height: NODE_H });
  for (const e of edges) if (g.hasNode(String(e.source_id)) && g.hasNode(String(e.target_id))) g.setEdge(String(e.source_id), String(e.target_id));
  dagre.layout(g);
  const pos: Record<number, { x: number; y: number }> = {};
  for (const n of nodes) {
    const p = g.node(String(n.id));
    pos[n.id] = { x: (p?.x ?? 0) - NODE_W / 2, y: (p?.y ?? 0) - NODE_H / 2 };
  }
  return pos;
}
