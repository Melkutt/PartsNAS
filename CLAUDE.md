# PartsNAS

Local electronics / mechanical **component database** for the home lab, in the
spirit of PartsBox and the old open-source ecDB. Runs on a Synology **DS224+**
(Container Manager) and is used from a browser on the LAN.

Author: **SA1CKW**. **Private repo** — local `git` only for now, no remote, no
pushes. Everything — code, comments, UI strings, seed data — is **English only**.
The source workbooks are Swedish; `scripts/translations.py` holds the
Swedish→English maps applied during extraction.

## What it does (target)

- Parts with shared fields + per-class fields (resistance, Vds, …) in a JSON
  column, driven by the spec workbook.
- **Category tree** and **storage-location tree**, both arbitrary depth. Create a
  sub-node inline, rename, drag to reparent, delete (contents move up a level).
- **Bulk edit**: filter the parts list, "select all matching", then move to a
  category / move stock to a location / tag / set min-stock — one endpoint, one
  undo entry. Built for "re-sort 112 parts into a new box in a few clicks".
- **Stock as an append-only ledger** (`stock_entry`): quantity = SUM(delta);
  a move writes paired entries sharing a `move_group` so it reverts in one click.
  One part can live in several locations at once.
- **KiCad**: HTTP Library (KiCad 8/9) as the primary integration + BOM import /
  export; optional `.kicad_dbl` (ODBC) and a later action plugin.
- **Import** from the PartsBox `.xlsx`/JSON export.
- Dark-first UI: **Gray** (default) / Dark / Light, amber accent, product images
  always on a neutral grey mat so white-background photos don't glare.

## Run / develop

Backend (from `backend/`, with `../.venv` active):

```bash
uvicorn app.main:app --reload --port 8000
```

Frontend is plain HTML/CSS/ES-modules under `frontend/`, served by FastAPI at
`/`. No build step. Bump the `?v=` query on a changed `css/`/`js/` file.

First run creates `data/partsnas.db` (SQLite, WAL) and seeds the category tree +
footprint aliases from `seed/*.json`.

Regenerate the seed from the spec workbook:

```bash
python scripts/extract_spec.py "…/komponentspec.xlsx" "…/partsbox.xlsx"
```

Container:

```bash
docker compose up -d   # http://localhost:8770  (8770 -> 8000)
```

## Architecture

```
backend/app/
  main.py            FastAPI app; create_all + seed on startup (lifespan);
                     mounts /api routers, /media (images), / (frontend)
  core/config.py     pydantic-settings; PARTSNAS_* env vars; paths under data/
  core/db.py         SQLAlchemy 2.0 engine, SQLite PRAGMAs (WAL, FK on), Session
  models.py          the whole schema (see below)
  seed.py            first-run load of seed/*.json; guarantees an Unsorted category
  api/
    treeutil.py      shared helpers for the two self-referential trees
    categories.py    GET tree / POST / PATCH (rename|move|part_class) / DELETE
    locations.py     same shape for storage_location
  importers/         (next) PartsBox xlsx/json -> parts + stock ledger
  kicad/             (next) HTTP Library endpoints + BOM in/out
frontend/
  index.html         shell: topbar (tabs + theme switch) + #view
  css/theme.css      3 palettes as CSS vars on :root[data-theme]; .img-mat
  css/app.css        layout, tree widget
  js/theme.js        Light/Gray/Dark switch, localStorage, prefers-color-scheme
  js/api.js          fetch wrapper (JSON, same-origin /api)
  js/tree.js         reusable tree: collapse, inline add-child/rename/delete
  js/app.js          tab router (Categories / Locations)
seed/                categories.json, footprint_aliases.json, part_classes.json,
                     common_fields.json, storage_locations.json  (generated)
scripts/extract_spec.py   Swedish workbooks -> English seed/*.json
scripts/translations.py   Swedish -> English maps used by extract_spec.py
data/                (git-ignored) partsnas.db, images/, thumbs/
```

### Data model (`models.py`)

- **Category** / **StorageLocation** — self-referential trees, unique name per
  parent, `sort_order`. Category has `part_class` (nearest-ancestor wins) and
  `is_unsorted` (the protected catch-all).
- **Part** — `id` = 8 hex chars. Shared fields as columns; `attributes` JSON for
  per-class fields; `price_cache` JSON for API prices. `category_id` / `footprint_id`
  are `SET NULL` on delete.
- **StockEntry** — ledger: `part_id`, `location_id`, `delta`, `kind`
  (add|remove|move|count|correction|build), `unit_price`, `move_group`.
- **FootprintAlias** — `canonical`, `aliases` JSON, `group`, `kicad_footprint`.
- **Project / BomLine / Build** — BOM lines may be unresolved (`unresolved_mpn`);
  a Build turns into negative `StockEntry` rows.
- **BulkOp** — audit + one-click undo payload for bulk edits.
- **Setting** — key/JSON (theme sync, currency, VAT, API keys later).

### Conventions

- English identifiers, UI copy and seed data. New Swedish source strings get a
  mapping in `scripts/translations.py`, never a raw passthrough.
- Backend money is plain floats + a currency string; quantities are integers.
- Timestamps are timezone-aware UTC (`datetime.now(timezone.utc)`).
- SQLite via `Base.metadata.create_all` — no Alembic yet; additive changes only,
  or delete `data/partsnas.db` in dev.
- New frontend file → add `<script>/<link>` to `index.html` with `?v=N`, bump on change.

## API surface so far

- `/api/categories`, `/api/locations` — tree CRUD (see files).
- `/api/parts` (list+filter), `/api/parts/ids` (select-all-matching),
  `/api/parts/lookup?code=` (scanner), `/api/parts/{id}` CRUD.
- `/api/parts/{id}/stock` (+ `/move`) — the ledger for one part.
- `/api/bulk` + `/api/bulk/{id}/undo` — move_category / move_stock / add_tag /
  remove_tag / set_min_stock / delete, each with an undo payload.
- `/api/import/partsbox` (multipart, `dry_run`), `/api/export/parts.{csv,xlsx}`.

Frontend: `js/parts.js` (table + bulk bar + detail drawer), `js/importexport.js`
(Import/Export topbar buttons), `js/scan.js` (global `partsnas:scan` event from a
keyboard-wedge USB scanner; parts view looks the code up and opens or ticks it).

## Roadmap

1. **done** — repo skeleton, schema, seed, category + location trees, theme.
2. **done** — English rename of all seed data / labels.
3. **done** — Parts list + detail drawer, stock ledger, **bulk move**
   (parts→category, stock→location) + undo, PartsBox importer (with the
   "≈75 in the other box" review list), CSV/XLSX export, USB scanner input.
4. Part detail **edit** form with per-class fields (`part_classes.json`), images
   (Pillow thumbnails on `.img-mat`), manual stock adjust UI, the review-list
   stock-split helper.
5. **Barcode / QR** — `GET /api/label/{id}?fmt=code128|qr` (server-side, offline)
   + a printable label view; "Label" button on a part.
6. KiCad HTTP Library + BOM import/export; footprint-alias → KiCad footprint map.
7. Projects / builds / shortage report; min-stock warnings.
8. API enrichment (Nexar/Mouser/Digi-Key), theme sync via `Setting`.
