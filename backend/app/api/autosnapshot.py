"""Settings for the automatic snapshot (see app/autosnapshot.py).

`GET  /api/settings/autosnapshot`       config + last result + the snapshots in the folder
`PUT  /api/settings/autosnapshot`       {enabled, folder, keep, hour}
`POST /api/settings/autosnapshot/run`   make one now
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import autosnapshot as auto
from ..core.db import get_db
from ..core.kv import set_kv

router = APIRouter(prefix="/api/settings/autosnapshot", tags=["settings"])


class ConfigIn(BaseModel):
    enabled: bool
    folder: str = Field(max_length=300)
    keep: int = Field(ge=1, le=365)
    hour: int = Field(ge=0, le=23)


def _view(db: Session) -> dict:
    cfg = auto.load_config(db)
    folder = auto.resolve_folder(cfg["folder"])
    return {
        "config": cfg,
        "folder_resolved": str(folder),
        "state": auto.load_state(db),
        "files": auto.list_files(folder)[:30],
        "default_folder": auto.DEFAULTS["folder"],
    }


@router.get("")
def get_config(db: Session = Depends(get_db)):
    return _view(db)


@router.put("")
def put_config(body: ConfigIn, db: Session = Depends(get_db)):
    folder = body.folder.strip() or auto.DEFAULTS["folder"]
    try:
        auto.check_folder(folder)   # refuse a folder we cannot write to, now rather than at 03:00
    except ValueError as e:
        raise HTTPException(400, str(e))
    set_kv(db, auto.CONFIG_KEY, {"enabled": body.enabled, "folder": folder, "keep": body.keep, "hour": body.hour})
    return _view(db)


@router.post("/run")
def run(db: Session = Depends(get_db)):
    res = auto.run_now("manual")
    if not res["ok"]:
        raise HTTPException(500, res["error"])
    return {**res, **_view(db)}
