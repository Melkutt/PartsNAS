# KiCad

There are two ways to use PartsNAS with KiCad. They can be mixed, per circuit.

| | You draw with… | You choose the real part… | Good when |
|---|---|---|---|
| **BOM tab** | generic values (`100n`) | afterwards, in the [BOM tab](bom.md) | you do not care yet which capacitor it is |
| **HTTP library** (this page) | real parts from PartsNAS | while you draw, in KiCad's symbol chooser | voltage, ESR, tolerance matter, or you want exact MPNs in the BOM |

The HTTP library needs **KiCad 8 or newer**. It works by KiCad asking PartsNAS for parts over the network; nothing
is written back.

## Which parts KiCad sees

Only **ready** parts: a part must have both a **KiCad symbol** and a **KiCad footprint**, each written with its
library:

- symbol: `Device:C`
- footprint: `Capacitor_SMD:C_0603_1608Metric`

A part without a library prefix (`C_0603_1608Metric`) is not ready, because KiCad could not find it. Set the two
fields on a part's details page (*KiCad symbol*, *KiCad footprint*).

### Footprint rules for ICs, transistors and diodes

Standard passives are named from category and size (below). Everything else with a package (SOIC, SOT-23, TO-220,
TQFP, DIP, diodes …) is named by **footprint rules**. A rule has patterns that must all match:

| Pattern on | Reads | Example |
|---|---|---|
| `case` | the supplier's *Package / Case* (attribute `packagecase`) | `8-SOIC (0.154", 3.90mm Width)` |
| `device` | the supplier's *Supplier Device Package* | `8-VSSOP` |
| `raw` | your own *Footprint* text | `SOIC-8` |

The width in *Package / Case* is what tells a narrow SOIC-8 (3.9 mm) from a wide one (5.3 mm), which your own
`SOIC-8` cannot. Rules that only read your own text are **guesses** of the common variant: they are proposed but not
ticked. The first matching rule wins; **your own rules (Settings → KiCad footprint rules) are tried before the
built-in ones**, and the built-in ones can be read there. Names that need more information (QFN and DFN pad sizes,
exposed-pad variants, modules) are left for you to name by hand.

**Scope.** Select a category in the Parts list first, then press **KiCad…**: only parts in that category (and below
it) are considered. With no category selected, every part is.

**New parts.** A new part gets its KiCad footprint straight away when a *certain* rule matches (never a guess), and
a *Look up specs* fills in *Footprint* the way people write it (the supplier's `8-SOIC` becomes `SOIC-8`) and then the
KiCad footprint. Existing values are never replaced. A footprint typed without its library (`SOIC-8_3.9x4.9mm_P1.27mm`)
is completed with it when a rule confirms that it is the right one.

### Naming standard passives automatically

On the **Parts** tab, **KiCad…** opens a dialog that names the standard SMD resistors, ceramic capacitors,
inductors and LEDs for you, from the category and the package size (`0603`, `0805`, …), with a preview. Things it
does not touch: electrolytics, tantalums, resistor networks, anything whose package is not a size code, and ICs and
connectors (those you name by hand). It only fills fields that are **empty**; a name you typed yourself is never
replaced.

Choose the **default footprint**: *hand-solder pads* (`…_Pad1.08x0.95mm_HandSolder`) or *standard pads*. The other
kind is added as an alternative. The names are KiCad's own (checked against KiCad's footprint libraries).

## Several footprints for one part

A part has one **default footprint** and, in *Other KiCad footprints* on the details page, any number of others
(one per line, each with its library). In KiCad's symbol chooser every footprint is its own row:

```
100n 25V X7R
100n 25V X7R · C_0603_1608Metric_Pad1.08x0.95mm_HandSolder
```

You pick the pads when you place the part. MPN, value and datasheet are the same. Every entry also tells KiCad's
footprint chooser to offer the package's other pad variants (a wildcard like `Capacitor_SMD:C_0603_1608Metric*`),
so you can change your mind later.

## Connect KiCad

1. In PartsNAS (Parts tab) press **KiCad…** and **Download partsnas.kicad_httplib**. The file contains the address
   you are using in the browser at that moment (`http://localhost:8000/api/kicad/` while experimenting on your own
   computer, `http://<nas-ip>:8770/api/kicad/` on the NAS). Download it from the address KiCad should use.
2. Save it on the computer you draw on.
3. In KiCad's schematic editor: *Preferences → Manage Symbol Libraries*, add the file as a library.
   - If the file dialog only shows `.kicad_sym` files, change the file type at the bottom of the dialog to
     *All files*, or type the full path into the file name field.
   - Or add a row with **+**: nickname `PartsNAS`, the full path to the file as the library path, library format
     **HTTP**.
4. Press **A** to add a symbol. Under *PartsNAS* the categories appear as libraries. Pick a part and place it.
5. Press **E** on the symbol: value, footprint, datasheet, `MPN` and `Manufacturer` are filled in.

Requirements: the computer must reach PartsNAS over plain **http** (a self-signed https certificate makes KiCad
refuse the connection), and the address must stay the same (use the NAS's fixed IP address).

There is no login or token, like the rest of PartsNAS: keep it on a trusted network.

## What is sent to KiCad

`value`, `footprint` (hidden), `datasheet` (hidden), `reference` (C, R, L, D for the standard symbols), `MPN` and
`Manufacturer` (hidden), and a description. **Stock and price are not sent**, on purpose: every field that changes
makes KiCad warn about a "library symbol mismatch" in the schematics that use the part.

KiCad caches the category list for about 10 minutes and the parts for about 1 minute. A newly named part can take
that long to appear; restarting KiCad is faster.

## Getting the MPN into the BOM

Placing a part from the library puts the MPN on the symbol, but KiCad's BOM export only includes the columns you
switch on. In the BOM export dialog tick **Show** for `MPN`. Then [PartsNAS](bom.md) matches the line exactly
(100 %). See also *Troubleshooting → The BOM only matches 95 %*.

## For developers

The endpoints follow KiCad's HTTP library specification (v1): `/api/kicad/v1/`, `categories.json`,
`parts/category/{id}.json`, `parts/{id}.json`; all values are strings. Extra footprints have the id
`<part id>~<n>`. Code: `backend/app/api/kicad.py`, `backend/app/kicadlib.py`, `frontend/js/kicadnames.js`.
