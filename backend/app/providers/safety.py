"""The guard rails around every outbound provider request.

Why: an over-eager Celestrak polling loop once got the host IP blocked. So:

* per-minute token bucket (in-process) + per-day quota (persisted in Setting)
* circuit breaker: a 403 / 429 / "blocked" body opens it for BACKOFF_S, persisted
* disk cache under data/providers/<name>/<sha1(mpn)>.json with a long TTL
* exponential backoff on 429 / 5xx, honouring Retry-After
* honest User-Agent
* callers pass through here ONLY on an explicit user click

State lives in Setting under `provider:<name>:state`:
    {"day": "2026-09-09", "used_today": N, "blocked_until": <epoch|null>}
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import date

import httpx
from sqlalchemy.orm import Session

from .. import __version__
from ..core.config import get_settings
from ..core.kv import get_kv, set_kv
from .base import ProviderBlocked, ProviderError

UA = f"PartsNAS/{__version__} (local component database; +https://github.com/Melkutt)"
BACKOFF_S = 8 * 3600          # circuit-breaker cool-down after a block
CACHE_TTL_S = 14 * 24 * 3600  # re-use a cached lookup for two weeks
HTTP_TIMEOUT = 12.0

_minute_bucket: dict[str, list[float]] = {}  # name -> recent request timestamps


def _state_key(name: str) -> str:
    return f"provider:{name}:state"


def _load_state(db: Session, name: str) -> dict:
    st = get_kv(db, _state_key(name), {}) or {}
    today = date.today().isoformat()
    if st.get("day") != today:
        st = {"day": today, "used_today": 0, "blocked_until": st.get("blocked_until")}
    st.setdefault("used_today", 0)
    st.setdefault("blocked_until", None)
    return st


def status(db: Session, name: str, *, per_min: int, per_day: int) -> dict:
    st = _load_state(db, name)
    now = time.time()
    blocked = bool(st["blocked_until"] and st["blocked_until"] > now)
    return {
        "used_today": st["used_today"],
        "quota_day": per_day,
        "per_min": per_min,
        "blocked_until": st["blocked_until"] if blocked else None,
    }


def _cache_path(name: str, mpn: str):
    d = get_settings().data_dir / "providers" / name
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.sha1(mpn.strip().lower().encode()).hexdigest() + ".json")


def cache_get(name: str, mpn: str) -> dict | None:
    p = _cache_path(name, mpn)
    if not p.exists() or time.time() - p.stat().st_mtime > CACHE_TTL_S:
        return None
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def cache_put(name: str, mpn: str, payload: dict) -> None:
    try:
        _cache_path(name, mpn).write_text(json.dumps(payload), "utf-8")
    except OSError:
        pass


def _trip_breaker(db: Session, name: str, why: str, retry_after: int | None) -> ProviderBlocked:
    wait = retry_after or BACKOFF_S
    st = _load_state(db, name)
    st["blocked_until"] = time.time() + wait
    set_kv(db, _state_key(name), st)
    human = f"~{round(wait / 3600, 1)} h" if wait >= 3600 else f"~{wait} s"
    return ProviderBlocked(f"{name}: {why} — pausing this provider for {human}", retry_after)


def reset_breaker(db: Session, name: str) -> None:
    """Manually lift a pause (Settings 'Reset' button). Leaves today's used_today count alone -
    only the block itself is cleared, so a config bug fixed mid-pause doesn't cost the rest of
    the day's runway too."""
    st = _load_state(db, name)
    st["blocked_until"] = None
    set_kv(db, _state_key(name), st)


def _api_error_detail(resp: httpx.Response) -> str | None:
    """A 403/429 whose body is the API's OWN structured error (not an anti-bot block page) -
    e.g. TME's {"ErrorCode":21,"ErrorMessage":"..."}. That means the server understood the
    request and rejected it for a reason it explains - a signature or parameter bug, fixed by a
    code change, not by waiting. Only an unexplained 403/429 (no such body) trips the breaker;
    otherwise a bug during development burns the same 8h pause as a real block, every time."""
    try:
        j = resp.json()
    except ValueError:
        return None
    if not isinstance(j, dict):
        return None
    for key in ("ErrorMessage", "error_description", "error", "message", "Message"):
        if j.get(key):
            code = j.get("ErrorCode") or j.get("Status") or j.get("code")
            return f"{code}: {j[key]}" if code else str(j[key])
    errs = j.get("Errors") or j.get("errors")
    if errs:
        return "; ".join(str(e) for e in (errs if isinstance(errs, list) else [errs]))
    return None


def guarded_request(
    db: Session,
    name: str,
    *,
    method: str,
    url: str,
    per_min: int,
    per_day: int,
    **kw,
) -> dict:
    """Rate-limited, quota-checked, breaker-guarded JSON request. Raises
    ProviderBlocked / ProviderError; never returns a non-2xx body."""
    st = _load_state(db, name)
    now = time.time()

    if st["blocked_until"] and st["blocked_until"] > now:
        left = int(st["blocked_until"] - now)
        raise ProviderBlocked(f"{name} is paused for another {left // 60} min", left)

    if st["used_today"] >= per_day:
        raise ProviderBlocked(f"{name}: daily quota of {per_day} reached — try tomorrow")

    bucket = _minute_bucket.setdefault(name, [])
    bucket[:] = [t for t in bucket if now - t < 60]
    if len(bucket) >= per_min:
        wait = int(60 - (now - bucket[0])) + 1
        raise ProviderBlocked(f"{name}: rate limit ({per_min}/min) — wait {wait}s", wait)

    headers = {"User-Agent": UA, "Accept": "application/json", **kw.pop("headers", {})}
    last_err = "unknown error"
    for attempt in range(3):
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT) as c:
                resp = c.request(method, url, headers=headers, **kw)
        except httpx.HTTPError as e:
            # a malformed/non-HTTP response (a raw HTML block or challenge page with no proper
            # status line - h11 calls that an "illegal header line") looks like this too; the
            # message can be arbitrarily long (it may echo the whole bad body), so cap it
            last_err = f"network error: {str(e)[:200]}"
            time.sleep(1.5 * (attempt + 1))
            continue

        bucket.append(time.time())
        st["used_today"] += 1
        set_kv(db, _state_key(name), st)

        if resp.status_code in (403, 429):
            detail = _api_error_detail(resp)
            if detail is not None:
                raise ProviderError(f"{name}: HTTP {resp.status_code} — {detail}")
            ra = _retry_after(resp)
            raise _trip_breaker(db, name, f"HTTP {resp.status_code} (rate limit / block)", ra)
        if _looks_blocked(resp):
            raise _trip_breaker(db, name, "response body looks like a rate-limit/block page", None)
        if resp.status_code >= 500:
            last_err = f"HTTP {resp.status_code}"
            time.sleep(1.5 * (attempt + 1))
            continue
        if resp.status_code >= 400:
            raise ProviderError(f"{name}: HTTP {resp.status_code} — {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError:
            raise ProviderError(f"{name}: response was not JSON")

    raise ProviderError(f"{name}: {last_err} after retries")


def _looks_blocked(resp: httpx.Response) -> bool:
    if resp.status_code != 200:
        return False
    low = resp.text[:600].lower()
    return any(s in low for s in ("rate limit", "blocked", "access denied", "abuse", "too many requests"))


def _retry_after(resp: httpx.Response) -> int | None:
    v = resp.headers.get("Retry-After")
    if v and v.isdigit():
        return int(v)
    return None
