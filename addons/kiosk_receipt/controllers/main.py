# -*- coding: utf-8 -*-
"""HTTP dispatch endpoint for POS kiosk receipts.

The kiosk's payment backend POSTs a formatted receipt here; this reuses the
existing comms models to send it. Guarded by a shared token stored in the
`kiosk_receipt.token` system parameter (Settings → Technical → System
Parameters) -- it must match the backend's ODOO_RECEIPT_TOKEN.
"""
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class KioskReceiptController(http.Controller):

    def _authorized(self):
        expected = request.env['ir.config_parameter'].sudo().get_param('kiosk_receipt.token')
        auth = request.httprequest.headers.get('Authorization', '')
        presented = auth[7:] if auth.startswith('Bearer ') else ''
        return bool(expected) and presented == expected

    # -- catalogue export (kiosk pulls this on "Import from Odoo") ------------

    @http.route('/catalog/export', type='http', auth='public', methods=['GET'], csrf=False)
    def catalog_export(self, **kw):
        if not self._authorized():
            return self._json({'status': 'error', 'detail': 'unauthorized'}, 401)
        products = request.env['product.product'].sudo().search([('active', '=', True)])
        out = []
        for p in products:
            # Odoo category "All / Food / Coffee" -> kiosk path ["Food","Coffee"]
            path = []
            categ = getattr(p, 'categ_id', False)
            if categ:
                name = getattr(categ, 'complete_name', False) or categ.name or ''
                parts = [s.strip() for s in name.split('/')]
                path = [s for s in parts if s and s.lower() != 'all'][:5]
            out.append({
                'name': p.name or '',
                'priceCents': int(round((getattr(p, 'lst_price', 0.0) or 0.0) * 100)),
                'sku': p.default_code or ('ODOO-%d' % p.id),
                'barcode': getattr(p, 'barcode', '') or '',
                'stockQty': int(getattr(p, 'qty_available', 0) or 0),
                'category': path,
            })
        return self._json(out)

    # -- receipt dispatch ----------------------------------------------------

    @http.route('/receipt/send', type='http', auth='public', methods=['POST'], csrf=False)
    def send_receipt(self, **kw):
        if not self._authorized():
            return self._json({'status': 'error', 'detail': 'unauthorized'}, 401)

        try:
            data = json.loads(request.httprequest.data or b'{}')
        except Exception:
            return self._json({'status': 'error', 'detail': 'invalid JSON'}, 400)

        channel = (data.get('channel') or '').upper()
        to = (data.get('to') or '').strip()
        if not to:
            return self._json({'status': 'error', 'detail': 'missing recipient'}, 400)

        try:
            if channel == 'EMAIL':
                return self._send_email(to, data)
            if channel == 'SMS':
                return self._send_sms(to, data)
            if channel == 'WHATSAPP':
                return self._send_whatsapp(to, data)
            return self._json({'status': 'error', 'detail': f'unknown channel: {channel}'}, 400)
        except Exception as exc:  # send failures are results, not 500s
            _logger.exception('kiosk receipt dispatch failed')
            return self._json({'status': 'failed', 'detail': str(exc)}, 200)

    # -- channels ------------------------------------------------------------

    def _send_email(self, to, data):
        mail = request.env['mail.mail'].sudo().create({
            'subject': data.get('subject') or 'Your receipt',
            'body_html': data.get('body') or '',
            'email_to': to,
        })
        mail.send()
        return self._json({'status': 'sent', 'detail': f'email {mail.state}', 'ref': str(mail.id)})

    def _send_sms(self, to, data):
        account = request.env['comm.sms.account'].sudo().get_default()
        vals = {'number': to, 'body': data.get('body') or ''}
        if account:
            vals['account_id'] = account.id
        sms = request.env['sms.sms'].sudo().create(vals)
        sms._send(raise_exception=False)
        ok = sms.state in ('sent', 'process', 'outgoing', 'pending')
        return self._json({'status': 'sent' if ok else 'failed', 'detail': f'sms {sms.state}', 'ref': str(sms.id)})

    def _send_whatsapp(self, to, data):
        name = data.get('template')
        if not name:
            return self._json({'status': 'error', 'detail': 'missing whatsapp template'}, 400)
        template = request.env['whatsapp.template'].sudo().search([('name', '=', name)], limit=1)
        if not template:
            return self._json({'status': 'failed', 'detail': f'template not found: {name}'}, 200)
        params = data.get('params') or []
        param_lines = [
            (0, 0, {'sequence': i, 'placeholder': '{{%d}}' % i, 'value': str(v)})
            for i, v in enumerate(params, start=1)
        ]
        wizard = request.env['whatsapp.template.send.wizard'].sudo().create({
            'template_id': template.id,
            'recipient_phone': to,
            'phone_number_id': template.account_id.phone_number_id if template.account_id else False,
            'parameter_ids': param_lines,
        })
        result = wizard.action_send_template() or {}
        notif = result.get('params', {}) if isinstance(result, dict) else {}
        if notif.get('type') == 'success':
            return self._json({'status': 'sent', 'detail': notif.get('message') or 'sent'})
        return self._json({'status': 'failed', 'detail': notif.get('message') or 'WhatsApp send failed'}, 200)

    def _json(self, payload, status=200):
        return request.make_json_response(payload, status=status)
