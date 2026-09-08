# PartsNAS

A local electronics & mechanical **component database** for the home lab —
categories, storage locations, stock, BOMs and KiCad integration — meant to run
in Docker on a Synology NAS (DS224+) and be used from a browser on the LAN.

Inspired by [PartsBox](https://partsbox.com/) and the old open-source
[ecDB](https://github.com/jwr/ecDB).

Status: **early scaffold.** Working today: category tree, storage-location tree
(create / rename / delete, arbitrary depth), and the Light / Gray / Dark theme.
See [CLAUDE.md](CLAUDE.md) for the design and roadmap.

## Quick start (development)

```bash
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements.txt   # Windows
# .venv/bin/pip install -r backend/requirements.txt      # Linux/macOS

cd backend
../.venv/Scripts/uvicorn app.main:app --reload --port 8000
```

Open <http://localhost:8000>.

## Docker / NAS

```bash
docker compose up -d
```

Serves on port **8770**; the SQLite database and uploaded images live in `./data`
(bind-mounted, so back it up by copying the folder).

## Stack

FastAPI + SQLAlchemy 2.0 + SQLite on the backend; plain HTML/CSS/ES-modules on
the frontend (no build step). Python 3.11+.
