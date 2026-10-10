from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api import serializers as ser
from app.api.deps import DB, Admin, Editor, Paging, Viewer, owned, paged
from app.core.errors import bad_request
from app.db import models as m
from app.services import audit, incidents
from app.services import lineage as lsvc
from app.services import remediation as rsvc
from datasentry_core import remediation as core
from datasentry_core.lineage import impact_of

router = APIRouter(tags=["incidents & remediation"])


@router.get("/incidents", summary="Incidents with filters, search and priority sorting")
def list_incidents(p: Viewer, db: DB, page: Paging, status: str | None = Query(None, description="comma-separated"),
                   severity: str | None = None, dataset_id: int | None = None, model_id: int | None = None,
                   q: str | None = Query(None, max_length=100),
                   sort: Literal["priority", "recent", "oldest"] = "priority") -> dict[str, Any]:
    stmt = select(m.Incident).where(m.Incident.workspace_id == p.workspace_id)
    if status:
        stmt = stmt.where(m.Incident.status.in_([s.strip() for s in status.split(",")]))
    if severity:
        stmt = stmt.where(m.Incident.severity == severity)
    if dataset_id:
        stmt = stmt.where(m.Incident.dataset_id == dataset_id)
    if model_id:
        stmt = stmt.where(m.Incident.model_id == model_id)
    if q:
        stmt = stmt.where(func.lower(m.Incident.title).like(f"%{q.lower()}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order = {"priority": (m.Incident.priority_score.desc(), m.Incident.id.desc()),
             "recent": (m.Incident.last_seen_at.desc(),), "oldest": (m.Incident.first_seen_at.asc(),)}[sort]
    rows = db.scalars(stmt.order_by(*order).offset(page.offset).limit(page.page_size))
    return paged([ser.incident(i) for i in rows], total, page)


def _names(db: DB, inc: m.Incident) -> dict[str, Any]:
    ds = db.get(m.Dataset, inc.dataset_id) if inc.dataset_id else None
    mo = db.get(m.MLModel, inc.model_id) if inc.model_id else None
    v = db.get(m.DatasetVersion, inc.version_id) if inc.version_id else None
    assignee = db.get(m.User, inc.assigned_to) if inc.assigned_to else None
    return {"dataset_name": ds.name if ds else None, "model_name": mo.name if mo else None,
            "version_number": v.version_number if v else None, "version_status": v.status if v else None,
            "assignee_name": assignee.display_name if assignee else None}


@router.get("/incidents/{incident_id}", summary="Incident with timeline, comments, evidence and remediation")
def get_incident(incident_id: int, p: Viewer, db: DB) -> dict[str, Any]:
    inc = owned(db, m.Incident, incident_id, p, "Incident")
    events = db.scalars(select(m.IncidentEvent).where(m.IncidentEvent.incident_id == inc.id).order_by(m.IncidentEvent.id))
    comments = db.execute(select(m.IncidentComment, m.User.display_name).outerjoin(m.User, m.User.id == m.IncidentComment.user_id)
                          .where(m.IncidentComment.incident_id == inc.id).order_by(m.IncidentComment.id)).all()
    proposals = list(db.scalars(select(m.RemediationProposal).where(m.RemediationProposal.incident_id == inc.id)
                                .order_by(m.RemediationProposal.id)))
    execs: dict[int, list[m.RemediationExecution]] = {}
    for x in db.scalars(select(m.RemediationExecution).where(m.RemediationExecution.proposal_id.in_([q.id for q in proposals] or [-1]))
                        .order_by(m.RemediationExecution.id)):
        execs.setdefault(x.proposal_id, []).append(x)
    related = {k: sorted({f.get(k) for f in inc.findings if f.get(k)}) for k in
               ("check_run_id", "drift_evaluation_id", "comparison_id", "rule_id", "model_evaluation_id")}
    return {**ser.incident(inc), **_names(db, inc), "events": [ser.event(e) for e in events],
            "comments": [ser.comment(c, n) for c, n in comments],
            "proposals": [ser.proposal(q, execs.get(q.id, [])) for q in proposals], "related": related}


@router.get("/incidents/{incident_id}/investigation", summary="Lineage subgraph for the incident investigation view")
def investigation(incident_id: int, p: Viewer, db: DB) -> dict[str, Any]:
    inc = owned(db, m.Incident, incident_id, p, "Incident")
    src = None
    if inc.dataset_id:
        src = lsvc.node_for_dataset(db, inc.dataset_id)
    elif inc.model_id:
        src = lsvc.node_for_model(db, inc.model_id)
    if src is None:
        return {"source_node_id": None, "nodes": [], "edges": [], "affected": [], "state": inc.status}
    g = lsvc.load_graph(db, p.workspace_id)
    imp = impact_of(g, [src.id])
    up = g.upstream(src.id, max_depth=1)
    ids = {src.id, *[a["node_id"] for a in imp["affected"]], *up.keys()}
    nodes = {n.id: n for n in db.scalars(select(m.LineageNode).where(m.LineageNode.id.in_(ids)))}
    edges = [e for e in db.scalars(select(m.LineageEdge).where(m.LineageEdge.source_id.in_(ids), m.LineageEdge.target_id.in_(ids)))]
    on_path = {eid for a in imp["affected"] for eid in a["edge_path"]}
    affected = {a["node_id"]: a for a in imp["affected"]}
    out_nodes = []
    for nid, n in nodes.items():
        role = "source" if nid == src.id else "affected" if nid in affected else "upstream"
        out_nodes.append({**ser.node(n), "role": role, "impact": affected.get(nid, {}).get("impact"),
                          "depth": affected.get(nid, {}).get("depth", 0 if role == "source" else -1),
                          "path": affected.get(nid, {}).get("path")})
    verified = next((x for x in db.scalars(select(m.RemediationProposal).where(
        m.RemediationProposal.incident_id == inc.id, m.RemediationProposal.status == "verified"))), None)
    return {"source_node_id": src.id, "state": inc.status, "contained": inc.status == "resolved" and verified is not None,
            "verified_remediation_id": verified.id if verified else None,
            "nodes": sorted(out_nodes, key=lambda n: (n["depth"], n["id"])),
            "edges": [{**ser.edge(e), "on_impact_path": e.id in on_path} for e in edges],
            "findings": inc.findings, "counts": imp["counts"]}


class StatusIn(BaseModel):
    status: Literal["acknowledged", "investigating", "resolved", "reopened"]
    note: str | None = Field(None, max_length=2000)


@router.post("/incidents/{incident_id}/status", summary="Change incident status (resolution requires a note)")
def change_status(incident_id: int, body: StatusIn, p: Editor, db: DB) -> dict[str, Any]:
    inc = owned(db, m.Incident, incident_id, p, "Incident")
    incidents.transition(db, inc, body.status, p, body.note)
    db.commit()
    return ser.incident(inc)


class AssignIn(BaseModel):
    user_id: int | None


@router.post("/incidents/{incident_id}/assign", summary="Assign or unassign an incident")
def assign(incident_id: int, body: AssignIn, p: Editor, db: DB) -> dict[str, Any]:
    inc = owned(db, m.Incident, incident_id, p, "Incident")
    name = None
    if body.user_id is not None:
        u = db.get(m.User, body.user_id)
        if u is None or u.workspace_id != p.workspace_id:
            raise bad_request("User is not in this workspace.")
        name = u.display_name
    inc.assigned_to = body.user_id
    incidents.add_event(db, inc, "assigned", f"Assigned to {name}." if name else "Unassigned.", {"user_id": body.user_id}, p)
    audit.record(db, p.workspace_id, "incident.assigned", "incident", inc.id, {"user_id": body.user_id}, p)
    db.commit()
    return ser.incident(inc)


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


@router.post("/incidents/{incident_id}/comments", status_code=201, summary="Comment on an incident")
def comment(incident_id: int, body: CommentIn, p: Editor, db: DB) -> dict[str, Any]:
    inc = owned(db, m.Incident, incident_id, p, "Incident")
    c = m.IncidentComment(incident_id=inc.id, user_id=p.user_id, body=body.body)
    db.add(c)
    db.flush()
    incidents.add_event(db, inc, "commented", body.body[:140], {"comment_id": c.id}, p)
    db.commit()
    u = db.get(m.User, p.user_id) if p.user_id else None
    return ser.comment(c, u.display_name if u else p.label)


# ---------------------------------------------------------------- remediation


@router.get("/remediations", summary="Remediation proposals across incidents")
def list_proposals(p: Viewer, db: DB, page: Paging, status: str | None = None, incident_id: int | None = None) -> dict[str, Any]:
    stmt = select(m.RemediationProposal).where(m.RemediationProposal.workspace_id == p.workspace_id)
    if status:
        stmt = stmt.where(m.RemediationProposal.status.in_(status.split(",")))
    if incident_id:
        stmt = stmt.where(m.RemediationProposal.incident_id == incident_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(m.RemediationProposal.id.desc()).offset(page.offset).limit(page.page_size)))
    titles = {i.id: i.title for i in db.scalars(select(m.Incident).where(m.Incident.id.in_([r.incident_id for r in rows] or [-1])))}
    return paged([{**ser.proposal(r), "incident_title": titles.get(r.incident_id)} for r in rows], total, page)


