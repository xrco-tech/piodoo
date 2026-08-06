# -*- coding: utf-8 -*-
# Provision the Chat2Work USSD flow as a whatsapp.chatbot (channel=ussd).
# Run with:  docker compose run --rm -T odoo odoo shell -d odoo --no-http < this_file
#
# Idempotent: deletes and rebuilds the "Chat2Work USSD" bot on each run.
# The dynamic lists (jobs, slots, statuses) are STATIC EXAMPLES here so the
# flow is fully navigable/testable — replace them with execute_code steps that
# read real records once the job/interview models exist.

Bot = env['whatsapp.chatbot'].sudo()
Step = env['whatsapp.chatbot.step'].sudo()
Answer = env['whatsapp.chatbot.answer'].sudo()
Account = env['comm.ussd.account'].sudo()

BOT_NAME = 'Chat To Work USSD'   # whatsapp.chatbot.name allows only letters/spaces/dashes
SERVICE_CODE = '*384*0000#'   # placeholder until Africa's Talking assigns the real code

# ── 1. USSD account (upsert by service code) ────────────────────────────────
account = Account.search([('service_code', '=', SERVICE_CODE)], limit=1)
if not account:
    vals = {'name': 'Chat2Work USSD', 'service_code': SERVICE_CODE}
    prov = dict(Account._fields['provider'].selection)
    for pref in ('africas_talking', 'africastalking', 'at'):
        if pref in prov:
            vals['provider'] = pref
            break
    account = Account.create(vals)

# ── 2. Fresh bot ────────────────────────────────────────────────────────────
old = Bot.search([('name', '=', BOT_NAME)])
if old:
    old.mapped('step_ids').unlink()
    old.unlink()
bot = Bot.create({
    'name': BOT_NAME,
    'channel': 'ussd',
    'status': 'draft',
    'ussd_account_id': account.id,
})

# ── helpers ─────────────────────────────────────────────────────────────────
def S(name, parent, stype='message', body=None, seq=10):
    return Step.create({
        'chatbot_id': bot.id,
        'parent_id': parent.id if parent else False,
        'name': name,
        'step_type': stype,
        'body_plain': body or '',
        'sequence': seq,
    })

def opt(menu, value, name, stype='message', body=None):
    """A numbered menu option: child step + a trigger answer on `value`."""
    child = S(name, menu, stype, body, seq=(int(value) if str(value).isdigit() else 999) * 10 + 1)
    ans = Answer.create({'value': str(value), 'operator': 'is_equal_to', 'step_id': child.id})
    child.trigger_answer_ids = [(4, ans.id)]
    return child

def nxt(parent, name, stype='message', body=None):
    """The single follow-on step after a free-text question (no trigger)."""
    return S(name, parent, stype, body, seq=10)

def home(menu, value='0', name='Main menu'):
    """A '0' option that jumps back to the root (main menu)."""
    child = S(name, menu, 'jump_to_flow', seq=999)
    child.write({'target_chatbot_id': bot.id, 'target_step_id': root.id})
    ans = Answer.create({'value': str(value), 'operator': 'is_equal_to', 'step_id': child.id})
    child.trigger_answer_ids = [(4, ans.id)]
    return child

THANKS_REG = "Thanks! Your profile is saved. We'll match you to jobs and SMS you when interviews open. Dial *384*0000# anytime."

# ── 3. Root: main menu ──────────────────────────────────────────────────────
root = S('Main menu', None, 'message',
         "Chat2Work - Jobs & Interviews\nReply with a number:")

# 1. Register / profile  (name -> area -> field -> done)
reg = opt(root, '1', 'Register profile', 'question_text', "Enter your full name:")
reg_area = nxt(reg, 'Register - area', 'question_text', "Enter your town/area:")
reg_field = nxt(reg_area, 'Register - field', 'message', "Choose your field:")
opt(reg_field, '1', 'Call Centre', 'message', THANKS_REG)
opt(reg_field, '2', 'Retail', 'message', THANKS_REG)
opt(reg_field, '3', 'Warehouse/Driver', 'message', THANKS_REG)
opt(reg_field, '4', 'Admin/General', 'message', THANKS_REG)
opt(reg_field, '5', 'Other', 'message', THANKS_REG)

