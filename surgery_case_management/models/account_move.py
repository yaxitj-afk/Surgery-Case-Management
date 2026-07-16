# -*- coding: utf-8 -*-
from odoo import models, fields, api


class AccountMove(models.Model):
    _inherit = 'account.move'

    surgery_case_id = fields.Many2one('clinic.surgery.case', string="Surgery Case")

class AccountMoveSend(models.AbstractModel):
    _inherit = "account.move.send"

    @api.model
    def _get_default_pdf_report_id(self, move):
        if move.surgery_case_id and not move.surgery_case_id.is_reimbursed_surgery:
            if move._drcolle_use_hospital_invoice_pdf():
                if move._drcolle_invoice_pdf_needs_update():
                    move._drcolle_invalidate_invoice_pdf_report()
                return self.env.ref("drcolle_hospital_invoicing.action_report_hospital_invoice")
        return super()._get_default_pdf_report_id(move)