@router.get("/remediations/catalog", summary="Available remediation actions and their risk levels")
def catalog() -> dict[str, Any]:
    return {"items": [a.to_dict() | {"auto_eligible": a.action in core.AUTO_ELIGIBLE} for a in core.CATALOG.values()]}


@router.get("/remediations/{proposal_id}", summary="Proposal with executions and verification")
def get_proposal(proposal_id: int, p: Viewer, db: DB) -> dict[str, Any]:
    q = owned(db, m.RemediationProposal, proposal_id, p, "Remediation proposal")
    execs = list(db.scalars(select(m.RemediationExecution).where(m.RemediationExecution.proposal_id == q.id)
                            .order_by(m.RemediationExecution.id)))
    return ser.proposal(q, execs)


class DecisionIn(BaseModel):
    note: str | None = Field(None, max_length=1000)


@router.post("/remediations/{proposal_id}/approve", summary="Approve a proposal")
def approve(proposal_id: int, body: DecisionIn, p: Editor, db: DB) -> dict[str, Any]:
    q = owned(db, m.RemediationProposal, proposal_id, p, "Remediation proposal")
    rsvc.approve(db, q, p, body.note)
    db.commit()
    return ser.proposal(q)


@router.post("/remediations/{proposal_id}/reject", summary="Reject a proposal")
def reject(proposal_id: int, body: DecisionIn, p: Editor, db: DB) -> dict[str, Any]:
    q = owned(db, m.RemediationProposal, proposal_id, p, "Remediation proposal")
    rsvc.reject(db, q, p, body.note)
    db.commit()
    return ser.proposal(q)


