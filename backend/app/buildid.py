"""A short fingerprint of the code that is actually running.

It is a hash of the backend, frontend and seed files, computed at start-up, so it needs no
git and no build step: if two installs show the same id they run the same code. It answers
"did the NAS really pick up the update?" - which a version number cannot, since the
version only changes when somebody remembers to bump it.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from .core.config import get_settings

_TEXT = {".py", ".js", ".css", ".html", ".json", ".svg", ".txt"}
_SKIP_DIRS = {"__pycache__", "tests", ".git"}


def _files(root: Path, pattern: str) -> list[Path]:
    return sorted(
        p for p in root.rglob(pattern)
        if p.is_file() and not (_SKIP_DIRS & set(p.relative_to(root).parts[:-1])) and p.suffix != ".pyc"
    )


def fingerprint(app_dir: Path, frontend_dir: Path, seed_dir: Path) -> str:
    h = hashlib.sha256()
    for label, root in (("app", app_dir), ("frontend", frontend_dir), ("seed", seed_dir)):
        for p in _files(root, "*"):
            data = p.read_bytes()
            if p.suffix.lower() in _TEXT:
                data = data.replace(b"\r\n", b"\n")  # the same code checked out on Windows or Linux
            h.update(f"{label}/{p.relative_to(root).as_posix()}\0".encode())
            h.update(data)
            h.update(b"\0")
    return h.hexdigest()[:7]


@lru_cache
def build_id() -> str:
    s = get_settings()
    return fingerprint(Path(__file__).resolve().parent, s.frontend_dir, s.seed_dir)
