#!/bin/sh
# Render ${VAR} placeholders in the Asterisk config templates from the
# environment, then start Asterisk. Uses sed (always present) rather than
# envsubst (missing on minimal Debian images). Templates live in
# /etc/asterisk/templates (read-only mount); rendered configs go to /etc/asterisk.
set -e

render() {
    sed \
        -e "s|\${VOX_SIP_HOST}|${VOX_SIP_HOST}|g" \
        -e "s|\${VOX_SIP_PORT}|${VOX_SIP_PORT}|g" \
        -e "s|\${VOX_USERNAME}|${VOX_USERNAME}|g" \
        -e "s|\${VOX_SECRET}|${VOX_SECRET}|g" \
        -e "s|\${VOX_DID}|${VOX_DID}|g" \
        -e "s|\${VOX_CODECS}|${VOX_CODECS}|g" \
        -e "s|\${EXTERNAL_IP}|${EXTERNAL_IP}|g" \
        -e "s|\${LOCAL_NET}|${LOCAL_NET}|g" \
        -e "s|\${ARI_USERNAME}|${ARI_USERNAME}|g" \
        -e "s|\${ARI_PASSWORD}|${ARI_PASSWORD}|g" \
        -e "s|\${ARI_APP}|${ARI_APP}|g" \
        -e "s|\${WSS_CERT}|${WSS_CERT}|g" \
        -e "s|\${WSS_KEY}|${WSS_KEY}|g" \
        "$1"
}

for tpl in /etc/asterisk/templates/*.conf; do
    [ -e "$tpl" ] || continue
    name=$(basename "$tpl")
    render "$tpl" > "/etc/asterisk/$name"
done

exec asterisk -f
