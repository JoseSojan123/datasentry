"""Lineage graph algorithms: traversal, cycle detection, validation and impact paths.

Edges carry a provenance:
  * ``confirmed`` – observed by the platform (e.g. a model version registered against a reference
    dataset, or an SDK call that reported reading/writing a dataset at run time);
  * ``declared``  – entered manually by a user;
  * ``inferred``  – suggested by a heuristic and not yet confirmed.

A downstream node is a *confirmed* impact only when there is a path to it made exclusively of
confirmed edges; otherwise it is a *potential* impact.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

NODE_TYPES = ("dataset", "transformation", "feature_table", "model", "report", "consumer")
PROVENANCE = ("confirmed", "declared", "inferred")


@dataclass
class Node:
    id: int
    type: str
    name: str
    criticality: str = "medium"
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    id: int
    source: int
    target: int
    provenance: str = "declared"
    dependency_type: str = "reads"


class Graph:
    def __init__(self, nodes: list[Node], edges: list[Edge]):
        self.nodes = {n.id: n for n in nodes}
        self.edges = [e for e in edges if e.source in self.nodes and e.target in self.nodes]
        self.dangling = [e for e in edges if e.source not in self.nodes or e.target not in self.nodes]
        self.out: dict[int, list[Edge]] = {n: [] for n in self.nodes}
        self.inc: dict[int, list[Edge]] = {n: [] for n in self.nodes}
        for e in self.edges:
            self.out[e.source].append(e)
            self.inc[e.target].append(e)

    # -- traversal -----------------------------------------------------------
    def _bfs(self, start: int, downstream: bool, max_depth: int | None = None) -> dict[int, dict[str, Any]]:
        """Breadth-first traversal returning, for every reachable node, its depth, one shortest path
        and whether it is reachable through confirmed edges only."""
        adj = self.out if downstream else self.inc
        seen: dict[int, dict[str, Any]] = {}
        q: deque[tuple[int, int, list[int], list[int]]] = deque([(start, 0, [start], [])])
        visited = {start}
        while q:
            node, depth, path, epath = q.popleft()
            if max_depth is not None and depth >= max_depth:
                continue
            for e in adj[node]:
                nxt = e.target if downstream else e.source
                if nxt in visited:
                    continue
                visited.add(nxt)
                seen[nxt] = {"depth": depth + 1, "path": path + [nxt], "edge_path": epath + [e.id]}
                q.append((nxt, depth + 1, path + [nxt], epath + [e.id]))
        confirmed = self._confirmed_reach(start, downstream)
        for nid, info in seen.items():
            info["confirmed"] = nid in confirmed
        return seen

    def _confirmed_reach(self, start: int, downstream: bool) -> set[int]:
        adj = self.out if downstream else self.inc
        reach: set[int] = set()
        stack = [start]
        while stack:
            n = stack.pop()
            for e in adj[n]:
                if e.provenance != "confirmed":
                    continue
                nxt = e.target if downstream else e.source
                if nxt not in reach and nxt != start:
                    reach.add(nxt)
                    stack.append(nxt)
        return reach

    def downstream(self, start: int, max_depth: int | None = None) -> dict[int, dict[str, Any]]:
        return self._bfs(start, True, max_depth)

    def upstream(self, start: int, max_depth: int | None = None) -> dict[int, dict[str, Any]]:
        return self._bfs(start, False, max_depth)

    # -- validation ------------------------------------------------------------
    def find_cycles(self) -> list[list[int]]:
        """Return elementary cycles found by DFS (one representative per back edge)."""
        color = dict.fromkeys(self.nodes, 0)
        parent: dict[int, int] = {}
        cycles: list[list[int]] = []

        for root in self.nodes:
            if color[root]:
                continue
            stack: list[tuple[int, int]] = [(root, 0)]
            color[root] = 1
            while stack:
                node, i = stack[-1]
                outs = self.out[node]
                if i < len(outs):
                    stack[-1] = (node, i + 1)
                    nxt = outs[i].target
                    if color[nxt] == 0:
                        color[nxt] = 1
                        parent[nxt] = node
                        stack.append((nxt, 0))
                    elif color[nxt] == 1:
                        cyc = [nxt]
                        cur = node
                        while cur != nxt:
                            cyc.append(cur)
                            cur = parent[cur]
                        cycles.append(list(reversed(cyc)))
                else:
                    color[node] = 2
                    stack.pop()
        return cycles

    def would_create_cycle(self, source: int, target: int) -> bool:
        if source == target:
            return True
        return source in self.downstream(target) or False

    def validate(self) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        for cyc in self.find_cycles():
            issues.append({"kind": "cycle", "severity": "critical", "nodes": cyc,
                           "message": "Cycle: " + " → ".join(self.nodes[n].name for n in cyc + [cyc[0]])})
        for e in self.dangling:
            issues.append({"kind": "dangling_edge", "severity": "warning", "edge": e.id,
                           "message": f"Edge {e.id} references a node that no longer exists."})
        for n in self.nodes.values():
            ins, outs = self.inc[n.id], self.out[n.id]
            if n.type in ("transformation", "feature_table", "model", "report") and not ins:
                issues.append({"kind": "missing_upstream", "severity": "warning", "node": n.id,
                               "message": f"{n.type.replace('_', ' ').title()} '{n.name}' has no registered inputs; "
                                          "its upstream dependencies are unknown."})
            if n.type in ("transformation", "feature_table") and not outs:
                issues.append({"kind": "missing_downstream", "severity": "info", "node": n.id,
                               "message": f"'{n.name}' has no registered consumers."})
            if not ins and not outs:
                issues.append({"kind": "isolated", "severity": "info", "node": n.id,
                               "message": f"'{n.name}' is not connected to any other node."})
        return {"valid": not any(i["severity"] == "critical" for i in issues), "issues": issues}

    def topological_order(self) -> list[int]:
        indeg = {n: len(self.inc[n]) for n in self.nodes}
        q = deque(sorted(n for n, d in indeg.items() if d == 0))
        order = []
        while q:
            n = q.popleft()
            order.append(n)
            for e in self.out[n]:
                indeg[e.target] -= 1
                if indeg[e.target] == 0:
                    q.append(e.target)
        return order


def impact_of(graph: Graph, source_ids: list[int]) -> dict[str, Any]:
    """All downstream nodes affected by failures at ``source_ids``."""
    affected: dict[int, dict[str, Any]] = {}
    for s in source_ids:
        if s not in graph.nodes:
            continue
        for nid, info in graph.downstream(s).items():
            prev = affected.get(nid)
            if prev is None or info["depth"] < prev["depth"] or (info["confirmed"] and not prev["confirmed"]):
                affected[nid] = {**info, "source": s, "confirmed": info["confirmed"] or bool(prev and prev["confirmed"])}
    nodes = []
    for nid, info in sorted(affected.items(), key=lambda kv: (kv[1]["depth"], kv[0])):
        n = graph.nodes[nid]
        nodes.append({
            "node_id": nid, "type": n.type, "name": n.name, "criticality": n.criticality,
            "depth": info["depth"], "path": info["path"], "edge_path": info["edge_path"],
            "impact": "confirmed" if info["confirmed"] else "potential",
        })
    by_type: dict[str, int] = {}
    for n in nodes:
        by_type[n["type"]] = by_type.get(n["type"], 0) + 1
    return {
        "sources": source_ids,
        "affected": nodes,
        "counts": {
            "total": len(nodes),
            "confirmed": sum(n["impact"] == "confirmed" for n in nodes),
            "potential": sum(n["impact"] == "potential" for n in nodes),
            "models": by_type.get("model", 0),
            "reports": by_type.get("report", 0) + by_type.get("consumer", 0),
            "transformations": by_type.get("transformation", 0) + by_type.get("feature_table", 0),
            "by_type": by_type,
        },
    }
