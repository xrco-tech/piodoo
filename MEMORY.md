# Piodoo — Session Work Log

## Stack
Odoo 18 + PostgreSQL 15 + Docker Compose + Cloudflare tunnel + Prometheus/Grafana  
**Server:** ubuntu@100.88.7.93 (Tailscale) | App root: `/home/ubuntu/odoo-stack`  
**GitHub:** https://github.com/xrco-tech/piodoo.git  
**Deployment:** `git pull && docker compose run --rm odoo odoo -d odoo -u <addon> --stop-after-init && docker compose restart odoo`

---

## `comm_whatsapp_chatbot` — Chatbot Flow Builder

### Architecture
- OWL client action registered as `comm_whatsapp_chatbot.chatbot_flow`
- Opened from the chatbot form via smart button (step count)
- Two-panel layout: canvas (left, flex:1) + properties panel (right, 210px)
- Canvas uses absolute-positioned cards + SVG bezier connectors
- Coordinates use `offsetLeft/offsetTop` (zoom-independent, not `getBoundingClientRect`)
- Positions persisted to `localStorage` keyed `chatbot_flow_pos_${chatbotId}`
- `_pendingDraw` pattern: set true after data load, `onPatched` triggers `_renderCanvas`

### Key Files
| File | Purpose |
|---|---|
| `static/src/js/chatbot_flow_widget.js` | Core OWL component — all canvas logic |
| `static/src/xml/chatbot_flow_action.xml` | OWL template — toolbar + canvas + props panel |
| `static/src/css/chatbot_flow_action.css` | Canvas styling |
| `models/whatsapp_chatbot.py` | Chatbot model |
| `models/whatsapp_chatbot_step.py` | Step model + button/list row models |
| `models/whatsapp_chatbot_variable.py` | Variable + variable trigger models |
| `models/whatsapp_chatbot_answer.py` | Answer model (has operator field) |
| `models/whatsapp_chatbot_global_interrupt.py` | Global interrupt keyword model |
| `views/whatsapp_chatbot_views.xml` | Chatbot form/list/kanban views |
| `views/whatsapp_chatbot_step_views.xml` | Step form view |
| `security/ir.model.access.csv` | Model access rights |

---

## Session Work Summary (June 2026)

### Canvas Flow Builder (OWL client action)
- Replaced iframe-based flow view with native OWL client action component
- Reingold-Tilford column layout for automatic tree positioning
- Free-form card drag-and-drop with localStorage position persistence
- Reset layout button clears saved positions
- Canvas pan (drag on background) + Ctrl+scroll zoom
- SVG fix: `svg.setAttribute("class", ...)` — `className` is read-only on SVGElement
- Connector fix: `offsetLeft/offsetTop` instead of `getBoundingClientRect` for zoom-independence

### Card Design
- Minimalist cards: `background:#eef0f8`, `border-radius:14px`, `overflow:visible`
- Card header: emoji type icon + editable name (contentEditable) + colour badge
- White content box with WhatsApp bubble preview
- Output dot (`bottom:-7px`, lavender → green on hover) replaces old + button
- Selected state: blue ring via `.o_flow_card_selected`
- Dead-end warning: amber ⚠ badge top-right + orange border on leaf nodes that aren't terminal

### Message Preview in Card Bubble
Bubble sub-elements rendered to match WhatsApp device layout:
- `o_flow_bubble_header_text` — bold text header
- `o_flow_bubble_header_media` — image/video placeholder with icon
- `o_flow_bubble_header_doc` — document row with file icon
- `o_flow_bubble_body` — body text
- `o_flow_bubble_footer` — italic grey caption
- `o_flow_bubble_flow_sep` + `o_flow_bubble_flow_cta` — teal CTA row for interactive_flow

Interactive reply buttons: `.o_flow_ia_btn` pills below separator  
Interactive list: `.o_flow_ia_list_btn` + `.o_flow_ia_list_row` items

### Connector Labels
- Bezier SVG connectors, dot at child end
- Trigger answers: `User input = Zee` (operator symbol + value)
- Trigger variables: `varName = 5` (variable name + operator + value)
- Both merged into `answers[]` array, shown on connector mid-label pill
- Label max 40 chars / 260px wide

### Toolbar
- Order: `‹` back (chevron-left, `history.back()`) | `Add Step` (btn-primary) | Bot name
- No WhatsApp icon, no + on Add Step button
- Right side: zoom −/label/+ + reset layout (sitemap icon)

