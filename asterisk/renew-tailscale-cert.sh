#!/bin/bash
# Renew the Tailscale (Let's Encrypt) cert used for Asterisk WSS, and bounce the
# running Asterisk container only if the cert actually changed. `tailscale cert`
# is a no-op until it's inside the renewal window, so this is safe to run often.
# Install as a root weekly cron (see below).
set -e

DOMAIN="ubuntu.taild8679b.ts.net"
KEYS="/home/ubuntu/odoo-stack/asterisk/keys"

before=$(sha256sum "$KEYS/fullchain.pem" 2>/dev/null | awk '{print $1}')
tailscale cert --cert-file "$KEYS/fullchain.pem" --key-file "$KEYS/privkey.pem" "$DOMAIN"
after=$(sha256sum "$KEYS/fullchain.pem" | awk '{print $1}')

if [ "$before" != "$after" ]; then
    # Cert rotated — restart whichever Asterisk container is up so it reloads TLS.
    cid=$(docker ps --filter "name=asterisk" --format "{{.Names}}" | head -1)
    [ -n "$cid" ] && docker restart "$cid" >/dev/null 2>&1 || true
    echo "$(date -Is) renewed cert and restarted ${cid:-<none>}"
else
    echo "$(date -Is) cert unchanged, no action"
fi

# Install (run once, as root):
#   cp /home/ubuntu/odoo-stack/asterisk/renew-tailscale-cert.sh /usr/local/bin/
#   chmod +x /usr/local/bin/renew-tailscale-cert.sh
#   ( crontab -l 2>/dev/null; echo '17 4 * * 1 /usr/local/bin/renew-tailscale-cert.sh >> /var/log/asterisk-cert-renew.log 2>&1' ) | crontab -
