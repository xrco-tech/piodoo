# -*- coding: utf-8 -*-
# Provision the Chat2Work USSD flow as a whatsapp.chatbot (channel=ussd).
# Run:  docker compose run --rm -T odoo odoo shell -d odoo --no-http < this_file
#
# Idempotent: rebuilds the "Chat To Work USSD" bot each run.
# Book & Browse are DYNAMIC — execute_code steps read live chat2work.job /
# chat2work.interview.slot records and create chat2work.interview.booking.
# Register / Status / My interviews / Consultant remain static examples.

Bot = env['whatsapp.chatbot'].sudo()
Step = env['whatsapp.chatbot.step'].sudo()
Answer = env['whatsapp.chatbot.answer'].sudo()
Account = env['comm.ussd.account'].sudo()
Var = env['whatsapp.chatbot.variable'].sudo()

BOT_NAME = 'Chat To Work USSD'   # name allows only letters/spaces/dashes
SERVICE_CODE = '*384*0000#'       # placeholder until Africa's Talking assigns it

# ── 1. USSD account ─────────────────────────────────────────────────────────
account = Account.search([('service_code', '=', SERVICE_CODE)], limit=1)
if not account:
    vals = {'name': 'Chat2Work USSD', 'service_code': SERVICE_CODE}
    prov = dict(Account._fields['provider'].selection)
    for pref in ('africas_talking', 'africastalking', 'at'):
        if pref in prov:
            vals['provider'] = pref
            break
    account = Account.create(vals)

# ── 2. Fresh bot + variables ────────────────────────────────────────────────
old = Bot.search([('name', '=', BOT_NAME)])
if old:
    # Messages + sessions FK-reference the bot and don't cascade — purge first.
    env['whatsapp.chatbot.message'].sudo().search([('chatbot_id', 'in', old.ids)]).unlink()
    env['whatsapp.chatbot.ussd.session'].sudo().search([('chatbot_id', 'in', old.ids)]).unlink()
    old.mapped('step_ids').unlink()
    old.unlink()
bot = Bot.create({'name': BOT_NAME, 'channel': 'ussd', 'status': 'draft',
                  'ussd_account_id': account.id})

for vn in ('job_menu', 'job_ids', 'chosen_job_id', 'chosen_job_label',
           'slot_menu', 'slot_ids', 'chosen_slot_id', 'chosen_slot_label', 'booking_ref',
           'status_text', 'iv_menu', 'iv_ids', 'chosen_booking_id', 'chosen_iv_label'):
    Var.create({'chatbot_id': bot.id, 'name': vn})

# ── helpers ─────────────────────────────────────────────────────────────────
def S(name, parent, stype='message', body=None, seq=10, extra=None):
    vals = {'chatbot_id': bot.id, 'parent_id': parent.id if parent else False,
            'name': name, 'step_type': stype, 'body_plain': body or '', 'sequence': seq}
    if extra:
        vals.update(extra)
    return Step.create(vals)

def opt(menu, value, name, stype='message', body=None, extra=None):
    sval = str(value)
    seq = 9000 if sval == '0' else (int(sval) * 10 if sval.isdigit() else 990)
    child = S(name, menu, stype, body, seq=seq, extra=extra)
    ans = Answer.create({'value': sval, 'operator': 'is_equal_to', 'step_id': child.id})
    child.trigger_answer_ids = [(4, ans.id)]
    return child

def nxt(parent, name, stype='message', body=None, extra=None):
    return S(name, parent, stype, body, seq=10, extra=extra)

def home(menu, value='0', name='Main menu'):
    child = Step.create({'chatbot_id': bot.id, 'parent_id': menu.id, 'name': name,
                         'step_type': 'jump_to_flow', 'sequence': 999,
                         'target_chatbot_id': bot.id, 'target_step_id': root.id})
    ans = Answer.create({'value': str(value), 'operator': 'is_equal_to', 'step_id': child.id})
    child.trigger_answer_ids = [(4, ans.id)]
    return child

