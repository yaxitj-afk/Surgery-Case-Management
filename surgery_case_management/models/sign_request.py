# -*- coding: utf-8 -*-
from odoo import models

class SignRequestItemExtension(models.Model):
    _inherit = 'sign.request.item'

    def write(self, vals):
        res = super().write(vals)
        if vals.get('state') == 'completed':
            for item in self:
                surgery_case = item.sign_request_id.surgery_case_id
                if surgery_case:
                    if item.partner_id == surgery_case.patient_id:
                        surgery_case.patient_consent_signed = True
                    if (surgery_case.surgeon_id
                            and item.partner_id == surgery_case.surgeon_id.partner_id):
                        surgery_case.doctor_consent_signed = True
                    surgery_case.message_post(
                        body=(
                            f'{item.partner_id.name} has signed the document: '
                            f'{item.sign_request_id.reference}.'
                        )
                    )
        return res
