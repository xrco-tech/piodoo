# -*- coding: utf-8 -*-
# Simulate a Chat2Work USSD session end-to-end (no Africa's Talking needed).
# Run:  docker compose run --rm -T odoo odoo shell -d odoo --no-http < this_file

Bot = env['whatsapp.chatbot'].sudo()
Session = env['whatsapp.chatbot.ussd.session'].sudo()
Contact = env['whatsapp.chatbot.contact'].sudo()
Msg = env['whatsapp.chatbot.message'].sudo()
Partner = env['res.partner'].sudo()

bot = Bot.search([('name', '=', 'Chat To Work USSD')], limit=1)
p = Partner.search([('mobile', '=', '+27600000009')], limit=1) or \
    Partner.create({'name': 'USSD Tester', 'mobile': '+27600000009'})
c = Contact.search([('partner_id', '=', p.id)], limit=1) or Contact.create({'partner_id': p.id})


def run(label, inputs):
    Session.search([('session_id', '=', 'TESTSESS')]).unlink()
    sess = Session.create({
        'session_id': 'TESTSESS', 'service_code': '*384*0000#',
        'phone_number': '+27600000009', 'chatbot_id': bot.id, 'contact_id': c.id,
    })
    print("\n########## PATH: %s ##########" % label)
    for i, inp in enumerate(inputs):
        body, term = Msg.render_ussd_session(sess, inp)
        print(">> turn %d, dialled=%r" % (i, inp))
        print(("END " if term else "CON ") + body)
        print("-" * 40)
        if term:
            break


run("Book an interview (main > 3 > 1 > 1 > 1)", [None, '3', '1', '1', '1'])   # creates a booking
run("Check my status (main > 4)", [None, '4'])                                # reads the booking
run("My interviews > reschedule (main > 5 > 1 > 2 > 2)", [None, '5', '1', '2', '2'])
run("My interviews > cancel (main > 5 > 1 > 1 > 1)", [None, '5', '1', '1', '1'])
run("Register (main > 1 > name > area > field)", [None, '1', 'John Dube', 'Soweto', '1'])

run("Consultant callback (main > 6 > 1)", [None, '6', '1'])

cand = env['chat2work.candidate'].sudo().search([('partner_id', '=', p.id)], limit=1)
print("\nCANDIDATE PROFILE created:", bool(cand))
if cand:
    print("  name=%r field=%r location=%r phone=%r via=%r" % (
        cand.name, cand.field, cand.location, cand.phone, cand.registered_via))

cb = env['chat2work.callback.request'].sudo().search([('partner_id', '=', p.id)], limit=1)
print("CALLBACK REQUEST created:", bool(cb))
if cb:
    print("  phone=%r state=%r candidate=%r via=%r" % (
        cb.phone, cb.state, cb.candidate_id.name, cb.channel))

env.cr.rollback()   # test only — don't persist the sim session/messages
print("\nDONE (rolled back test session).")