# Shared prelude for every execute_code snippet: setv/getv/last_input helpers.
# NOTE: execute_code runs `exec(code, {}, locals)`, so a nested function's
# globals is the EMPTY dict — it can't see exec-locals like `env`. We capture
# the deps as DEFAULT ARGS (evaluated at def-time in the local scope) so they
# bind correctly.
HELP = """
_contact = record.contact_id
_botid = record.chatbot_id.id
def setv(n, v, env=env, contact=_contact, botid=_botid):
    Var = env['whatsapp.chatbot.variable'].sudo()
    Val = env['whatsapp.chatbot.value'].sudo()
    var = Var.search([('chatbot_id','=',botid),('name','=',n)], limit=1)
    if not var: return
    ex = Val.search([('contact_id','=',contact.id),('variable_id','=',var.id)], limit=1)
    val = '' if v is None else str(v)
    if ex: ex.value = val
    else: Val.create({'contact_id':contact.id,'variable_id':var.id,'value':val})
def getv(n, env=env, contact=_contact, botid=_botid):
    Var = env['whatsapp.chatbot.variable'].sudo()
    Val = env['whatsapp.chatbot.value'].sudo()
    var = Var.search([('chatbot_id','=',botid),('name','=',n)], limit=1)
    if not var: return ''
    ex = Val.search([('contact_id','=',contact.id),('variable_id','=',var.id)], limit=1)
    return (ex.value or '') if ex else ''
def last_input(env=env, contact=_contact, botid=_botid):
    Msg = env['whatsapp.chatbot.message'].sudo()
    m = Msg.search([('contact_id','=',contact.id),('chatbot_id','=',botid),('type','=','incoming')], order='id desc', limit=1)
    return (m.message_plain or '').strip() if m else ''
"""

LOAD_JOBS = HELP + """
jobs = env['chat2work.job'].sudo().search([('active','=',True)], order='sequence,id')
jobs = [j for j in jobs if j.available_slot_count > 0][:9]
lines=[]; ids=[]
for i,j in enumerate(jobs, start=1):
    lines.append('%d. %s' % (i, j.ussd_label())); ids.append(str(j.id))
setv('job_menu', '\\n'.join(lines) if lines else 'No jobs available right now.')
setv('job_ids', ','.join(ids))
"""

RESOLVE_JOB = HELP + """
ans = last_input()
ids = [x for x in (getv('job_ids') or '').split(',') if x]
job = None
if ans.isdigit() and 1 <= int(ans) <= len(ids):
    job = env['chat2work.job'].sudo().browse(int(ids[int(ans)-1]))
if job and job.exists():
    setv('chosen_job_id', job.id); setv('chosen_job_label', job.ussd_label())
    slots = job.slot_ids.filtered(lambda s: s.is_available).sorted(lambda s: (s.start_datetime, s.id))[:9]
    sl=[]; si=[]
    for i,s in enumerate(slots, start=1):
        sl.append('%d. %s' % (i, s.ussd_label())); si.append(str(s.id))
    setv('slot_menu', '\\n'.join(sl) if sl else 'No slots available for this job.')
    setv('slot_ids', ','.join(si))
else:
    setv('chosen_job_id',''); setv('chosen_job_label',''); setv('slot_menu','Invalid choice. Please dial in again.'); setv('slot_ids','')
"""

RESOLVE_SLOT = HELP + """
ans = last_input()
sids = [x for x in (getv('slot_ids') or '').split(',') if x]
slot = None
if ans.isdigit() and 1 <= int(ans) <= len(sids):
    slot = env['chat2work.interview.slot'].sudo().browse(int(sids[int(ans)-1]))
if slot and slot.exists() and slot.is_available:
    setv('chosen_slot_id', slot.id); setv('chosen_slot_label', slot.ussd_label())
else:
    setv('chosen_slot_id',''); setv('chosen_slot_label','(unavailable)')
"""

BOOK_CREATE = HELP + """
sid = getv('chosen_slot_id')
ref = ''
if sid.isdigit():
    slot = env['chat2work.interview.slot'].sudo().browse(int(sid))
    if slot.exists() and slot.is_available:
        partner = _contact.partner_id
        phone = (partner.mobile or partner.phone or '') if partner else ''
        bk = env['chat2work.interview.booking'].sudo().book_slot(slot, partner=partner, phone=phone)
        ref = bk.reference
setv('booking_ref', ref or 'unavailable')
"""

