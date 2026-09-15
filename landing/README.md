# XRCO landing page

The marketing site for **xrco.tech** / **www.xrco.tech**.

- `index.html` — the whole page (self-contained: inline CSS + JS, Google Fonts).
- `xrco_logo.png` — the logo, referenced relatively from `index.html`.

Clean & light design, coral `#F73C58` accent, Sora / IBM Plex type. Light theme
by default with a dark-mode toggle in the header. CTA = Book a call
(`mailto:hello@xrco.tech`).

## Edit & preview locally

Edit `index.html` (and/or swap `xrco_logo.png`), then serve the folder:

```bash
cd ~/claude-projects/piodoo/landing
python3 -m http.server 8899
# open http://localhost:8899
```

Use a server (not a `file://` open) so the relative logo path and fonts load
exactly as they do in production.

## How it's served in production

This folder is part of the [piodoo](../) repo. On the piodoo server it's
bind-mounted read-only into the nginx container at `/var/www/xrco`
(see `../docker-compose.yml` and `../nginx.conf`). nginx serves it for the
hosts `xrco.tech` and `www.xrco.tech`; every other host still goes to Odoo.

## Deploy a change

Standard piodoo workflow — edit here, push, pull on the server. Because nginx
bind-mounts this folder, a `git pull` updates the live files instantly (no
container restart needed):

```bash
# local
git add landing && git commit -m "landing: <what changed>" && git push

# server (ssh -i ~/.ssh/claude_code_key ubuntu@100.88.7.93)
cd /home/ubuntu/odoo-stack && git pull
```

Then verify: `curl -s https://xrco.tech | grep -o '<title>.*</title>'`
