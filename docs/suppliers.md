# Suppliers and API keys

**Look up specs…** on a part asks a supplier's API for parameters, datasheet, picture and price, and lets you copy
what you want onto the part. It only runs when you press the button, never in bulk or on a timer. Keys are entered
under **Settings** (the gear) and are stored in your database (and in snapshots: keep those private).

| Supplier | What you need | Notes |
|---|---|---|
| **Mouser** | an API key | The country is set on Mouser's side, per key (a `.se` key gives SEK). |
| **Digi-Key** | client id + client secret | Site, language and currency default to SE / en / SEK. |
| **Farnell** | an API key (element14 Partner Portal → *View API Key*) | Asks `se.farnell.com` in SEK by default. A wrong store gives a price in the wrong currency without any error. |
| **TME** | token + application secret | **Does not work yet**, see [Troubleshooting](troubleshooting.md). Built, but the tested account is not allowed to use TME's *Search* action. |

## What a lookup gives you

- Manufacturer, description, datasheet link and picture.
- The supplier's **price breaks** (ex VAT). The lowest quantity is used as the unit price and is stored as a supplier
  link on the part, so a quote, the BOM and the Price column in the parts list use it.
- Parameters. Digi-Key returns real parameters; Mouser and Farnell return fewer, so PartsNAS also reads what it can
  out of the description (capacitance, voltage, tolerance, size …).
- For an IC, the package text. An empty **Footprint** is filled in the way people write it (`8-SOIC` becomes
  `SOIC-8`), and the KiCad footprint from the [footprint rules](kicad.md) when a rule is certain.

**Fetch prices from all APIs** (on a part) asks every configured supplier at once and files one price per supplier.
Tick *search prices from here* per supplier in Settings to choose which ones take part.

## Suppliers without an API

A lot of parts come from shops that have no API, or from eBay, Tradera or a drawer of unlabelled bits. For those, use
**Add supplier link** on the part's Suppliers tab instead of *Look up specs…*: pick the supplier, optionally an
article number, the product page and a price, and mark it *Preferred* if a quote should use it.

The dialog starts on the supplier you picked **last time**, whichever it was, so going through a box of parts from
one shop takes a single pick. The first time it starts on Mouser. The choice is remembered by the browser you use.

## Limits and protection

Every supplier has a rate limit and a daily quota (shown in Settings, like `ready · 3/1000 today · 10/min`), and an
answer is cached for two weeks, so looking at the same MPN again costs nothing.

If a supplier answers 403/429 or a block page, PartsNAS **pauses** that supplier (about 8 hours) so it is not
hammered into a longer block. The status shows *paused until …* with a **Reset** button. Use it only when the pause
came from a bug you have fixed; a real block just trips again. A supplier that explains an error itself (a wrong
signature, a missing permission) does not pause anything: you see the message.

Prices, stock and specifications come from third parties and can be wrong or out of date. Check them before you buy.