STATUS_LOAD = HELP + """
partner = _contact.partner_id
Bk = env['chat2work.interview.booking'].sudo()
bks = Bk.search([('partner_id','=',partner.id)], order='create_date desc', limit=8) if partner else Bk.browse()
if not bks:
    txt = 'You have no applications yet.\\nChoose Book interview to get started.'
else:
    labels = dict(Bk._fields['state'].selection)
    lines = []
    for b in bks:
        lines.append('%s - %s (%s)' % (b.job_id.name or '', b.slot_id.ussd_label() if b.slot_id else 'TBD', labels.get(b.state, b.state)))
    txt = 'Your applications:\\n' + '\\n'.join(lines)
setv('status_text', txt)
"""

MYINT_LOAD = HELP + """
import datetime as _dt
partner = _contact.partner_id
Bk = env['chat2work.interview.booking'].sudo()
bks = Bk.search([('partner_id','=',partner.id),('state','=','booked')], order='id') if partner else Bk.browse()
now = _dt.datetime.now()
rows = [b for b in bks if b.slot_id and (not b.slot_id.start_datetime or b.slot_id.start_datetime > now)][:9]
lines=[]; ids=[]
for i,b in enumerate(rows, start=1):
    lines.append('%d. %s - %s' % (i, b.job_id.name or '', b.slot_id.ussd_label() if b.slot_id else 'TBD')); ids.append(str(b.id))
setv('iv_menu', '\\n'.join(lines) if lines else 'You have no upcoming interviews.')
setv('iv_ids', ','.join(ids))
"""

MYINT_RESOLVE = HELP + """
ans = last_input()
ids = [x for x in (getv('iv_ids') or '').split(',') if x]
bk = None
if ans.isdigit() and 1 <= int(ans) <= len(ids):
    bk = env['chat2work.interview.booking'].sudo().browse(int(ids[int(ans)-1]))
if bk and bk.exists():
    setv('chosen_booking_id', bk.id)
    setv('chosen_iv_label', '%s - %s' % (bk.job_id.name or '', bk.slot_id.ussd_label() if bk.slot_id else 'TBD'))
else:
    setv('chosen_booking_id',''); setv('chosen_iv_label','(not found)')
"""

CANCEL_DO = HELP + """
bid = getv('chosen_booking_id')
if bid.isdigit():
    bk = env['chat2work.interview.booking'].sudo().browse(int(bid))
    if bk.exists(): bk.action_cancel()
"""

RESCH_LOAD = HELP + """
bid = getv('chosen_booking_id')
sl=[]; si=[]
if bid.isdigit():
    bk = env['chat2work.interview.booking'].sudo().browse(int(bid))
    if bk.exists() and bk.job_id:
        slots = bk.job_id.slot_ids.filtered(lambda s: s.is_available).sorted(lambda s:(s.start_datetime, s.id))[:9]
        for i,s in enumerate(slots, start=1):
            sl.append('%d. %s' % (i, s.ussd_label())); si.append(str(s.id))
setv('slot_menu', '\\n'.join(sl) if sl else 'No other slots available.')
setv('slot_ids', ','.join(si))
"""

RESCH_DO = HELP + """
bid = getv('chosen_booking_id'); sid = getv('chosen_slot_id')
if bid.isdigit() and sid.isdigit():
    bk = env['chat2work.interview.booking'].sudo().browse(int(bid))
    slot = env['chat2work.interview.slot'].sudo().browse(int(sid))
    if bk.exists() and slot.exists() and slot.is_available:
        bk.reschedule(slot)
"""

THANKS_REG = "Thanks! Your profile is saved. We'll match you to jobs and SMS you when interviews open. Dial *384*0000# anytime."

# ── 3. Root: main menu ──────────────────────────────────────────────────────
root = S('Main menu', None, 'message', "Chat2Work - Jobs & Interviews\nReply with a number:")

# 1. Register (static)
reg = opt(root, '1', 'Register profile', 'question_text', "Enter your full name:")
reg_area = nxt(reg, 'Register - area', 'question_text', "Enter your town/area:")
reg_field = nxt(reg_area, 'Register - field', 'message', "Choose your field:")
opt(reg_field, '1', 'Call Centre', 'message', THANKS_REG)
opt(reg_field, '2', 'Retail', 'message', THANKS_REG)
opt(reg_field, '3', 'Warehouse/Driver', 'message', THANKS_REG)
opt(reg_field, '4', 'Admin/General', 'message', THANKS_REG)
opt(reg_field, '5', 'Other', 'message', THANKS_REG)

