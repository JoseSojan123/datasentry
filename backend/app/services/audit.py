from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db import models as m

log = logging.getLogger("datasentry.audit")


def record(
    db: Session,
    workspace_id: int,
    action: str,
    entity_type: str,
    entity_id: Any = None,
    data: dict[str, Any] | None = None,
    principal: Any = None,
    ip: str | None = None,
) -> m.AuditEvent:
    """Append an audit event. Callers commit as part of their own transaction.

    ``data`` must contain identifiers and summaries only, never raw records or secrets.
    """
    ev = m.AuditEvent(
        workspace_id=workspace_id,
        actor_user_id=getattr(principal, "user_id", None),
        actor_api_key_id=getattr(principal, "api_key_id", None),
        actor_label=getattr(principal, "label", None) or "system",
        action=action,
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        data=data or {},
        ip=ip,
    )
    db.add(ev)
    log.info("audit action=%s entity=%s:%s actor=%s", action, entity_type, entity_id, ev.actor_label)
    return ev
