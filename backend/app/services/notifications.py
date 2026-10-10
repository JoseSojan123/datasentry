"""In-app notifications with dedup/cooldown, plus optional SMTP email for opted-in users."""

from __future__ import annotations

import logging
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import models as m

log = logging.getLogger("datasentry.notifications")
SEV_RANK = {"info": 0, "warning": 1, "critical": 2}
DEFAULT_COOLDOWN = timedelta(hours=1)


def notify(
    db: Session,
    workspace_id: int,
    kind: str,
    title: str,
    body: str = "",
    severity: str = "info",
    link: str | None = None,
    dedup_key: str | None = None,
    cooldown: timedelta = DEFAULT_COOLDOWN,
) -> m.Notification | None:
    """Create one workspace-wide notification unless an identical one (same dedup_key) was sent within
    the cooldown window. Returns None when suppressed."""
    if dedup_key:
        recent = db.scalar(select(m.Notification.id).where(
            m.Notification.workspace_id == workspace_id, m.Notification.dedup_key == dedup_key,
            m.Notification.created_at >= datetime.now(UTC) - cooldown))
        if recent:
            return None
    n = m.Notification(workspace_id=workspace_id, kind=kind, severity=severity, title=title[:240], body=body,
                       link=link, dedup_key=dedup_key)
    db.add(n)
    db.flush()
    _maybe_email(db, n)
    return n


def _maybe_email(db: Session, n: m.Notification) -> None:
    s = get_settings()
    if not s.smtp_host or not s.smtp_from:
        return
    users = db.scalars(select(m.User).where(m.User.workspace_id == n.workspace_id, m.User.is_active.is_(True)))
    recipients = [u.email for u in users
                  if (u.preferences or {}).get("email_notifications")
                  and SEV_RANK.get(n.severity, 0) >= SEV_RANK.get((u.preferences or {}).get("email_min_severity", "critical"), 2)]
    if not recipients:
        return
    msg = EmailMessage()
    msg["Subject"] = f"[DataSentry] {n.title}"
    msg["From"] = s.smtp_from
    msg["To"] = ", ".join(recipients)
    msg.set_content(f"{n.body}\n\n{n.link or ''}")
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password or "")
            smtp.send_message(msg)
        n.email_status = "sent"
    except Exception as exc:  # noqa: BLE001 - email is best-effort
        log.warning("email delivery failed: %s", exc)
        n.email_status = "failed"


def visible_to(user: m.User | None, n: m.Notification) -> bool:
    if user is None:
        return True
    pref = (user.preferences or {}).get("in_app_min_severity", "info")
    return SEV_RANK.get(n.severity, 0) >= SEV_RANK.get(pref, 0)
