# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'xrco')
class TestQuoteReport(TransactionCase):

    def setUp(self):
        super().setUp()
        partner = self.env['res.partner'].create({'name': 'Gospel Garden Church', 'is_company': True})
        product = self.env['product.product'].create({'name': 'Custom Branded T-Shirt', 'list_price': 200})
        self.order = self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [
                (0, 0, {'display_type': 'line_section', 'name': 'Merchandise'}),
                (0, 0, {'product_id': product.id, 'product_uom_qty': 16, 'price_unit': 200, 'tax_id': False}),
            ],
        })

    def _html(self, report):
        html, _type = self.env['ir.actions.report']._render_qweb_html(report, self.order.ids)
        return html.decode()

    def test_quote_uses_invoice_design(self):
        html = self._html('sale.report_saleorder')
        for text in ('Quote', 'QUOTE TOTAL', 'Client:', 'Provider:', 'Merchandise',
                     'Custom Branded T-Shirt', 'Subtotal (excl. VAT)', 'Accepting This Quote'):
            self.assertIn(text, html)
        self.assertNotIn('Quotation #', html)
        self.assertEqual(self.env.ref('sale.action_report_saleorder').paperformat_id,
                         self.env.ref('xrco_quote_report.paperformat_quote'))

    def test_confirmed_order_and_pro_forma(self):
        self.order.action_confirm()
        self.assertIn('ORDER TOTAL', self._html('sale.report_saleorder'))
        self.assertIn('Pro-Forma Invoice', self._html('sale.report_saleorder_pro_forma'))
