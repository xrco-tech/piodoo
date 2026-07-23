# WhatsApp Calling — handoff (July 2026)

Written for a fresh Claude Code session picking this up with no memory of
the conversation that built it. Read this before touching
`comm_whatsapp_calling`, `comm_whatsapp` (templates), or the calling parts
of `contact_centre_inbox`.

Everything below is verified against real commits (`git log`), not
recalled from conversation — this doc survived a context compaction that
lost some of the reasoning, so trust `git log -p <hash>` over prose here
if the two ever disagree.

## What exists now

A unified design system across every floating call-related widget
(`comm_whatsapp_calling/static/src/js/incoming_call_popup.js` — this one
file is the vast majority of the client-side logic):

| Widget | Opened from | Notes |
|---|---|---|
| Incoming call popup | `whatsapp_incoming_call` bus event | Accept/decline, suggested voice script, ringing (audio + tab-title flash + desktop notification) |
| Active-call HUD | after accept/dial connects | Mute, record, transfer, voice-script toggle, live duration |
| New Call / dial pad | systray phone icon | Script select, campaign linking, call history, contacts |
| Call History picker | dial pad shortcut | Searchable, all calls both directions, click-to-call, shows recording length |
| Contacts picker | dial pad shortcut | Searchable, click-to-call |
| Transfer-to-team picker | HUD shortcut | Cold transfer — see "Known-fixed bug" below |
| Voice-script picker | HUD/popup shortcut | Shared `showChatbotPicker` helper |
| Campaign picker | HUD/popup shortcut | Add caller to an existing campaign |
| Call-permission-request prompt | after a "no permission" dial failure | Sends Meta's `call_permission_request` template |
| Transfer-request popup | `whatsapp_transfer_request` bus event | Receiving agent's "someone wants to transfer you a call" |
| Presence dropdown | `systray_presence.js` (separate file) | Available/Away/DND — same outside-click-close pattern, CSS-anchored not JS-positioned |

**Shared conventions across all of these:**
- Purple (`#714B67`) header bar, light-theme-by-default (`getStoredTheme()`
  falls back to light), theme toggle, VoIP-card look.
- All non-destructive pickers close on outside click (`4575111`) — the
  incoming popup, active HUD, and voice-script conversation panel are
  **deliberately excluded** since dismissing those has real consequences
  (a still-ringing call losing its UI, or an active call's controls
  vanishing — the script panel's own × button actually **ends the call**,
  so it must never be reachable via a stray outside click).
- Pickers opened *from* the dial pad show a back-arrow (←) instead of ×,
  since dismissing them returns to the dial pad rather than closing
  everything (`eb52d54`).
- All floating widgets are the same 280px width and anchor near the
  phone icon (`7cee59c`, `d3744b1`) — no more width/position jump between
  screens.
- Shortcut icon rows are horizontally centered (`d7659bd`).
- Systray now shows exactly one green phone icon (`85f938e`/`d6906df`);
  the older separate "WhatsApp Calls" badge/dropdown icon was
  unregistered from the manifest, not deleted from disk — files still
  exist, just not loaded (`80ba1d1`).

### Call recording (`2459ac0` onward)

WhatsApp calls are end-to-end encrypted between the browser and Meta —
confirmed against Meta's actual API/webhook reference during this work,
there is **no server-side recording feature** in the Cloud API (a
plausible-sounding AI-generated claim to the contrary was fact-checked
and found to be hallucinated — don't trust claims about a native
`recording: {status: ENABLED}` field without re-verifying against
`developers.facebook.com/documentation/business-messaging/whatsapp/calling/reference/`
directly).

So recording is entirely client-side: the HUD's Record button mixes
`localStream` + `remoteStream` via Web Audio API into one track, records
with `MediaRecorder`, uploads to `/whatsapp/call/upload_recording/<id>`
on stop/hangup, stored as an `ir.attachment` (`res_field='recording_ids'`
on `whatsapp.call.log`). Duration is tracked client-side (browser is the
only party that knows how long `MediaRecorder` actually ran) and shown
next to every player.

