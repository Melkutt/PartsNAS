"""Provider API-key configuration + live status.

`GET  /api/settings/providers`        list with configured / quota / breaker state
`PUT  /api/settings/providers/{name}` body {api_key: "..."} — "" clears it

Keys are stored in the Setting table (single-user LAN app). An env var
PARTSNAS_<NAME>_API_KEY, if set, wins and is reported as `from_env`.
The actual key value is never returned.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.kv import get_kv, set_kv
from ..providers import all_providers, get_provider
from ..providers.mouser import PER_DAY, PER_MIN
from ..providers.safety import status as breaker_status

router = APIRouter(prefix="/api/settings", tags=["settings"])


class KeyBody(BaseModel):
    api_key: str = ""


def _limits(name: str) -> tuple[int, int]:
    return {"mouser": (PER_MIN, PER_DAY)}.get(name, (10, 1000))


@router.get("/providers")
def list_providers(db: Session = Depends(get_db)):
    out = []
    for p in all_providers():
        per_min, per_day = _limits(p.name)
        st = breaker_status(db, p.name, per_min=per_min, per_day=per_day)
        from_env = bool(os.environ.get(f"PARTSNAS_{p.name.upper()}_API_KEY"))
        stored = bool((get_kv(db, f"provider:{p.name}:config", {}) or {}).get("api_key"))
        out.append(
            {
                "name": p.name,
                "label": p.label,
                "website": p.website,
                "configured": p.configured(db),
                "from_env": from_env,
                "has_stored_key": stored,
                **st,
            }
        )
    return out


@router.put("/providers/{name}")
def set_key(name: str, body: KeyBody, db: Session = Depends(get_db)):
    if get_provider(name) is None:
        raise HTTPException(404, "unknown provider")
    cfg = get_kv(db, f"provider:{name}:config", {}) or {}
    key = body.api_key.strip()
    if key:
        cfg["api_key"] = key
    else:
        cfg.pop("api_key", None)
    set_kv(db, f"provider:{name}:config", cfg)
    return {"ok": True, "configured": get_provider(name).configured(db)}