# 2. Browse jobs (DYNAMIC — lists live jobs)
browse = opt(root, '2', 'Browse jobs', 'execute_code', extra={'code': LOAD_JOBS})
nxt(browse, 'Browse - list', 'message',
    "Jobs near you:\n{{variables.job_menu}}\nTo book, choose 'Book interview' from the main menu.")

# 3. Book an interview (DYNAMIC — job -> slot -> confirm -> booking)
book = opt(root, '3', 'Book interview', 'execute_code', extra={'code': LOAD_JOBS})
book_pick = nxt(book, 'Book - pick job', 'question_text',
                "Select a job to interview for:\n{{variables.job_menu}}")
book_resolve = nxt(book_pick, 'Book - resolve job', 'execute_code', extra={'code': RESOLVE_JOB})
slot_pick = nxt(book_resolve, 'Book - pick slot', 'question_text',
                "Pick an interview slot:\n{{variables.slot_menu}}")
slot_resolve = nxt(slot_pick, 'Book - resolve slot', 'execute_code', extra={'code': RESOLVE_SLOT})
confirm = nxt(slot_resolve, 'Book - confirm', 'message',
              "Confirm interview:\n{{variables.chosen_job_label}}\n{{variables.chosen_slot_label}}")
c_yes = opt(confirm, '1', 'Confirm', 'execute_code', extra={'code': BOOK_CREATE})
nxt(c_yes, 'Book - booked', 'message',
    "Booked! Ref {{variables.booking_ref}}.\n{{variables.chosen_job_label}}\n{{variables.chosen_slot_label}}.\nWe'll SMS the address & reminders.")
opt(confirm, '2', 'Cancel', 'message', "Booking cancelled. Dial in again to pick another slot.")

# 4. Check my status (DYNAMIC — the caller's real bookings)
status = opt(root, '4', 'My status', 'execute_code', extra={'code': STATUS_LOAD})
nxt(status, 'Status - show', 'message', "{{variables.status_text}}")

# 5. My interviews (DYNAMIC — list -> cancel / reschedule)
mine = opt(root, '5', 'My interviews', 'execute_code', extra={'code': MYINT_LOAD})
mine_pick = nxt(mine, 'My interviews - pick', 'question_text', "Your interviews:\n{{variables.iv_menu}}")
mine_resolve = nxt(mine_pick, 'My interviews - resolve', 'execute_code', extra={'code': MYINT_RESOLVE})
mine_action = nxt(mine_resolve, 'My interviews - action', 'message', "{{variables.chosen_iv_label}}")
# 1. Cancel
mine_cancel = opt(mine_action, '1', 'Cancel', 'message', "Cancel this interview?")
mc_yes = opt(mine_cancel, '1', 'Yes, cancel', 'execute_code', extra={'code': CANCEL_DO})
nxt(mc_yes, 'Cancel - done', 'message', "Interview cancelled. Rebook anytime by dialling in.")
opt(mine_cancel, '2', 'No, keep it', 'message', "Kept. We'll SMS you a reminder before the interview.")
# 2. Reschedule
mine_resch = opt(mine_action, '2', 'Reschedule', 'execute_code', extra={'code': RESCH_LOAD})
resch_pick = nxt(mine_resch, 'Reschedule - pick slot', 'question_text', "Pick a new slot:\n{{variables.slot_menu}}")
resch_resolve = nxt(resch_pick, 'Reschedule - resolve slot', 'execute_code', extra={'code': RESOLVE_SLOT})
resch_do = nxt(resch_resolve, 'Reschedule - apply', 'execute_code', extra={'code': RESCH_DO})
nxt(resch_do, 'Reschedule - done', 'message', "Rescheduled to {{variables.chosen_slot_label}}. SMS confirmation sent.")

# 6. Consultant (static)
cons = opt(root, '6', 'Consultant', 'message', "Request a callback?")
opt(cons, '1', 'Yes, call me', 'message',
    "Thanks! A Chat2Work consultant will call you on this number within 1 business day.")
opt(cons, '2', 'No', 'message', "No problem. Dial in anytime for jobs & interviews.")

# 0. Exit
opt(root, '0', 'Exit', 'message', "Goodbye! Dial *384*0000# anytime for jobs & interviews.")

bot.status = 'published'
env.cr.commit()
print("PROVISIONED bot id=%s steps=%s vars=%s account=%s (%s)" % (
    bot.id, len(bot.step_ids), len(bot.bot_variable_ids), account.id, account.service_code))
