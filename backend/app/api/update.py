"""Is there a newer PartsNAS? (About tab -> "Check for updates")

`GET /api/update/check[?refresh=1]`   fetch the published `version.json` and compare it with what is running
`GET/PUT /api/update/settings`        the address of that file, and an optional GitHub token (Settings -> Updates)

`version.json` (in the repository root, written by `scripts/write_version_json.py`) says
`{"version": "0.8.0", "build": "147408f", "released": "2026-09-26", "notes": "..."}`. The default address is the
file in the GitHub repository; a private repository cannot be read without a login, so the check then says so
instead of guessing - enter a read-only GitHub token or another address in Settings, or make the repository public. The check only
runs when the button is pressed, and the answer is kept for ten minutes.
"""
from __future__ import annotations

import time
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import __version__
from ..buildid import build_id
from ..core.db import get_db
from ..core.kv import get_kv, set_kv
from ..versioning import compare

router = APIRouter(prefix="/api/update", tags=["update"])

DEFAULT_URL = "https://raw.githubusercontent.com/Melkutt/PartsNAS/master/version.json"
_KEY = "update:url"
_TOKEN_KEY = "update:token"
_cache: dict[str, tuple[float, dict]] = {}
_TTL = 600


_GITHUB_HOSTS = {"raw.githubusercontent.com", "api.github.com"}


def _headers(url: str, token: str) -> dict:
    h = {"User-Agent": f"PartsNAS/{__version__}"}
    # a GitHub token (read-only access to this one repository) is only ever sent to GitHub, never to another address
    if token and urlparse(url).hostname in _GITHUB_HOSTS:
        h["Authorization"] = f"Bearer {token}"
    return h


def _fetch(url: str, token: str = "") -> dict:
    """The published version.json; raises ValueError with a message for the user."""
    try:
        r = httpx.get(url, timeout=8.0, follow_redirects=True, headers=_headers(url, token))
    except httpx.HTTPError as e:
        raise ValueError(f"could not reach {url}: {str(e)[:120]}") from e
    if r.status_code in (401, 403, 404):
        raise ValueError(
            f"{url} answered {r.status_code}: the file is not there, or the repository is private and needs a GitHub "
            "token (Settings -> Updates), or you can enter another address or make the repository public.")
    if r.status_code != 200:
        raise ValueError(f"{url} answered HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError as e:
        raise ValueError("the file is not JSON") from e
    if not isinstance(data, dict) or not data.get("version"):
        raise ValueError("the file has no \"version\"")
    return data


def evaluate(latest: dict | None, error: str | None = None) -> dict:
    cur = {"version": __version__, "build": build_id()}
    out = {"current": cur, "latest": latest, "status": "error", "message": error or "", "checked_at": time.time()}
    if latest is None:
        return out
    c = compare(latest.get("version"), cur["version"])
    lb = str(latest.get("build") or "")
    if c is None:
        out["message"] = "the published version number could not be read"
    elif c > 0:
        out["status"], out["message"] = "newer", f"Version {latest['version']} is available (you run {cur['version']})."
    elif c < 0:
        out["status"], out["message"] = "ahead", f"You run {cur['version']}, newer than the published {latest['version']}."
    elif lb and lb != cur["build"]:
        out["status"] = "other_build"
        out["message"] = (f"Same version ({cur['version']}), but the code differs: you run build {cur['build']}, "
                          f"the published one is {lb}.")
    else:
        out["status"], out["message"] = "same", f"Up to date ({cur['version']}, build {cur['build']})."
    return out


@router.get("/check")
def check(refresh: bool = False, db: Session = Depends(get_db)):
    url = get_kv(db, _KEY, "") or DEFAULT_URL
    token = get_kv(db, _TOKEN_KEY, "") or ""
    hit = _cache.get(url)
    if hit and not refresh and time.time() - hit[0] < _TTL:
        return {**hit[1], "url": url}
    try:
        res = evaluate(_fetch(url, token))
    except ValueError as e:
        res = evaluate(None, str(e))
    if res["status"] != "error":
        _cache[url] = (time.time(), res)
    return {**res, "url": url}


class UpdateSettings(BaseModel):
    url: str = ""
    token: str | None = None      # None = leave as it is, "" = remove


@router.get("/settings")
def get_settings_(db: Session = Depends(get_db)):
    return {"url": get_kv(db, _KEY, "") or "", "default": DEFAULT_URL, "has_token": bool(get_kv(db, _TOKEN_KEY, ""))}


@router.put("/settings")
def put_settings(body: UpdateSettings, db: Session = Depends(get_db)):
    set_kv(db, _KEY, body.url.strip())
    if body.token is not None:
        set_kv(db, _TOKEN_KEY, body.token.strip())
    _cache.clear()
    return {"url": body.url.strip(), "has_token": bool(get_kv(db, _TOKEN_KEY, ""))}
