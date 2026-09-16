#!/bin/sh
# Render ${VAR} placeholders in the Asterisk config templates from the
# environment, then start Asterisk. Uses sed (always present) rather than
# envsubst (missing on minimal Debian images). Templates live in
# /etc/asterisk/templates (read-only mount); rendered configs go to /etc/asterisk.
set -e

# Escape a value so it is safe inside a sed replacement: backslash, ampersand
# (whole-match ref) and the "|" delimiter. Without this a secret containing any
# of those (Vox/ARI passwords can) would corrupt the rendered config.
esc() { printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'; }

E_VOX_SIP_HOST=$(esc "$VOX_SIP_HOST")
E_VOX_SIP_PORT=$(esc "$VOX_SIP_PORT")
E_VOX_USERNAME=$(esc "$VOX_USERNAME")
E_VOX_SECRET=$(esc "$VOX_SECRET")
E_VOX_DID=$(esc "$VOX_DID")
E_VOX_CODECS=$(esc "$VOX_CODECS")
E_EXTERNAL_IP=$(esc "$EXTERNAL_IP")
E_LOCAL_NET=$(esc "$LOCAL_NET")
E_ARI_USERNAME=$(esc "$ARI_USERNAME")
E_ARI_PASSWORD=$(esc "$ARI_PASSWORD")
E_ARI_APP=$(esc "$ARI_APP")
E_WSS_CERT=$(esc "$WSS_CERT")
E_WSS_KEY=$(esc "$WSS_KEY")

render() {
    sed \
        -e "s|\${VOX_SIP_HOST}|${E_VOX_SIP_HOST}|g" \
        -e "s|\${VOX_SIP_PORT}|${E_VOX_SIP_PORT}|g" \
        -e "s|\${VOX_USERNAME}|${E_VOX_USERNAME}|g" \
        -e "s|\${VOX_SECRET}|${E_VOX_SECRET}|g" \
        -e "s|\${VOX_DID}|${E_VOX_DID}|g" \
        -e "s|\${VOX_CODECS}|${E_VOX_CODECS}|g" \
        -e "s|\${EXTERNAL_IP}|${E_EXTERNAL_IP}|g" \
        -e "s|\${LOCAL_NET}|${E_LOCAL_NET}|g" \
        -e "s|\${ARI_USERNAME}|${E_ARI_USERNAME}|g" \
        -e "s|\${ARI_PASSWORD}|${E_ARI_PASSWORD}|g" \
        -e "s|\${ARI_APP}|${E_ARI_APP}|g" \
        -e "s|\${WSS_CERT}|${E_WSS_CERT}|g" \
        -e "s|\${WSS_KEY}|${E_WSS_KEY}|g" \
        "$1"
}

for tpl in /etc/asterisk/templates/*.conf; do
    [ -e "$tpl" ] || continue
    name=$(basename "$tpl")
    render "$tpl" > "/etc/asterisk/$name"
done

exec asterisk -f