- **Access control** (`113686f`): a `Call Recording Manager` security
  group gates delete (Python-level `ir.attachment.unlink()` override,
  not a record rule — deliberate, simpler to reason about) and download;
  everyone else can listen inline via a dedicated streaming route that
  serves `Content-Disposition: inline` unless `?download=1` is present
  and authorized.
- 90-day retention cron (`ir_cron_purge_call_recordings`), opt-in per
  call, no automated consent disclosure — that's on the agent
  deliberately, not silently automated.
- Surfaced in: call log form (Recording page), Inbox thread bubble
  (`4107aa3`), Call History picker (headphone icon).

### WhatsApp templates (`comm_whatsapp` module)

- `whatsapp.template` gained `is_call_permission_request` (`d2f89e2`) —
  adds Meta's `CALL_PERMISSION_REQUEST` component (mutually exclusive
  with buttons), and a `_send_simple()` method for system-triggered sends
  outside the interactive wizard. Fills both named (`{{param_name}}`) and
  positional (`{{1}}`) body placeholders at send time.
- **Two stale-access-token bugs fixed** (`abd30b4`, `249cd01`): several
  send paths (Inbox replies, automations, campaigns, one chatbot reply
  path, the template send wizard) called `send_whatsapp_message()`
  without an explicit `account=`, silently falling back to a **stale**
  legacy `comm_whatsapp.access_token` system parameter instead of the
  current `comm.whatsapp.account` record's real token. If outbound
  WhatsApp sends start failing with 401/Authentication Error again,
  **check for a new call site making this same mistake** — grep for
  `send_whatsapp_message(` without an `account=` kwarg.

### WhatsApp BSUID / usernames (Meta's April 2026 rollout)

Real Meta feature, not hypothetical — verified against
`developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids/`.
Once a WhatsApp user adopts a username, phone number is **omitted from
webhooks** after 30 days of no phone-number interaction; only a BSUID
(`US.13491208655302741918` format — always contains a literal `.`,
phone numbers never do) remains. Both phases are done:

- **Phase 1** (`3539284`): capture `wa_bsuid` alongside phone number
  everywhere webhooks/contacts are already handled, plus a
  `user_id_update` webhook handler (BSUIDs can rotate — `{previous,
  current}` payload) to keep stored BSUIDs current.
- **Phase 2** (`51a7994`): match/resolve/send by BSUID once phone isn't
  available. Outbound sends (`send_whatsapp_message`, `_send_simple`,
  `action_connect`, `dial_call`) use Meta's `to` (phone, takes
  precedence when both present) + `recipient` (BSUID) dual-param
  pattern — confirmed the Calling API uses the **same** pattern as
  Messages, not a different one, before writing this.

**Not yet done — explicitly deferred, scope discussed but not built:**
the dial pad's "type a number to call" flow has no way to reach a
BSUID-only contact (nothing to type). Contacts/Call History (search by
name) are the only path to such a contact today. Whether the dial pad
needs its own "search instead of dial" mode for this case was raised as
an open question, not decided.

## Known-fixed bug — verify it stayed fixed

