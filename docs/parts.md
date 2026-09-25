# Parts, categories and locations

## Categories and storage locations

The **Categories** and **Locations** tabs each hold a tree of any depth. Hover a row for the actions: **+ sub**
(add below it), **rename** (or double-click the name), **delete** (its parts and sub-levels move up one level) and
**▲ ▼**, which put the row earlier or later among its siblings, at the top level and in sub-trees alike. There is no
drag-and-drop and no way yet to move a branch under another parent.

In the **Parts** tab the same trees sit in the list on the left (switch between *Categories* and *Locations*). Click
a node to see only the parts in it and below it; the list keeps its scroll position when you do.

## The parts list

- Search, and **faceted filters** built from what your parts actually have (mount, footprint, manufacturer,
  location, capacitance, voltage …), with counts. *Customize filters* chooses which appear.
- Filters for **Low stock**, **Uncategorized** and **Same MPN** (parts that share a manufacturer part number: pointed
  out, never merged), and for parts **missing a footprint or datasheet**.
- **Price** column: the unit price ex VAT, the same one a quote or the BOM would use.
- Select rows for **bulk edit**: move to a category or location, tag, set min stock. One undo covers the whole edit.

## The part panel

Click a part's **name** to open it. With a part open:

- click another part's **name** in the list behind it to go straight to that part,
- press **↑ / ↓** to step to the previous / next part in the list (in the order shown, within your filter). This does
  nothing while you are typing in a field, while something is unsaved, or while another window is open on top,
- click anywhere else, or press Esc, to close the panel. Unsaved changes in the panel are then discarded.

The tabs hold details (name, MPN, footprint, KiCad names, datasheet, description, notes), stock (a ledger: add, remove,
count, move, one part in several places), suppliers and prices, pictures, labels and design notes.

## Stock

Stock is a ledger, not a number you overwrite. A move is a pair of entries that can be reversed in one click.
Give a part a **Min stock** and it appears on the **Order** tab when it reaches it (see the README).

## KiCad names on a part

*KiCad symbol*, *KiCad footprint* and *Other KiCad footprints* on the details tab make the part available in KiCad's
symbol chooser. See [KiCad](kicad.md).
