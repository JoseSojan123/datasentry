from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import bad_request, conflict
from app.db import models as m
from datasentry_core.lineage import Edge, Graph, Node, impact_of


def load_graph(db: Session, workspace_id: int) -> Graph:
    nodes = db.scalars(select(m.LineageNode).where(m.LineageNode.workspace_id == workspace_id))
    edges = db.scalars(select(m.LineageEdge).where(m.LineageEdge.workspace_id == workspace_id))
    return Graph(
        [Node(n.id, n.node_type, n.name, n.criticality, {"dataset_id": n.dataset_id, "model_id": n.model_id}) for n in nodes],
        [Edge(e.id, e.source_id, e.target_id, e.provenance, e.dependency_type) for e in edges],
    )


def node_for_dataset(db: Session, dataset_id: int) -> m.LineageNode | None:
    return db.scalar(select(m.LineageNode).where(m.LineageNode.dataset_id == dataset_id))


def node_for_model(db: Session, model_id: int) -> m.LineageNode | None:
    return db.scalar(select(m.LineageNode).where(m.LineageNode.model_id == model_id))


def dataset_impact(db: Session, ds: m.Dataset) -> dict[str, Any]:
    node = node_for_dataset(db, ds.id)
    if node is None:
        return {"sources": [], "affected": [], "counts": {"total": 0, "confirmed": 0, "potential": 0, "models": 0,
                                                            "reports": 0, "transformations": 0, "by_type": {}}}
    return impact_of(load_graph(db, ds.workspace_id), [node.id])


def add_edge(db: Session, workspace_id: int, source_id: int, target_id: int, dependency_type: str, provenance: str,
             meta: dict[str, Any] | None, user_id: int | None) -> m.LineageEdge:
    src, dst = db.get(m.LineageNode, source_id), db.get(m.LineageNode, target_id)
    if not src or not dst or src.workspace_id != workspace_id or dst.workspace_id != workspace_id:
        raise bad_request("Source and target must be existing lineage nodes in this workspace.")
    if source_id == target_id:
        raise bad_request("A node cannot depend on itself.")
    if db.scalar(select(m.LineageEdge.id).where(m.LineageEdge.source_id == source_id, m.LineageEdge.target_id == target_id)):
        raise conflict("This dependency already exists.")
    g = load_graph(db, workspace_id)
    if g.would_create_cycle(source_id, target_id):
        path = g.downstream(target_id).get(source_id, {}).get("path", [])
        names = " → ".join(g.nodes[n].name for n in path) if path else ""
        raise bad_request(f"Adding {src.name} → {dst.name} would create a cycle" + (f" ({names} → {dst.name})." if names else "."),
                          code="cycle_detected")
    e = m.LineageEdge(workspace_id=workspace_id, source_id=source_id, target_id=target_id,
                      dependency_type=dependency_type, provenance=provenance, meta=meta or {}, created_by=user_id)
    db.add(e)
    db.flush()
    return e


def ensure_edge(db: Session, workspace_id: int, source_id: int, target_id: int, dependency_type: str, provenance: str,
                meta: dict[str, Any] | None = None) -> m.LineageEdge | None:
    """Idempotently record an observed dependency (used for confirmed edges the platform observes)."""
    existing = db.scalar(select(m.LineageEdge).where(m.LineageEdge.source_id == source_id, m.LineageEdge.target_id == target_id))
    if existing:
        if provenance == "confirmed" and existing.provenance != "confirmed":
            existing.provenance = "confirmed"
            existing.meta = {**(existing.meta or {}), **(meta or {}), "confirmed_by_observation": True}
        return existing
    try:
        return add_edge(db, workspace_id, source_id, target_id, dependency_type, provenance, meta, None)
    except Exception:  # cycle or invalid: an observation must not break the caller
        return None
