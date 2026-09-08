"""PartsNAS application entrypoint.

    uvicorn app.main:app --reload --port 8000     (dev, from backend/)
    python -m app.main                            (same, no reload)

Serves the JSON API under /api, the KiCad HTTP library under /kicad, uploaded
images under /media, and the static vanilla-JS frontend at /.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import __version__
from .core.config import get_settings
from .core.db import Base, SessionLocal, engine
from .seed import run_all

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        run_all(db)
    yield


app = FastAPI(title="PartsNAS", version=__version__, lifespan=lifespan)


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok", "version": __version__}


@app.get("/api/info", tags=["meta"])
def info():
    return {
        "version": __version__,
        "default_currency": settings.default_currency,
        "default_vat_percent": settings.default_vat_percent,
    }


def _mount_routers() -> None:
    from .api import categories, locations

    app.include_router(categories.router)
    app.include_router(locations.router)
    # parts, stock, bulk, import, kicad -> added in the next milestone


_mount_routers()

app.mount("/media", StaticFiles(directory=settings.images_dir), name="media")
app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
