# -*- coding: utf-8 -*-
"""HTTP dispatch endpoint for POS kiosk receipts.

The kiosk's payment backend POSTs a formatted receipt here; this reuses the
existing comms models to send it. Guarded by a shared token stored in the
`kiosk_receipt.token` system parameter (Settings → Technical → System
Parameters) -- it must match the backend's ODOO_RECEIPT_TOKEN.
"""
import json
import logging
from datetime import datetime

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

    # -- push sync (kiosk -> Odoo, when the device is online) -----------------

    @http.route('/sync/push', type='http', auth='public', methods=['POST'], csrf=False)
    def sync_push(self, **kw):
        if not self._authorized():
            return self._json({'status': 'error', 'detail': 'unauthorized'}, 401)
        try:
            data = json.loads(request.httprequest.data or b'{}')
        except Exception:
            return self._json({'status': 'error', 'detail': 'invalid JSON'}, 400)
        dataset = data.get('dataset')
        records = data.get('records') or []
        try:
            if dataset == 'orders':
                n = self._upsert_orders(records)
            elif dataset == 'audit':
                n = self._upsert_audit(records)
            elif dataset == 'customers':
                n = self._upsert_customers(records)
            else:
                return self._json({'status': 'error', 'detail': f'unknown dataset: {dataset}'}, 400)
            return self._json({'status': 'ok', 'synced': n})
        except Exception as exc:
            _logger.exception('kiosk sync push failed')
            return self._json({'status': 'failed', 'detail': str(exc)}, 200)

    def _dt(self, millis):
        try:
            return datetime.utcfromtimestamp(int(millis) / 1000.0) if millis else False
        except Exception:
            return False

    def _upsert_orders(self, records):
        model = request.env['kiosk.order'].sudo()
        n = 0
        for r in records:
            ref = str(r.get('kiosk_ref') or '')
            if not ref:
                continue
            vals = {
                'kiosk_ref': ref,
                'sold_at': self._dt(r.get('soldAt')),
                'subtotal': (r.get('subtotalCents') or 0) / 100.0,
                'tip': (r.get('tipCents') or 0) / 100.0,
                'total': (r.get('totalCents') or 0) / 100.0,
                'item_count': r.get('itemCount') or 0,
                'staff_ref': r.get('staffId') or '',
                'shift_ref': r.get('shiftId') or '',
                'checkout_id': r.get('checkoutId') or '',
                'refund_id': r.get('refundId') or '',
                'lines_json': json.dumps(r.get('lines') or []),
            }
            existing = model.search([('kiosk_ref', '=', ref)], limit=1)
            existing.write(vals) if existing else model.create(vals)
            n += 1
        return n

    def _upsert_audit(self, records):
        model = request.env['kiosk.audit'].sudo()
        n = 0
        for r in records:
            ref = str(r.get('kiosk_ref') or '')
            if not ref:
                continue
            vals = {
                'kiosk_ref': ref,
                'happened_at': self._dt(r.get('happenedAt')),
                'event_type': r.get('eventType') or '',
                'staff_name': r.get('staffName') or '',
                'staff_ref': r.get('staffId') or '',
                'detail': r.get('detail') or '',
            }
            existing = model.search([('kiosk_ref', '=', ref)], limit=1)
            existing.write(vals) if existing else model.create(vals)
            n += 1
        return n

    def _upsert_customers(self, records):
        model = request.env['res.partner'].sudo()
        n = 0
        for r in records:
            ref = str(r.get('kiosk_ref') or r.get('id') or '')
            if not ref:
                continue
            vals = {'x_kiosk_ref': ref, 'name': r.get('name') or 'Kiosk Customer'}
            if r.get('phone'):
                vals['phone'] = r.get('phone')
            existing = model.search([('x_kiosk_ref', '=', ref)], limit=1)
            existing.write(vals) if existing else model.create(vals)
            n += 1
        return n

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
