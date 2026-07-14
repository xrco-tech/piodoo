# Contact Centre AI roadmap — handoff (July 2026)

Written for a fresh Claude Code session picking this up with no memory of
the conversation that built it. Read this before touching any
`contact_centre*` addon.

## What exists now

Seven phases shipped, in order, each verified against the real production
instance (`ubuntu@100.88.7.93` via Tailscale, app at
`https://assessment...`/piodoo's own domain — see main `CLAUDE.md`/project
memory for exact server details):

| Phase | What | Where |
|---|---|---|
| 0 | Mirrors live WhatsApp/call traffic into `contact_centre`'s unified inbox (was previously dormant — 0 rows despite real traffic) | `contact_centre_sync` |
| 1 | Real dashboard analytics (channel breakdown, conversation-state counts, avg first-response time) | `contact_centre/static/src/dashboard/` |
| 2 | Wires the dormant `contact.centre.automation` model into real inbound WhatsApp/SMS traffic | `contact_centre` (webhook_controller.py, contact_centre_automation.py) |
| 3 | Per-contact AI summary/sentiment/suggested-reply via Anthropic (cron-driven) | `contact_centre_ai_copilot` |
| 4 | Custom 3-pane unified inbox (conversation list / thread+composer / AI copilot+internal notes), real-time via `bus.bus` | `contact_centre_inbox` |
| 5 | "Call WhatsApp" button + live voice-script follower panel | `contact_centre_inbox` (voice_script_panel.js) |
| 6a/6b | AI Copilot **chat** (separate from Phase 3's per-contact analysis) that can create/update campaigns and linear chatbot flows via Anthropic tool-calling | `contact_centre_ai_ops` |
| 7 | AI-editable custom dashboard cards, additive to Phase 1's dashboard | `contact_centre` (dashboard_card model) + `contact_centre_ai_ops` (tools) |

All of this was planned via Claude Code's plan mode, phase by phase, with
real research against the live deployed source each time rather than
assumptions. The plan file with full reasoning for every decision is at
`~/.claude/plans/fuzzy-jumping-toucan.md` on the machine this was built on
— it won't travel with the repo, but the **why** behind everything below
is recorded there if you have access to it. If not, this doc is the
summary.

## Architectural conventions established — follow these for consistency

- **New module per genuinely new capability** (`contact_centre_sync`,
  `contact_centre_ai_copilot`, `contact_centre_inbox`, `contact_centre_ai_ops`),
  **edit `contact_centre` directly** when completing/extending its own
  already-declared intent (Phase 1, 2, 7's dashboard-card model, security
  group hierarchy). Don't create a new module reflexively — ask "is this
  separable, or is `contact_centre` itself gaining a feature?"
- **`auto_install: True`** only for pure glue that silently completes
  behavior other already-installed modules obviously intended
  (`contact_centre_sync`). **`auto_install: False`** for anything with an
  external cost, a new visible menu, or that should be a deliberate opt-in
  (`contact_centre_ai_copilot`, `contact_centre_inbox`, `contact_centre_ai_ops`).
- **AI tool safety posture** (Phase 6a/6b/7): tools never run as `sudo()` —
  they run as the calling user, so existing ACLs apply exactly as they
  would through the UI. Tools that create business records (campaigns,
  chatbot flows) only ever produce **draft** state — there is deliberately
  no "launch campaign" or "publish chatbot" tool; a human always does that
  step manually. Dashboard-card tools are the one exception allowed to
  delete, since that's pure UI config with no customer-facing side effect.
- **Anthropic integration**: raw `requests.post` to
  `https://api.anthropic.com/v1/messages`, not the SDK — confirmed the
  `anthropic` Python package isn't installed in this Docker image and nothing
  in the repo installs it. Tool-calling works fine as plain JSON
  (`tools`/`tool_use`/`tool_result` are just request/response fields, no SDK
  required). The API key lives in `ir.config_parameter` under
  `whatsapp.anthropic_api_key` (shared by Phase 3 and Phase 6a/6b/7 — don't
  add a third key param, reuse this one).
- **Verification discipline**: never trigger a real WhatsApp send/call
  yourself to "test" something — always use a throwaway contact with no
  phone number (guards skip the actual send safely) or roll back the DB
  transaction after testing (`env.cr.rollback()` in `odoo shell`). Real
  live-send/live-call testing is the user's job; say so explicitly rather
  than claiming it's verified.

## Environment gotchas discovered the hard way — don't re-learn these

1. **The compiled asset bundle does not reliably auto-invalidate** on this
   deployment after `-u`/restart. After any JS/XML/SCSS change, clear it
   explicitly before trusting a "looks deployed" state:
   ```python
   atts = env['ir.attachment'].sudo().search([
       '|', '|', ('name', 'like', 'web.assets_backend%'),
       ('name', 'like', '%.assets_backend%'), ('url', 'like', '%assets_backend%')])
   atts.unlink(); env.cr.commit()
   ```
   Then confirm the new code is actually present in a **freshly rendered**
   bundle (`env['ir.qweb']._get_asset_bundle('web.assets_backend').js()/.css()`,
   read `.raw`) before telling the user it's live.
2. **QWeb's JS-expression compiler translates `and`/`or` but not the word
   `not`.** Use `!x`, never `not x`, in any `t-if`/`t-att-class` expression.
   Using `not` produced `SyntaxError: Unexpected identifier 'ctx'` and broke
   the *entire* Contact Centre app's template compilation, not just the one
   view — this is a "whole app down" class of bug, not a cosmetic one.
3. **Buttons can't call private (underscore-prefixed) methods.** Always add
   a public `action_*`/plain-named wrapper for anything a `type="object"`
   button needs to call.
4. **`fields.Char(..., config_parameter='xxx')` is inert on plain models.**
   It only auto-syncs to `ir.config_parameter` for `res.config.settings`
   models. `contact.centre.whatsapp.config` is a regular model, so this
   kwarg silently does nothing (that's what the recurring "unknown
   parameter 'config_parameter'" deploy warning was actually telling us,
   for `open_ai_api_key` too — same latent bug there, never fixed, nothing
   reads that field so it doesn't matter yet). If you add another config
   field like this, write an explicit `create()`/`write()` override that
   calls `ir.config_parameter.sudo().set_param(...)` — don't trust the kwarg.
5. **A new model's DB table can silently fail to get created on `-u`** even
   though Odoo reports "Modules loaded" with no visible error — this
   happened once, likely from a transient lock collision with an unrelated
   cron (`mcp_server`'s own `_register_hook`) during the same update run.
   Symptom: `psycopg2.errors.UndefinedTable: relation "..." does not exist`
   the first time you try to use the model. Fix: just re-run `-u` for that
   module; it's idempotent and safe.
6. **Odoo groups created under `noupdate="1"`** (i.e. already existed
   before your change) don't retroactively pick up new field values
   (`implied_ids`, etc.) from a normal `-u` — only newly-created records do.
   Use a migration script (`migrations/<version>/post-migrate.py` + a
   version bump) to apply the fix once, not an ad-hoc `odoo shell` write —
   the latter is an untracked production change outside the normal deploy
   path and (correctly) gets blocked by this environment's safety
   classifier without the user's explicit, specific sign-off.
7. **`@mail/core`'s `Thread`/`Composer` operate on `mail.message`** (internal
   notes/chatter), not on `contact.centre.message` (the actual WhatsApp/SMS
   conversation) — don't try to reuse them for a customer-conversation view.
   `Chatter` (`threadModel`/`threadId` props) is genuinely reusable for an
   *internal notes* panel, just not as the main conversation thread.
8. **Outbound WhatsApp calling and the voice-chatbot script engine are
   two separate systems with no FK between them** —
   `env.services.comm_whatsapp_calling.dialCall({..., chatbotId})` places
   the call; `/voice/start` + `/voice/turn` + `/voice/end` (in
   `comm_whatsapp_chatbot`) run the script session. Wiring "call + follow a
   script" together means driving both APIs from your own UI code, not
   assuming one triggers the other.

## What's verified vs. what still needs a human

Everything above was checked via `odoo shell` (safe, rolled-back
transactions) wherever it didn't require a real external side effect.
These still need a **live UI check** by the user (sandboxed browser here
can't reach the Tailscale-only server):
- Visual correctness of every OWL UI (inbox 3-pane layout, voice script
  panel, AI Copilot chat, dashboard custom cards) in an actual browser.
- A real WhatsApp call end-to-end (`dialCall` + voice script follower).
- A real AI Copilot chat session creating a chatbot flow and confirming it
  actually plays out correctly when a real WhatsApp message arrives.

## Known, deliberately-not-fixed things (flagged, not bugs)

- `contact.centre.whatsapp.config.open_ai_api_key` has the same inert
  `config_parameter` bug as gotcha #4 above — never fixed since nothing
  reads it. Harmless as long as it stays unused.
- Four different models (`contact_centre_chatbot.py`'s `_send_whatsapp_reply`/
  `_send_sms_reply`, `contact_centre_campaign.py`'s `_send_whatsapp`/
  `_send_sms`, `contact_centre_automation.py`'s `_fire_whatsapp`/`_fire_sms`,
  `contact_centre_inbox`'s `action_send_reply`) each independently
  reimplement "send via WhatsApp/SMS then log a `contact.centre.message`."
  Spotted as duplication each time, never refactored into a shared helper —
  each addition was scoped tightly enough that touching three
  already-deployed files for a fourth copy wasn't worth the risk. Worth a
  cleanup pass if you're back in this area for other reasons.
- Chatbot-flow AI tools only support **linear** (non-branching) flows —
  building branching/button flows via chat needs its own design pass
  (safe `parent_id`/`fallback_step_id` rewiring), deliberately deferred.

## Natural next steps, roughly in order of how they were prioritized

1. Live UI verification of everything in the list above (needs the user).
2. Real-time push for the AI Copilot chat (currently plain synchronous
   request/response — fine for a single user, but no `bus.bus` notification
   if e.g. two people are collaborating on the same session).
3. Branching chatbot flows via the AI (needs the safe-rewiring design work
   flagged above).
4. The duplicated send-and-log helper cleanup, if touching that area again.
5. Nothing else was explicitly requested or scoped beyond this — check with
   the user for what they actually want next rather than assuming.
