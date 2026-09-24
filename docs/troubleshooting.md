# Troubleshooting

Messages you can meet, what they mean, and what to do. Most are about supplier lookups and KiCad.

## Supplier lookups (Settings → API keys)

**Every provider is paused with "pausing this provider for ~8 h".**
A supplier answered 403/429 (or a block page) and PartsNAS stopped calling it to avoid getting blocked. If you know
the cause was a bug that has been fixed, press **Reset** next to the provider in *Settings*. A real block will just
trip again. An answer where the supplier explains the error itself (like TME's "Signature value is invalid") does
**not** pause the provider.

**TME: "HTTP 403 – 4: Access denied. You are not allowed to execute this action."**
The signature is right, but the account is not allowed to use the *Search* action, so an MPN cannot be turned into
TME's article number. It is a permission on TME's side. PartsNAS then tries the MPN as the article number, which
only sometimes works. Until TME enables Search for the account, treat TME as not working and use Mouser, Digi-Key
or Farnell.

**Mouser: "network error: illegal header line: … <!doctype html …".**
Mouser (or something in front of it) answered with a web page instead of data. Check <https://www.mouser.se>: if it
shows "Be back soon…" the site is down; try again later. It does not use up the daily quota and does not pause
the provider.

**Farnell shows a price that is far too low or too high.**
The price is for the wrong store and currency. PartsNAS asks `se.farnell.com` in SEK by default. Lookups are cached
for two weeks, so an old wrong answer can linger: delete `data/providers/farnell/` (or wait).

**A provider says "not configured".**
Enter its key in *Settings*. Each provider has its own fields (Mouser: API key; Digi-Key: client id and secret; TME:
token and secret; Farnell: API key).

## BOM

**The BOM only matches 95 % (or 65 %), although I have MPNs in KiCad.**
The MPN is not in the CSV. KiCad only exports the columns that are switched on: in the BOM export dialog tick
**Show** for `MPN`. Open the CSV in a text editor to check that the column is there. See [BOM](bom.md).

**A line is "unresolved".**
No part matched. Use **Change…**, **Browse…** or **+ New part** on the line.

**The board shows no silkscreen text.**
The board was saved before PartsNAS could draw text. Press **Replace board…** once with the same `.kicad_pcb`.
(If you just updated PartsNAS and it still shows no text, the server may still be running the old code: restart it.)

## KiCad

**The PartsNAS library is empty in KiCad.**
Open `<address>/api/kicad/v1/categories.json` in a browser. If it is `[]`, no part is *ready* yet: press **KiCad…** on
the Parts tab and name the parts, or fill in *KiCad symbol* and *KiCad footprint* (with libraries) by hand.

**KiCad cannot connect.**
The address in the `.kicad_httplib` file must be reachable from that computer over plain **http**, and the server
must be running. A file downloaded from `localhost` only works on the same computer; download it again from the
NAS address when you move over.

**A part I just named is missing.**
KiCad caches categories (about 10 minutes) and parts (about 1 minute). Restart KiCad.

**The file dialog only shows `.kicad_sym`.**
Set the file type to *All files*, or type the full path, or add the library with the **+** button (format **HTTP**).
See [KiCad](kicad.md).

**KiCad says "library symbol mismatch".**
A field of the part changed since the symbol was placed. Use *Update symbols from library* in KiCad. PartsNAS avoids
this by not sending stock or price as fields.

## Running PartsNAS

**After an update nothing changed.**
- On your own computer: the server does not reload by itself. Stop it and start it again, and reload the page
  (Ctrl+F5).
- On the NAS: copy the new code, then delete the project's **container and image** in Container Manager and create
  it again (*Start* alone re-uses the old image). `/api/health` shows the build id; compare it with your copy.

**A new version number.** `0.x.y`: the middle number goes up when something new is added, the last when only bugs
are fixed. `1.0.0` is reserved for "finished and stable".
