from odoo import fields, models


class SurgeryProcedure(models.Model):
    _name = 'clinic.surgery.procedure'
    _description = 'Surgery Procedure'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Procedure', required=True, tracking=True)
    doctor_fee = fields.Float(string='Doctor Fee', tracking=True)
    hospital_fee = fields.Float(string='Hospital Fee', tracking=True)
    anesthesia_type = fields.Selection([
        ('local', 'Local Anesthesia'),
        ('general', 'General Anesthesia'),
        ('sedation', 'Sedation'),
    ], string='Anesthesia Type')
    location_type = fields.Selection([
        ('hospital', 'Hospital'),
        ('practice', 'Private Practice'),
    ], string='Location Type')

    product_tmpl_id = fields.Many2one(
        'product.product',
        string='Product',
        domain=[('sale_ok', '=', True)],
        help='Product used at the time of creating invoice for surgery case')

    # ── IC / Sign templates ───────────────────────────────────────────────
    sign_template_ids = fields.Many2many(
        'sign.template',
        'surgery_procedure_sign_template_rel',
        'procedure_id', 'template_id',
        string='Consent Templates (IC)',
        help='All sign templates that must be sent for this procedure (e.g. procedure IC + implant IC)')

    # ── Task templates ────────────────────────────────────────────────────
    task_ids = fields.One2many(
        'clinic.surgery.procedure.task', 'procedure_id', string='Task Templates')

    # ── Post-op consult defaults ──────────────────────────────────────────
    postop_consult_ids = fields.One2many(
        'clinic.procedure.postop.config', 'procedure_id',
        string='Default Post-op Consult Schedule')

    # ── Brochures ─────────────────────────────────────────────────────────
    # info_brochures = fields.Many2many('ir.attachment', 'patient_brochure_rel', 'procedure_id', 'attachment_id',
    #                                   string='Information Brochures (PDF)')
    #
    # postop_brochure_ids = fields.Many2many('ir.attachment','clinic_procedure_postop_brochure_rel','procedure_id',
    #     'attachment_id',string='Post-op Brochures (PDF)',help='Post-operative care brochures shared with the patient after surgery. You can upload multiple files.',)
    info_brochures = fields.Many2many(
        'documents.document',
        'clinic_procedure_info_brochure_rel',
        'procedure_id', 'document_id',
        string='Information Brochures (PDF)',
        domain=[('mimetype', '=', 'application/pdf')],
        help='Select brochure PDFs directly from the Documents app.')

    postop_brochure_ids = fields.Many2many(
        'documents.document',
        'clinic_procedure_postop_brochure_rel',
        'procedure_id', 'document_id',
        string='Post-op Brochures (PDF)',
        domain=[('mimetype', '=', 'application/pdf')],
        help='Post-operative care brochures shared with the patient after surgery.')
    # postop_brochure = fields.Binary(string='Post-op Brochure (PDF)')
    # postop_brochure_filename = fields.Char()

    surgery_duration_hours = fields.Float(
        string='Surgery Duration (Hours)',
        help='Estimated duration of this surgical procedure, in hours. Used for scheduling and planning purposes.',)
    surgeon_id = fields.Many2one(
        'res.users',
        string='Doctor',
        help='The Doctor who normally performs this procedure. Automatically filled in when this procedure is selected on a surgery case.',
    )
    preop_instruction_body = fields.Html(
        string='Pre-op Instructions',
        default=(
            '<p><b>Please note the following pre-operative instructions:</b></p>'
            '<ul>'
            '<li><b>Fasting:</b> Do not eat or drink anything from midnight the night before.</li>'
            '<li><b>Shaving:</b> Shave the operative area the evening before if instructed.</li>'
            '<li><b>What to bring:</b> ID, insurance documents, and any pre-operative test results.</li>'
            '<li><b>Check-in:</b> Please arrive at the location indicated below at the scheduled time. '
            '<em>Note: the exact hour may still be confirmed by phone.</em></li>'
            '</ul>'
            '<p><b>Location:</b> To be confirmed with the patient closer to the surgery date.</p>'
        ),
        help='Medication and surgery preparation instructions shown to the patient '
             'in the automated D-1 pre-operative email. If left empty, a generic '
             'fallback message is used instead.')

    state = fields.Selection([('draft', 'Draft'), ('confirmed', 'Confirmed'), ], string='Status', default='draft',
                             tracking=True, copy=False)

    consent_deadline_days = fields.Integer(string='Consent Deadline (Days Before Surgery)', default=14,
                                           help='Number of days before the surgery date by which the patient must '
                                                'sign the consent form. Used to auto-calculate the consent deadline '
                                                'on surgery cases using this procedure.')

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_set_draft(self):
        self.write({'state': 'draft'})

class SurgeryProcedureTask(models.Model):
    _name = 'clinic.surgery.procedure.task'
    _description = 'Surgery Procedure Task Template'
    _order = 'deadline_days_before desc, sequence, id'

    sequence = fields.Integer(default=10)
    procedure_id = fields.Many2one(
        'clinic.surgery.procedure', string='Procedure', ondelete='cascade')
    name = fields.Char(string='Task Name', required=True)
    responsible = fields.Selection([
        ('doctor', 'Doctor'),
        ('secretary', 'Secretary'),
        ('patient', 'Patient'),
        ('hospital', 'Hospital'),
    ], default='secretary')
    deadline_days_before = fields.Integer(
        string='Days Before Surgery',
        default=0,
        help=(
            'Positive = N days BEFORE surgery date. '
            'Negative = N days AFTER surgery date (e.g. -3 = 3 days post-op). '
            '0 = day of surgery.'
        ))
    description = fields.Html(string='Instructions / Notes')


class ProcedurePostopConfig(models.Model):
    """Per-procedure default post-op consult schedule."""
    _name = 'clinic.procedure.postop.config'
    _description = 'Procedure Post-op Consult Config'
    _order = 'days_after'

    procedure_id = fields.Many2one(
        'clinic.surgery.procedure', string='Procedure', ondelete='cascade')
    label = fields.Char(string='Label', help='e.g. "Dressing removal"')
    days_after = fields.Integer(string='Days After Surgery', required=True)
    is_fixed_day = fields.Boolean(
        string='Fixed Day (clinically required)',
        help='If checked, this consult must happen exactly on this day. '
             'If unchecked, it is a flexible window.')
    window_days = fields.Integer(
        string='Window ± days',
        default=0,
        help='Only used when not a fixed day. Consult can happen within ±N days.')
    responsible_id = fields.Selection([
        ('doctor', 'Doctor'),
        ('secretary', 'Secretary'),
        ('patient', 'Patient'),
        ('hospital', 'Hospital'),
    ], default='secretary')
