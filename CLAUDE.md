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
  (add|remove|move|count|correction|build), `unit_price` (**EX VAT**),
  `vat_percent`, `supplier_id`/`supplier_sku`, `move_group`.
- **Supplier** — master list; 6 built-ins seeded (Digi-Key, Mouser, RS, Farnell,
  TME, Electrokit), user adds more. **PartSupplier** — part↔supplier link:
  `sku`, `url`, `unit_price` (EX VAT) + `vat_percent`, `active`, `preferred`.
- **Attachment** — `kind` (image|datasheet|file), `stored`/`thumb` paths under
  DATA_DIR, served at `/media/<stored>`. Part.image_path caches the primary thumb.
- **DesignNote** + **DesignNoteLink** — a hint anchored to a part ("for Vout=5V
  use R1/R2…"); links point at companion parts (or an unresolved MPN).
- Prices are stored **ex VAT** everywhere; `app/money.py` derives the inc-VAT
  figure. Input forms take a "price includes VAT" toggle.
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
- `/api/parts` (list), `/api/parts/ids` (select-all-matching),
  `/api/parts/facets` (available filter values + counts), `/api/parts/lookup?code=`
  (scanner), `/api/parts/{id}` CRUD. Filters (all repeatable / multi-value):
  `q`, `category_id` (+subcats), `location_id`, `mount`, `footprint`,
  `manufacturer`, `tag`, `in_stock=yes|no`, `attr=<key>:<value>`, `low_stock`.
  `PartFilter` + `_query()` in `api/parts.py`; facets count each group with the
  *other* filters applied but not its own.
- `/api/parts/{id}/stock` (+ `/move`) — the ledger for one part; the `add` body
  takes `supplier_id`/`supplier_sku`/`price_includes_vat` and upserts PartSupplier.
- `/api/bulk` + `/api/bulk/{id}/undo` — move_category / move_stock / add_tag /
  remove_tag / set_min_stock / delete, each with an undo payload.
- `/api/suppliers` CRUD; `/api/parts/{id}/suppliers` link CRUD.
- `/api/parts/{id}/images` upload (Pillow thumbs) / delete / `…/primary`.
- `/api/design-notes` searchable list + CRUD; `/api/parts/{id}/design-notes`.
- `/api/meta/part-classes` — field schemas: `seed/part_classes.json` (from the
  workbook) + `seed/part_classes_extra.json` overlay (hand-kept extra dims —
  lead pitch, body W/H, radial/axial mounting), merged in `app/partschema.py`.
- `/api/meta/attr-values` — distinct values already used per attribute key, so
  the edit form offers them as a `<datalist>` (recurring params → dropdown).
- `/api/settings/providers` (GET list + status, PUT `{api_key}`), `/api/lookup/providers`,
  `POST /api/lookup` `{mpn, provider}`, `POST /api/parts/{id}/apply-lookup`.
- `/api/import/partsbox` (multipart, `dry_run`), `/api/export/parts.{csv,xlsx}`.

### Supplier providers (`app/providers/`)

`base.py` (Provider ABC + `ProviderResult`), `mouser.py` (Search API v1),
`safety.py` — every outbound call goes through `guarded_request()`:
per-minute token bucket + per-day quota (persisted in `Setting` under
`provider:<name>:state`), disk cache at `data/providers/<name>/<sha1(mpn)>.json`
(14-day TTL), exponential backoff on 429/5xx honouring `Retry-After`, and a
**circuit breaker** — a 403/429/"blocked" body sets `blocked_until` and the
provider is skipped for 8 h (the Celestrak lesson). Providers run **only** from
the "Look up specs" button, never bulk/auto. Keys: env
`PARTSNAS_MOUSER_API_KEY` wins, else the `Setting` value; never returned by the API.

Frontend: `js/parts.js` is a two-pane view — `js/catrail.js` (left: selectable
Categories/Locations tree) + faceted filter bar (multi-select checkboxes with
live counts, active-filter chips) + results table + bulk bar. `js/partdetail.js`
(right-side panel: Details edit w/ per-class fields + `<datalist>` of prior
values + images, Stock adjust/move, Suppliers ex/inc VAT, Notes),
`js/suppliers.js`, `js/designnotes.js`, `js/importexport.js`, `js/scan.js`
(USB keyboard-wedge → `partsnas:scan`). Clicking a Category/Location tree node on
the *Categories/Locations tabs* also jumps to Parts filtered by it.

## Roadmap

1. **done** — repo skeleton, schema, seed, category + location trees, theme.
2. **done** — English rename of all seed data / labels.
3. **done** — Parts list, stock ledger, **bulk move** + undo, PartsBox importer,
   CSV/XLSX export, USB scanner input.
4. **done** — part detail panel (edit + per-class fields + images), stock
   adjust/move UI, suppliers + VAT (ex/inc), 6 built-in suppliers + custom,
   supplier SKU, tree→parts linking.
5. **done** — Design Notes tab.
6. **done** — two-pane Parts view (left rail + faceted dynamic filters incl.
   class parameters over subcategories), expanded per-class dimensions
   (`part_classes_extra.json`), parameter datalists from prior values.
7. **partly done** — `app/providers/` framework (rate limit + quota + disk cache
   + backoff + circuit breaker), **Mouser** provider, Settings modal for keys,
   "Look up specs" button → apply attributes / price / datasheet / image /
   supplier link. TODO: TME (HMAC), Digi-Key (OAuth2), Farnell.
8. Review-list stock-split helper; label/QR (`GET /api/label/{id}?fmt=code128|qr`,
   server-side offline) + printable label view.
9. KiCad HTTP Library + BOM import/export; footprint-alias → KiCad footprint map.
10. Projects / builds / shortage report; min-stock warnings; theme sync.
