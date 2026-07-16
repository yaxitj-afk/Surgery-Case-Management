# -*- coding: utf-8 -*-
from odoo import fields, models,api, _
from odoo.exceptions import ValidationError

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ── 7.2 IC Reminder Engine ────────────────────────────────────────────
    ic_patient_reminder_weeks = fields.Integer(
        string='IC Patient Reminder (days before surgery)',
        default=21,
        config_parameter='clinic.ic_patient_reminder_weeks',
        help='Send automatic IC reminder to patient this many weeks before surgery. Default: 3 (D-3w).'
    )
    ic_secretary_escalation_weeks = fields.Integer(
        string='IC Secretary Escalation (days before surgery)',
        default=14,
        config_parameter='clinic.ic_secretary_escalation_weeks',
        help='Create escalation task for Secretariat this many weeks before surgery. Default: 2 (D-2w).'
    )

    # ── 7.3 Payment Guards ────────────────────────────────────────────────
    payment_patient_reminder_days = fields.Integer(
        string='Payment Patient Reminder (days before surgery)',
        default=10,
        config_parameter='clinic.payment_patient_reminder_days',
        help='Send payment reminder to patient this many days before surgery. Default: 10 (D-10d).'
    )
    payment_secretary_alert_days = fields.Integer(
        string='Payment Secretary Alert (days before surgery)',
        default=7,
        config_parameter='clinic.payment_secretary_alert_days',
        help='Alert Secretariat about unpaid hospital fee this many days before surgery. Default: 7 (D-7d).'
    )
    honorarium_patient_reminder_days = fields.Integer(
        string='Fee Patient Reminder (days before surgery)',
        default=10,
        config_parameter='clinic.honorarium_patient_reminder_days',
        help='Send BV Fee reminder to patient this many days before surgery. Default: 10 (D-10d).'
    )
    honorarium_secretary_alert_days = fields.Integer(
        string='Fee Secretary Alert (days before surgery)',
        default=7,
        config_parameter='clinic.honorarium_secretary_alert_days',
        help='Alert Secretariat about unpaid fee this many days before surgery. Default: 7 (D-7d).'
    )

    # ── 7.6 D-1 Instruction Email ─────────────────────────────────────────
    preop_instruction_days_before = fields.Integer(
        string='Pre-op Instruction Email (days before surgery)',
        default=1,
        config_parameter='clinic.preop_instruction_days_before',
        help='Send pre-operative instruction email this many days before surgery. Default: 1 (D-1).'
    )

    # ── 7.7 Review Request ────────────────────────────────────────────────
    review_request_days_after = fields.Integer(
        string='Review Request Email (days after surgery)',
        default=42,
        config_parameter='clinic.review_request_days_after',
        help='Send Google review request this many days after surgery. Default: 42 (D+6w).'
    )
    google_review_url = fields.Char(
        string='Google Review URL',
        config_parameter='clinic.google_review_url',
        help='Your practice Google Maps review link.'
    )

    from odoo.exceptions import ValidationError

    @api.constrains('ic_patient_reminder_weeks', 'ic_secretary_escalation_weeks')
    def _check_ic_reminder_order(self):
        for rec in self:
            if rec.ic_patient_reminder_weeks <= rec.ic_secretary_escalation_weeks:
                raise ValidationError(_(
                    'Patient IC Reminder (%s days) must be greater than '
                    'Secretary Escalation (%s days).'
                ) % (rec.ic_patient_reminder_weeks, rec.ic_secretary_escalation_weeks))
