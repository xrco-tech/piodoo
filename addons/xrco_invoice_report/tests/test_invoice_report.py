# -*- coding: utf-8 -*-
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install', 'xrco')
class TestInvoiceReport(AccountTestInvoicingCommon):

    def _html(self, move):
        html, _type = self.env['ir.actions.report']._render_qweb_html('account.report_invoice', move.ids)
        return html.decode()

    def test_invoice_uses_our_design(self):
        invoice = self.init_invoice('out_invoice', amounts=[1000], post=True)
        html = self._html(invoice)
        for text in ('INVOICE TOTAL', 'Client:', 'Provider:', 'Invoice Issued:',
                     'Subtotal (excl. VAT)', 'Bank Payment Instructions'):
            self.assertIn(text, html)
        paperformat = self.env.ref('xrco_invoice_report.paperformat_invoice')
        self.assertEqual(self.env.ref('account.account_invoices').paperformat_id, paperformat)
        self.assertEqual(self.env.ref('account.account_invoices_without_payment').paperformat_id, paperformat)

    def test_credit_note_title(self):
        refund = self.init_invoice('out_refund', amounts=[100], post=True)
        self.assertIn('Credit Note', self._html(refund))
