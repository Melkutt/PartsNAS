"""Exact snapshot: the whole data/ folder as it is *right now*, verbatim.

`GET  /api/export/snapshot.zip`   download it
`POST /api/import/snapshot`       multipart file=<zip>, confirm=REPLACE — put it back

Unlike the portable backup (api/backup.py, a logical export you can merge into
another database), a snapshot is a point-in-time copy of everything: the SQLite
database (taken with SQLite's online-backup API, so it is consistent even while
the app is running) plus every file next to it — part images, thumbnails, the
logo, provider caches. Nothing is interpreted or filtered, so nothing can be
"forgotten" when a new table or setting is added later. Restoring REPLACES the
current data with the snapshot; a safety snapshot of the current state is
written to data/backups/ first. Every file carries a SHA-256 in snapshot.json
and is verified before anything is touched.

A snapshot contains the supplier API keys (they live in the database) — keep it
private.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .. import __version__
from ..core.config import get_settings
from ..core.db import Base, SessionLocal, engine, sync_columns
from ..seed import run_all
from ..versioning import compare

router = APIRouter(tags=["snapshot"])
settings = get_settings()

FMT = "partsnas-snapshot"
BACKUPS = "backups"  # safety snapshots live here and are never snapshotted themselves
_DB_FILES = {"partsnas.db", "partsnas.db-wal", "partsnas.db-shm"}
_restore_lock = threading.Lock()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _table_counts(db_path: Path) -> dict[str, int]:
    con = sqlite3.connect(db_path)
    try:
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {n: con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}
    finally:
        con.close()


def _copy_db(dest: Path) -> None:
    """Consistent copy of the live database (safe while the app is writing)."""
    src = sqlite3.connect(settings.db_path, timeout=15)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _data_files() -> list[Path]:
    root = settings.data_dir
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if rel.parts[0] == BACKUPS or (len(rel.parts) == 1 and rel.name in _DB_FILES):
            continue
        out.append(p)
    return out


def build_snapshot(dest_zip: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / "partsnas.db"
        _copy_db(db_copy)
        files: dict[str, str] = {}
        total = db_copy.stat().st_size
        with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(db_copy, "partsnas.db")
            for p in _data_files():
                rel = p.relative_to(settings.data_dir).as_posix()
                files[rel] = _sha256(p)
                total += p.stat().st_size
                z.write(p, f"files/{rel}")
            manifest = {
                "format": FMT, "version": 1, "app_version": __version__,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "sqlite_version": sqlite3.sqlite_version,
                "db_sha256": _sha256(db_copy),
                "tables": _table_counts(db_copy),
                "file_count": len(files), "total_bytes": total,
                "files": files,
            }
            z.writestr("snapshot.json", json.dumps(manifest, indent=1))
    return manifest


@router.get("/api/export/snapshot.zip")
def export_snapshot():
    fd, name = tempfile.mkstemp(suffix=".zip", prefix="partsnas-snapshot-")
    os.close(fd)
    dest = Path(name)
    try:
        build_snapshot(dest)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    fn = f"partsnas-snapshot-{datetime.now():%Y%m%d-%H%M}.zip"
    return FileResponse(dest, media_type="application/zip", filename=fn,
                        background=BackgroundTask(dest.unlink, missing_ok=True))


def _safe_member(name: str) -> str | None:
    """'files/<rel>' -> '<rel>' if it is a plain relative path, else None."""
    if not name.startswith("files/"):
        return None
    rel = PurePosixPath(name[len("files/"):])
    if rel.is_absolute() or not rel.parts or any(p in ("", ".", "..") or ":" in p for p in rel.parts):
        return None
    return rel.as_posix()


def _verify(zf: zipfile.ZipFile, tmp: Path) -> dict:
    try:
        manifest = json.loads(zf.read("snapshot.json"))
    except KeyError:
        raise HTTPException(400, "snapshot.json missing — not a PartsNAS snapshot")
    if manifest.get("format") != FMT:
        raise HTTPException(400, "not a PartsNAS snapshot")
    listed = manifest.get("files", {})
    members = {n for n in zf.namelist() if n.startswith("files/") and not n.endswith("/")}
    for n in members:
        rel = _safe_member(n)
        if rel is None:
            raise HTTPException(400, f"unsafe path in snapshot: {n}")
        if rel not in listed:
            raise HTTPException(400, f"file not listed in the manifest: {rel}")
    for rel, digest in listed.items():
        if f"files/{rel}" not in members:
            raise HTTPException(400, f"file missing from snapshot: {rel}")
        h = hashlib.sha256()
        with zf.open(f"files/{rel}") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != digest:
            raise HTTPException(400, f"checksum mismatch (corrupt snapshot): {rel}")
    db_path = tmp / "partsnas.db"
    with zf.open("partsnas.db") as src, db_path.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    if _sha256(db_path) != manifest.get("db_sha256"):
        raise HTTPException(400, "checksum mismatch (corrupt snapshot): partsnas.db")
    con = sqlite3.connect(db_path)
    try:
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise HTTPException(400, "the snapshot's database failed SQLite's integrity check")
    finally:
        con.close()
    if _table_counts(db_path) != manifest.get("tables"):
        raise HTTPException(400, "table row counts don't match the manifest")
    return manifest


@router.post("/api/import/snapshot")
def import_snapshot(file: UploadFile = File(...), confirm: str = Form(""), allow_newer: str = Form("")):
    if confirm != "REPLACE":
        raise HTTPException(400, 'restoring replaces everything — send confirm="REPLACE"')
    if not _restore_lock.acquire(blocking=False):
        raise HTTPException(409, "a restore is already running")
    try:
        with tempfile.TemporaryDirectory() as tmpd:
            tmp = Path(tmpd)
            upload = tmp / "upload.zip"
            with upload.open("wb") as out:
                shutil.copyfileobj(file.file, out)
            try:
                zf = zipfile.ZipFile(upload)
            except zipfile.BadZipFile:
                raise HTTPException(400, "not a zip file")
            with zf:
                manifest = _verify(zf, tmp)  # nothing is touched until this passes

                # a snapshot from a NEWER PartsNAS may hold data this build does not understand: say so first
                theirs = manifest.get("app_version")
                if compare(theirs, __version__) == 1 and allow_newer != "YES":
                    raise HTTPException(409, {
                        "code": "newer_snapshot", "snapshot_version": theirs, "running_version": __version__,
                        "message": (f"This snapshot was made by PartsNAS {theirs}, newer than the {__version__} that is "
                                    "running. This build may not understand everything in it. Update PartsNAS first, "
                                    "or restore anyway.")})

                # safety net: the state we're about to overwrite
                bdir = settings.data_dir / BACKUPS
                bdir.mkdir(exist_ok=True)
                safety = bdir / f"pre-restore-{datetime.now():%Y%m%d-%H%M%S}.zip"
                build_snapshot(safety)

                # database: page-copy the snapshot INTO the live file
                engine.dispose()
                src = sqlite3.connect(tmp / "partsnas.db")
                try:
                    dst = sqlite3.connect(settings.db_path, timeout=30)
                    try:
                        src.backup(dst)
                    finally:
                        dst.close()
                finally:
                    src.close()
                engine.dispose()

                # files: wipe everything but the db + safety snapshots, lay the snapshot's down
                for child in settings.data_dir.iterdir():
                    if child.name == BACKUPS or child.name in _DB_FILES:
                        continue
                    shutil.rmtree(child) if child.is_dir() else child.unlink()
                root = settings.data_dir.resolve()
                for rel in manifest["files"]:
                    target = (settings.data_dir / rel).resolve()
                    if root not in target.parents:
                        raise HTTPException(400, f"unsafe path: {rel}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(f"files/{rel}") as s, target.open("wb") as d:
                        shutil.copyfileobj(s, d)

        # an older snapshot may predate newer tables/columns/seed rows
        settings.ensure_dirs()
        Base.metadata.create_all(engine)
        sync_columns()
        with SessionLocal() as db:
            run_all(db)
        return {"ok": True, "snapshot_created": manifest["created_at"],
                "app_version": manifest.get("app_version"), "tables": manifest["tables"],
                "files": manifest["file_count"], "safety_snapshot": f"{BACKUPS}/{safety.name}"}
    finally:
        _restore_lock.release()
