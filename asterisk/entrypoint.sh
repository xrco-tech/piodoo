#!/bin/sh
# Substitute ${VAR} placeholders from the environment into the Asterisk configs,
# then start Asterisk. Templates live in /etc/asterisk/templates (read-only mount);
# rendered configs are written to /etc/asterisk.
set -e
VARS='$VOX_SIP_HOST $VOX_SIP_PORT $VOX_USERNAME $VOX_SECRET $VOX_DID $VOX_CODECS $EXTERNAL_IP $LOCAL_NET $ARI_USERNAME $ARI_PASSWORD $ARI_APP $WSS_CERT $WSS_KEY'
for tpl in /etc/asterisk/templates/*.conf; do
    name=$(basename "$tpl")
    envsubst "$VARS" < "$tpl" > "/etc/asterisk/$name"
done
exec asterisk -f