**Cold transfer never told Meta the source call ended** (`d253f28`,
latest commit as of this doc). `openTransferPicker`'s success handler
called `teardownCall(true)` — which only closes the local
`RTCPeerConnection` and stops local media, **never** calls
`/whatsapp/call/decline`. Meta kept seeing an "ongoing" call with that
customer, so when the receiving agent tried to call back, Meta rejected
it with exactly this error: `Dial failed: A call with this number is
already ongoing`. Fixed by calling `hangupCall(callLogId)` instead
(same local teardown, but also fires the decline RPC — which already
correctly routes *answered* calls to Meta's `terminate` action). If this
error resurfaces, check for any **other** place that tears down a call
locally without a matching server-side decline/hangup RPC — that's the
bug class, not a one-off.

## Deploy procedure (same as `MEMORY.md`, repeated here for convenience)

```bash
# Local: commit + push as normal.
ssh -i ~/.ssh/claude_code_key ubuntu@100.88.7.93 "cd /home/ubuntu/odoo-stack && git pull origin main"

# Pure JS/CSS/XML asset change → just clear the bundle + restart:
ssh -i ~/.ssh/claude_code_key ubuntu@100.88.7.93 "cd /home/ubuntu/odoo-stack && docker compose exec -T odoo odoo shell -d odoo --no-http" <<'EOF'
env['ir.attachment'].search([('name','like','web.assets_web%')]).unlink()
env.cr.commit()
EOF
ssh -i ~/.ssh/claude_code_key ubuntu@100.88.7.93 "cd /home/ubuntu/odoo-stack && docker compose restart odoo"

# New fields/views/data/manifest changes → full module update first:
ssh -i ~/.ssh/claude_code_key ubuntu@100.88.7.93 "cd /home/ubuntu/odoo-stack && docker compose run --rm odoo odoo -d odoo -u comm_whatsapp_calling --stop-after-init"
# (then the asset-clear + restart steps above)
```

Always check post-restart logs for real errors, filtering out the two
permanently-present, harmless noise sources:
```bash
docker compose logs --tail=60 odoo 2>&1 | grep -i 'traceback\|error' | \
  grep -v 'is_modifying_relations\|_field_triggers\|resolve_depends\|recursive=True'
```
(`is_modifying_relations`/`_field_triggers`/`resolve_depends`/
`recursive=True` is a pre-existing cron-lock deprecation warning on
every odoo-shell invocation, unrelated to any of this work — it always
self-resolves.)

## Verification discipline established this session

- **Never trigger a real outbound WhatsApp call or message send without
  explicit permission each time** — even for testing. Permission for one
  send doesn't carry to the next. When verification requires a real
  send, ask first; when it doesn't (most bugs), verify via `odoo shell`
  reproducing the exact code path, or via the browser without completing
  the send action (e.g., open a picker and inspect it without clicking
  the row that sends).
- The Claude Browser pane's session to `piodoo.xrco.tech` **expires
  frequently** and there are no stored credentials to log back in —
  don't attempt to enter credentials (that's off-limits by policy
  anyway). When it's logged out, fall back to `odoo shell`-based
  verification (field reads, dry-run domain checks, safe method calls)
  rather than guessing.
- When a live UI check is genuinely needed and the action is 100% inert
  regardless of outcome (e.g., re-deriving the exact markup a compute
  field would render, byte-for-byte), injecting that exact markup via
  `javascript_tool` for a screenshot is acceptable **debugging**, never
  a substitute for shipping the change through source.
- Real production traffic showed up unprompted a few times during
  testing (a genuine inbound call rang while verifying an unrelated
  change) — treat that as real signal, not noise, and don't let it
  derail the current task without flagging it.

## Gaps in this doc's own knowledge

This session went through at least one context compaction, and the
handoff was requested immediately after a tool-call error interrupted
an in-progress investigation. Specifically uncertain / worth
re-deriving rather than trusting blindly:
- Whether there's a **client-side `activeCall` staleness** issue beyond
  the (now-fixed) server-side transfer bug above — flagged verbally at
  some point this session but the specifics didn't survive compaction.
  The most defensible reconstruction: `activeCall` is a module-level
  singleton cleared only by `teardownCall()`, which is wired to
  `RTCPeerConnection.onconnectionstatechange` firing `"failed"` or
  `"closed"` — but **not** `"disconnected"` (a valid intermediate ICE
  state that can persist indefinitely on a flaky network without ever
  resolving to `"failed"`), and there's no timeout on the
  accept/dial negotiation phase itself. Either could leave `activeCall`
  permanently stuck, blocking all future dial/accept attempts on that
  browser tab until a manual refresh. **Not yet fixed as of this doc** —
  next session should decide whether to harden this or treat it as
  acceptable risk (a manual refresh is a low-cost workaround for a rare
  failure mode).
