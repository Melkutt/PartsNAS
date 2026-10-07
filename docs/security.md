# Security: there is no login

**PartsNAS has no login, no passwords and no user accounts.** Anyone who can open its page can do everything in it.
It is built for one person (or one household) on a trusted home network, and that is the only way it should be run.

## What "anyone who can reach it" can do

- Read, change and **delete** every part, stock entry, quote, invoice and customer (names, addresses, phone numbers
  and email addresses you have typed in).
- **Download a snapshot**, which contains your **supplier API keys** (Mouser, Digi-Key, Farnell, TME) and, if you set
  one, your GitHub token for *Check for updates*. With those, someone else can use your supplier accounts.
- **Restore a snapshot**, which replaces everything.
- Press *Look up specs…* as often as they like and use up your supplier quotas, or get you paused or blocked.
- Make the server fetch web addresses (supplier lookups, images, the update check), so it is a way to send requests
  from inside your network.

There are no roles ("read only", "admin") and nothing is logged per person. The setting `PARTSNAS_API_TOKEN` that you
may see in `docker-compose.yml` is **reserved and not enforced**: it does nothing today.

## What to do, and not do

**Do**

- Run it on your **home LAN** and open it from computers and phones on that network.
- Reach it from outside only through a **VPN** into your home network (the Synology *VPN Server* package, WireGuard,
  Tailscale and similar), then use the same local address.
- Keep phones, TVs, guests and smart-home devices you do not trust on a **separate or guest network** that is
  isolated from the NAS. Everything on the same network segment can reach port 8770.
- On a Synology you can also add a **firewall rule** (*Control Panel → Security → Firewall*) that lets port 8770
  through only from your own subnet.
- Treat every snapshot and portable backup as a **secret**: it holds the API keys. Do not put it in cloud storage
  that others can open, in a chat, or in a git repository. The `data/` folder is already ignored by git.
- If a snapshot or the NAS might have been exposed, **create new API keys** at the suppliers and paste them in
  Settings.

**Do not**

- **Forward port 8770** (or 8000) on your router, and do not give the NAS a public address.
- Publish it through DDNS, a tunnel (Cloudflare Tunnel, ngrok and similar) or Synology's reverse proxy **without
  something in front of it that asks for a login**. A tunnel makes it public to the whole internet.
- Run it on a shared or office network where you do not trust everyone.

## Putting a login in front of it

PartsNAS cannot ask for a password itself, but a **reverse proxy** can, for example Caddy, nginx or Traefik with basic
authentication or an identity provider. Publish PartsNAS's port only to the proxy (in `docker-compose.yml`:
`"127.0.0.1:8770:8000"`) and let people reach the proxy. This has **not been tried** with PartsNAS: KiCad's library
connection uses the same address, so test that it still works through the proxy.

## Why it is built this way

It is a hobby tool for a private network, and a login system that is half done would give a false feeling of safety.
If PartsNAS ever gets real authentication it will be written down here and in the README. Until then, **the network
is the lock.**
