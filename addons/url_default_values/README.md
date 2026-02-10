# url_default_values

An Odoo module that restores support for passing default field values to new
record forms via clean URL query parameters — compatible with **Odoo 17, 18, and 19**.

---

## The Problem

In Odoo 17+, the web client was rewritten using OWL and a new SPA router.
This router strips unrecognised query parameters from the URL before the form
view loads, so the classic approach of appending `?default_field=value` to a
URL no longer works.

---

## The Solution

This module uses a two-layer fix:

**Layer 1 — JavaScript (front-end):**
Reads `?default_*` query parameters from `window.location` _immediately_ on
module load, before the SPA router processes the URL. It then patches Odoo's
`action` service so that whenever a new-record form is opened, those defaults
are injected into the action's context.

**Layer 2 — Python (back-end):**
Extends `base.default_get()` to read the injected defaults from the action
context and apply them to the new record — exactly the same way Odoo's own
internal `default_*` context keys work.

---

## Installation

1. Copy the `url_default_values` folder into your Odoo addons path.
2. Restart Odoo.
3. Go to **Settings → Apps**, search for **URL Default Values**, and install it.

---

## Usage

Simply append `?default_<field_name>=<value>` parameters to any new-record URL:

```
# Odoo 17+ clean URL format
https://your-instance.com/odoo/whatsapp.chatbot.step/new?default_chatbot_id=1&default_parent_id=2

# Works with any model
https://your-instance.com/odoo/helpdesk.ticket/new?default_partner_id=42&default_team_id=3

# Also works with the legacy hash URL format
https://your-instance.com/web#model=sale.order&view_type=form&context={"default_partner_id":5}
```

### Field Type Reference

| Field Type    | Example Value          | Notes                        |
|---------------|------------------------|------------------------------|
| Many2one      | `?default_partner_id=42` | Pass the integer database ID |
| Integer       | `?default_sequence=10`   | Parsed to int automatically  |
| Float         | `?default_price=9.99`    | Parsed to float automatically|
| Boolean       | `?default_active=true`   | true/1/yes → True            |
| Char / Text   | `?default_name=Hello`    | URL-encode spaces as `%20`   |
| Selection     | `?default_state=draft`   | Pass the selection key       |
| Date          | `?default_date=2025-01-15` | ISO 8601 format            |

---

## How It Works (Technical Detail)

```
Browser loads URL with ?default_chatbot_id=1
        │
        ▼
[JS] url_default_values.js runs immediately
     → Captures {chatbot_id: "1"} from window.location.search
     → OWL SPA router starts and strips the query params (too late — we got them!)
        │
        ▼
[JS] User navigates / action loads a new form
     → Patched doAction() detects it's a new-record form
     → Injects context: {url_defaults: {chatbot_id: "1"}, default_chatbot_id: "1"}
        │
        ▼
[Python] Form view calls whatsapp.chatbot.step.default_get()
         → Extended default_get reads ctx['url_defaults']
         → Coerces "1" → 1 (int, because chatbot_id is Many2one)
         → Returns {chatbot_id: 1, ...}
        │
        ▼
Form opens pre-filled ✓
```

---

## Compatibility

| Odoo Version | Status |
|---|---|
| 17.0 | ✅ Supported |
| 18.0 | ✅ Supported |
| 19.0 | ✅ Supported |
| 16.0 and earlier | ❌ Not needed — `default_*` URL params worked natively |

---

## License

LGPL-3
