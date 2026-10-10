from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api import serializers as ser
from app.api.deps import DB, Editor, Viewer, owned
from app.core.errors import bad_request, conflict
from app.db import models as m
from app.services import audit
from app.services import lineage as lsvc
from datasentry_core.lineage import impact_of

router = APIRouter(tags=["lineage"])
NodeType = Literal["dataset", "transformation", "feature_table", "model", "report", "consumer"]


class NodeIn(BaseModel):
    node_type: Literal["transformation", "feature_table", "report", "consumer"]
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(None, max_length=1000)
    criticality: Literal["low", "medium", "high", "critical"] = "medium"
    owner: str | None = Field(None, max_length=120)
    meta: dict[str, Any] = Field(default_factory=dict)


class NodePatch(BaseModel):
    description: str | None = Field(None, max_length=1000)
    criticality: Literal["low", "medium", "high", "critical"] | None = None
    owner: str | None = Field(None, max_length=120)


class EdgeIn(BaseModel):
    source_id: int
    target_id: int
    dependency_type: str = Field("reads", max_length=32)
    provenance: Literal["declared", "inferred"] = Field(
        "declared", description="'confirmed' edges are created only by the platform when it observes a dependency")
    meta: dict[str, Any] = Field(default_factory=dict)


@router.get("/lineage/graph", summary="Full lineage graph with validation issues")
def graph(p: Viewer, db: DB) -> dict[str, Any]:
    nodes = list(db.scalars(select(m.LineageNode).where(m.LineageNode.workspace_id == p.workspace_id).order_by(m.LineageNode.id)))
    edges = list(db.scalars(select(m.LineageEdge).where(m.LineageEdge.workspace_id == p.workspace_id).order_by(m.LineageEdge.id)))
    health = {d.id: d.health for d in db.scalars(select(m.Dataset).where(m.Dataset.workspace_id == p.workspace_id))}
    open_by_ds: dict[int, int] = {}
    open_by_model: dict[int, int] = {}
    for inc in db.scalars(select(m.Incident).where(m.Incident.workspace_id == p.workspace_id,
                                                   m.Incident.status.in_(("open", "acknowledged", "investigating", "reopened")))):
        if inc.dataset_id:
            open_by_ds[inc.dataset_id] = open_by_ds.get(inc.dataset_id, 0) + 1
        if inc.model_id:
            open_by_model[inc.model_id] = open_by_model.get(inc.model_id, 0) + 1
    g = lsvc.load_graph(db, p.workspace_id)
    return {
        "nodes": [{**ser.node(n), "health": health.get(n.dataset_id) if n.dataset_id else None,
                   "open_incidents": open_by_ds.get(n.dataset_id, 0) if n.dataset_id else open_by_model.get(n.model_id, 0)}
                  for n in nodes],
        "edges": [ser.edge(e) for e in edges],
        "validation": g.validate(),
    }


@router.post("/lineage/nodes", status_code=201, summary="Declare a transformation, feature table, report or consumer")
def create_node(body: NodeIn, p: Editor, db: DB) -> dict[str, Any]:
    if db.scalar(select(m.LineageNode.id).where(m.LineageNode.workspace_id == p.workspace_id,
                                                m.LineageNode.node_type == body.node_type, m.LineageNode.name == body.name)):
        raise conflict("A node with this type and name already exists.")
    n = m.LineageNode(workspace_id=p.workspace_id, **body.model_dump())
    db.add(n)
    db.flush()
    audit.record(db, p.workspace_id, "lineage.node_created", "lineage_node", n.id, {"type": n.node_type, "name": n.name}, p)
    db.commit()
    return ser.node(n)


@router.patch("/lineage/nodes/{node_id}", summary="Update node criticality/owner/description")
def patch_node(node_id: int, body: NodePatch, p: Editor, db: DB) -> dict[str, Any]:
    n = owned(db, m.LineageNode, node_id, p, "Lineage node")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(n, k, v)
    if n.dataset_id and body.criticality:
        ds = db.get(m.Dataset, n.dataset_id)
        ds.criticality = body.criticality
    db.commit()
    return ser.node(n)


@router.delete("/lineage/nodes/{node_id}", summary="Delete a declared node and its edges")
def delete_node(node_id: int, p: Editor, db: DB) -> dict[str, Any]:
    n = owned(db, m.LineageNode, node_id, p, "Lineage node")
    if n.dataset_id or n.model_id:
        raise bad_request("Dataset and model nodes are managed automatically; delete the dataset or model instead.")
    audit.record(db, p.workspace_id, "lineage.node_deleted", "lineage_node", n.id, {"name": n.name}, p)
    db.delete(n)
    db.commit()
    return {"deleted": True}


@router.post("/lineage/edges", status_code=201, summary="Declare a dependency (rejected if it would create a cycle)")
def create_edge(body: EdgeIn, p: Editor, db: DB) -> dict[str, Any]:
    e = lsvc.add_edge(db, p.workspace_id, body.source_id, body.target_id, body.dependency_type, body.provenance, body.meta, p.user_id)
    audit.record(db, p.workspace_id, "lineage.edge_created", "lineage_edge", e.id,
                 {"source": body.source_id, "target": body.target_id, "provenance": body.provenance}, p)
    db.commit()
    return ser.edge(e)


@router.delete("/lineage/edges/{edge_id}", summary="Remove a dependency")
def delete_edge(edge_id: int, p: Editor, db: DB) -> dict[str, Any]:
    e = owned(db, m.LineageEdge, edge_id, p, "Lineage edge")
    audit.record(db, p.workspace_id, "lineage.edge_deleted", "lineage_edge", e.id, {}, p)
    db.delete(e)
    db.commit()
    return {"deleted": True}


@router.get("/lineage/nodes/{node_id}/impact", summary="Downstream impact of a node")
def node_impact(node_id: int, p: Viewer, db: DB) -> dict[str, Any]:
    n = owned(db, m.LineageNode, node_id, p, "Lineage node")
    return impact_of(lsvc.load_graph(db, p.workspace_id), [n.id])


@router.get("/lineage/nodes/{node_id}/upstream", summary="Upstream dependencies of a node")
def node_upstream(node_id: int, p: Viewer, db: DB) -> dict[str, Any]:
    n = owned(db, m.LineageNode, node_id, p, "Lineage node")
    g = lsvc.load_graph(db, p.workspace_id)
    up = g.upstream(n.id)
    return {"node_id": n.id, "upstream": [{"node_id": k, "name": g.nodes[k].name, "type": g.nodes[k].type, **v}
                                          for k, v in sorted(up.items(), key=lambda kv: kv[1]["depth"])]}
