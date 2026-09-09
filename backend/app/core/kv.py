"""Tiny helpers over the Setting (key -> JSON) table."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import Setting


def get_kv(db: Session, key: str, default: Any = None) -> Any:
    row = db.get(Setting, key)
    return row.value if row is not None else default


def set_kv(db: Session, key: str, value: Any) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    db.commit()
