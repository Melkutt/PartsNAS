# BOM and building a board

The **BOM** tab turns a KiCad project into a to-do list you can shop, build and solder from, matched against
what you actually have in stock.

## 1. Get a BOM out of KiCad

In the schematic editor use the BOM export: the **BOM** button in the toolbar (in some KiCad versions also under
*Tools*). PartsNAS reads the CSV.

**Make sure the MPN is a column.** KiCad only exports the columns that are switched on. In the export dialog
tick **Show** for the `MPN` field (and `Manufacturer` if you like). Without an MPN column PartsNAS can only guess
from value and footprint, and a line then shows as a suggestion (about 65–95 %), never as certain.

Recognised column names:

| Meaning | Header (any case) |
|---|---|
| Reference | Reference, References, Refdes, Designator, Designators |
| Value | Value |
| Footprint | Footprint, Package |
| Quantity | Qty, Quantity, Count |
| MPN | MPN, Manufacturer Part Number, Mfr Part #, Part Number, … |
| MPN, second choice | LCSC Part #, JLCPCB Part #, Mfg Part … |

The JLCPCB fabrication plugin's `production/bom.csv` names the column **LCSC Part #** whatever field you mapped
into it. PartsNAS reads it as the MPN, unless it holds a real LCSC number (`C14663`), which is not an MPN and is
ignored. A column that plainly says MPN always wins.

## 2. Import

*Import BOM…* asks for the CSV and, optionally, the project's **`.kicad_pcb`** (see *The board view* below).
Nothing is saved until you press **Save project**.

## 3. Review the match

Every line is matched against your parts:

| Badge | Meaning |
|---|---|
| **MPN exact** (100 %) | The MPN is one of your parts. Certain. |
| **Remembered** (100 %) | You confirmed this value + footprint before (*Remember*). |
| **~NN % match** | A suggestion from footprint and value. Never applied on its own; you confirm it. |
| **No match** | Nothing fitted. |

For a line you are not happy with:

- **Change…** opens a search box.
- **Browse…** opens the Parts list with the right category (from the reference letter), package size and value
  already chosen. Click a part to look at it (nothing is added), press **Use** to take it. Unit prices (ex VAT) are
  shown so a wrong-priced part stands out.
- **+ New part** creates a part on the spot.
- Tick **Remember** to reuse the choice for the same value + footprint in later BOMs.

A BOM says "100n", not the voltage, dielectric or ESR: you decide which real part it is. (If you want to decide
while drawing instead, see [KiCad](kicad.md).)

**Skip** column: mounting holes, fiducials, logos and similar (`H`, `MH`, `FID`, `G`, `LOGO`, `SYM`, `NT`) are ticked
from the start. Skipped lines stay in the project but are left out of shortages, builds, prices and the pick list.

## 4. The project

- **Boards to build** sets the quantity; *Needed*, *On hand* and *Short* follow.
- **Where it is** shows the storage locations. *Sort by location* orders the rows by shelf, so you walk the
  shelves once.
- **Price** is the unit price ex VAT: the preferred supplier's price, else the dearest supplier price, else the last
  purchase, the same figure a quote would use.
- **Show N skipped** reveals the skipped lines.
- **Change…** and **Skip / Use** edit a saved line. **✎ Rename** renames the project.
- **Build (deduct stock)** takes the parts out of stock. It can be undone under *Build history*.

### Placed

Tick **Placed** as you solder a line on. The tick is saved, the row fades, and on the board the part turns blue,
so a half-built board can be picked up another evening. *Clear placed* starts over for the next board.

Switch on **One row per component** to give every C1, C2, C3 … its own box. It is off by default, because the list
gets long on a big board. Ticking all of a line's components ticks the line, and the reverse.

## The board view

With a `.kicad_pcb` attached, PartsNAS draws the board itself, straight from KiCad's file (KiCad 6 to 10, no
plugin, no 3D models): outline, pads, silkscreen and its text, tracks and zones.

- Turn it (⟲ ⟳), flip to the back, zoom, pan, switch layers.
- **Click a line** and its parts light up in **neon green**, on the side they sit on.
- **Click a part** on the board and the list jumps to its line.
- Placed parts are **blue**.
- Text is drawn in Courier New at the size in the file (KiCad's own stroke font is not available in a browser), so
  it is close, not identical.

PartsNAS keeps the drawing and a compressed copy of the file, so the drawing can be redone when PartsNAS learns to
show more. A board saved before text was supported shows a hint: use **Replace board…** once with the same file.

## Printing a pick list

*Print pick list* opens a dialog (your choices are remembered):

- **Columns**: tick box, reference, part, value, where it is, per board, needed, on hand, short, price.
- **Rows**: optionally one row per component, each with its own tick box.
- **Board**: the list from page 1, or the board on page 1 (front and/or back, with the reference names drawn on it)
  and the list from page 2. The board is printed light, for paper, as you have turned it on screen.
- **Price summary**: what the parts cost, and what they sell for with a margin you set (default 50 %), each ex and
  inc VAT. Lines without a price are counted and left out; the summary says how many.

On paper the references are ranges, one per line (`C3-8`, `C10-11`, `C13`), so the column stays narrow. Skipped
lines are not printed.