### Properties Panel (right, 210px)
Shows when a node is clicked:
- Dead-end warning callout (amber, if applicable)
- Type badge | Name | Sequence + Delivery type
- Message preview bubble
- Header (type + text) | Footer
- Expected answer type (question steps)
- Reply buttons list / List rows / Flow name + CTA
- Variable name + source (set_variable steps)
- Max retries + fallback step name (question steps)
- Trigger conditions chips (answers + variable triggers)
- Child step count
- Edit / Add Child / Delete action buttons

### Step Model Additions
| Field | Purpose |
|---|---|
| `button_ids` | One2many to `whatsapp.chatbot.step.button` (interactive reply buttons) |
| `list_row_ids` | One2many to `whatsapp.chatbot.step.list.row` (interactive list rows) |
| `trigger_variable_ids` | One2many to `whatsapp.chatbot.variable.trigger` |
| `max_retries` | Integer (default 3) — validation retry limit for question steps |
| `fallback_step_id` | Many2one to self — route after exhausting retries |
| `agent_partner_ids` | Many2many to `res.partner` — override agents for transfer step |
| `target_chatbot_id` | Many2one to `whatsapp.chatbot` — destination of a jump_to_flow step |
| `target_step_id` | Many2one to self (target chatbot) — explicit entry; empty = root step |
| `jump_mode` | Selection: `one_way` / `subroutine` |
| `variable_mapping_ids` | One2many to `whatsapp.chatbot.step.var.mapping` — cross-bot variable plumbing |
| `step_type` additions | `transfer_to_agent`, `jump_to_flow` |

### Chatbot Model Additions
| Field | Purpose |
|---|---|
| `status` | Selection: draft/published/inactive (default: draft) |
| `global_interrupt_ids` | One2many to `whatsapp.chatbot.global.interrupt` |
| Action buttons | `action_publish`, `action_deactivate`, `action_reset_to_draft` |

### New Models
- `whatsapp.chatbot.step.list.row` — list row for interactive list messages
- `whatsapp.chatbot.global.interrupt` — keyword → action interrupts (goto_step / transfer_agent / end_flow)
- `whatsapp.chatbot.step.var.mapping` — per-jump variable mapping (`source_variable_id → target_variable_id`, direction in/out/both)

### Contact Model Additions
| Field | Purpose |
|---|---|
| `call_stack` | Json (list) — subroutine call stack. Frames: `{caller_chatbot_id, return_step_id, out_mapping: [{src_var, tgt_var}, …]}`. Cleared on trigger restart.

### Defensive Architecture Features (June 2026)
1. **Max retries + fallback step** — question steps get retry limit + fallback routing; dashed orange connector shown on canvas
2. **Transfer to Agent step type** — purple 🎧 badge, terminal node, handover message + agent override
3. **Dead-end warnings** — amber ⚠ badge on non-terminal leaf nodes + properties panel callout
4. **Global interrupt keywords** — per-chatbot keyword table in chatbot form; routes to step/agent/end on match

### Jump to Flow/Bot (June 2026)
- 16th step type `jump_to_flow`: indigo 🔀 badge. Either one-way (terminal) or subroutine (returns to caller's continuation = jump step's children)
- Runtime helpers in `whatsapp_chatbot_message.py`: `_process_jump_to_flow_step`, `_handle_end_flow`, `_apply_var_mapping`, `_apply_var_mapping_snapshot`
- `MAX_CALL_STACK_DEPTH = 8` guards against infinite jump loops (e.g. A↔B)
- Out-mapping snapshot stored on stack frame at jump time so mid-session edits don't break in-flight calls
- `_send_step_message` auto-advance recognises `jump_to_flow` and pops `end_flow` only when `call_stack` is non-empty
- Trigger restart now clears `call_stack` alongside variables and `last_step_id`
- Canvas: dashed indigo self-loop drawn on subroutine jump cards via `[data-jump-sub]` selector; one-way cards are treated as terminal (no out-dot)
- Tests in `tests/test_jump_to_flow.py`: constraints, one-way dispatch, subroutine push/pop, in/out/both mapping, nested subroutines, recursion guard

---

## Known Issues / Notes
- `flattenTree` must include ALL node properties — omitting any means `_buildCard` won't see them
- `whatsapp.chatbot.answer` uses `value` field (not `name`) and has `operator` field
- `context="{'default_chatbot_id': id}"` needed on trigger/variable tag fields in chatbot form
- Module update (`-u comm_whatsapp_chatbot`) required whenever Python model fields change
