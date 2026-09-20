"""Automatic snapshots: once a day the app writes a snapshot (the same file as Export ->
Snapshot) into a folder you choose, and keeps only the newest few.

Off by default. Settings -> Automatic backup turns it on and picks the folder, how many to keep
and the hour of the day. The scheduler is a small thread that wakes once a minute; a snapshot is
"due" when it is on, the hour has passed today and none has been made today - so a NAS that was off
at 03:00 still makes it when it comes back. A failed attempt is retried after half an hour and its
error is shown in Settings, instead of failing silently.

In Docker the folder is a path INSIDE the container. The default (backups/auto, under the data
folder) lands next to your data on the NAS. To write somewhere else, mount that folder as a volume
in docker-compose.yml and enter the container-side path here.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from .core.config import get_settings
from .core.db import SessionLocal
from .core.kv import get_kv, set_kv

CONFIG_KEY = "autosnapshot"
STATE_KEY = "autosnapshot:state"
DEFAULTS = {"enabled": False, "folder": "backups/auto", "keep": 7, "hour": 3}
PREFIX = "partsnas-auto-"
RETRY_AFTER = timedelta(minutes=30)

_run_lock = threading.Lock()
_thread: threading.Thread | None = None


def load_config(db) -> dict:
    return {**DEFAULTS, **(get_kv(db, CONFIG_KEY, {}) or {})}


def load_state(db) -> dict:
    return get_kv(db, STATE_KEY, {}) or {}


def resolve_folder(folder: str) -> Path:
    """Relative paths live under the data folder; absolute ones are used as given."""
    p = Path(folder.strip())
    return p if p.is_absolute() else get_settings().data_dir / p


def check_folder(folder: str) -> Path:
    """Resolve, create and test-write the folder. Raises ValueError with a plain message."""
    if not folder.strip():
        raise ValueError("Enter a folder")
    path = resolve_folder(folder)
    data = get_settings().data_dir.resolve()
    inside = data == path.resolve() or data in path.resolve().parents
    if inside and (data / "backups") not in (path.resolve(), *path.resolve().parents):
        # a snapshot contains everything under data/ except backups/ - a snapshot folder elsewhere
        # in there would be copied into every new snapshot and grow without end
        raise ValueError("Inside the data folder only backups/... is allowed (it is left out of snapshots). "
                         "Use e.g. backups/auto, or a folder outside data.")
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok")
        probe.unlink()
    except OSError as e:
        raise ValueError(f"Can't write to {path}: {e.strerror or e}") from e
    return path


def _newest_first(folder: Path) -> list[Path]:
    return sorted(folder.glob(f"{PREFIX}*.zip"), key=lambda f: (f.stat().st_mtime, f.name), reverse=True)


def list_files(folder: Path) -> list[dict]:
    if not folder.is_dir():
        return []
    files = _newest_first(folder)
    return [{"name": f.name, "bytes": f.stat().st_size,
             "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")} for f in files]


def prune(folder: Path, keep: int) -> list[str]:
    """Delete all but the newest `keep` automatic snapshots. Only files with our own name pattern."""
    files = _newest_first(folder)
    gone = []
    for f in files[max(keep, 1):]:
        try:
            f.unlink()
            gone.append(f.name)
        except OSError:
            pass
    return gone


def run_now(reason: str = "manual") -> dict:
    """Make one snapshot now. Returns {ok, file, bytes, removed} or {ok: False, error}."""
    from .api.snapshot import _restore_lock, build_snapshot

    if not _run_lock.acquire(blocking=False):
        return {"ok": False, "error": "a backup is already running"}
    now = datetime.now()
    with SessionLocal() as db:
        cfg = load_config(db)
    result: dict
    try:
        if _restore_lock.locked():
            raise RuntimeError("a restore is in progress")
        folder = check_folder(cfg["folder"])
        dest = folder / f"{PREFIX}{now:%Y%m%d-%H%M%S}.zip"
        n = 1
        while dest.exists():                       # two in the same second (e.g. "Back up now" twice)
            dest = folder / f"{PREFIX}{now:%Y%m%d-%H%M%S}-{n}.zip"
            n += 1
        partial = dest.with_name(dest.name + ".partial")
        try:
            build_snapshot(partial)
            os.replace(partial, dest)
        finally:
            partial.unlink(missing_ok=True)
        removed = prune(folder, int(cfg["keep"]))
        result = {"ok": True, "file": dest.name, "bytes": dest.stat().st_size, "removed": removed}
    except Exception as e:  # noqa: BLE001 - shown to the user in Settings
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        _run_lock.release()
    with SessionLocal() as db:
        state = load_state(db)
        state["last_attempt_at"] = now.isoformat(timespec="seconds")
        state["last_reason"] = reason
        if result["ok"]:
            state.update(last_ok_at=now.isoformat(timespec="seconds"), last_file=result["file"],
                         last_bytes=result["bytes"], last_error=None)
        else:
            state["last_error"] = result["error"]
        set_kv(db, STATE_KEY, state)
    return result


def is_due(cfg: dict, state: dict, now: datetime) -> bool:
    if not cfg.get("enabled") or now.hour < int(cfg["hour"]):
        return False
    last_ok = state.get("last_ok_at")
    if last_ok and datetime.fromisoformat(last_ok).date() >= now.date():
        return False                                   # already made one today
    last_try = state.get("last_attempt_at")
    if last_try and state.get("last_error") and now - datetime.fromisoformat(last_try) < RETRY_AFTER:
        return False                                   # it just failed: not every minute
    return True


def _loop() -> None:
    while True:
        try:
            with SessionLocal() as db:
                cfg, state = load_config(db), load_state(db)
            if is_due(cfg, state, datetime.now()):
                run_now("scheduled")
        except Exception:  # noqa: BLE001 - the scheduler itself must never die
            import traceback

            traceback.print_exc()
        time.sleep(60)


def start_scheduler() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, name="autosnapshot", daemon=True)
    _thread.start()
