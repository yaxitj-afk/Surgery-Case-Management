# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import timedelta, datetime, time
import pytz
import json
import io
import zipfile
import base64

PHYSICAL_CONSENT_PLACEHOLDER_PNG = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII='
)


class SurgeryCase(models.Model):
    _name = 'clinic.surgery.case'
    _description = 'Surgery Case'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'surgery_date desc, id desc'

    # ── Core ──────────────────────────────────────────────────────────────
    name = fields.Char(required=True, tracking=True, help="Name of the Patient Surgery")
    patient_id = fields.Many2one('res.partner', string='Patient', tracking=True, help="Name of the patient")
    procedure_id = fields.Many2one(
        'clinic.surgery.procedure', string='Surgery', tracking=True, copy=False,
        help='The surgical procedure planned for this case.')

    # surgeon_id = fields.Many2one('res.users', related='procedure_id.surgeon_id',string='Doctor', tracking=True, copy=False, help='The surgeon responsible for performing this procedure.')
    # WORKING VERSION
    surgeon_id = fields.Many2one('res.users', string='Doctor', tracking=True, copy=False,
                                 help='The surgeon responsible for performing this procedure.')
    secretary_id = fields.Many2one('res.users', string='Secretary', tracking=True, copy=False,
                                   help='The secretary managing administrative tasks for this surgery case.')
    surgery_date = fields.Date(tracking=True, copy=False, help='Planned date and time of the surgery.')
    # ── Operating block link ──────────────────────────────────────────────
    operating_block_id = fields.Many2one(
        'clinic.operating.block',
        string='Operating Block', tracking=True,
        help='The operating block this surgery is scheduled in. ''Determines location and time window automatically.')

    # ── Available dates JSON (used by the JS date picker widget) ─────────
    available_surgery_dates = fields.Text(string='Available Surgery Dates (JSON)',
                                          compute='_compute_available_surgery_dates',
                                          help='JSON list of available dates based on doctor operating blocks.')

    # ── Auto-filled from block when surgery_date is set ───────────────────
    block_location_id = fields.Many2one('res.partner', string='Block Location', compute='_compute_block_info',
                                        store=True, )
    block_location_type = fields.Selection([
        ('hospital', 'Hospital'),
        ('practice', 'Private Practice'), ], string='Block Location Type', compute='_compute_block_info', store=True, )
    block_start_time = fields.Char(string='Block Start', compute='_compute_block_info', store=True, )
    block_end_time = fields.Char(string='Block End', compute='_compute_block_info', store=True, )

    hospital_location_id = fields.Many2one('res.partner', string='Hospital Location', tracking=True, copy=False,
                                           help='The hospital or private practice where the surgery will take place.')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('planned', 'Planned'),
        ('reschedule', 'Resechedule'),
        ('in_progress', 'In Progress'),
        ('surgery_completed', 'Surgery Completed'),
        ('post_follow_ups', 'Post Follow-ups'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True, copy=False)

    state_before_reschedule = fields.Selection([
        ('planned', 'Planned'),
        ('in_progress', 'In Progress'),
    ], string='State Before Reschedule', copy=False)

    mediris_reference = fields.Char(
        string='Mediris Reference',
        related='patient_id.mediris_patient_id', tracking=True,
        help='Mediris patient ID linked to this patient. Pulled automatically from the patient record.')
    notes = fields.Html(string='Internal Notes')

    # ── Related fields from Procedure ────────────────────────────────────
    procedure_doctor_fee = fields.Float(
        related='procedure_id.doctor_fee', string='Doctor Fee', store=True, copy=False,
        help='The doctors fee for this procedure.')
    procedure_hospital_fee = fields.Float(
        related='procedure_id.hospital_fee', string='Hospital Fee', store=True, copy=False,
        help='The hospital costs for this procedure.')
    procedure_anesthesia_type = fields.Selection(
        related='procedure_id.anesthesia_type',
        string='Anesthesia', store=True, help='The type of anesthesia used for this procedure.')
    procedure_location_type = fields.Selection([
        ('hospital', 'Hospital'),
        ('practice', 'Private Practice'), ], string='Location Type',
        help='Where this procedure is normally performed — hospital or private practice.')
    procedure_task_ids = fields.One2many(
        related='procedure_id.task_ids',
        string='Procedure Templates',
        help='The list of tasks that will be created when you click "Fetch & Generate Tasks".')
    procedure_sign_template_ids = fields.Many2many(
        related='procedure_id.sign_template_ids',
        string='Consent Templates')

    surgery_end_time = fields.Char(
        string='Surgery End Time',
        compute='_compute_surgery_end_time',
        store=True,
        help='Estimated end time of the surgery, calculated from the selected start time slot plus the procedure\'s estimated duration.',
    )
    surgery_datetime_start = fields.Datetime(
        string="Surgery Start", compute="_compute_surgery_datetime",
        inverse="_inverse_surgery_datetime", store=True)
    surgery_datetime_stop = fields.Datetime(
        string="Surgery End", compute="_compute_surgery_datetime",
        inverse="_inverse_surgery_datetime", store=True)

    # ── Consent / Sign ────────────────────────────────────────────────────
    consent_required = fields.Boolean(string='Consent Sent', tracking=True, copy=False,
                                      help='Turn this on if the patient needs to sign a consent form before surgery.')
    consent_deadline = fields.Date(
        string='Consent Deadline', tracking=True,
        compute='_compute_consent_deadline', store=True,
        help='The last date by which the patient must sign the consent form. Normally 2 weeks before surgery.')
    sign_request_ids = fields.One2many(
        'sign.request', 'surgery_case_id', string='Sign Requests')
    consent_count = fields.Integer(
        string='Consent Documents', compute='_compute_consent_count',
        help='How many consent documents have been sent for this surgery.')
    consent_status = fields.Selection([
        ('none', 'Not Sent'),
        ('sent', 'Sent – Awaiting Signature'),
        ('signed', 'Signed'),
        ('overdue', 'Overdue'),
    ], string='Consent Status', compute='_compute_consent_status', store=True)
    is_physical_consent = fields.Boolean(
        string='Physical Consent', tracking=True, copy=False,)
    physical_consent_attachment_ids = fields.Many2many(
        'ir.attachment', 'clinic_surgery_case_physical_consent_rel',
        'case_id', 'attachment_id',
        string='Upload Signed Consents (Scanned)', copy=False,
        help='Scanned copies of the physically (wet-ink) signed consent forms, '
             'for patients who signed on paper instead of digitally. '
             'Upload exactly one file per required consent document — the '
             'count is validated when confirming physical signature.')

    # ── 7.2 Surgery At Risk flag ──────────────────────────────────────────
    surgery_at_risk = fields.Boolean(
        string='Surgery At Risk',
        compute='_compute_surgery_at_risk',
        store=True,
        copy=False,
        help='Red flag: set when IC or payment deadline is breached close to surgery date.'
    )
    surgery_at_risk_reason = fields.Char(
        string='At Risk Reason',
        compute='_compute_surgery_at_risk',
        store=True,
    )

    # ── Payment / Financial ───────────────────────────────────────────────
    prepayment_required = fields.Boolean(string='Prepayment Required', tracking=True)
    doctor_fee = fields.Float(string='Doctor Fee', tracking=True)
    hospital_fee = fields.Float(
        string='Hospital Fee (patient pays hospital)', tracking=True)
    expected_settlement = fields.Float(
        string='Expected Hospital Settlement', tracking=True)
    invoice_ids = fields.Many2many('account.move', string='Invoices')
    invoice_count = fields.Integer(compute='_compute_invoice_count')

    # Hospital fee paid flag (used for payment guard logic)
    hospital_fee_paid = fields.Boolean(
        string='Hospital Fee Paid', default=False, tracking=True, copy=False)
    honorarium_paid = fields.Boolean(
        string='BV Fee Paid', default=False, tracking=True, copy=False)

    admission_document_sent = fields.Boolean(
        string='Admission Document Sent', default=False, copy=False,
        help='Automatically set to True when the admission document is generated and sent to the patient.')

    # ── Tasks ─────────────────────────────────────────────────────────────
    task_ids = fields.One2many(
        'project.task', 'surgery_case_id', string='Tasks')
    task_count = fields.Integer(compute='_compute_task_count')
    tasks_generated = fields.Boolean(string='Tasks Generated', default=False, copy=False)
    info_brochure_sent = fields.Boolean(string="Info Brochure Sent", default=False,
                                        help="Automatically set to True when the info brochure is sent.ncheck to resend the brochure.", )

    # ── Post-op consults ──────────────────────────────────────────────────
    postop_consult_ids = fields.One2many('clinic.postop.consult', 'surgery_case_id', string='Post-op Consults')

    # ── 7.6 / 7.7 Automation flags ───────────────────────────────────────
    preop_email_sent = fields.Boolean(
        string='Pre-op Instruction Email Sent', default=False, copy=False)
    review_request_sent = fields.Boolean(
        string='Review Request Sent', default=False, copy=False)
    send_review_request = fields.Boolean(
        string='Send Review Request to Patient',
        default=False, tracking=True, copy=False,
        help='If checked, an automatic review request email will be sent to this patient after surgery (D+6w by default).'
    )
    review_request_email = fields.Char(string='Review Request Email',
                                       help='The email address where the review invitation will be sent. Automatically filled from the patient record but can be changed if needed.')

    patient_consent_signed = fields.Boolean(
        string='Patient Consent Signed',
        default=False, copy=False,
        help='Automatically set to True when the patient signs the consent document.',
    )
    doctor_pending_signature = fields.Boolean(
        string='Doctor Signature Pending',
        compute='_compute_doctor_pending_signature',
        help='True if the doctor still has an unsigned consent request on this case.',
    )
    doctor_consent_signed = fields.Boolean(
        string='Doctor Consent Signed',
        default=False, copy=False,
        help='Automatically set to True when the doctor signs the consent document.',
    )

    surgery_time_slot = fields.Char(
        string='Surgery Time Slot',
        help='Start time of the selected slot, e.g. "08:00".',
    )

    # ── Human label stored for list view display ───────────────────────────
    surgery_time_slot_display = fields.Char(
        string='Time Slot',
        compute='_compute_surgery_time_slot_display',
        store=True,
    )

    # ── JSON list of available slots — read by the view ────────────────────
    # NOT stored — always computed fresh so it reflects current block config.
    available_time_slots = fields.Text(
        string='Available Time Slots (JSON)',
        compute='_compute_available_time_slots',
        store=False,
    )

    # ── Brochure availability (used for button visibility) ────────────────
    brochure_available = fields.Boolean(
        compute='_compute_brochure_available', copy=False)

    admission_type = fields.Selection([('daycare', 'Day Care'),
                                       ('overnight', 'Overnight Stay'), ('private', 'Private Practice')],
                                      string="Admission Type")

    admission_point_id = fields.Many2one('admission.point', string="Admission Point")
    admission_time = fields.Selection([
        ('00:00', '00:00'),
        ('00:30', '00:30'),
        ('01:00', '01:00'),
        ('01:30', '01:30'),
        ('02:00', '02:00'),
        ('02:30', '02:30'),
        ('03:00', '03:00'),
        ('03:30', '03:30'),
        ('04:00', '04:00'),
        ('04:30', '04:30'),
        ('05:00', '05:00'),
        ('05:30', '05:30'),
        ('06:00', '06:00'),
        ('06:30', '06:30'),
        ('07:00', '07:00'),
        ('07:30', '07:30'),
        ('08:00', '08:00'),
        ('08:30', '08:30'),
        ('09:00', '09:00'),
        ('09:30', '09:30'),
        ('10:00', '10:00'),
        ('10:30', '10:30'),
        ('11:00', '11:00'),
        ('11:30', '11:30'),
        ('12:00', '12:00'),
        ('12:30', '12:30'),
        ('13:00', '13:00'),
        ('13:30', '13:30'),
        ('14:00', '14:00'),
        ('14:30', '14:30'),
        ('15:00', '15:00'),
        ('15:30', '15:30'),
        ('16:00', '16:00'),
        ('16:30', '16:30'),
        ('17:00', '17:00'),
        ('17:30', '17:30'),
        ('18:00', '18:00'),
        ('18:30', '18:30'),
        ('19:00', '19:00'),
        ('19:30', '19:30'),
        ('20:00', '20:00'),
        ('20:30', '20:30'),
        ('21:00', '21:00'),
        ('21:30', '21:30'),
        ('22:00', '22:00'),
        ('22:30', '22:30'),
        ('23:00', '23:00'),
        ('23:30', '23:30'),
    ], string="Admission Time")

    is_reimbursed_surgery = fields.Boolean(
        string='Reimbursed Surgery', tracking=True, copy=False,
        help='Check this when the surgery is fully covered/reimbursed and no '
             'invoice or payment for the procedure fee is sent to the patient. '
             'The normal workflow (consent, brochure, admission document) still '
             'applies. An optional supplement (e.g. an "esthetisch supplement") '
             'payable directly to the practice can still be invoiced below.')

    reimbursed_supplement_description = fields.Char(
        string='Supplement Description', tracking=True,
        help='What the extra cost is for (e.g. "Esthetisch supplement"). '
             'This amount is paid directly to the practice, not the hospital.')

    reimbursed_supplement_amount = fields.Float(
        string='Supplement Amount', tracking=True,
        help='Amount payable directly to the practice for this supplement.')

    surgery_duration_hours = fields.Float(
        string='Surgery Duration (Hours)',
        help='Estimated duration of this surgical procedure, in hours. Used for scheduling and planning purposes.',
    )

    # ═══════════════════════════ ONCHANGE ══════════════════════════════════

    @api.onchange('admission_type')
    def _onchange_admission_type(self):
        self.admission_point_id = False
        points = self.env['admission.point'].search([('admission_type', '=', self.admission_type)])
        if len(points) == 1:
            self.admission_point_id = points.id

    @api.onchange('patient_id')
    def _onchange_review_request_email(self):
        if self.patient_id and self.patient_id.email:
            self.review_request_email = self.patient_id.email

    @api.onchange('procedure_id')
    def _onchange_procedure_id_clear_surgery_date(self):
        procedure = self.procedure_id

        if not procedure:
            return
        self.surgeon_id = procedure.surgeon_id
        self.doctor_fee = procedure.doctor_fee
        self.hospital_fee = procedure.hospital_fee
        self.surgery_duration_hours = procedure.surgery_duration_hours

    @api.onchange('procedure_location_type')
    def _onchange_location_type_clear_schedule(self):
        """Wipe the whole scheduling chain when the location type genuinely
        changes (hospital <-> practice). Odoo only invokes this onchange when
        the field's value actually changes, so re-selecting the SAME location
        type never fires this method and the schedule stays untouched."""
        self.surgery_date = False
        self.operating_block_id = False
        self.surgery_time_slot = False
        self.available_time_slots = "[]"

    # models/clinic_surgery_case.py
    @api.onchange('operating_block_id')
    def _onchange_surgery_date_slots(self):
        self.surgery_time_slot = False
        Block = self.env['clinic.operating.block']

        if not self.surgery_date or not self.surgeon_id:
            self.available_time_slots = "[]"
            return

        slots = Block.get_timeslots_for_date(self.surgeon_id.id, self.surgery_date.strftime('%Y-%m-%d'))
        self.available_time_slots = json.dumps(
            [{'value': v, 'label': l} for v, l in slots])

    @api.onchange('surgery_date', 'surgeon_id')
    def _onchange_surgery_date_block(self):
        """
        When the surgery date is selected:
        1. Find which operating block covers this date for this doctor
        2. Auto-fill operating_block_id
        3. Auto-fill hospital_location_id from the block
        """
        self.surgery_time_slot = False
        self.surgery_time_slot_display = False
        self.operating_block_id = False
        self.hospital_location_id = False

        if not self.surgery_date or not self.surgeon_id:
            return

        if self.procedure_id and not self.surgery_duration_hours:
            self.surgery_duration_hours = self.procedure_id.surgery_duration_hours

        surgery_day = self.surgery_date

        Block = self.env['clinic.operating.block']
        slots = Block.get_timeslots_for_date(
            self.surgeon_id.id,
            surgery_day.strftime('%Y-%m-%d')
        )
        # self.surgery_time_slot = json.dumps(
        #     [{'value': v, 'label': l} for v, l in slots]
        # )
        self.available_time_slots = json.dumps(
            [{'value': v, 'label': l} for v, l in slots]
        )

        blocks = self.env['clinic.operating.block'].search([
            ('doctor_id', '=', self.surgeon_id.id),
            ('active', '=', True),
        ])

        matched_block = None
        for block in blocks:
            # Check regular weekday match
            if int(block.day_of_week) == surgery_day.weekday():
                # Make sure it's not closed
                closed_ranges = [
                    (c.from_date, c.to_date)
                    for c in block.closure_ids
                    if c.from_date and c.to_date
                ]
                if not block._is_date_closed(surgery_day, closed_ranges):
                    matched_block = block
                    break
            # Check extra slots
            extra = block.extra_ids.filtered(
                lambda e: e.extra_date == surgery_day)
            if extra:
                matched_block = block
                break

        if matched_block:
            self.operating_block_id = matched_block
            self.hospital_location_id = matched_block.location_id
        else:
            # Date is not in any configured operating block — warn user
            return {
                'warning': {
                    'title': 'Date Not in Operating Schedule',
                    'message': (
                        f'{surgery_day.strftime("%A %d %B %Y")} is not a '
                        f'configured operating day for '
                        f'{self.surgeon_id.name}. '
                        f'Please select a date from the configured schedule.'
                    )
                }
            }

    # ═══════════════════════════ COMPUTES ══════════════════════════════════

    @api.depends('procedure_id', 'procedure_id.info_brochures')
    def _compute_brochure_available(self):
        for rec in self:
            rec.brochure_available = bool(
                rec.procedure_id and rec.procedure_id.info_brochures)

    @api.depends('surgery_date', 'surgery_time_slot', 'surgery_end_time')
    def _compute_surgery_datetime(self):
        user_tz = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'UTC')
        for rec in self:
            if not rec.surgery_date or not rec.surgery_time_slot:
                rec.surgery_datetime_start = False
                rec.surgery_datetime_stop = False
                continue
            try:
                start_h, start_m = map(int, rec.surgery_time_slot.split(':'))
                local_start = user_tz.localize(
                    datetime.combine(rec.surgery_date, time(start_h, start_m)))
                rec.surgery_datetime_start = local_start.astimezone(pytz.UTC).replace(tzinfo=None)

                if rec.surgery_end_time:
                    end_h, end_m = map(int, rec.surgery_end_time.split(':'))
                    local_end = user_tz.localize(
                        datetime.combine(rec.surgery_date, time(end_h, end_m)))
                    rec.surgery_datetime_stop = local_end.astimezone(pytz.UTC).replace(tzinfo=None)
                else:
                    rec.surgery_datetime_stop = rec.surgery_datetime_start + timedelta(hours=1)
            except (ValueError, AttributeError):
                rec.surgery_datetime_start = False
                rec.surgery_datetime_stop = False

    def _inverse_surgery_datetime(self):
        if self.env.context.get('_skip_surgery_datetime_inverse'):
            return

        user_tz = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'UTC')

        for rec in self:
            if not rec.surgery_datetime_start:
                continue

            utc_start = pytz.UTC.localize(rec.surgery_datetime_start)
            local_start = utc_start.astimezone(user_tz)

            rec.surgery_date = local_start.date()
            rec.surgery_time_slot = local_start.strftime("%H:%M")

    @api.depends('sign_request_ids.request_item_ids.state', 'sign_request_ids.request_item_ids.partner_id',
                 'surgeon_id', )
    def _compute_doctor_pending_signature(self):
        for rec in self:
            pending = False
            if rec.surgeon_id:
                doctor_partner = rec.surgeon_id.partner_id
                for req in rec.sign_request_ids:
                    if req.request_item_ids.filtered(
                            lambda i: i.partner_id == doctor_partner and i.state != 'completed'):
                        pending = True
                        break
            rec.doctor_pending_signature = pending

    @api.depends('surgeon_id')
    def _compute_available_surgery_dates(self):
        """
        Build a JSON list of available dates for the surgeon's operating blocks.
        Used by the date picker to enable only valid dates.
        """
        import json
        Block = self.env['clinic.operating.block']
        for rec in self:
            if not rec.surgeon_id:
                rec.available_surgery_dates = '[]'
                continue
            dates = Block.get_available_dates_for_doctor(rec.surgeon_id.id)
            rec.available_surgery_dates = json.dumps(dates)

    @api.depends('operating_block_id', 'surgery_date')
    def _compute_block_info(self):
        """
        When the operating block is set, auto-fill location and time window.
        This ensures location_type on the case matches the block.
        """
        import json
        Block = self.env['clinic.operating.block']
        for rec in self:
            if not rec.operating_block_id or not rec.surgery_date:
                rec.block_location_id = False
                rec.block_location_type = False
                rec.block_start_time = False
                rec.block_end_time = False
                continue

            surgery_day = rec.surgery_date
            block = rec.operating_block_id

            # Check if it's an extra slot date
            extra = block.extra_ids.filtered(
                lambda e: e.extra_date == surgery_day)

            if extra:
                e = extra[0]
                rec.block_start_time = '{:02d}:{:02d}'.format(
                    e.open_time_hour, e.open_time_minute)
                rec.block_end_time = '{:02d}:{:02d}'.format(
                    e.close_time_hour, e.close_time_minute)
            else:
                rec.block_start_time = '{:02d}:{:02d}'.format(
                    block.open_time_hour, block.open_time_minute)
                rec.block_end_time = '{:02d}:{:02d}'.format(
                    block.close_time_hour, block.close_time_minute)

            rec.block_location_id = block.location_id
            rec.block_location_type = block.location_type

    def _compute_consent_count(self):
        for rec in self:
            rec.consent_count = len(rec.sign_request_ids)

    @api.depends('sign_request_ids', 'sign_request_ids.state', 'consent_deadline',
                 'is_physical_consent', 'patient_consent_signed', 'doctor_consent_signed')
    def _compute_consent_status(self):
        today = fields.Date.today()
        for rec in self:
            if rec.is_physical_consent and rec.patient_consent_signed and rec.doctor_consent_signed:
                rec.consent_status = 'signed'
                if rec.state in ('confirmed', 'planned'):
                    rec.state = 'in_progress'
                continue

            requests = rec.sign_request_ids
            if not requests:
                rec.consent_status = 'none'
            elif all(r.state == 'signed' for r in requests):
                rec.consent_status = 'signed'
                if rec.state in ('confirmed', 'planned'):
                    rec.state = 'in_progress'
            elif rec.consent_deadline and today > rec.consent_deadline:
                rec.consent_status = 'overdue'
            else:
                rec.consent_status = 'sent'

    @api.depends('surgery_time_slot', 'surgery_date', 'surgeon_id')
    def _compute_surgery_time_slot_display(self):
        """Resolve the stored start-time value to a human label."""
        Block = self.env['clinic.operating.block']
        for rec in self:
            if not rec.surgery_time_slot or not rec.surgery_date or not rec.surgeon_id:
                rec.surgery_time_slot_display = rec.surgery_time_slot or ''
                continue
            date_str = rec.surgery_date.strftime('%Y-%m-%d')
            slots = Block.get_timeslots_for_date(rec.surgeon_id.id, date_str)
            label = next((lbl for val, lbl in slots if val == rec.surgery_time_slot), rec.surgery_time_slot, )
            rec.surgery_time_slot_display = label

    @api.depends('surgery_date', 'surgeon_id')
    def _compute_available_time_slots(self):
        """Build JSON list of slots from the operating block configuration."""
        Block = self.env['clinic.operating.block']
        for rec in self:
            if rec.surgery_date and rec.surgeon_id:
                date_str = rec.surgery_date.strftime('%Y-%m-%d')
                # get_timeslots_for_date returns [(value, label), ...]
                slots = Block.get_timeslots_for_date(rec.surgeon_id.id, date_str)
                rec.available_time_slots = json.dumps([
                    {'value': v, 'label': l} for v, l in slots
                ])
            else:
                rec.available_time_slots = '[]'

    @api.depends('surgery_time_slot', 'surgery_duration_hours')
    def _compute_surgery_end_time(self):
        for rec in self:
            if rec.surgery_time_slot and rec.surgery_duration_hours:
                try:
                    start_h, start_m = map(int, rec.surgery_time_slot.split(':'))
                    start_minutes = start_h * 60 + start_m
                    duration_minutes = int(rec.surgery_duration_hours * 60)
                    end_minutes = start_minutes + duration_minutes

                    end_h = (end_minutes // 60) % 24
                    end_m = end_minutes % 60
                    rec.surgery_end_time = '%02d:%02d' % (end_h, end_m)
                except (ValueError, AttributeError):
                    rec.surgery_end_time = False
            else:
                rec.surgery_end_time = False

    @api.depends('consent_status', 'hospital_fee_paid', 'honorarium_paid',
                 'surgery_date', 'is_reimbursed_surgery')
    def _compute_surgery_at_risk(self):
        """
        7.2 + 7.3 — Flag surgery as "at risk" when IC or payment deadline
        is breached within the escalation window.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        secretary_days = int(ICP.get_param('clinic.ic_secretary_escalation_weeks', 14))
        payment_secretary_days = int(ICP.get_param('clinic.payment_secretary_alert_days', 7))
        honorarium_secretary_days = int(ICP.get_param('clinic.honorarium_secretary_alert_days', 7))
        today = fields.Date.today()

        for rec in self:
            reasons = []
            if rec.surgery_date:
                surgery_day = rec.surgery_date
                days_to_surgery = (surgery_day - today).days

                # IC at risk: unsigned AND within secretary escalation window
                if rec.consent_status in ('none', 'sent', 'overdue'):
                    if days_to_surgery <= secretary_days:
                        reasons.append('IC unsigned')

                # Payment at risk: hospital fee unpaid AND within payment alert window
                if not rec.hospital_fee_paid and rec.hospital_fee > 0 and not rec.is_reimbursed_surgery:
                    if days_to_surgery <= payment_secretary_days:
                        reasons.append('Hospital fee unpaid')

                # Honorarium at risk
                if not rec.honorarium_paid and rec.doctor_fee > 0 and not rec.is_reimbursed_surgery:
                    if days_to_surgery <= honorarium_secretary_days:
                        reasons.append('BV Fee unpaid')

            rec.surgery_at_risk = bool(reasons)
            rec.surgery_at_risk_reason = ', '.join(reasons) if reasons else False

    def _compute_task_count(self):
        for rec in self:
            rec.task_count = len(rec.task_ids)

    @api.depends('invoice_ids')
    def _compute_invoice_count(self):
        for rec in self:
            rec.invoice_count = len(rec.invoice_ids)

    @api.depends('surgery_date', 'procedure_id', 'procedure_id.consent_deadline_days')
    def _compute_consent_deadline(self):
        for rec in self:
            if rec.surgery_date:
                days = rec.procedure_id.consent_deadline_days if rec.procedure_id else 14
                rec.consent_deadline = rec.surgery_date - timedelta(days=days)
            else:
                rec.consent_deadline = False

    def _send_surgery_confirmation_sms(self):
        """Send the confirmation text message to the patient, alongside the
        confirmation email, at the moment the surgery is confirmed only."""
        self.ensure_one()
        number = self.patient_id.phone if self.patient_id else False
        if not number:
            self.message_post(
                body=_('Surgery confirmed, but no confirmation SMS was sent '
                       '— patient has no phone number on file.')
            )
            return

        sms = self.env['sms.sms'].create({
            'number': number,
            'body': self._render_sms_body('surgery_confirmed'),
            'partner_id': self.patient_id.id,
        })
        sms.send()
        self.message_post(
            body=_('Confirmation SMS sent to patient (%s).') % number)

    def _render_sms_body(self, template_key, **kwargs):
        """Central SMS body renderer. Plain text only (no HTML), kept short
        on purpose to fit SMS length conventions."""
        self.ensure_one()
        patient_name = self.patient_id.name if self.patient_id else 'Patient'
        doctor_name = self.surgeon_id.name if self.surgeon_id else 'the medical team'
        procedure_name = self.procedure_id.name if self.procedure_id else ''
        surgery_dt = (self.surgery_date.strftime('%d %B %Y')
                      if self.surgery_date else 'a date to be confirmed')
        if self.surgery_date and self.admission_time:
            surgery_dt += ' (admission at %s)' % self.admission_time

        bodies = {
            'surgery_confirmed': _(
                'Dear %(patient)s, your surgery (%(procedure)s) with '
                '%(doctor)s is confirmed for %(date)s. Please check your '
                'email for full details.'
            ) % {
                                     'patient': patient_name,
                                     'procedure': procedure_name,
                                     'doctor': doctor_name,
                                     'date': surgery_dt,
                                 },
        }
        return bodies.get(template_key, '')

    # ═══════════════════════════ ACTIONS ═══════════════════════════════════

    def action_reset_to_draft(self):
        """Reset cancelled record(s) back to draft state."""
        self.write({'state': 'draft', 'tasks_generated': False})
        self.message_post(body=_('Record reset to draft.'))

    def action_mark_surgery_completed(self):
        """Move the case to Surgery Completed state."""
        self.ensure_one()
        self.state = 'surgery_completed'
        self.message_post(body=_('Surgery marked as completed.'))

    def action_confirm(self):
        """Move the case from Draft to Confirmed once core details are set."""
        self.ensure_one()
        if not self.patient_id:
            raise UserError(_('Please select a patient before confirming.'))
        if not self.procedure_id:
            raise UserError(_('Please select a procedure before confirming.'))
        if not self.surgeon_id:
            raise UserError(_('Please assign a doctor before confirming.'))
        if not self.surgery_date:
            raise UserError(_('Please set a surgery date before confirming.'))

        self.state = 'confirmed'
        self.message_post(body=_('Surgery case confirmed.'))
        self._send_surgery_confirmation_email()
        self._send_surgery_confirmation_sms()

    def action_confirm_physical_consent(self):
        """Confirm that the physically signed, scanned consent(s) have been
        uploaded. Validates that one scanned file was uploaded per required
        consent template, then auto-signs the PATIENT's pending item(s) on
        every open sign.request on this case through Sign's real completion
        pipeline (same mechanism already used for the doctor's digital
        auto-sign) so each patient item moves from unsigned to signed.
        The doctor's item is never touched here -- it's either already
        auto-signed at send time, or must be completed via
        action_doctor_sign_now.

        patient_consent_signed / doctor_consent_signed are deliberately NOT
        set directly here -- they are only ever set by
        SignRequestItemExtension.write() when a sign.request.item's state
        genuinely becomes 'completed'. This guarantees the case's displayed
        consent status can never say "signed" while the underlying
        sign.request is still actually pending."""
        self.ensure_one()

        required_count = len(self.procedure_sign_template_ids)
        uploaded_count = len(self.physical_consent_attachment_ids)

        if not uploaded_count:
            raise UserError(_('Please upload the scanned signed consent document(s) first.'))
        if required_count and uploaded_count != required_count:
            raise UserError(_(
                'This procedure requires exactly %(required)d signed consent '
                'document(s), but %(uploaded)d file(s) have been uploaded. '
                'Please upload exactly one scanned file per consent document '
                'before confirming.'
            ) % {'required': required_count, 'uploaded': uploaded_count})

        failed_items = []
        signed_count = 0
        patient_partner = self.patient_id
        for sign_request in self.sign_request_ids.filtered(lambda r: r.state != 'signed'):
            pending_items = sign_request.request_item_ids.filtered(
                lambda i: i.state != 'completed' and i.partner_id == patient_partner
            )
            for item in pending_items:
                try:
                    item.sudo().write({
                        'state': 'completed',
                        'signing_date': fields.Date.context_today(self),
                    })
                    signed_count += 1
                except Exception as e:
                    failed_items.append(_(
                        '"%(partner)s" on "%(tmpl)s": %(reason)s'
                    ) % {
                                            'partner': item.partner_id.name,
                                            'tmpl': sign_request.reference,
                                            'reason': str(e),
                                        })
                    self.message_post(
                        body=_(
                            'Could not auto-complete "%(partner)s" on "%(tmpl)s" from the '
                            'physical consent upload: %(reason)s'
                        ) % {
                                 'partner': item.partner_id.name,
                                 'tmpl': sign_request.reference,
                                 'reason': str(e),
                             }
                    )
            # If every item on this request is now completed, move the
            # request itself to 'signed' so consent_status picks it up.
            if all(i.state == 'completed' for i in sign_request.request_item_ids):
                sign_request.sudo().write({'state': 'signed'})

        # NOTE: patient_consent_signed / doctor_consent_signed are NOT set
        # here directly. They're only ever set by
        # SignRequestItemExtension.write() (sign_request.py) when a
        # sign.request.item's state genuinely becomes 'completed'. That
        # keeps the surgery case's displayed consent status permanently in
        # sync with the real state of the underlying sign.request(s) --
        # if a physical-sign attempt above failed, the case will correctly
        # keep showing that signature as pending instead of lying about it.
        self.is_physical_consent = True
        # self.consent_required = True

        filenames = ', '.join(self.physical_consent_attachment_ids.mapped('name'))
        self.message_post(
            body=_('Physical consent confirmed — %(count)d scanned signed document(s) uploaded (%(files)s), '
                   '%(signed)d sign request item(s) auto-completed.') % {
                     'count': uploaded_count,
                     'files': filenames or _('unnamed file(s)'),
                     'signed': signed_count,
                 }
        )

        # Intentionally NOT raised as an error: doing so would roll back
        # this entire transaction, including the item(s) that WERE
        # successfully signed above. Instead, surface it as a non-blocking
        # notification -- the per-item failure is already on the chatter,
        # consent_status will correctly stay off 'signed' until the
        # remaining item(s) are completed, and the user can retry by
        # clicking "Confirm Physical Signature" again once fixed.
        if failed_items:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Some items still need attention'),
                    'message': _(
                        '%(signed)d item(s) signed successfully, but %(count)d could not be '
                        'auto-completed:\n%(details)s'
                    ) % {
                                   'signed': signed_count,
                                   'count': len(failed_items),
                                   'details': '\n'.join(failed_items),
                               },
                    'type': 'warning',
                    'sticky': True,
                },
            }

    def _physically_sign_item(self, item):
        """Complete a sign.request.item using placeholder values, for a
        consent document that was signed on paper and re-uploaded as a
        scan. Uses the exact same completion pipeline as
        _auto_sign_doctor_item (sign.request.item.sign()), so the item, and
        eventually the whole sign.request, moves through Sign's real state
        machine rather than having its state written directly.

        The placeholder signature image below is NOT the legal evidence —
        the scanned document in physical_consent_attachment_ids is. This
        placeholder only exists to satisfy Sign's "required fields must be
        filled" check on the digital template."""
        self.ensure_one()
        role_items = item.sign_request_id.template_id.sign_item_ids.filtered(
            lambda si: si.responsible_id == item.role_id
        )

        values = {}
        for si in role_items:
            item_type = si.type_id.item_type
            key = str(si.id)
            if item_type in ('signature', 'initial'):
                values[key] = 'data:image/png;base64,%s' % PHYSICAL_CONSENT_PLACEHOLDER_PNG
            elif item_type == 'text' and si.required:
                values[key] = _('Signed on paper — scanned copy on file')
            elif item_type == 'date' and si.required:
                values[key] = fields.Date.context_today(self).strftime('%m/%d/%Y')
            elif item_type == 'checkbox' and si.required:
                values[key] = True
            elif item_type == 'stamp' and si.required:
                values[key] = item._get_stamp_value()

        item.sudo().sign(values)

    def _send_surgery_confirmation_email(self):
        """Send the confirmation email to the patient using the mail template."""
        self.ensure_one()
        if not self.patient_id or not self.patient_id.email:
            self.message_post(
                body=_('Surgery confirmed, but no confirmation email was sent '
                       '— patient has no email address on file.')
            )
            return

        mail = self.env['mail.mail'].create({
            'subject': _('Surgery Confirmed – %s') % self.name,
            'email_to': self.patient_id.email,
            'email_from': self.surgeon_id.email or self.env.user.email,
            'body_html': self._render_email_body('surgery_confirmed'),
        })
        mail.send()
        self.message_post(
            body=_('Confirmation email sent to patient.'))

    def action_reschedule(self):
        """Enter reschedule mode: remember current state, let user edit
        surgery date/slot, then Submit moves it back to that state."""
        self.ensure_one()
        if self.state not in ('planned', 'in_progress'):
            raise UserError(_('Reschedule is only available from Planned or In Progress.'))

        self.state_before_reschedule = self.state
        self.state = 'reschedule'
        self.message_post(body=_('Surgery case moved to Reschedule — please update the date/time slot.'))

    def action_submit_reschedule(self):
        """Confirm the new date/slot and return to the previous state."""
        self.ensure_one()
        if self.state != 'reschedule':
            raise UserError(_('This action is only available while rescheduling.'))
        if not self.surgery_date:
            raise UserError(_('Please set a new surgery date before submitting.'))
        if not self.surgery_time_slot:
            raise UserError(_('Please select a new surgery time slot before submitting.'))

        previous_state = self.state_before_reschedule or 'planned'
        self.state = previous_state
        self.state_before_reschedule = False
        self.message_post(
            body=_('Surgery rescheduled to %(date)s at %(time)s.') % {
                'date': self.surgery_date.strftime('%d/%m/%Y'),
                'time': self.surgery_time_slot_display or self.surgery_time_slot,
            }
        )



    def action_get_available_dates(self):
        """
        Open a wizard with the available operating dates and timeslots.
        """
        self.ensure_one()
        if not self.surgeon_id:
            raise UserError(_('Please select a doctor first.'))

        wizard = self.env['clinic.surgery.date.wizard'].create({
            'case_id': self.id,
        })
        wizard._populate_lines()
        if not wizard.line_ids:
            raise UserError(_('No operating dates configured for this doctor.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Select Surgery Date'),
            'res_model': 'clinic.surgery.date.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }

    def action_send_brochure(self):
        """Send the procedure's information brochure(s) to the patient by email."""
        self.ensure_one()

        if not self.patient_id or not self.patient_id.email:
            raise UserError(_('Patient must have a valid email address.'))
        if not self.procedure_id:
            raise UserError(_('Please select a procedure first.'))
        if not self.procedure_id.info_brochures:
            raise UserError(_('No information brochure(s) attached to this procedure.'))

        mail = self.env['mail.mail'].create({
            'subject': _('Information Brochure – %s') % self.procedure_id.name,
            'email_to': self.patient_id.email,
            'body_html': self._render_email_body('brochure'),
            'attachment_ids': [(6, 0, (self.procedure_id.info_brochures | self.procedure_id.postop_brochure_ids).mapped(
                'attachment_id').ids)],
        })
        mail.send()
        self.info_brochure_sent = True

    def action_generate_tasks(self):
        """7.1 — Generate tasks from procedure template."""
        self.ensure_one()
        if not self.procedure_id:
            raise UserError(_('Please select a procedure before generating tasks.'))
        if not self.surgery_date:
            raise UserError(_('Please set a surgery date before generating tasks.'))

        project = self._get_or_create_surgery_project()
        created = 0

        for tmpl in self.procedure_id.task_ids:
            deadline = self._compute_task_deadline(tmpl.deadline_days_before)
            user = self._resolve_responsible(tmpl.responsible)
            self.env['project.task'].create({
                'name': tmpl.name,
                'project_id': project.id,
                'surgery_case_id': self.id,
                'user_ids': [(4, user.id)] if user else [],
                'date_deadline': deadline,
                'description': tmpl.description
                               or f'Auto-generated from procedure: {self.procedure_id.name}',
                'tag_ids': self._get_task_tags(tmpl.responsible),
                'partner_id': self.patient_id.id if self.patient_id else False,
            })
            created += 1

        # 7.4 — Generate post-op consult schedule
        self._generate_postop_consults()

        self.tasks_generated = True
        self.state = 'planned'
        self.message_post(
            body=_(f'{created} tasks generated from procedure template.'))

    def action_cancel(self):
        """
        7.1 — Cancellation handler:
        - Closes all open tasks
        - Logs cancellation policy message in chatter
        """
        self.ensure_one()
        if self.state == 'cancelled':
            return

        # Close all open tasks
        open_tasks = self.task_ids.filtered(
            lambda t: t.stage_id.name not in ('Done', 'Cancelled')
        )
        cancelled_stage = self._get_or_create_cancelled_stage()
        open_tasks.write({'stage_id': cancelled_stage.id})

        self.state = 'cancelled'
        self.message_post(
            body=_(
                '<b>Surgery Cancelled</b><br/>'
                f'{len(open_tasks)} open task(s) have been closed.<br/>'
                '<i>Note: Per the general terms, the Fee for pre/post-operative '
                'care is retained.</i>'
            )
        )

    def action_generate_postop_tasks(self):
        """
        Button: Post Generate Task
        Creates one project.task per record in postop_consult_ids,
        using the consult's label and planned_date. Skips consults
        that already have a matching task (safe to click more than once).
        """
        self.ensure_one()

        if self.state != 'surgery_completed':
            raise UserError(_(
                'Post-op tasks can only be generated after the surgery '
                'is marked as completed.'
            ))

        if not self.postop_consult_ids:
            raise UserError(_(
                'There are no post-op consults on this case to generate tasks from.'
            ))

        project = self._get_or_create_surgery_project()
        created = 0
        skipped = 0

        for consult in self.postop_consult_ids:

            responsible = self._resolve_responsible(consult.responsible_id)
            task_name = _('Post-op Consult: %(label)s') % {
                'label': consult.label,
            }

            # Avoid duplicate tasks if the button is clicked more than once
            existing = self.task_ids.filtered(lambda t: t.name == task_name)
            if existing:
                skipped += 1
                continue

            deadline = consult.planned_date if consult.planned_date else False

            description_parts = [f'<p><b>Post-operative consult:</b> {consult.label}</p>', ]
            if consult.planned_date:
                description_parts.append(f'<p>Planned date: <b>{consult.planned_date.strftime("%d/%m/%Y")}</b></p>')
            if consult.source_procedure_id:
                description_parts.append(f'<p>Related procedure: {consult.source_procedure_id.name}</p>')
            if consult.notes:
                description_parts.append(f'<p>{consult.notes}</p>')

            self.env['project.task'].create({
                'name': task_name,
                'project_id': project.id,
                'surgery_case_id': self.id,
                'user_ids': [(4, responsible.id)] if responsible else [],
                'date_deadline': deadline,
                'description': ''.join(description_parts),
                'tag_ids': self._get_task_tags('postop'),
                'partner_id': self.patient_id.id if self.patient_id else False,
            })
            created += 1

        if created:
            self.message_post(
                body=_('%(created)d post-op task(s) generated from %(total)d consult(s).%(skipped)s') % {
                    'created': created,
                    'total': len(self.postop_consult_ids),
                    'skipped': _(' (%d already existed)') % skipped if skipped else '',
                }
            )
        else:
            self.message_post(
                body=_('No new post-op tasks created — all %d consult(s) already had tasks.') % skipped
            )

        self.state = 'post_follow_ups'

    def action_send_consent(self):
        """Send IC consent documents to patient and doctor via Odoo Sign.
        The doctor's portion is completed automatically at send time using
        their saved profile signature — only the patient needs to sign."""
        self.ensure_one()
        if not self.patient_id or not self.patient_id.email:
            raise UserError(_('Patient must have a valid email address.'))
        if not self.surgeon_id or not self.surgeon_id.partner_id.email:
            raise UserError(_('Doctor must have a valid email address.'))
        if not self.procedure_id.sign_template_ids:
            raise UserError(_('No consent templates configured for this procedure.'))
        if not self.surgeon_id.sudo().sign_signature:
            raise UserError(_(
                'Dr. %s has no saved signature. Ask them to save one under '
                'My Profile > Preferences before consent forms can be auto-signed.'
            ) % self.surgeon_id.name)

        auto_signed_count = 0
        skipped_templates = []

        for tmpl in self.procedure_id.sign_template_ids:
            roles = tmpl.sign_item_ids.mapped('responsible_id')
            if not roles:
                raise UserError(_(
                    'Template "%s" has no signature roles configured.'
                ) % tmpl.name)
            if len(roles) < 2:
                raise UserError(_(
                    'Template "%s" must have 2 signature roles '
                    '(one for Patient, one for Doctor).'
                ) % tmpl.name)

            patient_role = roles[0]
            doctor_role = roles[1]

            sign_request = self.env['sign.request'].create({
                'template_id': tmpl.id,
                'reference': f'{self.name} – {tmpl.name}',
                'subject': f'Signature Request – {self.name} – {tmpl.name}',
                'surgery_case_id': self.id,
                'request_item_ids': [
                    (0, 0, {
                        'partner_id': self.patient_id.id,
                        'role_id': patient_role.id,
                    }),
                    (0, 0, {
                        'partner_id': self.surgeon_id.partner_id.id,
                        'role_id': doctor_role.id,
                    }),
                ],
            })

            try:
                self._auto_sign_doctor_item(sign_request, doctor_role)
                auto_signed_count += 1
            except UserError as e:
                skipped_templates.append(tmpl.name)
                sign_request.message_post(
                    body=_(
                        'Doctor auto-sign skipped for "%(tmpl)s": %(reason)s '
                        'Use the "Doctor: Sign Now" button on the case instead.'
                    ) % {'tmpl': tmpl.name, 'reason': str(e)}
                )

        self.consent_required = True
        body = _('Consent document(s) sent to %s.') % self.patient_id.name
        if auto_signed_count:
            body += _(' Dr. %(doctor)s\'s signature was applied automatically on %(count)d document(s).') % {
                'doctor': self.surgeon_id.name, 'count': auto_signed_count,
            }
        if skipped_templates:
            body += _(' Doctor signature still pending for: %s.') % ', '.join(skipped_templates)
        self.message_post(body=body)

    def _auto_sign_doctor_item(self, sign_request, doctor_role):
        """Complete the doctor's sign.request.item immediately, using their
        saved profile signature, so only the patient needs to sign.
        Uses the real Sign completion pipeline (sign.request.item.sign())
        so the signature is properly stamped onto the PDF and hashed —
        not just a status flag flip. Raises UserError if it can't safely
        complete (caller falls back to the manual Sign Now button)."""
        self.ensure_one()
        doctor_partner = self.surgeon_id.partner_id
        doctor_item = sign_request.request_item_ids.filtered(
            lambda i: i.role_id == doctor_role and i.partner_id == doctor_partner
        )
        if not doctor_item:
            raise UserError(_('No doctor request item found on this sign request.'))
        doctor_item.ensure_one()

        signature_b64 = self.surgeon_id.sudo().sign_signature
        if not signature_b64:
            raise UserError(_('Doctor has no saved signature on their user profile.'))
        if isinstance(signature_b64, bytes):
            signature_b64 = signature_b64.decode()

        role_items = sign_request.template_id.sign_item_ids.filtered(
            lambda si: si.responsible_id == doctor_role
        )

        values = {}
        for item in role_items:
            item_type = item.type_id.item_type
            key = str(item.id)
            if item_type in ('signature', 'initial'):
                values[key] = 'data:image/png;base64,%s' % signature_b64
            elif item_type == 'text' and item.required:
                values[key] = self.surgeon_id.name
            elif item_type == 'date' and item.required:
                values[key] = fields.Date.context_today(self).strftime('%m/%d/%Y')
            elif item_type == 'checkbox' and item.required:
                values[key] = True
            elif item_type == 'stamp' and item.required:
                values[key] = doctor_item._get_stamp_value()
            # any other required, unhandled item type is intentionally left
            # unfilled -- sign() will raise a clear "required items not
            # filled" error rather than silently completing an incomplete
            # document.

        doctor_item.sudo().sign(values)

    def action_doctor_sign_now(self):
        """Open the doctor's outstanding consent request directly. The
        signature field is pre-filled from the doctor's saved profile
        signature (Sign > My Profile), so this is effectively a 1-click sign:
        open -> Validate & Send. Nothing is auto-completed server-side --
        the doctor still performs the actual signing action, which is what
        keeps the signature legally valid."""
        self.ensure_one()
        if not self.surgeon_id:
            raise UserError(_('No doctor set on this case.'))
        doctor_partner = self.surgeon_id.partner_id
        pending_request = self.sign_request_ids.filtered(
            lambda r: r.request_item_ids.filtered(
                lambda i: i.partner_id == doctor_partner and i.state != 'completed'
            )
        )[:1]
        if not pending_request:
            raise UserError(_('No pending consent signature for the doctor on this case.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sign.request',
            'res_id': pending_request.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {'dialog_size': 'extra-large'},
        }

    def action_view_tasks(self):
        self.ensure_one()

        action = self.env["ir.actions.actions"]._for_xml_id("project.action_view_all_task")

        action["domain"] = [
            ("surgery_case_id", "=", self.id)
        ]

        context = dict(self.env.context)
        context.update({
            "default_surgery_case_id": self.id,
        })
        action["context"] = context

        return action

    def action_view_consents(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Consent Documents'),
            'res_model': 'sign.request',
            'view_mode': 'list,form',
            'domain': [('surgery_case_id', '=', self.id)],
        }

    def action_view_invoices(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoices'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.invoice_ids.ids)],
        }

    # ═══════════════════════════ SCHEDULED ACTIONS (CRON) ══════════════════

    @api.model
    def cron_surgery_automation_daily(self):
        """
        Master daily cron — runs all automation checks:
          7.2 IC reminder engine
          7.3 Payment guards
          7.6 D-1 instruction email
          7.7 Review request
        """
        ICP = self.env['ir.config_parameter'].sudo()

        # Read all thresholds from settings
        ic_patient_days = int(ICP.get_param('clinic.ic_patient_reminder_weeks', 21))
        ic_secretary_days = int(ICP.get_param('clinic.ic_secretary_escalation_weeks', 14))
        pay_patient_days = int(ICP.get_param('clinic.payment_patient_reminder_days', 10))
        pay_secretary_days = int(ICP.get_param('clinic.payment_secretary_alert_days', 7))
        hon_patient_days = int(ICP.get_param('clinic.honorarium_patient_reminder_days', 10))
        hon_secretary_days = int(ICP.get_param('clinic.honorarium_secretary_alert_days', 7))
        preop_days = int(ICP.get_param('clinic.preop_instruction_days_before', 1))
        review_days = int(ICP.get_param('clinic.review_request_days_after', 42))

        today = fields.Date.today()

        # Only process planned/in_progress cases with a future surgery date
        active_cases = self.sudo().search([
            ('state', 'in', ('planned', 'in_progress')),
            ('surgery_date', '!=', False),
        ])

        for case in active_cases:
            surgery_day = case.surgery_date
            days_to = (surgery_day - today).days  # positive = future
            days_since = (today - surgery_day).days  # positive = past

            # ── 7.2 IC Reminder ──────────────────────────────────────────
            if case.consent_status not in ('signed'):
                # Patient reminder at D-Xw
                if days_to == ic_patient_days and not case.patient_consent_signed:
                    case._send_ic_patient_reminder()
                if days_to == ic_secretary_days and not case.patient_consent_signed:
                    case._create_ic_secretary_task()

            # ── 7.3 Payment Guards — Hospital Fee ────────────────────────
            if not case.hospital_fee_paid and case.hospital_fee > 0:
                if days_to == pay_patient_days:
                    case._send_payment_reminder('hospital')
                if days_to == pay_secretary_days:
                    case._create_payment_secretary_task('hospital')

            # ── 7.3 Payment Guards — Honorarium ──────────────────────────
            if not case.honorarium_paid and case.doctor_fee > 0:
                if days_to == hon_patient_days:
                    case._send_payment_reminder('honorarium')
                if days_to == hon_secretary_days:
                    if case.invoice_payment_state not in ('in_payment', 'paid'):
                        case._create_payment_secretary_task('honorarium')

            # ── 7.6 D-1 Pre-op Instruction Email ─────────────────────────
            if days_to == preop_days and not case.preop_email_sent:
                case._send_preop_instructions()

        # ── 7.7 Review Request (post-surgery, opt-in) ────────────────────
        post_cases = self.search([
            ('state', '=', 'done'),
            ('send_review_request', '=', True),
            ('review_request_sent', '=', False),
            ('surgery_date', '!=', False),
        ])
        for case in post_cases:
            surgery_day = case.surgery_date.date()
            days_since = (today - surgery_day).days
            if days_since >= review_days:
                case._send_review_request()

    # ═══════════════════════════ NOTIFICATION HELPERS ══════════════════════

    def _send_ic_patient_reminder(self):
        """7.2 — Automated IC reminder email to patient."""
        self.ensure_one()
        if not self.patient_id or not self.patient_id.email:
            return
        ICP = self.env['ir.config_parameter'].sudo()
        days = int(ICP.get_param('clinic.ic_patient_reminder_weeks', 3))
        mail = self.env['mail.mail'].create({
            'subject': f'Sign consent documents – {self.name}',
            'email_to': self.patient_id.email,
            'body_html': self._render_email_body('ic_reminder', days=days),
        })
        mail.send()
        self.message_post(
            body=_(f'IC reminder sent to patient ({self.patient_id.email}). '
                   f'Surgery in {days}  day(s).')
        )

    def _create_ic_secretary_task(self):
        """7.2 — Create escalation task for secretary when IC is still unsigned."""
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        days = int(ICP.get_param('clinic.ic_secretary_escalation_weeks', 14))
        project = self._get_or_create_surgery_project()
        task_name = f'IC unsigned — {self.name}'
        # Avoid duplicate escalation tasks
        existing = self.task_ids.filtered(lambda t: task_name in t.name)
        if existing:
            return
        user = self.secretary_id or self.surgeon_id
        self.env['project.task'].create({
            'name': task_name,
            'project_id': project.id,
            'surgery_case_id': self.id,
            'user_ids': [(4, user.id)] if user else [],
            'date_deadline': fields.Date.today(),
            'description': (
                f'<p><b>IC Escalation – {days} day(s) before surgery (threshold reached)</b></p>'
                f'<p>Patient <b>{self.patient_id.name}</b> has not yet signed the consent '
                f'documents for <b>{self.name}</b>.</p>'
                f'<ul>'
                f'<li>Procedure: <b>{self.procedure_id.name if self.procedure_id else "N/A"}</b></li>'
                f'<li>Doctor: <b>{self.surgeon_id.name if self.surgeon_id else "N/A"}</b></li>'
                f'<li>Surgery date: <b>{self.surgery_date.strftime("%d/%m/%Y") if self.surgery_date else "TBC"}</b></li>'
                f'<li>Consent deadline: <b>{self.consent_deadline.strftime("%d/%m/%Y") if self.consent_deadline else "N/A"}</b></li>'
                f'<li>Consent status: <b>{dict(self._fields["consent_status"].selection).get(self.consent_status, self.consent_status)}</b></li>'
                f'<li>Patient phone: <b>{self.patient_id.phone or "N/A"}</b></li>'
                f'<li>Patient email: <b>{self.patient_id.email or "N/A"}</b></li>'
                f'</ul>'
                f'<p>Please follow up with the patient immediately to complete signing.</p>'
            ),
            'tag_ids': self._get_task_tags('secretary'),
        })
        self.message_post(
            body=_(f'IC escalation task created for secretary. {days} day(s) to surgery.')
        )

    def _send_payment_reminder(self, payment_type):
        """7.3 — Automated payment reminder email to patient."""
        self.ensure_one()
        if not self.patient_id or not self.patient_id.email:
            return
        ICP = self.env['ir.config_parameter'].sudo()
        if payment_type == 'hospital':
            days = int(ICP.get_param('clinic.payment_patient_reminder_days', 10))
            subject = f'Payment Reminder: Hospital Fee – {self.name}'
        else:
            days = int(ICP.get_param('clinic.honorarium_patient_reminder_days', 10))
            subject = f'Payment Reminder: Medical Fee – {self.name}'

        mail = self.env['mail.mail'].create({
            'subject': subject,
            'email_to': self.patient_id.email,
            'body_html': self._render_email_body(
                'payment_reminder', payment_type=payment_type, days=days),
        })
        mail.send()
        self.message_post(
            body=_(f'{payment_type.capitalize()} payment reminder sent to patient. '
                   f'Surgery in {days} day(s).')
        )

    def _create_payment_secretary_task(self, payment_type):
        """7.3 — Create alert task for secretary when payment is overdue."""
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        if payment_type == 'hospital':
            days = int(ICP.get_param('clinic.payment_secretary_alert_days', 7))
            label = 'Hospital Fee'
        else:
            days = int(ICP.get_param('clinic.honorarium_secretary_alert_days', 7))
            label = 'BV Fee'

        project = self._get_or_create_surgery_project()
        task_name = f'UNPAID: {label} — {self.name}'
        existing = self.task_ids.filtered(lambda t: task_name in t.name)
        if existing:
            return
        user = self.secretary_id or self.surgeon_id
        fee_amount = self.hospital_fee if payment_type == 'hospital' else self.doctor_fee
        due_date = self.hospital_fee_due_date if payment_type == 'hospital' else self.surgery_date
        self.env['project.task'].create({
            'name': task_name,
            'project_id': project.id,
            'surgery_case_id': self.id,
            'user_ids': [(4, user.id)] if user else [],
            'date_deadline': fields.Date.today(),
            'description': (
                f'<p><b>{label} Unpaid – {days} day(s) before surgery (threshold reached)</b></p>'
                f'<p>Patient <b>{self.patient_id.name}</b> has not paid the {label} '
                f'for <b>{self.name}</b>.</p>'
                f'<ul>'
                f'<li>Amount due: <b>€{fee_amount:.2f}</b></li>'
                f'<li>Procedure: <b>{self.procedure_id.name if self.procedure_id else "N/A"}</b></li>'
                f'<li>Doctor: <b>{self.surgeon_id.name if self.surgeon_id else "N/A"}</b></li>'
                f'<li>Surgery date: <b>{self.surgery_date.strftime("%d/%m/%Y") if self.surgery_date else "TBC"}</b></li>'
                f'<li>Payment due date: <b>{due_date.strftime("%d/%m/%Y") if due_date else "N/A"}</b></li>'
                f'<li>Payment method: <b>{dict(self._fields["honorarium_payment_method"].selection).get(self.honorarium_payment_method, "Not set")}</b></li>'
                f'<li>Patient phone: <b>{self.patient_id.phone or "N/A"}</b></li>'
                f'<li>Patient email: <b>{self.patient_id.email or "N/A"}</b></li>'
                f'</ul>'
                f'<p>Please contact the patient immediately to arrange payment.</p>'
            ),
            'tag_ids': self._get_task_tags('secretary'),
        })
        self.message_post(
            body=_(f'{label} secretary alert task created. {days} day(s) to surgery.')
        )

    def _send_preop_instructions(self):
        """7.6 — D-1 pre-operative instruction email."""
        self.ensure_one()
        if not self.patient_id or not self.patient_id.email:
            return
        mail = self.env['mail.mail'].create({
            'subject': f'Your Surgery Tomorrow – Important Instructions | {self.name}',
            'email_to': self.patient_id.email,
            'body_html': self._render_email_body('preop_instructions'),
        })
        mail.send()
        self.preop_email_sent = True
        self.message_post(
            body=_('Pre-operative instruction email sent to patient (D-1).')
        )

    def _send_review_request(self):
        """7.7 — Post-op review request email (opt-in)."""
        self.ensure_one()
        if not self.patient_id or not self.patient_id.email:
            return
        ICP = self.env['ir.config_parameter'].sudo()
        review_url = ICP.get_param('clinic.google_review_url', '#')
        mail = self.env['mail.mail'].create({
            'subject': f'How was your experience? – {self.procedure_id.name if self.procedure_id else "Your Procedure"}',
            'email_to': self.review_request_email if self.review_request_email else self.patient_id.email,
            'body_html': self._render_email_body('review_request', review_url=review_url),
        })
        mail.send()
        self.review_request_sent = True
        self.message_post(
            body=_('Review request email sent to patient.')
        )

    # ═══════════════════════════ EMAIL RENDERER ═════════════════════════════

    def _render_email_body(self, template_key, **kwargs):
        """
        Central email body renderer.
        All patient-facing emails are built here for easy customisation.
        """
        self.ensure_one()
        patient_name = self.patient_id.name if self.patient_id else 'Patient'
        doctor_name = self.surgeon_id.name if self.surgeon_id else 'The Medical Team'
        procedure_name = self.procedure_id.name if self.procedure_id else 'your procedure'
        surgery_dt = (self.surgery_date.strftime('%A %d %B %Y at %H:%M')
                      if self.surgery_date else 'TBC – you will be contacted')

        base_footer = (
            f'<br/><p>Kind regards,<br/><b>{doctor_name}</b></p>'
            f'<p style="font-size:11px;color:#888;">If you have any questions, '
            f'please do not hesitate to contact our practice.</p>'
        )

        bodies = {
            'surgery_confirmed': (
                    f'<div style="font-family: Arial, sans-serif; font-size: 14px; color: #333;">'
                    f'<p>Dear {patient_name},</p>'
                    f'<p>We are pleased to confirm your upcoming surgery.</p>'
                    f'<table style="border-collapse: collapse; width: 100%; max-width: 500px;">'
                    f'<tr>'
                    f'<td style="padding: 4px 8px;"><b>Surgery:</b></td>'
                    f'<td style="padding: 4px 8px;">{procedure_name}</td>'
                    f'</tr>'
                    f'<tr>'
                    f'<td style="padding: 4px 8px;"><b>Doctor:</b></td>'
                    f'<td style="padding: 4px 8px;">{doctor_name}</td>'
                    f'</tr>'
                    f'<tr>'
                    f'<td style="padding: 4px 8px;"><b>Date &amp; Time:</b></td>'
                    f'<td style="padding: 4px 8px;">'
                    f'{self.surgery_date.strftime("%d %B %Y") if self.surgery_date else "TBC"}'
                    + (f' at {self.surgery_time_slot}' if self.surgery_time_slot else '')
                    + f'</td>'
                      f'</tr>'
                      f'<tr>'
                      f'<td style="padding: 4px 8px;"><b>Location:</b></td>'
                      f'<td style="padding: 4px 8px;">{self.hospital_location_id.name if self.hospital_location_id else "TBC"}</td>'
                      f'</tr>'
                      f'</table>'
                      f'<p>If any of the details above are incorrect, or if you have any questions, '
                      f'please contact us as soon as possible.</p>'
                      f'<p>Kind regards,<br/><b>{doctor_name}</b></p>'
                      f'<p style="font-size: 11px; color: #888;">'
                      f'If you have any questions, please do not hesitate to contact us.</p>'
                      f'</div>'
            ),

            'brochure': (
                    f'<p>Dear {patient_name},</p>'
                    f'<p>Please find attached the information brochure for your upcoming '
                    f'procedure: <b>{procedure_name}</b>.</p>'
                    f'<p>Please read this document carefully before your surgery.</p>'
                    + base_footer
            ),

            'ic_reminder': (
                    f'<p>Dear {patient_name},</p>'
                    f'<p>Your surgery (<b>{procedure_name}</b>) is scheduled for '
                    f'<b>{surgery_dt}</b>.</p>'
                    f'<p><b>Action required:</b> You have not yet signed your consent '
                    f'documents. Please sign them as soon as possible — your surgery '
                    f'cannot proceed without your signature.</p>'
                    f'<p>You should have received a signing link by email. '
                    f'If you cannot find it, please contact us.</p>'
                    + base_footer
            ),

            'payment_reminder': (
                    f'<p>Dear {patient_name},</p>'
                    f'<p>Your surgery (<b>{procedure_name}</b>) is scheduled for '
                    f'<b>{surgery_dt}</b>.</p>'
                    f'<p>Our records show that the '
                    f'{"hospital fee" if kwargs.get("payment_type") == "hospital" else "medical honorarium"} '
                    f'has not yet been received.</p>'
                    f'<p>Please arrange payment at your earliest convenience to ensure '
                    f'your surgery can proceed as planned.</p>'
                    f'<p>If you believe this is an error, please contact our practice directly.</p>'
                    + base_footer
            ),

            'preop_instructions': (
                    f'<p>Dear {patient_name},</p>'
                    f'<p>Your surgery (<b>{procedure_name}</b>) is scheduled for '
                    f'<b>{surgery_dt}</b>.</p>'
                    + (
                        # Use the procedure-specific instructions if the doctor filled them in,
                        # otherwise fall back to the old generic text unchanged.
                        self.procedure_id.preop_instruction_body
                    )
                    + base_footer
            ),

            'review_request': (
                    f'<p>Dear {patient_name},</p>'
                    f'<p>We hope you are recovering well following your '
                    f'<b>{procedure_name}</b>.</p>'
                    f'<p>If you are satisfied with your care, we would greatly appreciate '
                    f'it if you could take a moment to leave us a review:</p>'
                    f'<p style="text-align:center;">'
                    f'<a href="{kwargs.get("review_url", "#")}" '
                    f'style="background:#4285F4;color:white;padding:10px 20px;'
                    f'border-radius:5px;text-decoration:none;font-weight:bold;">'
                    f'Leave a Google Review</a></p>'
                    f'<p>Your feedback helps other patients find quality care.</p>'
                    + base_footer
            ),
        }
        return bodies.get(template_key, f'<p>Dear {patient_name},</p>' + base_footer)

    # ═══════════════════════════ POST-OP CONSULT GENERATOR ══════════════════

    # ═══════════════════════════ HELPERS ═══════════════════════════════════

    def _compute_task_deadline(self, deadline_days_before):
        """Return a date from surgery_date given a days_before value."""
        if not self.surgery_date:
            return None
        if deadline_days_before >= 0:
            return (self.surgery_date - timedelta(days=deadline_days_before))
        return (self.surgery_date + timedelta(days=abs(deadline_days_before)))

    def _get_or_create_surgery_project(self):
        Project = self.env['project.project']
        patient_name = self.patient_id.name if self.patient_id else 'Unknown Patient'
        project_name = f'Surgery – {patient_name} – {self.name}'
        project = Project.search([('name', '=', project_name)], limit=1)
        if not project:
            project = Project.create({
                'name': project_name,
                'partner_id': self.patient_id.id,
            })
        return project

    def _get_or_create_cancelled_stage(self):
        """Return (or create) a 'Cancelled' stage in the first available project."""
        Stage = self.env['project.task.type']
        stage = Stage.search([('name', '=', 'Cancelled')], limit=1)
        if not stage:
            stage = Stage.create({'name': 'Cancelled', 'sequence': 999})
        return stage

    def _resolve_responsible(self, responsible_code):
        if responsible_code == 'doctor':
            return self.surgeon_id
        if responsible_code == 'secretary':
            return self.secretary_id
        return self.env['res.users'].browse()

    def _get_task_tags(self, responsible_code):
        tag = self.env['project.tags'].search(
            [('name', '=', responsible_code)], limit=1)
        if not tag:
            tag = self.env['project.tags'].create({'name': responsible_code})
        return [(4, tag.id)]

    # ═══════════════════════════ DATE CHANGE HANDLER ═══════════════════════

    def write(self, vals):
        if vals.get('surgery_time_slot'):
            # Strip everything after a dash/en-dash — only keep the start time
            raw = vals['surgery_time_slot']
            for sep in (' – ', ' - ', '–', '-'):
                if sep in raw:
                    raw = raw.split(sep)[0].strip()
                    break
            vals['surgery_time_slot'] = raw
        if ('surgery_date' in vals or 'surgery_time_slot' in vals) and 'surgery_duration_hours' not in vals:
            for rec in self:
                procedure_id = vals.get('procedure_id', rec.procedure_id.id)
                procedure = self.env['clinic.surgery.procedure'].browse(
                    procedure_id) if procedure_id else rec.procedure_id
                current_duration = vals.get('surgery_duration_hours', rec.surgery_duration_hours)
                if procedure and not current_duration:
                    rec.surgery_duration_hours = procedure.surgery_duration_hours
        res = super().write(vals)
        if 'surgery_date' in vals:
            self._recalculate_task_deadlines()
            self._recalculate_postop_consults()
        return res

    def _recalculate_task_deadlines(self):
        """7.1 — Recalculate open task deadlines when surgery date changes."""
        for rec in self:
            if not rec.surgery_date:
                continue
            for task in rec.task_ids.filtered(
                    lambda t: t.stage_id.name not in ('Done', 'Cancelled')):
                tmpl = rec.procedure_id.task_ids.filtered(
                    lambda t: t.name == task.name)
                if tmpl:
                    task.date_deadline = rec._compute_task_deadline(
                        tmpl[0].deadline_days_before)

    def _recalculate_postop_consults(self):
        """7.1 + 7.4 — Recalculate post-op consult dates when surgery date changes."""
        for rec in self:
            if not rec.surgery_date:
                continue
            for consult in rec.postop_consult_ids:
                if consult.days_after_surgery is not False:
                    consult.planned_date = (rec.surgery_date + timedelta(days=consult.days_after_surgery))

    """

    G4 — Invoicing:
      hospital_fee is labelled "patient pays hospital" in your own code, which
      confirms it's settled directly between patient and hospital. So this
      invoice covers DOCTOR FEE ONLY. hospital_fee stays exactly as you have
      it — a tracked boolean guard (hospital_fee_paid), never invoiced here.

    G5 — adds the trigger button for post-op consult consolidation.
    """

    invoice_payment_state = fields.Selection([
        ('not_paid', 'Not Paid'),
        ('in_payment', 'In Payment'),
        ('paid', 'Paid'),
        ('partial', 'Partially Paid'),
        ('reversed', 'Reversed'),
    ], string='Invoice Payment Status', copy=False, compute='_compute_invoice_status', store=True)

    invoice_exists = fields.Boolean(
        compute='_compute_invoice_status', store=True,
        help='Technical field driving button visibility.')

    hospital_fee_due_date = fields.Date(
        string='Hospital Fee Due (D-7)',
        compute='_compute_hospital_fee_due_date', store=True,
        help='G4: the hospital part must be paid no later than 7 days before surgery.')

    honorarium_payment_method = fields.Selection([
        ('bank_transfer', 'Bank Transfer (structured reference)'),
        ('stripe_terminal', 'Stripe Terminal'),
        ('stripe_online', 'Stripe Online'),
    ], string='Fee Payment Method', tracking=True)

    extra_fee_enabled = fields.Boolean(
        string='Add Extra Fee', tracking=True,
        help='Enable to add an extra fee on top of the doctor fee. '
             'When enabled the amount is added to the doctor fee invoice.')
    extra_fee_description = fields.Char(
        string='Extra Fee Description', tracking=True)
    extra_fee_amount = fields.Float(
        string='Extra Fee Amount', tracking=True,
        help='Extra amount added to the doctor fee invoice')

    # ═══════════════════════════ COMPUTES ══════════════════════════════════

    @api.depends('invoice_ids', 'invoice_ids.payment_state', 'invoice_ids.state')
    def _compute_invoice_status(self):
        for rec in self:
            active = rec.invoice_ids.filtered(lambda m: m.state != 'cancel')
            rec.invoice_exists = bool(active)
            rec.invoice_payment_state = active[:1].payment_state if active else False
            if rec.invoice_payment_state in ('in_payment', 'paid'):
                rec.honorarium_paid = True

    @api.depends('surgery_date')
    def _compute_hospital_fee_due_date(self):
        for rec in self:
            rec.hospital_fee_due_date = (
                rec.surgery_date - timedelta(days=7) if rec.surgery_date else False
            )

    # ═══════════════════════════ INVOICE ACTIONS (G4) ═══════════════════════

    def action_receive_settlement(self):
        """Move the case to Done once post-op follow-ups are wrapped up."""
        self.ensure_one()
        if self.state != 'post_follow_ups':
            raise UserError(_('Only cases in "Post Follow-ups" can be marked as Done.'))
        if self.invoice_payment_state not in ('in_payment', 'paid'):
            raise UserError(_('Please make the payment of the invoice before proceeding.'))
        if not self.expected_settlement:
            raise UserError(_('Please complete the hospital expected settlement before proceeding.'))
        open_tasks = self.task_ids.filtered(lambda t: t.state not in ('1_done', '1_canceled'))
        if open_tasks:
            raise UserError(_('All tasks must be completed before marking this surgery case as Done.'))
        self.state = 'done'
        self.message_post(body=_('Surgery case marked as Done.'))

    def action_mark_done(self):
        """Move the case to Done once post-op follow-ups are wrapped up."""
        self.ensure_one()
        if self.state != 'post_follow_ups':
            raise UserError(_('Only cases in "Post Follow-ups" can be marked as Done.'))
        if not self.reimbursed_supplement_amount and not self.expected_settlement:
            raise UserError(
                _('Please complete the reimbursed supplement amount'))
        if self.invoice_payment_state not in ('in_payment', 'paid'):
            raise UserError(_('Please make the payment of the invoice before proceeding.'))
        open_tasks = self.task_ids.filtered(lambda t: t.state not in ('1_done', '1_canceled'))
        if open_tasks:
            raise UserError(_('All tasks must be completed before marking this surgery case as Done.'))
        self.state = 'done'
        self.message_post(body=_('Surgery case marked as Done.'))

    # ── NEW: reimbursed-surgery supplement invoice ──────────────────────────
    def action_create_reimbursed_invoice(self):
        """Invoice ONLY the optional supplement (e.g. esthetic supplement) on a
        reimbursed surgery. This amount is payable directly to the practice —
        it is a separate concept from the doctor/hospital fee, which is never
        invoiced to the patient on a reimbursed case."""
        self.ensure_one()
        if not self.is_reimbursed_surgery:
            raise UserError(_('This action is only available for reimbursed surgeries.'))
        if not self.patient_id:
            raise UserError(_('Please set a patient before creating the invoice.'))
        if not self.reimbursed_supplement_description:
            raise UserError(_('Please enter a description for the supplement.'))
        if self.reimbursed_supplement_amount <= 0:
            raise UserError(_('Please enter a supplement amount greater than 0.'))
        if self.invoice_ids.filtered(lambda m: m.state != 'cancel'):
            raise UserError(_('An active invoice already exists for this surgery case.'))

        product = self.procedure_id.product_tmpl_id

        invoice_line_vals = {
            'name': _(self.reimbursed_supplement_description),
            'quantity': 1,
            'price_unit': self.reimbursed_supplement_amount,
        }
        if product:
            invoice_line_vals['product_id'] = product.id

        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.patient_id.id,
            'invoice_date': fields.Date.today(),
            'invoice_date_due': self.surgery_date,
            'invoice_origin': self.name,
            'surgery_case_id': self.id,
            'ref': _('Surgeon Fee – %s') % self.name,
            'invoice_line_ids': [(0, 0, invoice_line_vals)],
        })
        self.invoice_ids = [(4, invoice.id)]
        self.message_post(
            body=_('Supplement invoice created for %(desc)s (%(amount).2f). '
                   'This surgery is reimbursed — only the supplement is invoiced, '
                   'payable directly to the practice.') % {
                     'desc': self.reimbursed_supplement_description,
                     'amount': self.reimbursed_supplement_amount,
                 }
        )
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': invoice.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _get_tax_excluded_price_unit(self, amount_incl, product):
        """
        G4 — Doctor fee (and extra fee) are entered as TAX-INCLUDED amounts.
        Take the product's own sale tax(es) (product.taxes_id) and back out
        the tax-EXCLUDED price_unit so that price_unit + tax == amount_incl.

        Handles both tax computation types Odoo supports:
          - 'percent'  : tax = base * rate/100          (added on top of base)
          - 'division' : tax = base * rate/(100-rate)    (Odoo's "Percentage
                          of Price Tax Included" — tax is defined as X% of
                          the FINAL tax-included total, which is what this
                          product's 21% tax actually is)
        Rate and type are read live from the actual tax record(s) on the
        product — nothing hardcoded.

        Returns a tuple: (tax_excluded_price_unit, taxes_recordset)
        """
        if not product:
            return amount_incl, self.env['account.tax']

        taxes = product.taxes_id
        if not taxes:
            return amount_incl, taxes

        denom = 1.0
        for t in taxes:
            if t.amount_type == 'percent':
                denom += t.amount / 100.0
            elif t.amount_type == 'division' and t.amount < 100:
                denom += t.amount / (100.0 - t.amount)

        amount_excl = amount_incl / denom if denom else amount_incl
        currency = self.env.company.currency_id
        amount_excl = currency.round(amount_excl)
        return amount_excl, taxes

    def action_create_invoice(self):
        """
        Generates the BV Colle Clinic honorarium invoice — doctor_fee
        (plus optional extra fee) only. hospital_fee is paid by the patient
        directly to the hospital and is deliberately never put on this
        invoice.

        Doctor fee and extra fee are entered TAX-INCLUDED: the amount typed
        by the user is the final total on the invoice line, tax included.
        """
        self.ensure_one()
        if self.is_reimbursed_surgery:
            raise UserError(_(
                'This is a reimbursed surgery — the procedure fee is not '
                'invoiced to the patient. Use "Create Supplement Invoice" '
                'instead if there is an additional cost.'
            ))
        if not self.patient_id:
            raise UserError(_('Please set a patient before creating the invoice.'))
        if self.doctor_fee <= 0:
            raise UserError(_('Doctor fee must be set before invoicing.'))
        if self.invoice_ids.filtered(lambda m: m.state != 'cancel'):
            raise UserError(_('An active invoice already exists for this surgery case.'))
        if not self.surgery_date:
            raise UserError(_('Please set a surgery date before invoicing.'))
        if self.extra_fee_enabled:
            if not self.extra_fee_description:
                raise UserError(_('Please enter a description for the extra fee.'))
            if self.extra_fee_amount <= 0:
                raise UserError(_('Please enter an extra fee amount greater than 0.'))

        product = self.procedure_id.product_tmpl_id

        # ── Doctor fee line: product from the procedure is added, and the
        # product's own sale tax is backed OUT of the tax-included doctor
        # fee, so that price_unit + tax == self.doctor_fee exactly (line
        # total on the invoice == doctor fee on the surgery case). ────────
        doctor_fee_excl, doctor_fee_taxes = self._get_tax_excluded_price_unit(
            self.doctor_fee, product)

        doctor_fee_line_vals = {
            'name': product.name if product else _('Doctor Fee'),
            'quantity': 1,
            'price_unit': doctor_fee_excl,
            'tax_ids': [(6, 0, doctor_fee_taxes.ids)],  # always explicit — never left for Odoo to guess/re-add
        }
        if product:
            doctor_fee_line_vals['product_id'] = product.id

        invoice_line_ids = [(0, 0, doctor_fee_line_vals)]

        # ── Extra fee line: simple line, NO product, NO tax back-calculation.
        # Description + price only, exactly as entered. ────────────────────
        if self.extra_fee_enabled and self.extra_fee_amount:
            extra_fee_line_vals = {
                'name': self.extra_fee_description,
                'quantity': 1,
                'price_unit': self.extra_fee_amount,
                'tax_ids': [(6, 0, [])],
            }
            invoice_line_ids.append((0, 0, extra_fee_line_vals))

        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.patient_id.id,
            'invoice_date': fields.Date.today(),
            'invoice_date_due': self.surgery_date,
            'invoice_origin': self.name,
            'surgery_case_id': self.id,
            'ref': _('Surgeon Fee – %s') % self.name,
            'invoice_line_ids': invoice_line_ids,
            'drcolle_planned_procedure': self.procedure_id.name or '',
            'drcolle_surgery_date': self.surgery_date,
        }

        if self.hospital_fee:
            invoice_vals['drcolle_remaining_amount'] = self.hospital_fee

        if self.block_location_type == 'hospital' and self.hospital_location_id:
            invoice_vals['drcolle_hospital_id'] = self.hospital_location_id.id
            bank = self.hospital_location_id.bank_ids[:1]
            if bank:
                invoice_vals['drcolle_hospital_bank_id'] = bank.id

        invoice = self.env['account.move'].create(invoice_vals)
        self.invoice_ids = [(4, invoice.id)]

        self.message_post(
            body=_('Fee invoice created — doctor fee line: %.2f (tax included, '
                   'product: %s)%s. Hospital fee is paid by the patient directly '
                   'to the hospital and is not invoiced here.') % (
                     self.doctor_fee,
                     product.name if product else _('none'),
                     _(' + extra fee line: %.2f (%s)') % (
                         self.extra_fee_amount, self.extra_fee_description
                     ) if self.extra_fee_enabled and self.extra_fee_amount else '',
                 )
        )
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': invoice.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_download_consent_templates(self):
        """Download the blank (unsigned) consent template PDF(s) configured on
        this case's procedure — used to print a paper copy for a patient who
        will sign on paper instead of digitally. Each sign.template stores its
        original source document on its own attachment_id field.

        Odoo's /web/content route only serves ONE attachment id per request —
        there is no built-in support for downloading several ids at once — so
        when more than one template is configured, this bundles them into a
        single zip attachment on the fly and downloads that instead."""
        self.ensure_one()

        if not self.procedure_sign_template_ids:
            raise UserError(_(
                'No consent templates are configured for this procedure yet.'
            ))

        attachments = self.procedure_sign_template_ids.mapped('document_ids.attachment_id')

        print('==========================================================================================', attachments)

        if not attachments:
            raise UserError(_(
                'The configured consent template(s) have no source document attached.'
            ))

        if len(attachments) == 1:
            return {
                'type': 'ir.actions.act_url',
                'url': '/web/content/%s?download=true' % attachments.id,
                'target': 'self',
            }

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            used_names = set()
            for attachment in attachments:
                filename = attachment.name or ('%s.pdf' % attachment.id)
                base, ext = (filename.rsplit('.', 1) + [''])[:2] if '.' in filename else (filename, '')
                candidate, suffix = filename, 1
                while candidate in used_names:
                    candidate = f'{base} ({suffix}).{ext}' if ext else f'{base} ({suffix})'
                    suffix += 1
                used_names.add(candidate)
                zf.writestr(candidate, base64.b64decode(attachment.datas or b''))

        zip_attachment = self.env['ir.attachment'].create({
            'name': _('%s - Consent Templates.zip') % self.name,
            'type': 'binary',
            'datas': base64.b64encode(buffer.getvalue()),
            'res_model': 'clinic.surgery.case',
            'res_id': self.id,
        })

        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % zip_attachment.id,
            'target': 'self',
        }

    def action_view_invoice(self):
        self.ensure_one()
        active = self.invoice_ids.filtered(lambda m: m.state != 'cancel')
        if not active:
            raise UserError(_('No invoice has been created yet.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': active[0].id,
            'view_mode': 'form',
            'target': 'current',
        }

    # Add a call to this at the TOP of your existing cron_surgery_automation_daily
    # (before the 7.3 guard loop) so honorarium_paid reflects the invoice's real
    # payment_state, instead of relying only on someone manually ticking the box.
    @api.model
    def cron_sync_invoice_payments(self):
        cases = self.sudo().search([
            ('state', 'in', ('planned', 'in_progress')),
            ('invoice_ids', '!=', False),
            ('honorarium_paid', '=', False),
        ])
        for case in cases:
            active = case.invoice_ids.filtered(lambda m: m.state == 'posted')
            if active and all(m.payment_state in ('paid', 'in_payment') for m in active):
                case.honorarium_paid = True
                case.message_post(body=_('Honorarium marked as paid — invoice settled.'))

    # ═══════════════════════════ POST-OP (G5) ═══════════════════════════════

    # WHAT THIS FIXES
    # ----------------
    # procedure_id is a single Many2one, so a case can only ever carry ONE
    # procedure's post-op schedule. G5 requires combined operations (facelift +
    # neck lift, breast lift + implants, brow lift variants) to each contribute
    # their own post-op consult(s) to the SAME case, and the surgeon must be able
    # to see/override each one individually, tagged by which procedure it came
    # from.
    #
    # WHAT CHANGES
    # ------------
    # 1. New field `additional_procedure_ids` (Many2many) — other procedures
    #    combined into this same operation. `procedure_id` stays exactly as-is
    #    (primary procedure — still drives fee/anesthesia/location defaults via
    #    the existing related fields, so nothing upstream breaks).
    # 2. New computed field `all_procedure_ids` — procedure_id + additional_ids,
    #    used everywhere post-op generation needs "every procedure in this case".
    # 3. `_generate_postop_consults()` is REPLACED — it now loops all_procedure_ids
    #    instead of just procedure_id, and dedupes per (procedure, days_after)
    #    instead of per days_after alone (so two procedures both defining a
    #    "+10d" consult no longer collide/skip each other).
    # 4. New button `action_sync_postop_schedule()` — lets the surgeon add a
    #    combined procedure AFTER initial planning and pull in its post-op
    #    lines without re-running the whole task generation flow.
    #
    # WHERE TO APPLY
    # ---------------
    # - Add the two new fields near the existing `procedure_id` field
    #   (right after the `procedure_id` field declaration).
    # - REPLACE the existing `_generate_postop_consults` method with the version
    #   below (same method name, same call sites — action_generate_tasks() and
    #   cron flows keep working unchanged).
    # - Add the new `_compute_all_procedure_ids` compute method and the new
    #   `action_sync_postop_schedule` action method.
    # ═══════════════════════════════════════════════════════════════════════════

    # ── NEW: combined-procedure support ────────────────────────────────────
    additional_procedure_ids = fields.Many2many(
        'clinic.surgery.procedure',
        'clinic_surgery_case_procedure_rel', 'case_id', 'procedure_id',
        string='Additional Procedures (Combined)',
        help='Other procedures performed in the same operation as the primary '
             'procedure above (e.g. Facelift + Neck Lift in one session). '
             'Each contributes its own post-op consult schedule from its '
             'template, tagged so the surgeon can tell them apart.')

    all_procedure_ids = fields.Many2many(
        'clinic.surgery.procedure',
        compute='_compute_all_procedure_ids',
        string='All Procedures in This Operation',
        help='Primary procedure + additional procedures combined. Used to '
             'pull in every post-op consult template that applies to this case.')

    @api.depends('procedure_id', 'additional_procedure_ids')
    def _compute_all_procedure_ids(self):
        for rec in self:
            rec.all_procedure_ids = rec.procedure_id | rec.additional_procedure_ids

    # ── REPLACES the existing _generate_postop_consults ────────────────────
    def _generate_postop_consults(self):
        """
        G5 — Lock post-op consult schedule from EVERY procedure's template
        (primary + combined). Existing consults are never deleted; only
        missing (procedure, days_after) combinations are added, so calling
        this repeatedly — e.g. after adding a combined procedure — is safe.
        """
        self.ensure_one()
        if not self.surgery_date:
            return

        procedures = self.all_procedure_ids
        if not procedures:
            return

        # Key by (procedure, label) — survives days_after being edited
        existing_by_key = {
            (c.source_procedure_id.id, c.label): c
            for c in self.postop_consult_ids
        }

        Consult = self.env['clinic.postop.consult']
        created = 0
        updated = 0

        for procedure in procedures:
            for config in procedure.postop_consult_ids:
                key = (procedure.id, config.label)
                planned_date = self.surgery_date + timedelta(days=config.days_after)
                window = config.window_days if not config.is_fixed_day else 0
                notes = (
                    f'Window \u00b1{config.window_days}d'
                    if not config.is_fixed_day and config.window_days
                    else ''
                )

                existing = existing_by_key.get(key)
                if existing:
                    vals = {}
                    if existing.is_fixed != config.is_fixed_day:
                        vals['is_fixed'] = config.is_fixed_day
                    if existing.days_after_surgery != config.days_after:
                        vals['days_after_surgery'] = config.days_after
                    if existing.window_days != window:
                        vals['window_days'] = window
                    if existing.notes != notes:
                        vals['notes'] = notes
                    if existing.planned_date != planned_date:
                        vals['planned_date'] = planned_date
                    if existing.responsible_id != config.responsible_id:
                        vals['responsible_id'] = config.responsible_id
                    if vals:
                        existing.write(vals)
                        updated += 1
                else:
                    Consult.create({
                        'surgery_case_id': self.id,
                        'source_procedure_id': procedure.id,
                        'label': config.label,
                        'responsible_id': config.responsible_id,
                        'planned_date': planned_date,
                        'is_fixed': config.is_fixed_day,
                        'days_after_surgery': config.days_after,
                        'window_days': window,
                        'notes': notes,
                    })
                    created += 1

        if created or updated:
            self.message_post(
                body=_(f'{created} post-op consult(s) created, {updated} updated '
                       f'from {len(procedures)} procedure(s).')
            )

    # ── NEW: let the surgeon pull in a combined procedure's schedule later ──
    def action_sync_postop_schedule(self):
        """
        Button: re-scan all_procedure_ids and add any post-op consult lines
        that aren't on the case yet (e.g. surgeon just added a combined
        procedure after the initial planning). Never touches existing lines.
        """
        self.ensure_one()
        if not self.surgery_date:
            raise UserError(_('Please set a surgery date first.'))
        self._generate_postop_consults()

    # ══════════════════════════════════════════════════════════════════
    # Smart button: "Dashboard" — opens the Surgery Dashboard client
    # action scoped to this single case (see surgery_case_dashboard.py /
    # get_case_dashboard_data for the data, and the "Back to Surgery"
    # button in the widget to return here). The main Dashboard menu item
    # is untouched — it opens the same client action with no params.
    # ══════════════════════════════════════════════════════════════════
    def action_view_case_dashboard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'surgery_dashboard',
            'name': _('Surgery Dashboard'),
            'params': {'case_id': self.id},
        }