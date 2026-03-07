# Enabling WebSocket (evented worker + proxy to 8072)

When Odoo runs with **workers > 0**, it starts an **evented (gevent) worker** on a separate port (default **8072**). The web client uses this for **WebSocket** (and longpolling) so the bus works and you get real-time popups (e.g. incoming WhatsApp call).

---

## 1. Odoo configuration

Use a config file (e.g. `odoo.conf` or `/etc/odoo.conf`) and set at least:

```ini
[options]
workers = 2
proxy_mode = True
```

- **workers**: Must be **> 0** (e.g. `2` for a small server, or `(CPU * 2) + 1` for production). With `workers = 0`, the gevent/WebSocket worker is **not** started.
- **proxy_mode**: Set to **True** when Odoo is behind a reverse proxy (nginx, etc.).

The **gevent port** defaults to **8072**. You can set it explicitly:

```ini
gevent_port = 8072
```

Start Odoo with that config, e.g.:

```bash
odoo -c odoo.conf
# or
python3 odoo-bin -c /etc/odoo.conf
```

---

## 2. Reverse proxy (nginx)

Route **WebSocket** (and optionally longpolling) to **127.0.0.1:8072**. Everything else goes to the main Odoo port (e.g. 8069).

**Upstreams and map** (add near the top of the server block or in `http`):

```nginx
upstream odoo {
    server 127.0.0.1:8069;
}
upstream odoochat {
    server 127.0.0.1:8072;
}
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}
```

**WebSocket** (inside your `server { ... }` for the Odoo domain):

```nginx
location /websocket {
    proxy_pass http://odoochat;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header X-Forwarded-Host $http_host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```

**Main app** (existing proxy to Odoo):

```nginx
location / {
    proxy_set_header X-Forwarded-Host $http_host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_redirect off;
    proxy_pass http://odoo;
}
```

If your Odoo version still uses **longpolling** on the same port 8072, you can add:

```nginx
location /longpolling {
    proxy_pass http://odoochat;
    proxy_set_header X-Forwarded-Host $http_host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```

Reload nginx after changes:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## 3. Docker

If Odoo runs in Docker:

1. **Start Odoo with workers and expose 8072**  
   Example with `docker run`:
   ```bash
   docker run -p 8069:8069 -p 8072:8072 \
     -e ODOO_OPTIONS="--workers=2 --gevent-port=8072 --proxy-mode" \
     ...
   ```
   Or in `docker-compose.yml` for the Odoo service:
   ```yaml
   ports:
     - "8069:8069"
     - "8072:8072"
   command: ["odoo", "--workers=2", "--gevent-port=8072", "--proxy-mode"]
   ```
   (Adjust image and env to match your setup.)

2. **Proxy**  
   Nginx (or another proxy) can run on the host or in another container. Point `odoochat` to:
   - Host: `127.0.0.1:8072` if nginx is on the host and 8072 is published.
   - Container name (e.g. `odoo:8072`) if nginx is in the same Docker network.

---

## 4. Check

1. Start Odoo with `workers > 0` and ensure no errors about the gevent port.
2. Open the Odoo web client in the browser (through the proxy).
3. If the bus connects, you should **not** see “Couldn’t bind the websocket” and real-time features (e.g. incoming call popup) should work.

If it still fails, check:

- Firewall allows port **8072** (at least from the proxy to Odoo).
- Nginx `proxy_pass` for `/websocket` (and `/longpolling` if used) goes to **8072**.
- Odoo is started with **workers** set to a value **> 0**.
