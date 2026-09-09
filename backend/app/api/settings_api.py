"""Provider API-credential configuration + live status.

`GET  /api/settings/providers`        list with cred fields / configured / quota
`PUT  /api/settings/providers/{name}` body {creds: {field: value}} — "" clears one

Credentials live in the Setting table (single-user LAN app). An env var
PARTSNAS_<NAME>_<FIELD> (e.g. PARTSNAS_DIGIKEY_CLIENT_ID) wins per field.
Values are never returned.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.kv import get_kv, set_kv
from ..providers import all_providers, get_provider
from ..providers.safety import status as breaker_status

router = APIRouter(prefix="/api/settings", tags=["settings"])

_LIMITS = {"mouser": (10, 1000), "digikey": (20, 1000)}


class CredsBody(BaseModel):
    creds: dict[str, str] = Field(default_factory=dict)
    api_key: str | None = None  # back-compat: mapped to creds["api_key"]


def _limits(name: str) -> tuple[int, int]:
    return _LIMITS.get(name, (10, 1000))


@router.get("/providers")
def list_providers(db: Session = Depends(get_db)):
    out = []
    for p in all_providers():
        per_min, per_day = _limits(p.name)
        st = breaker_status(db, p.name, per_min=per_min, per_day=per_day)
        cfg = get_kv(db, f"provider:{p.name}:config", {}) or {}
        fields = []
        for fld in p.cred_fields:
            env = f"PARTSNAS_{p.name.upper()}_{fld.upper()}"
            fields.append({
                "name": fld,
                "from_env": bool(os.environ.get(env)),
                "stored": bool(cfg.get(fld)),
            })
        out.append({
            "name": p.name,
            "label": p.label,
            "website": p.website,
            "configured": p.configured(db),
            "cred_fields": fields,
            **st,
        })
    return out


@router.put("/providers/{name}")
def set_creds(name: str, body: CredsBody, db: Session = Depends(get_db)):
    p = get_provider(name)
    if p is None:
        raise HTTPException(404, "unknown provider")
    incoming = dict(body.creds)
    if body.api_key is not None:
        incoming.setdefault("api_key", body.api_key)
    cfg = get_kv(db, f"provider:{name}:config", {}) or {}
    for fld, val in incoming.items():
        if fld not in p.cred_fields:
            continue
        val = (val or "").strip()
        if val:
            cfg[fld] = val
        else:
            cfg.pop(fld, None)
    set_kv(db, f"provider:{name}:config", cfg)
    # a credential change invalidates any cached OAuth token
    set_kv(db, f"provider:{name}:token", {})
    return {"ok": True, "configured": p.configured(db)}
