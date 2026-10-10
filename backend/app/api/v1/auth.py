from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.api import serializers as ser
from app.api.deps import DB, Admin, CurrentPrincipal
from app.core.config import get_settings
from app.core.errors import APIError, conflict, not_found
from app.core.ratelimit import client_ip, rate_limit
from app.core.security import (
    create_access_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    verify_password,
)
from app.db import models as m
from app.services import audit

router = APIRouter(tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    workspace_name: str = Field("My workspace", min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class DemoIn(BaseModel):
    load_sample_data: bool = True


def _token_response(u: m.User, ws: m.Workspace) -> dict[str, Any]:
    token, exp = create_access_token(u.id, u.workspace_id, u.role)
    return {"access_token": token, "token_type": "bearer", "expires_at": exp.isoformat(), "user": ser.user(u),
            "workspace": {"id": ws.id, "name": ws.name, "is_demo": ws.is_demo, "expires_at": ser.iso(ws.expires_at),
                          "settings": ws.settings or {}}}


@router.post("/auth/register", status_code=201, dependencies=[Depends(rate_limit("auth"))],
             summary="Create a workspace and its first (admin) user")
def register(body: RegisterIn, db: DB, request: Request) -> dict[str, Any]:
    if not get_settings().allow_registration:
        raise APIError(403, "registration_closed", "Self-service registration is disabled on this deployment.")
    if db.scalar(select(m.User.id).where(func.lower(m.User.email) == body.email.lower())):
        raise conflict("An account with this email already exists.")
    ws = m.Workspace(name=body.workspace_name)
    db.add(ws)
    db.flush()
    u = m.User(workspace_id=ws.id, email=body.email.lower(), display_name=body.display_name,
               password_hash=hash_password(body.password), role="admin")
    db.add(u)
    db.flush()
    audit.record(db, ws.id, "user.registered", "user", u.id, {"email_domain": body.email.split("@")[1]}, ip=client_ip(request))
    db.commit()
    return _token_response(u, ws)


@router.post("/auth/login", dependencies=[Depends(rate_limit("auth"))], summary="Exchange email and password for a token")
def login(body: LoginIn, db: DB, request: Request) -> dict[str, Any]:
    u = db.scalar(select(m.User).where(func.lower(m.User.email) == body.email.lower()))
    if u is None or not u.is_active or not verify_password(body.password, u.password_hash):
        raise APIError(401, "invalid_credentials", "Email or password is incorrect.")
    ws = db.get(m.Workspace, u.workspace_id)
    if ws.expires_at and ws.expires_at < datetime.now(UTC):
        raise APIError(401, "workspace_expired", "This demo workspace has expired.")
    u.last_login_at = datetime.now(UTC)
    audit.record(db, ws.id, "user.login", "user", u.id, {}, ip=client_ip(request))
    db.commit()
    return _token_response(u, ws)


@router.post("/auth/demo", status_code=201, dependencies=[Depends(rate_limit("auth"))],
             summary="Create an isolated, expiring demo workspace (optionally with synthetic sample data)")
def demo(db: DB, request: Request, body: DemoIn | None = None) -> dict[str, Any]:
    body = body or DemoIn()
    s = get_settings()
    if not s.demo_mode_enabled:
        raise APIError(403, "demo_disabled", "Demo mode is disabled on this deployment.")
    active = db.scalar(select(func.count()).select_from(m.Workspace).where(
        m.Workspace.is_demo.is_(True), m.Workspace.expires_at > datetime.now(UTC))) or 0
    if active >= s.max_demo_workspaces:
        raise APIError(503, "demo_capacity", "The demo is at capacity. Please try again later.")
    ws = m.Workspace(name="Demo workspace", is_demo=True, expires_at=datetime.now(UTC) + timedelta(hours=s.demo_workspace_ttl_hours))
    db.add(ws)
    db.flush()
    u = m.User(workspace_id=ws.id, email=f"demo-{secrets.token_hex(6)}@demo.datasentry.local", display_name="Demo user",
               password_hash=hash_password(secrets.token_urlsafe(24)), role="admin")
    db.add(u)
    db.flush()
    audit.record(db, ws.id, "workspace.demo_created", "workspace", ws.id, {}, ip=client_ip(request))
    db.commit()
    if body.load_sample_data:
        from app.api.deps import Principal
        from app.services.seed import seed_workspace

        seed_workspace(db, ws.id, Principal(ws.id, u.id, "admin", None, u.email, True))
        db.refresh(ws)
    return _token_response(u, ws)


@router.get("/auth/me", summary="Current user, workspace and role")
def me(p: CurrentPrincipal, db: DB) -> dict[str, Any]:
    ws = db.get(m.Workspace, p.workspace_id)
    u = db.get(m.User, p.user_id) if p.user_id else None
    return {"user": ser.user(u) if u else None, "role": p.role, "via_api_key": p.api_key_id is not None,
            "workspace": {"id": ws.id, "name": ws.name, "is_demo": ws.is_demo, "expires_at": ser.iso(ws.expires_at),
                          "settings": ws.settings or {}}}


class PreferencesIn(BaseModel):
    in_app_min_severity: Literal["info", "warning", "critical"] | None = None
    email_notifications: bool | None = None
    email_min_severity: Literal["info", "warning", "critical"] | None = None
    theme: Literal["dark", "light", "system"] | None = None
    reduced_motion: bool | None = None
    onboarding_completed: bool | None = None


@router.patch("/auth/me/preferences", summary="Update notification and UI preferences")
def update_preferences(body: PreferencesIn, p: CurrentPrincipal, db: DB) -> dict[str, Any]:
    if not p.user_id:
        raise APIError(400, "no_user", "API keys have no user preferences.")
    u = db.get(m.User, p.user_id)
    u.preferences = {**(u.preferences or {}), **body.model_dump(exclude_none=True)}
    db.commit()
    return ser.user(u)


class UserIn(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=128)
    role: Literal["admin", "editor", "viewer"] = "viewer"


@router.get("/users", summary="List users in the workspace")
def list_users(p: CurrentPrincipal, db: DB) -> dict[str, Any]:
    users = db.scalars(select(m.User).where(m.User.workspace_id == p.workspace_id).order_by(m.User.id))
    return {"items": [ser.user(u) for u in users]}


@router.post("/users", status_code=201, summary="Add a user to the workspace (admin)")
def create_user(body: UserIn, p: Admin, db: DB) -> dict[str, Any]:
    if db.scalar(select(m.User.id).where(func.lower(m.User.email) == body.email.lower())):
        raise conflict("An account with this email already exists.")
    u = m.User(workspace_id=p.workspace_id, email=body.email.lower(), display_name=body.display_name,
               password_hash=hash_password(body.password), role=body.role)
    db.add(u)
    db.flush()
    audit.record(db, p.workspace_id, "user.created", "user", u.id, {"role": body.role}, p)
    db.commit()
    return ser.user(u)


class RoleIn(BaseModel):
    role: Literal["admin", "editor", "viewer"]


@router.patch("/users/{user_id}/role", summary="Change a user's role (admin)")
def change_role(user_id: int, body: RoleIn, p: Admin, db: DB) -> dict[str, Any]:
    u = db.get(m.User, user_id)
    if u is None or u.workspace_id != p.workspace_id:
        raise not_found("User", user_id)
    if u.id == p.user_id and body.role != "admin":
        raise APIError(400, "self_demotion", "You cannot remove your own admin role.")
    u.role = body.role
    audit.record(db, p.workspace_id, "user.role_changed", "user", u.id, {"role": body.role}, p)
    db.commit()
    return ser.user(u)


# ---------------------------------------------------------------- API keys


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: Literal["admin", "editor", "viewer"] = "editor"
    expires_in_days: int | None = Field(None, ge=1, le=365)


@router.get("/api-keys", tags=["api-keys"], summary="List API keys (secrets are never returned)")
def list_keys(p: Admin, db: DB) -> dict[str, Any]:
    keys = db.scalars(select(m.ApiKey).where(m.ApiKey.workspace_id == p.workspace_id).order_by(m.ApiKey.id.desc()))
    return {"items": [ser.api_key(k) for k in keys]}


@router.post("/api-keys", status_code=201, tags=["api-keys"], summary="Create an API key; the secret is shown only once")
def create_key(body: ApiKeyIn, p: Admin, db: DB) -> dict[str, Any]:
    if not p.user_id:
        raise APIError(400, "user_required", "Create API keys while signed in as a user.")
    if body.role == "admin" and p.role != "admin":
        raise APIError(403, "forbidden", "Only admins can create admin keys.")
    secret, prefix = generate_api_key()
    k = m.ApiKey(workspace_id=p.workspace_id, user_id=p.user_id, name=body.name, prefix=prefix, key_hash=hash_api_key(secret),
                 role=body.role, expires_at=datetime.now(UTC) + timedelta(days=body.expires_in_days) if body.expires_in_days else None)
    db.add(k)
    db.flush()
    audit.record(db, p.workspace_id, "api_key.created", "api_key", k.id, {"name": body.name, "role": body.role}, p)
    db.commit()
    return {**ser.api_key(k), "secret": secret, "note": "Store this key now; it cannot be shown again."}


@router.delete("/api-keys/{key_id}", tags=["api-keys"], summary="Revoke an API key")
def revoke_key(key_id: int, p: Admin, db: DB) -> dict[str, Any]:
    k = db.get(m.ApiKey, key_id)
    if k is None or k.workspace_id != p.workspace_id:
        raise not_found("API key", key_id)
    if k.revoked_at is None:
        k.revoked_at = datetime.now(UTC)
        audit.record(db, p.workspace_id, "api_key.revoked", "api_key", k.id, {"name": k.name}, p)
        db.commit()
    return ser.api_key(k)
