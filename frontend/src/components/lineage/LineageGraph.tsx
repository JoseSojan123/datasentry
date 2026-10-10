import { Background, Controls, Handle, MarkerType, Position, ReactFlow, ReactFlowProvider, useReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/base.css";
import { motion } from "framer-motion";
import { memo, useEffect, useMemo } from "react";
import { cn } from "@/lib/cn";
import { useMediaQuery } from "@/lib/hooks";
import { useMotion } from "@/lib/motion";
import type { LineageEdge, LineageNode } from "@/lib/types";
import { useChartColors } from "../charts/colors";
import { layoutGraph, NODE_H, NODE_W } from "./layout";
import { NODE_TYPE, PROVENANCE } from "./meta";

type Mode = "explore" | "investigation";

interface NodeData extends Record<string, unknown> {
  node: LineageNode;
  mode: Mode;
  selected: boolean;
  dimmed: boolean;
  contained: boolean;
  reduced: boolean;
  dir: "LR" | "TB";
}

const STEP = 0.32; // seconds between propagation rings

function healthTone(h: string | null | undefined) {
  return h === "failing" ? "bg-crit" : h === "warning" ? "bg-warn" : h === "healthy" ? "bg-ok" : "bg-faint";
}

const LineageNodeView = memo(function LineageNodeView({ data }: NodeProps<Node<NodeData>>) {
  const { node, mode, selected, dimmed, contained, reduced, dir } = data;
  const T = NODE_TYPE[node.node_type] ?? NODE_TYPE.dataset;
  const isSource = mode === "investigation" && node.role === "source";
  const affected = mode === "investigation" && node.role === "affected";
  const confirmed = affected && node.impact === "confirmed";
  const delay = reduced ? 0 : (node.depth ?? 0) * STEP;

  const ring = isSource ? (contained ? "border-ok" : "border-crit") : confirmed ? (contained ? "border-ok/60" : "border-crit/70") : affected ? (contained ? "border-ok/40" : "border-warn/70") : "border-line-strong";
  const tint = isSource ? (contained ? "bg-ok/[0.08]" : "bg-crit/[0.09]") : confirmed ? (contained ? "bg-ok/[0.05]" : "bg-crit/[0.05]") : affected ? (contained ? "bg-ok/[0.04]" : "bg-warn/[0.06]") : "bg-surface";

  return (
    <motion.div
      initial={mode === "investigation" && !reduced ? { opacity: 0.35, scale: 0.97 } : false}
      animate={{ opacity: dimmed ? 0.38 : 1, scale: 1 }}
      transition={{ delay, duration: reduced ? 0 : 0.35, ease: [0.22, 0.8, 0.32, 1] }}
      style={{ width: NODE_W, height: NODE_H }}
      className={cn(
        "relative flex items-center gap-3 rounded-lg border bg-surface px-3 shadow-panel transition-[box-shadow,border-color]",
        ring,
        selected && "ring-2 ring-accent ring-offset-2 ring-offset-bg",
      )}
    >
      <div className={cn("absolute inset-0 rounded-lg", tint)} aria-hidden />
      {isSource && !contained && !reduced && <span className="pointer-events-none absolute -inset-1 animate-pulse-ring rounded-xl border-2 border-crit/50" aria-hidden />}
      <Handle type="target" position={dir === "LR" ? Position.Left : Position.Top} className="!h-1.5 !w-1.5 !min-w-0 !border-0 !bg-line-strong" isConnectable={false} />
      <div className={cn("relative flex h-9 w-9 shrink-0 items-center justify-center rounded-md border", isSource ? (contained ? "border-ok/40 text-ok" : "border-crit/40 text-crit") : "border-line bg-raised text-muted")}>
        <T.icon className="h-4 w-4" aria-hidden />
      </div>
      <div className="relative min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-base font-medium text-fg" title={node.name}>
            {node.name}
          </span>
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 text-2xs text-faint">
          <span className="uppercase tracking-[0.06em]">{T.label}</span>
          <span aria-hidden>·</span>
          <span className={cn(node.criticality === "critical" ? "text-crit" : node.criticality === "high" ? "text-warn" : "")}>{node.criticality}</span>
          {mode === "investigation" && affected && (
            <>
              <span aria-hidden>·</span>
              <span className={cn(contained ? "text-ok" : confirmed ? "text-crit" : "text-warn")}>{contained ? "protected" : node.impact}</span>
            </>
          )}
        </div>
      </div>
      {(node.health || (node.open_incidents ?? 0) > 0) && (
        <div className="relative flex flex-col items-end gap-1">
          {node.health && <span className={cn("h-2 w-2 rounded-full", healthTone(node.health))} title={`health: ${node.health}`} />}
          {(node.open_incidents ?? 0) > 0 && <span className="rounded-sm bg-crit/15 px-1 font-mono text-2xs text-crit">{node.open_incidents}</span>}
        </div>
      )}
      <Handle type="source" position={dir === "LR" ? Position.Right : Position.Bottom} className="!h-1.5 !w-1.5 !min-w-0 !border-0 !bg-line-strong" isConnectable={false} />
    </motion.div>
  );
});

const nodeTypes = { lineage: LineageNodeView };

export interface LineageGraphProps {
  nodes: LineageNode[];
  edges: LineageEdge[];
  mode?: Mode;
  selectedId?: number | null;
  onSelect?: (id: number | null) => void;
  highlight?: Set<number> | null;
  contained?: boolean;
  height?: number | string;
  className?: string;
}

function GraphInner({ nodes, edges, mode = "explore", selectedId, onSelect, highlight, contained = false }: LineageGraphProps) {
  const c = useChartColors();
  const { reduced } = useMotion();
  const narrow = useMediaQuery("(max-width: 640px)");
  const dir: "LR" | "TB" = narrow && nodes.length > 2 ? "TB" : "LR";
  const rf = useReactFlow();
  const depthOf = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, n.depth ?? 0])), [nodes]);
  const impactOf = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, n.impact])), [nodes]);

  const pos = useMemo(() => layoutGraph(nodes, edges, dir), [nodes, edges, dir]);

  const rfNodes: Node<NodeData>[] = useMemo(
    () =>
      nodes.map((n) => ({
        id: String(n.id),
        type: "lineage",
        position: pos[n.id],
        data: { node: n, mode, selected: selectedId === n.id, dimmed: !!highlight && !highlight.has(n.id), contained, reduced, dir },
        draggable: false,
        selectable: true,
        ariaLabel: `${NODE_TYPE[n.node_type]?.label ?? n.node_type} ${n.name}`,
      })),
    [nodes, pos, mode, selectedId, highlight, contained, reduced, dir],
  );

  const rfEdges: Edge[] = useMemo(
    () =>
      edges.map((e) => {
        const onPath = mode === "investigation" && e.on_impact_path;
        const targetImpact = impactOf[e.target_id];
        const color = onPath ? (contained ? c.ok : targetImpact === "confirmed" ? c.crit : c.warn) : c["border-strong"];
        const dimmed = !!highlight && !(highlight.has(e.source_id) && highlight.has(e.target_id));
        return {
          id: String(e.id),
          source: String(e.source_id),
          target: String(e.target_id),
          type: "smoothstep",
          animated: onPath && !contained && !reduced,
          style: {
            stroke: color,
            strokeWidth: onPath ? 2 : 1.4,
            strokeDasharray: onPath && !contained && !reduced ? undefined : PROVENANCE[e.provenance]?.dash,
            opacity: dimmed ? 0.25 : 1,
            transition: "opacity 200ms",
            animationDelay: onPath && !reduced ? `${(depthOf[e.source_id] ?? 0) * STEP}s` : undefined,
          },
          markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
          ariaLabel: `${e.dependency_type} (${e.provenance})`,
          data: { provenance: e.provenance },
        };
      }),
    [edges, mode, impactOf, contained, c, highlight, reduced, depthOf],
  );

  useEffect(() => {
    const t = setTimeout(() => rf.fitView({ padding: 0.08, duration: reduced ? 0 : 300, maxZoom: 1.155 }), 30);
    return () => clearTimeout(t);
  }, [rf, nodes.length, edges.length, dir, reduced]);

  return (
    <ReactFlow
      nodes={rfNodes}
      edges={rfEdges}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.08, maxZoom: 1.155 }}
      minZoom={0.2}
      maxZoom={1.8}
      nodesConnectable={false}
      nodesDraggable={false}
      onNodeClick={(_, n) => onSelect?.(Number(n.id))}
      onPaneClick={() => onSelect?.(null)}
      proOptions={{ hideAttribution: false }}
      panOnScroll={false}
      zoomOnScroll={!narrow}
      preventScrolling={!narrow}
    >
      <Background gap={24} size={1} color={c.border} />
      <Controls showInteractive={false} position="bottom-right" />
    </ReactFlow>
  );
}

export function LineageGraph(props: LineageGraphProps) {
  return (
    <div className={cn("relative w-full overflow-hidden rounded-lg border border-line bg-bg grid-bg", props.className)} style={{ height: props.height ?? 460 }}>
      <ReactFlowProvider>
        <GraphInner {...props} />
      </ReactFlowProvider>
    </div>
  );
}

export function LineageLegend({ mode = "explore", className }: { mode?: Mode; className?: string }) {
  const c = useChartColors();
  return (
    <div className={cn("flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted", className)}>
      {Object.entries(PROVENANCE).map(([k, p]) => (
        <span key={k} className="flex items-center gap-1.5" title={p.description}>
          <svg width="22" height="6" aria-hidden>
            <line x1="0" y1="3" x2="22" y2="3" stroke={c.muted} strokeWidth="1.6" strokeDasharray={p.dash} />
          </svg>
          {p.label}
        </span>
      ))}
      {mode === "investigation" && (
        <>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm border border-crit bg-crit/20" /> Source of incident
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm border border-crit/70" /> Confirmed impact
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm border border-warn/70" /> Potential impact
          </span>
        </>
      )}
    </div>
  );
}
