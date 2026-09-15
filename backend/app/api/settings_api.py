"""Provider API-credential configuration + live status, and the company logo.

`GET  /api/settings/providers`        list with cred fields / configured / quota
`PUT  /api/settings/providers/{name}` body {creds: {field: value}} — "" clears one
`GET  /api/settings/logo`             {logo_url} or {logo_url: null}
`POST /api/settings/logo`             multipart upload (field: file) — replaces any existing one
`DELETE /api/settings/logo`           removes it

Credentials live in the Setting table (single-user LAN app). An env var
PARTSNAS_<NAME>_<FIELD> (e.g. PARTSNAS_DIGIKEY_CLIENT_ID) wins per field.
Values are never returned.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.db import get_db
from ..core.kv import get_kv, set_kv
from ..providers import all_providers, get_provider
from ..providers.safety import status as breaker_status

router = APIRouter(prefix="/api/settings", tags=["settings"])

_LIMITS = {"mouser": (10, 1000), "digikey": (20, 1000)}
_LOGO_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


class CredsBody(BaseModel):
    creds: dict[str, str] = Field(default_factory=dict)
    api_key: str | None = None  # back-compat: mapped to creds["api_key"]
    price_enabled: bool | None = None  # include this provider in "refresh prices from all"


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
            "price_enabled": bool(get_kv(db, f"provider:{p.name}:price_enabled", True)),
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
    changed_cred = False
    for fld, val in incoming.items():
        if fld not in p.cred_fields:
            continue
        val = (val or "").strip()
        if val:
            cfg[fld] = val
        else:
            cfg.pop(fld, None)
        changed_cred = True
    if changed_cred:
        set_kv(db, f"provider:{name}:config", cfg)
        set_kv(db, f"provider:{name}:token", {})  # invalidate cached OAuth token
    if body.price_enabled is not None:
        set_kv(db, f"provider:{name}:price_enabled", bool(body.price_enabled))
    return {"ok": True, "configured": p.configured(db)}


@router.get("/logo")
def get_logo(db: Session = Depends(get_db)):
    rel = get_kv(db, "branding:logo", None)
    return {"logo_url": f"/media/{rel}" if rel else None}


@router.post("/logo")
async def upload_logo(file: UploadFile = File(...), db: Session = Depends(get_db)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _LOGO_EXT:
        raise HTTPException(400, f"unsupported image type {ext!r}")
    s = get_settings()
    old = get_kv(db, "branding:logo", None)
    if old:
        (s.data_dir / old).unlink(missing_ok=True)
    raw = await file.read()
    key = secrets.token_hex(8)
    rel = f"branding/logo_{key}{ext}"
    (s.data_dir / rel).write_bytes(raw)
    set_kv(db, "branding:logo", rel)
    return {"logo_url": f"/media/{rel}"}


@router.delete("/logo")
def delete_logo(db: Session = Depends(get_db)):
    s = get_settings()
    old = get_kv(db, "branding:logo", None)
    if old:
        (s.data_dir / old).unlink(missing_ok=True)
    set_kv(db, "branding:logo", None)
    return {"ok": True}
