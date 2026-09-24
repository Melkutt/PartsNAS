# PartsNAS

**Your parts bin, in a browser.** A private, self-hosted database for electronic and
mechanical components — what you have, where it is, what it costs, and what you
need to order next. It runs in Docker on a Synology NAS (built and tested on a
DS224+) or any other machine, and you use it from any browser on your home network.
No cloud, no account, no subscription: the data is one SQLite file on your own disk.

![Parts list with category tree and filters](docs/screenshots/parts-list.png)

Built by a hobbyist for a home lab that also does the odd repair job for other
people, so it goes a bit further than an inventory: it can price a job, invoice it,
and tell you when a resistor drawer is running low. Inspired by
[PartsBox](https://partsbox.com/) and the old open-source
[ecDB](https://github.com/jwr/ecDB).

Version **0.7.0** · Python / FastAPI / SQLite · vanilla JS, no build step · [GPL-3.0 license](LICENSE)

> **Please read this first.** PartsNAS is a **hobby project**, shared as it is, free of charge and with
> **no warranty of any kind**. It is **not** business, accounting or invoicing software. Use it at your
> own risk: **you alone are responsible** for how you use it and for anything that follows from it —
> including lost or wrong data, wrong prices, stock counts or totals, and anything you print, send or
> file based on it. The author takes **no responsibility or liability** for that. See
> [Disclaimer](#disclaimer) and the [LICENSE](LICENSE).

---

## What it does

**Keep track of everything you own**
- A category tree and a storage-location tree, both any depth. Create sub-levels
  inline, rename and delete; parts move up a level when you delete a branch.
- Stock is a ledger, not a number you overwrite: add, remove, count and move, one
  part in several places at once, and every change stays in the part's history.
- Fast filtering: search plus faceted filters (mount, footprint, manufacturer,
  location, capacitance, voltage, … whatever your parts actually have), with counts.
  You can also filter for parts that are **missing a footprint or a datasheet**, so
  the gaps in your data are easy to find.
- One click on the datasheet icon opens the datasheet in a new tab.
- Parts that share a manufacturer part number are pointed out (never merged or deleted): a chip
  in the list, a **Same MPN** filter, a banner on the part, and a warning in **+ New part** if the
  part you are typing already exists somewhere. Case and punctuation are ignored.
- A through-hole resistor shows its **colour bands**, drawn from the value and tolerance.
- Pictures, notes, tags, replacement/discontinued links, and design notes such as
  "with this regulator use these resistors for 5 V".
- Barcode and QR labels you can print (also for label printers such as a DYMO), and
  USB barcode scanners work anywhere in the app.
- Bulk edit: select everything that matches a filter and move it, tag it or set its
  minimum stock in one go, with an Undo button.

**Never run out of the small stuff**
- Give a part a *Min stock*. When it reaches it, it lands on the **Order** tab, worst
  first, grouped by supplier, with a red counter on the tab itself.
- Set the quantity, then **Copy SKU + qty** for a supplier's quick-order page, or
  download a CSV. The quantity you type is remembered for that part, so a resistor you always buy
  in tens stays at 50 instead of resetting to "one short".
- When you have placed the order, press **Ordered** (or **Mark all ordered…** for a whole supplier).
  The parts move to **On order** and are not ordered twice. When the package arrives, **Received…**
  asks for the quantity, the box it goes into and the price you paid, adds the stock, and can make
  that price the part's supplier price — so a later quote uses what you really paid.

![The Order tab](docs/screenshots/order-list.png)

**Price a job, invoice it**
- Build a quote like a web shop: open **Browse parts**, click parts into the cart and
  press *Done*. Filters, search and datasheet links all work while you shop.
- Cost is a snapshot from the part's supplier price; a markup (default 50 %, changeable
  per quote and per line) gives the selling price. Add labour, shipping and other lines.
- Quotes become invoices with a running number and an invoice date. **Lock** an invoice
  to freeze it, find it later in the **Archive**, and deleted ones go to a **Trash**
  first instead of vanishing.
- Prints cleanly with your logo, a page footer (name, address, payment details) and an
  optional **Swish QR code** with the total and invoice number filled in. Export to
  CSV or Excel. VAT can be shown, or folded into one price if you are not VAT-registered.
- A part that has no price yet is flagged before you invoice it, and clicking its
  article number opens the part so you can fetch a price and continue.

![Building a quote with the cart](docs/screenshots/quote-cart.png)

**Fill it without typing**
- **Look up specs** from Mouser, Digi-Key and Farnell (bring your own API keys; TME is built but does not work yet, see *Good to know*): parameters,
  datasheet, picture and prices. Only when you press the button — never in bulk — and
  rate-limited, pausing itself if a supplier ever blocks you.
- Import from a PartsBox export, a Mouser order history (`.xls`), a vendor kit list,
  or a **BOM exported from KiCad** (with matching against your stock).
- The **Parts list** has a Price column (ex VAT): the preferred supplier's price, else the last
  purchase — the same figure a quote or the BOM's price summary would use, at a glance while you browse.

**Build a board from a KiCad project (the BOM tab)**

The BOM tab turns a KiCad project into a to-do list you can shop, build and solder from,
matched against what you actually have in stock.

1. **Import BOM.** Choose the BOM file KiCad writes (`.csv`: in the schematic editor, *Tools →
   Generate BOM*, or the *Export BOM* button). Optionally add the project's board file
   (`<project>.kicad_pcb`) in the same dialog. Nothing is saved until you press *Save project*.
2. **Review the match.** Every line is matched against your parts. An exact MPN, or a
   value + footprint you confirmed before, is picked automatically; anything else is only a
   *suggestion* with a score and the reasons. *Change…* opens a search, and *Browse…* opens the
   parts list with the right category and footprint already chosen, the way the quote cart does: click a
   part to look at it (nothing is added), press *Use* to take it. Unit prices (ex VAT) are shown while you
   choose and in the project list.
   Tick *Remember* to reuse your choice for the same value + footprint in the next BOM. The BOM
   does not say voltage, dielectric or fuse type: you decide which real part a "100n" is.
3. **Skip what is not built in.** Mounting holes, fiducials, logos and similar (`H`, `MH`, `FID`,
   `G`, `LOGO`, `SYM`, `NT`) are ticked *Skip* from the start; tick or untick any line. Skipped
   lines stay in the project but are not counted in shortages, builds or the pick list, and are
   hidden behind *Show N skipped*.
4. **The project.** Set how many boards to build to see what each line needs, what you have,
   where it is stored and what is **short**. Rows can be sorted by storage location, so you walk the
   shelves once. *Build (deduct stock)* takes the parts out of stock, and can be undone.
5. **Edit later.** A saved line can be changed at any time (*Change…* to pick another part, *Skip* /
   *Use*), and the project can be renamed with ✎. Nothing needs to be imported again.
6. **Placed.** Tick a line as you solder it on. The tick is saved, the row fades, and on the
   board the part turns blue, so you see what is left and can pick the job up again another evening.
   *Clear placed* starts over for the next board.
   Switch on **One row per component** to give every C1, C2, C3 … its own Placed box (off by default, since
   the list gets long on a big board); ticking all of a line's components ticks the line, and the reverse.
   The print dialog has the same choice (also off by default), with a tick box per component on paper.
7. **Print pick list.** Choose which columns go on the paper (tick box, reference, part, value, where it is,
   per board, needed, on hand, short), and print just the list or the board on page 1 and the list from
   page 2, with front and/or back and the reference names (C1, R2 …) drawn on it. The board is printed
   light, for paper, as you have turned it on screen. On paper the references are written as ranges, one per
   line (C3-8, C10-11, C13), so the list stays narrow. Optionally add a **price summary** at the end: what the
   parts cost, and what they sell for with a margin you set, each ex and inc VAT, using the same supplier
   prices a quote would use (lines without a price are counted and left out). Skipped lines are not printed,
   and your choices are remembered.

*The board view.* With a `.kicad_pcb` attached, PartsNAS draws the board itself next to the list,
straight from KiCad's own file (KiCad 6 to 10, no plugin and no 3D models): outline, pads,
silkscreen and its text, tracks and zones. Turn it, flip it to the back, zoom and pan, and switch
layers. **Click a line** and its parts light up in neon green on the side they sit on; **click a
part on the board** and the list jumps to its line, with what it is and where you keep it.
PartsNAS keeps the drawing (a few hundred KB per board) and a compressed copy of the file, so
the drawing can be redone when PartsNAS learns to show more. The BOM works without a board, and a
board that PartsNAS cannot read never breaks the BOM. If a board was saved before PartsNAS could
draw text, use *Replace board…* once with the same file.

**Pick the real part while you draw (KiCad 8 or newer)**
- On the Parts tab, **KiCad…** downloads a small `partsnas.kicad_httplib` file. Save it on the computer you
  draw on and add it in KiCad under *Preferences → Manage Symbol Libraries*. Your parts then show up in the
  symbol chooser, and placing one fills in value, footprint, MPN, manufacturer and datasheet, so the BOM comes
  out with exact MPNs. The NAS must be reachable from that computer over plain http (no login, like the rest).
- KiCad only sees **ready** parts: those with both a KiCad symbol and a footprint, each written with its library
  (`Device:C`, `Capacitor_SMD:C_0603_1608Metric`). Set them on a part's details, or let **KiCad…** name the
  standard SMD resistors, ceramic capacitors, inductors and LEDs from their category and package size, with a
  preview. Names you have typed yourself are never replaced; ICs and connectors are named by hand.
- Stock and price are not sent as fields on purpose: every changed field makes KiCad warn about a mismatched
  library symbol in the schematics that use the part.

**Yours to keep**
- Light, Gray and Dark themes, and a layout that works on a phone or tablet (categories and
  filters sit behind a **Filters** button there, so the list gets the screen).
- **Snapshot backup**: one ZIP that is an exact copy of everything — database, images,
  logo, settings — and a restore that puts it all back.
- **Automatic backup** (Settings, off by default): a snapshot every day into a folder you choose,
  keeping the newest few, with the last result or error shown in Settings.

![A part in detail](docs/screenshots/part-detail.png)

---

## Getting started

### Option 1 — Synology NAS (Container Manager)

Needs DSM 7.2 or newer with **Container Manager** installed.

1. Download this repository (green **Code** button → *Download ZIP*, or `git clone`).
2. In **File Station**, copy the whole folder to your NAS, for example
   `/docker/partsnas`. It must contain `docker-compose.yml`, `Dockerfile`, `backend/`,
   `frontend/` and `seed/`.
3. Open **Container Manager → Project → Create**. Give it a name (`partsnas`), pick
   that folder as the path, and choose to use the existing `docker-compose.yml`.
4. Continue and let it build. The first build takes a few minutes.
5. Open `http://<your-nas-ip>:8770` in a browser.

Your data lives in the `data/` folder next to the compose file, so it survives
restarts and updates.

### Option 2 — Any machine with Docker

```bash
git clone https://github.com/Melkutt/PartsNAS.git
cd PartsNAS
docker compose up -d
```

Then open <http://localhost:8770>. Stop it with `docker compose down`; your data stays
in `./data`.

### Option 3 — Run it directly with Python (development)

Needs Python 3.11 or newer.

```bash
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements.txt    # Windows
# .venv/bin/pip install -r backend/requirements.txt       # Linux / macOS

cd backend
../.venv/Scripts/uvicorn app.main:app --reload --port 8000   # Windows
# ../.venv/bin/uvicorn app.main:app --reload --port 8000      # Linux / macOS
```

Open <http://localhost:8000>. The database is created in `./data` the first time.

---

## Your first ten minutes

1. **Look around.** The category tree is already filled in (passives, semiconductors,
   connectors, mechanical, …). It also comes with a few example storage locations;
   rename or delete them under **Locations** and add your own boxes and drawers.
2. **Settings (the gear).** Choose your default currency and VAT rate, upload a logo,
   and write the name, address and payment details that should appear at the bottom of
   your invoices. If you use Swish, enter your number to get the QR code. Paste your
   Mouser, Digi-Key, TME and/or Farnell API keys if you want spec and price lookups.
3. **Add your first parts.** Press **+ New part**, or **Import** a spreadsheet you
   already have. Open a part and use *Look up specs…* to fill in the details.
4. **Say how much you have.** On a part's *Stock* tab, add a quantity to a location.
   Set a *Min stock* on the parts you never want to run out of.
5. **Try a quote.** On the **Quotes** tab, create one, press **Browse parts** and click
   a few parts in.

### Running the tests

```bash
cd backend
../.venv/Scripts/pip install -r requirements-dev.txt
../.venv/Scripts/python -m pytest                    # backend, against a throw-away database

cd ..
deno test --allow-read --allow-run tests/js          # frontend (Deno: https://deno.com)
```

The backend tests never touch your `data/` folder. The frontend tests check the supplier-attribute
mapping against 399 real Mouser and Digi-Key attribute names, the resistor colour code, and that every
module still parses.

## Configuration

Set these as environment variables (in `docker-compose.yml` under `environment:`).

| Variable | Default | What it does |
| --- | --- | --- |
| `PARTSNAS_DEFAULT_CURRENCY` | `SEK` | Starting currency; can also be changed in Settings. |
| `PARTSNAS_DEFAULT_VAT_PERCENT` | `25` | Starting VAT rate; can also be changed in Settings. |
| `PARTSNAS_DATA_DIR` | `./data` (`/data` in Docker) | Where the database and images are kept. |

## Backups and updating

- **Back up:** *Export → Snapshot — ZIP* gives you one file with everything. Keep a copy
  somewhere other than the NAS. (It contains your supplier API keys, so keep it private.)
- **Restore:** *Import → Restore a snapshot instead…* replaces everything with the
  snapshot. A safety copy of what was there is saved on the server first.
- **Automatic backup:** *Settings → Automatic backup* saves a snapshot every day at the hour you
  choose and keeps the newest few (default folder: `data/backups/auto`, next to your data). To save
  in another NAS folder, map it as a volume in `docker-compose.yml` (there is a commented example)
  and enter its container path. The last result, or the error, is shown in Settings.
- **Portable backup:** the other export in the same dialog is a data export you can merge
  into another database.
- **Update:** take a snapshot, replace the code on the server with the new version, and
  rebuild the project (*Container Manager → Project → Build*, or
  `docker compose up -d --build`). The `data/` folder is left alone. On Synology, starting an
  existing project again re-uses the old image, so remove the container and image first if the
  new code does not show up. The version and a **build id** in the top bar (a fingerprint of the
  code that is running) tell you which code the server really runs;
  `scripts/deploy_nas.ps1` copies the files, checks each one, and compares that id.

## Good to know

- **TME does not work yet.** The TME lookup is built (their own HMAC signature scheme, and it signs
  correctly), but on the account it was tested with, TME answers the *Search* action with
  "HTTP 403 – Access denied. You are not allowed to execute this action", even though the application,
  token and secret were set up as their guide describes. Without Search there is no way to turn an MPN
  into TME's own article number, so a lookup fails; a fallback that tries the MPN as the article number
  exists but has not been seen to work. Until that is sorted out with TME (it is a permission on their
  side, not something PartsNAS can change), treat TME as **not working** and use Mouser, Digi-Key or
  Farnell. If your TME account is allowed to Search, it may well work for you - the code is there.
- **There is no login.** PartsNAS is meant for a trusted home network. Do not expose its
  port to the internet; if you need to reach it from outside, use a VPN. Anyone who can
  open the page can read and change everything.
- The Swish QR code only handles SEK. Currency and VAT are configurable, but the wording
  and a few defaults lean Swedish.
- KiCad integration is the **BOM tab** (import a BOM, draw the board from its `.kicad_pcb`) and the
  **KiCad HTTP library** (below). It has only been checked against KiCad's own specification and PartsNAS's
  tests, not yet in a real KiCad, so tell me if KiCad complains.

## Under the hood

FastAPI, SQLAlchemy 2.0 and SQLite (WAL) on the backend; plain HTML, CSS and ES modules
on the frontend, so there is nothing to build. One container serves both.

```
backend/app/     FastAPI app, models, importers, supplier lookups
backend/tests/   pytest
frontend/        the browser app (index.html, css/, js/)
tests/js/        Deno tests for the frontend logic
seed/            starter categories, footprint aliases, part-class fields
scripts/         seed generator, deploy_nas.ps1
docs/            screenshots
```

See [CLAUDE.md](CLAUDE.md) for the design notes, data model and roadmap. To start from
scratch, delete the `data/` folder while the app is stopped.

## Disclaimer

PartsNAS is a private hobby project that the author uses at home and has chosen to share. It is
provided **"as is"**, without warranty of any kind, and **you use it entirely at your own risk**.

- **Not a business tool.** The quotes, invoices, VAT handling, Swish QR code and totals are conveniences
  for a hobbyist. They are **not** a bookkeeping, tax or invoicing system and are not checked against
  any accounting, tax or invoicing rules. If you issue invoices or rely on the numbers, you are
  responsible for making sure they are correct and lawful where you live.
- **Your data is your responsibility.** Software has bugs, disks fail and updates go wrong. Make
  backups (see above), keep them somewhere else, and test that you can restore them. The author is not
  liable for lost, damaged or wrong data.
- **Supplier data can be wrong.** Specifications, prices, stock levels and part numbers fetched from
  Mouser, Digi-Key, TME, Farnell or anywhere else come from third parties and may be incorrect or out of date.
  Check them before you rely on them, especially before you buy, order or build something.
- **No security promises.** There is no login. Keep it on a trusted network and never expose it to the
  internet. API keys are stored in the database and in snapshots — keep those private.
- **Third-party services.** You need your own accounts and API keys, and you must follow those
  services' terms. PartsNAS is not affiliated with or endorsed by Mouser, Digi-Key, TME, Farnell, PartsBox, KiCad,
  Synology or anyone else mentioned here; the names belong to their owners.

To the fullest extent the law allows, the author is not responsible or liable for any claim, damage,
loss or other consequence arising from the use of, or inability to use, this software.

## License

PartsNAS is **free software**: you can redistribute it and/or modify it under the terms of the
[GNU General Public License](LICENSE), version 3, as published by the Free Software Foundation.

Copyright © 2026 SA1CKW.

In short: you may use, study, change and share it, free of charge. If you share a copy, modified or
not, you must pass it on under the same license and make the source available, so it stays free for
everyone. This program is distributed in the hope that it will be useful, but **WITHOUT ANY WARRANTY**;
without even the implied warranty of merchantability or fitness for a particular purpose. See the
[LICENSE](LICENSE) for the details, including the disclaimer of warranty and the limitation of
liability (sections 15 and 16).
