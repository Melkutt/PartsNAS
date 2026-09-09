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
- Prices are stored **ex VAT** everywhere; `app/money.py` derives `inc_vat`
  (precise) and `inc_vat_ceil` (integer, rounded **up** — the figure shown in the
  UI). Input forms take a "price includes VAT" toggle and accept `,` or `.`
  (`units.js parseNum`).
- `Part.discontinued` + `Part.replaced_by_id` (self-FK) / `replacement_mpn` /
  `replacement_sku` / `replacement_source`. The detail panel shows a banner when
  a discontinued / zero-stock part has a replacement; the list shows a `→ x` chip.
- `frontend/js/units.js`: `formatValue(raw, kind)` — capacitor/inductor/crystal
  `value` in engineering notation split on 1000 (0.1µF→100nF, 1000pF→1nF),
  resistor `value` in RKM style (2200→2k2, 4.7→4R7, 1e6→1M). Applied when copying
  from a provider and on blur of the `value` field.
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
- SQLite via `Base.metadata.create_all` + `db.sync_columns()` on startup — a
  tiny additive migration that `ALTER TABLE … ADD COLUMN`s anything an older DB
  is missing (nullable / scalar-default only). So new model columns are safe to
  ship; the user's `data/partsnas.db` self-upgrades. No Alembic. Anything beyond
  adding a column still needs a hand-written step.
- New frontend file → it's imported by `app.js` (ES modules). Assets are served
  `Cache-Control: no-store`, so no `?v=` juggling is needed for sub-imports; the
  `?v=N` on the top-level `app.js`/css in `index.html` is belt-and-braces.
- Responsive: `app.css` `@media (max-width: 900px)` (tablet) + `600px` (phone) —
  wrapping topbar, scrolling tabs, stacked rail, full-screen overlays, single-col
  forms. Test at ~390px.

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
  workbook) + `seed/part_classes_extra.json` overlay (extra dims, `series`,
  `operating_temp_min/max`, ESR, ripple, a `fuse` class, wider `tempchar` enum
  incl. `C0G (NP0)`). `app/partschema.py` merges — **extra overrides base** on a
  key collision, and a `_shared` block is appended to every class. The part
  detail form also shows an **"Additional parameters"** section with every
  `attributes` key the class schema doesn't cover, so nothing copied from a
  lookup is ever hidden.
- `/api/meta/attr-values` — distinct values already used per attribute key, so
  the edit form offers them as a `<datalist>` (recurring params → dropdown).
- `/api/settings/providers` (GET list incl. `cred_fields` + status, PUT
  `{creds:{field:value}}`), `/api/lookup/providers`,
  `POST /api/lookup` `{mpn, provider}` (each result carries `category_match` from
  `app/catmatch.py` — keyword rules + token overlap mapping the supplier category
  string onto our tree), `POST /api/parts/{id}/apply-lookup` (`apply.category` +
  `category_id`, plus manufacturer/description/datasheet/image/lifecycle/attributes).
- `/api/quotes` CRUD (`?status=open|invoiced`) + `/lines` (+ `/lines/bulk`) +
  `/export.{csv,xlsx}` + `/commit-stock` / `/uncommit-stock` / `/invoice` /
  `/unarchive` — the invoice basis. `snapshot_cost()` freezes the ex-VAT unit
  cost at add time (preferred supplier → any supplier → last purchase → 0) with a
  `cost_source` label; `Quote.markup_percent` (default 50) or a per-line
  `QuoteLine.markup_percent` gives the sell price; totals round inc-VAT **up**.
  `commit-stock` writes `kind="build"` `StockEntry` rows (`move_group=quote-<id>`,
  largest location first, shortfall as a negative at NULL); `uncommit-stock`
  writes compensating rows. `invoice` sets `status="invoiced"` (auto-commits
  stock), hiding the quote from the default list; `unarchive` reverses it. All
  reversible.
- `/api/import/partsbox` (multipart, `dry_run`), `/api/export/parts.{csv,xlsx}`.
- `/api/export/backup.zip?only_with_supplier=&category_id=&q=&include_secrets=` —
  a full, re-importable backup: `parts.json` (attributes, tags, suppliers, stock,
  replacement links, design notes) + `images/<part_id>/<file>`, and with
  `include_secrets` a `secrets.json` (Mouser key, Digi-Key client id/secret,
  locale). `/api/import/backup` (multipart `file`=zip, `mode`=merge|update|replace,
  `dry_run`) — matches parts by `id` then `mpn`, creates categories / locations by
  path, links suppliers by name, restores `secrets.json` if present. `merge` never doubles.
- `POST /api/parts/{id}/refresh-prices` — query every configured +
  `price_enabled` provider for the MPN and upsert one supplier link per
  provider (uses the disk cache; explicit-action only). Button on the Suppliers
  tab.
- `/api/parts/{id}/cost` — supplier price options for a quote line
  (`auto_link_id` = ★ preferred, else the **dearest**). `POST /api/quotes/{id}/lines`
  takes `supplier_link_id` to pin the price; the ★ on the Suppliers tab
  (`PartSupplier.preferred`) is the price source and skips the picker.
- Settings: per-provider `price_enabled` (Setting `provider:<name>:price_enabled`,
  default true) — the "search prices from here" checkbox; gates `refresh-prices`.

### Supplier providers (`app/providers/`)

`base.py` (Provider ABC + `ProviderResult`; `cred_fields` lists the credential
inputs), `mouser.py` (Search API v1 — price/stock/datasheet only, its
`ProductAttributes` is packaging-only for ICs), `digikey.py` (Product Information
**V4** — real `Parameters[]`; 2-legged OAuth `client_credentials`, token cached in
`Setting provider:digikey:token`; creds `client_id`+`client_secret` from env
`PARTSNAS_DIGIKEY_CLIENT_ID/_SECRET` or Setting; locale SE/SEK/en).
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
7. **mostly done** — `app/providers/` framework (rate limit + quota + disk cache
   + backoff + circuit breaker); **Mouser** (Search v1 — price/stock/datasheet)
   and **Digi-Key** (Product Info V4 — real parameters). Settings modal takes
   per-field creds. "Look up specs" applies attributes / category / mount / price
   / datasheet / image / supplier link. TODO: TME (HMAC), Farnell (element14 key).
8. **done** — Quotes / invoice basis (`js/quotes.js` tab, markup default 50 %,
   static cost snapshots + source, print + CSV, "Add to quote…" bulk action).
9. Review-list stock-split helper; label/QR (`GET /api/label/{id}?fmt=code128|qr`,
   server-side offline) + printable label view.
9. KiCad HTTP Library + BOM import/export; footprint-alias → KiCad footprint map.
10. Projects / builds / shortage report; min-stock warnings; theme sync.
