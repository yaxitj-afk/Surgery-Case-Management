from datetime import timedelta
from odoo import api, fields, models, _

class PostopConsult(models.Model):
    """Per-surgery actual post-op consult entries (surgeon-adjustable)."""
    _name = 'clinic.postop.consult'
    _description = 'Post-op Consult'
    _order = 'planned_date'
    _rec_name = 'label'

    surgery_case_id = fields.Many2one(
        'clinic.surgery.case', string='Surgery Case', ondelete='cascade')
    label = fields.Char(string='Label')
    planned_date = fields.Date(string='Planned Date', required=True)
    is_fixed = fields.Boolean(string='Fixed Day')
    mediris_booked = fields.Boolean(string='Booked in Mediris')
    notes = fields.Char(string='Notes')
    # Needed to recalculate date when surgery date changes (7.1 + 7.4)
    days_after_surgery = fields.Integer(
        string='Days After Surgery',
        default=0,
        help='Used to recalculate this consult date automatically when the surgery date changes.'
    )
    patient_id = fields.Many2one(related='surgery_case_id.patient_id', string='Patient', store=True)
    surgery_state = fields.Selection(related='surgery_case_id.state', string='Surgery State',
        store=True)
    """
    Extends your existing clinic.postop.consult model — does NOT redeclare it.
    Your base fields (surgery_case_id, label, planned_date, is_fixed,
    mediris_booked, notes, days_after_surgery) stay exactly as you wrote them.

    Adds what G5 still needs:
      - a flexible WINDOW (vs. fixed day) so the surgeon can say "12-15d, doesn't
        matter which day" instead of only a single planned_date
      - a flag for when the doctor has manually overridden the procedure default
      - a "done" flag (you only had mediris_booked, nothing for post-visit)
      - consolidation, for when combined procedures produce overlapping consults
    """
    # ── G5: fixed day OR flexible window, surgeon-set per booking ─────────
    window_days = fields.Integer(
        string='Window ± days', default=0,
        help='Only used when Fixed Day is off, e.g. 12-15d post-op → planned_date=13, window_days=1... '
             'more naturally: set planned_date as the window MIDPOINT and window_days as the ± spread.')
    window_start_date = fields.Date(string='Window Start', compute='_compute_window', store=True)
    window_end_date = fields.Date(string='Window End', compute='_compute_window', store=True)

    surgeon_overridden = fields.Boolean(
        string='Overridden by Doctor', default=False, copy=False,
        help='Set automatically once the doctor changes the default timing generated from the procedure template.')

    consult_done = fields.Boolean(string='Consult Done', default=False, copy=False)

    # ── Consolidation: combined procedures can produce same-date consults ──
    consolidated_with_id = fields.Many2one(
        'clinic.postop.consult', string='Consolidated Into', copy=False,
        help='If set, this consult was merged into another one on the same case because the dates coincided.')
    is_consolidated_away = fields.Boolean(
        compute='_compute_is_consolidated_away', store=True, string='Merged Elsewhere')

    responsible_id = fields.Selection([('doctor', 'Doctor'),('secretary', 'Secretary'),
        ('patient', 'Patient'),('hospital', 'Hospital')], default='secretary')

    # ═══════════════════════════ COMPUTES ══════════════════════════════════

    @api.depends('planned_date', 'window_days', 'is_fixed')
    def _compute_window(self):
        for rec in self:
            if rec.planned_date and not rec.is_fixed and rec.window_days:
                rec.window_start_date = rec.planned_date - timedelta(days=rec.window_days)
                rec.window_end_date = rec.planned_date + timedelta(days=rec.window_days)
            else:
                rec.window_start_date = rec.planned_date
                rec.window_end_date = rec.planned_date

    @api.depends('consolidated_with_id')
    def _compute_is_consolidated_away(self):
        for rec in self:
            rec.is_consolidated_away = bool(rec.consolidated_with_id)

    # ═══════════════════════════ SURGEON OVERRIDE ACTIONS ══════════════════

    # ── NEW: traceability back to the procedure that generated this line ───
    source_procedure_id = fields.Many2one('clinic.surgery.procedure', string='From Procedure',
        help='Which procedure\'s template generated this consult. Empty if '
             'the doctor added this line manually rather than from a '
             'procedure default.')


class SignRequestExtension(models.Model):
    """Add surgery_case_id to Odoo Sign requests so we can link them back."""
    _inherit = 'sign.request'

    surgery_case_id = fields.Many2one('clinic.surgery.case', string='Surgery Case', ondelete='set null', index=True)


class ProjectTaskExtension(models.Model):
    _inherit = 'project.task'

    surgery_case_id = fields.Many2one('clinic.surgery.case',string='Surgery Case',ondelete='set null',index=True)