@router.post("/remediations/{proposal_id}/execute", summary="Execute an approved proposal and verify the result")
def execute(proposal_id: int, p: Editor, db: DB) -> dict[str, Any]:
    q = owned(db, m.RemediationProposal, proposal_id, p, "Remediation proposal")
    exe = rsvc.execute(db, q, p, "manual")
    db.refresh(q)
    execs = list(db.scalars(select(m.RemediationExecution).where(m.RemediationExecution.proposal_id == q.id)
                            .order_by(m.RemediationExecution.id)))
    inc = db.get(m.Incident, q.incident_id)
    return {"proposal": ser.proposal(q, execs), "execution": ser.execution(exe), "incident": ser.incident(inc)}


class RemediationPolicyIn(BaseModel):
    mode: Literal["recommend", "approval", "auto"]
    auto_allowlist: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(60, ge=5, le=600)


@router.get("/settings/remediation", summary="Workspace remediation policy")
def get_policy(p: Viewer, db: DB) -> dict[str, Any]:
    return {**rsvc.workspace_policy(db, p.workspace_id), "auto_eligible": sorted(core.AUTO_ELIGIBLE)}


@router.put("/settings/remediation", summary="Set remediation mode and auto-execution allowlist (admin)")
def put_policy(body: RemediationPolicyIn, p: Admin, db: DB) -> dict[str, Any]:
    try:
        allow = core.validate_allowlist(body.auto_allowlist)
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    ws = db.get(m.Workspace, p.workspace_id)
    ws.settings = {**(ws.settings or {}), "remediation": {"mode": body.mode, "auto_allowlist": allow,
                                                          "timeout_seconds": body.timeout_seconds}}
    audit.record(db, p.workspace_id, "settings.remediation_updated", "workspace", ws.id, ws.settings["remediation"], p)
    db.commit()
    return get_policy(p, db)

