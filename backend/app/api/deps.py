from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import APIError, forbidden, not_found
from app.core.security import decode_access_token, hash_api_key, parse_api_key
from app.db import models as m
from app.db.session import get_db

ROLE_RANK = {"viewer": 0, "editor": 1, "admin": 2}


@dataclass
class Principal:
    workspace_id: int
    user_id: int | None
    role: str
    api_key_id: int | None = None
    label: str = "user"
    is_demo: bool = False

    def at_least(self, role: str) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[role]


DB = Annotated[Session, Depends(get_db)]


def _unauthorized(msg: str = "Authentication required.") -> APIError:
    return APIError(401, "unauthorized", msg)


def get_principal(
    request: Request,
    db: DB,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> Principal:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    key = x_api_key or (token if token and token.startswith("dsk_") else None)
    if key:
        prefix = parse_api_key(key)
        if not prefix:
            raise _unauthorized("Malformed API key.")
        row = db.scalar(select(m.ApiKey).where(m.ApiKey.prefix == prefix))
        now = datetime.now(UTC)
        import hmac

        if (row is None or row.revoked_at is not None or (row.expires_at and row.expires_at < now)
                or not hmac.compare_digest(row.key_hash, hash_api_key(key))):
            raise _unauthorized("Invalid or revoked API key.")
        if row.last_used_at is None or (now - row.last_used_at).total_seconds() > 60:
            row.last_used_at = now
            db.commit()
        ws = db.get(m.Workspace, row.workspace_id)
        p = Principal(row.workspace_id, row.user_id, row.role, row.id, f"api_key:{row.name}", bool(ws and ws.is_demo))
        request.state.principal = p
        return p
    if not token:
        raise _unauthorized()
    try:
        claims = decode_access_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("Session expired; sign in again.") from exc
    except jwt.PyJWTError as exc:
        raise _unauthorized("Invalid access token.") from exc
    user = db.get(m.User, int(claims["sub"]))
    if user is None or not user.is_active or user.workspace_id != claims.get("ws"):
        raise _unauthorized("User no longer exists or is disabled.")
    ws = db.get(m.Workspace, user.workspace_id)
    if ws is None or (ws.expires_at and ws.expires_at < datetime.now(UTC)):
        raise _unauthorized("This demo workspace has expired. Start a new demo.")
    p = Principal(user.workspace_id, user.id, user.role, None, user.email, ws.is_demo)
    request.state.principal = p
    return p


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require(role: str):
    def dep(p: CurrentPrincipal) -> Principal:
        if not p.at_least(role):
            raise forbidden(f"This action requires the '{role}' role.")
        return p

    return dep


Viewer = Annotated[Principal, Depends(require("viewer"))]
Editor = Annotated[Principal, Depends(require("editor"))]
Admin = Annotated[Principal, Depends(require("admin"))]


@dataclass
class Page:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def pagination(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200)) -> Page:
    return Page(page, page_size)


Paging = Annotated[Page, Depends(pagination)]


def paged(items: list[Any], total: int, page: Page) -> dict[str, Any]:
    return {"items": items, "total": total, "page": page.page, "page_size": page.page_size,
            "pages": (total + page.page_size - 1) // page.page_size}


def owned(db: Session, model: type, obj_id: int, p: Principal, label: str | None = None):
    """Fetch a workspace-scoped row or 404 (never reveal other tenants' records)."""
    obj = db.get(model, obj_id)
    if obj is None or getattr(obj, "workspace_id", None) != p.workspace_id:
        raise not_found(label or model.__name__, obj_id)
    return obj


def owned_dataset(db: Session, dataset_id: int, p: Principal) -> m.Dataset:
    return owned(db, m.Dataset, dataset_id, p, "Dataset")


def owned_version(db: Session, version_id: int, p: Principal) -> tuple[m.DatasetVersion, m.Dataset]:
    v = db.get(m.DatasetVersion, version_id)
    if v is None:
        raise not_found("Version", version_id)
    ds = db.get(m.Dataset, v.dataset_id)
    if ds is None or ds.workspace_id != p.workspace_id:
        raise not_found("Version", version_id)
    return v, ds
