"""
SQLAlchemy database models — base mixins and audit columns.
Concrete domain models are added in later milestones.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UUIDMixin:
    """Primary-key mixin using UUID strings."""
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )


class TimestampMixin:
    """Automatic created_at / updated_at timestamps (UTC)."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class AuditMixin(UUIDMixin, TimestampMixin):
    """Combined UUID PK + timestamps — base for most domain models."""
    __abstract__ = True


# ─── Placeholder model (keeps SQLAlchemy happy in M1) ─────────────────────────
class SystemEvent(AuditMixin, db.Model):
    """
    Audit log for system-level events (startup, config changes, etc.).
    Provides a minimal DB schema for Milestone 1.
    """
    __tablename__ = "system_events"

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