# 2. Browse jobs
browse = opt(root, '2', 'Browse jobs', 'message', "Jobs near you:")
opt(browse, '1', 'Call Centre Agent - JHB', 'message',
    "Call Centre Agent (JHB)\nR6 500/mo. Matric required.\nTo book: main menu > 3.")
opt(browse, '2', 'Warehouse Asst - PTA', 'message',
    "Warehouse Assistant (PTA)\nR5 800/mo. No experience needed.\nTo book: main menu > 3.")
opt(browse, '3', 'Retail Cashier - Soweto', 'message',
    "Retail Cashier (Soweto)\nR6 000/mo. Matric preferred.\nTo book: main menu > 3.")
home(browse, '0', 'Main menu')

# 3. Book an interview  (job -> slot -> confirm -> booked)
book = opt(root, '3', 'Book interview', 'message', "Select a job to interview for:")
def booking_job(value, label, header):
    job = opt(book, value, label, 'message', header + "\nPick an interview slot:")
    for sval, slabel in (('1', 'Mon 12 Aug 09:00'), ('2', 'Mon 12 Aug 11:00'), ('3', 'Tue 13 Aug 10:00')):
        slot = opt(job, sval, slabel, 'message', "%s\n%s\n1. Confirm  2. Cancel" % (label, slabel))
        opt(slot, '1', 'Confirm', 'message',
            "Booked! Ref CW10432.\n%s, %s.\nWe'll SMS the address & reminders." % (label, slabel))
        opt(slot, '2', 'Cancel', 'message', "Booking cancelled. Dial in again to pick another slot.")
    home(job, '0', 'Back to main menu')
booking_job('1', 'Call Centre Agent - JHB', "Call Centre Agent (JHB)")
booking_job('2', 'Warehouse Asst - PTA', "Warehouse Assistant (PTA)")
home(book, '0', 'Main menu')

# 4. Check my status
status = opt(root, '4', 'My status', 'message', "Your applications:")
opt(status, '1', 'Call Centre Agent - Interview booked', 'message',
    "Call Centre Agent (JHB)\nStatus: Interview booked\nMon 12 Aug 09:00 - Ref CW10432\nWe'll SMS reminders.")
opt(status, '2', 'Warehouse Asst - Under review', 'message',
    "Warehouse Assistant (PTA)\nStatus: Under review. We'll SMS you if shortlisted.")
home(status, '0', 'Main menu')

# 5. My interviews  (list -> action -> reschedule/cancel)
mine = opt(root, '5', 'My interviews', 'message', "Your interviews:")
iv = opt(mine, '1', 'Call Centre Agent - Mon 12 Aug 09:00', 'message',
         "Call Centre Agent, Mon 12 Aug 09:00\n1. Reschedule  2. Cancel")
resch = opt(iv, '1', 'Reschedule', 'message', "Pick a new slot:")
opt(resch, '1', 'Tue 13 Aug 10:00', 'message', "Rescheduled to Tue 13 Aug 10:00. SMS confirmation sent.")
opt(resch, '2', 'Wed 14 Aug 14:00', 'message', "Rescheduled to Wed 14 Aug 14:00. SMS confirmation sent.")
canc = opt(iv, '2', 'Cancel', 'message', "Cancel this interview?\n1. Yes  2. No")
opt(canc, '1', 'Yes, cancel', 'message', "Interview cancelled. Rebook anytime by dialling in.")
opt(canc, '2', 'No, keep it', 'message', "Kept. We'll SMS you a reminder before the interview.")
home(mine, '0', 'Main menu')

# 6. Talk to a consultant
cons = opt(root, '6', 'Consultant', 'message', "Request a callback?\n1. Yes, call me\n2. No")
opt(cons, '1', 'Yes, call me', 'message',
    "Thanks! A Chat2Work consultant will call you on this number within 1 business day.")
opt(cons, '2', 'No', 'message', "No problem. Dial in anytime for jobs & interviews.")

# 0. Exit
opt(root, '0', 'Exit', 'message', "Goodbye! Dial *384*0000# anytime for jobs & interviews.")

# Publish once the tree exists.
bot.status = 'published'

env.cr.commit()
print("PROVISIONED bot id=%s steps=%s account=%s (%s)" % (
    bot.id, len(bot.step_ids), account.id, account.service_code))
