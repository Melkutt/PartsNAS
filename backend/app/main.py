"""PartsNAS application entrypoint.

    uvicorn app.main:app --reload --port 8000     (dev, from backend/)
    python -m app.main                            (same, no reload)

Serves the JSON API under /api, the KiCad HTTP library under /api/kicad, uploaded
images under /media, and the static vanilla-JS frontend at /.
"""
from __future__ import annotations

import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .autosnapshot import start_scheduler as start_autosnapshot
from .buildid import build_id
from .core.config import get_settings
from .core.db import Base, SessionLocal, engine, sync_columns
from .seed import run_all

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    added = sync_columns()  # ADD COLUMN for anything an older DB is missing
    if added:
        print(f"[migrate] added columns: {', '.join(added)}")
    with SessionLocal() as db:
        run_all(db)
    start_autosnapshot()
    yield


app = FastAPI(title="PartsNAS", version=__version__, lifespan=lifespan)


@app.exception_handler(Exception)
async def _json_errors(request: Request, exc: Exception):
    # Single-user LAN app: return the message as JSON so the frontend can show
    # something useful instead of choking on a plain-text "Internal Server Error".
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


@app.middleware("http")
async def _no_cache_assets(request, call_next):
    resp = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".html", ".js", ".css")):
        # no-store: the frontend is unbundled ES modules and iterates fast;
        # a stale sub-import is worse than re-fetching a few KB on a LAN.
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok", "version": __version__, "build": build_id()}


@app.get("/api/info", tags=["meta"])
def info():
    return {
        "version": __version__,
        "default_currency": settings.default_currency,
        "default_vat_percent": settings.default_vat_percent,
    }


def _mount_routers() -> None:
    from .api import (
        autosnapshot,
        backup,
        bom,
        bulk,
        categories,
        customers,
        design_notes,
        exports,
        images,
        imports,
        kicad,
        labels,
        locations,
        lookup,
        meta,
        order,
        parts,
        quotes,
        settings_api,
        snapshot,
        stats,
        stock,
        suppliers,
    )

    app.include_router(bom.router)
    app.include_router(kicad.router)
    app.include_router(categories.router)
    app.include_router(locations.router)
    app.include_router(parts.router)
    app.include_router(stock.router)
    app.include_router(bulk.router)
    app.include_router(suppliers.router)
    app.include_router(customers.router)
    app.include_router(images.router)
    app.include_router(labels.router)
    app.include_router(design_notes.router)
    app.include_router(meta.router)
    app.include_router(quotes.router)
    app.include_router(stats.router)
    app.include_router(order.router)
    app.include_router(settings_api.router)
    app.include_router(lookup.router)
    app.include_router(imports.router)
    app.include_router(exports.router)
    app.include_router(backup.router)
    app.include_router(snapshot.router)
    app.include_router(autosnapshot.router)


_mount_routers()

class MediaFiles(StaticFiles):
    """Only the public-facing asset folders — data/ also holds the database
    (with the supplier API keys in it), provider caches and snapshots, none of
    which may ever be downloadable by URL."""

    _ALLOWED = {"images", "thumbs", "branding"}

    async def get_response(self, path, scope):
        first = path.replace("\\", "/").lstrip("/").split("/", 1)[0]
        if first not in self._ALLOWED:
            raise StarletteHTTPException(status_code=404)
        return await super().get_response(path, scope)


app.mount("/media", MediaFiles(directory=settings.data_dir), name="media")
app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
