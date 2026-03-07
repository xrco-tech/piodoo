# How to check nginx and Cloudflare config (for WebSocket / 8072)

Your stack uses **Cloudflare Tunnel** (cloudflared) in Docker. You may or may not have **nginx** on the host. Below is how to check both and ensure `/websocket` (and `/longpolling`) reach Odoo on port **8072**.

---

## 1. Check if nginx is in front of Odoo

On the **server** (where Docker runs):

```bash
# Is nginx installed and running?
sudo systemctl status nginx
# or
which nginx
```

- If nginx is **not** installed or not running, traffic likely goes **directly**: Cloudflare Tunnel → Odoo container. Then you only need to check **Cloudflare Tunnel** (section 3).
- If nginx **is** running, it might sit **in front of** the tunnel (e.g. Tunnel → nginx → Odoo) or **behind** it (Browser → Cloudflare → Tunnel → nginx → Odoo). Then check both nginx (section 2) and Cloudflare (section 3).

---

## 2. Check nginx config

**Where configs live (typical):**

- Main config: `/etc/nginx/nginx.conf`
- Site configs: `/etc/nginx/sites-enabled/` or `/etc/nginx/conf.d/`
- Your Odoo vhost is often: `/etc/nginx/sites-enabled/odoo` or `/etc/nginx/conf.d/odoo.conf`

**Commands on the server:**

```bash
# List enabled sites
ls -la /etc/nginx/sites-enabled/
# or
ls -la /etc/nginx/conf.d/

# Show full effective config (all included files)
sudo nginx -T

# Test config without applying
sudo nginx -t

# Search for your Odoo domain and for 8072 / websocket / longpolling
sudo grep -r "8072\|websocket\|longpolling\|odoo\|proxy_pass" /etc/nginx/
```

**What you want to see for WebSocket:**

- An `upstream` (or equivalent) for the **gevent** port, e.g. `server 127.0.0.1:8072;` or `server odoo:8072;`.
- A `location /websocket` (and ideally `location /longpolling`) that `proxy_pass` to that upstream, with:
  - `proxy_http_version 1.1;`
  - `proxy_set_header Upgrade $http_upgrade;`
  - `proxy_set_header Connection $connection_upgrade;`

If nginx is in front of Odoo and **nothing** proxies to 8072, add the blocks from `WEBSOCKET_SETUP.md` and run `sudo nginx -t && sudo systemctl reload nginx`.

---

## 3. Check Cloudflare Tunnel (Zero Trust) config

With **Cloudflare Tunnel**, routing is defined in the **Cloudflare dashboard**, not in this repo.

**Where to look:**

1. Log in to **Cloudflare Dashboard**: https://dash.cloudflare.com  
2. Go to **Zero Trust** (or **Networks** → **Tunnels**).  
3. Open your **Tunnel** (the one whose token is in `CLOUDFLARE_TOKEN`).  
4. Check **Public Hostname** (or **Routes** / **Ingress**).

**What you’ll see:**

- One or more **Public Hostname** entries: e.g. `odoo.yourdomain.com` → Service `http://odoo:8069` (or `http://localhost:8069`).

**What you need for WebSocket:**

- Traffic to **the same hostname** but path **`/websocket`** (and optionally **`/longpolling`**) must go to the **8072** service.

**Ways to do it in Zero Trust:**

- **Option A – Path-based (recommended)**  
  - Hostname: `odoo.yorudomain.com` (or your real subdomain).  
  - Add **two** ingress rules (order can matter):  
    1. Path: `Prefix` → `/websocket` → Service: `http://odoo:8072` (or `http://localhost:8072` if the tunnel runs on the host).  
    2. Path: `Prefix` → `/longpolling` → same service `http://odoo:8072`.  
    3. Default: `/` → Service: `http://odoo:8069`.  

- **Option B – Second hostname**  
  - e.g. `ws.yourdomain.com` → `http://odoo:8072`.  
  - Then Odoo would need to be configured to use that URL for the bus (less common).

**How to “check” it:**

- In the Tunnel’s **Public Hostname** / **Ingress** list, confirm:
  - There is an entry for **path** `/websocket` (and optionally `/longpolling`) → **port 8072**.
  - The default `/` goes to **8069**.

Cloudflare Tunnel does **not** use nginx config files; it uses only what you set in the dashboard for that tunnel.

---

## 4. Quick connectivity check (from server)

After config changes, from the **host** (or a container that can reach Odoo):

```bash
# Odoo main app (should respond)
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8069/web

# Gevent/longpolling port (may return 400 or 405 for GET; important is that something answers)
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8072/longpolling/poll
```

If 8069 returns 200 (or 303) and 8072 returns something other than “connection refused”, the server side is likely correct; then the remaining issue is routing from the browser (nginx and/or Cloudflare) so that `/websocket` and `/longpolling` hit 8072.
