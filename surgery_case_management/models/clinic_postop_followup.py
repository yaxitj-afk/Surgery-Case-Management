# -*- coding: utf-8 -*-
from odoo import api, fields, models

class ClinicPostopFollowup(models.Model):
    """Pick a patient, see every post-op consult from that patient's
    completed surgeries, across all their surgery cases."""
    _name = 'clinic.postop.followup'
    _description = 'Post-op Follow-up Dashboard'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'patient_id'

    patient_id = fields.Many2one(
        'res.partner', string='Patient', required=True,
        help='Select a patient to pull in the post-op consult schedule '
             'from all of their completed surgeries.')

    # ── Not stored: fine as list/tags on the form, never used in pivot ─────
    surgery_case_ids = fields.Many2many(
        'clinic.surgery.case', compute='_compute_case_and_consult_ids',
        string='Completed Surgeries')

    postop_consult_ids = fields.Many2many(
        'clinic.postop.consult', compute='_compute_case_and_consult_ids',
        string='Post-op Consults', store=True)

    # ── Stored numeric measures for the pivot — SAFE because the depends
    #    below is a real relation path, so Odoo recomputes automatically
    #    whenever a case's state or a consult's done flag changes, even
    #    though we never touch this record directly. ─────────────────────
    consult_count = fields.Integer(
        string='Total Consults', compute='_compute_consult_stats', store=True)
    consult_done_count = fields.Integer(
        string='Done', compute='_compute_consult_stats', store=True)
    consult_pending_count = fields.Integer(
        string='Pending', compute='_compute_consult_stats', store=True)

    @api.depends('patient_id')
    def _compute_case_and_consult_ids(self):
        """Not stored — always correct on read, no dependency-tracking risk."""
        Case = self.env['clinic.surgery.case']
        for rec in self:
            cases = Case.search([
                ('patient_id', '=', rec.patient_id.id),
                ('state', 'in', ('surgery_completed', 'post_follow_ups')),
            ]) if rec.patient_id else Case
            rec.surgery_case_ids = cases
            rec.postop_consult_ids = cases.mapped('postop_consult_ids')

    @api.depends(
        'patient_id.surgery_case_ids.state',
        'patient_id.surgery_case_ids.postop_consult_ids.consult_done',
    )
    def _compute_consult_stats(self):
        """Stored + safe: depends walks a real relation path
        (partner -> surgery_case_ids -> postop_consult_ids -> consult_done),
        so Odoo invalidates/recomputes this automatically whenever a case's
        state or any of its consults' done flag changes — no staleness."""
        for rec in self:
            cases = rec.patient_id.surgery_case_ids.filtered(
                lambda c: c.state in ('surgery_completed', 'post_follow_ups')
            )
            consults = cases.mapped('postop_consult_ids')
            rec.consult_count = len(consults)
            rec.consult_done_count = len(consults.filtered('consult_done'))
            rec.consult_pending_count = rec.consult_count - rec.consult_done_count

    def action_view_consults(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Post-op Consults',
            'res_model': 'clinic.postop.consult',  # adjust to your actual consult model name
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.postop_consult_ids.ids)],
            'context': {'default_followup_id': self.id},
        }

    def action_view_pending_consults(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Pending Post-op Consults',
            'res_model': 'clinic.postop.consult',
            'view_mode': 'list,form',
            'domain': [
                ('id', 'in', self.postop_consult_ids.ids),
                ('consult_done', '=', False),
            ],
            'context': {'default_followup_id': self.id},
        }