# -*- coding: utf-8 -*-
from odoo import models


class SignRequestItem(models.Model):
    _inherit = 'sign.request.item'

    def _send_signature_access_message(self):
        """Suppress the 'please sign' invite email for items that our
        clinic workflow auto-signs on someone's behalf:
        - the doctor's item (see clinic.surgery.case._auto_sign_doctor_item),
          completed programmatically using the doctor's saved profile
          signature at request-creation time; and
        - the patient's item when the case is marked for physical (paper)
          consent, since that patient will sign on paper and be completed
          later via action_confirm_physical_consent — they should never get
          a "please sign online" invite in that case.

        Only affects sign requests linked to a clinic.surgery.case where the
        item's partner is that surgery's surgeon or patient; every other
        Sign use case in the system (unrelated templates, other apps) is
        untouched.
        """
        def _is_auto_signed(item):
            case = item.sign_request_id.surgery_case_id
            if not case:
                return False
            is_doctor_item = (
                case.surgeon_id
                and item.partner_id == case.surgeon_id.partner_id
            )
            is_physical_patient_item = (
                case.is_physical_consent
                and case.patient_id
                and item.partner_id == case.patient_id
            )
            return is_doctor_item or is_physical_patient_item

        to_notify = self.filtered(lambda item: not _is_auto_signed(item))
        return super(SignRequestItem, to_notify)._send_signature_access_message()