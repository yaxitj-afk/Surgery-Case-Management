# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import base64


class AdmissionDocumentWizard(models.TransientModel):
	_name = 'clinic.admission.wizard'
	_description = 'Admission Document Wizard'

	surgery_case_id = fields.Many2one(
		'clinic.surgery.case', string='Surgery Case', required=True)

	# ── Pulled from surgery case ──────────────────────────────────────────
	patient_id = fields.Many2one(
		related='surgery_case_id.patient_id', readonly=True)
	surgeon_id = fields.Many2one(
		related='surgery_case_id.surgeon_id', readonly=True)
	procedure_id = fields.Many2one(
		related='surgery_case_id.procedure_id', readonly=True)
	surgery_date = fields.Date(related='surgery_case_id.surgery_date',)
	hospital_location_id = fields.Many2one(
		related='surgery_case_id.hospital_location_id', readonly=True)

	# ── Section: Check-in ─────────────────────────────────────────────────
	checkin_place = fields.Selection([
		('hospital', 'Hospital'),
		('practice', 'Private Practice'),
	], string='Place of Surgery',
		compute='_compute_checkin_place', store=True, readonly=False)

	checkin_timing = fields.Selection([
		('same_day', 'Same Day'),
		('day_before', 'Day Before'),
	], string='Check-in Timing', default='same_day')

	checkin_date = fields.Date(string='Check-in Date')
	checkin_time = fields.Float(string='Check-in Hour',
								help='e.g. 8.5 = 08:30')
	full_day_available = fields.Boolean(
		string='Full Day Available',
		help='Exact hour may change — patient will be phoned')

	# ── Section: Anesthesia ───────────────────────────────────────────────
	anesthesia_type = fields.Selection([
		('local', 'Local'),
		('general', 'General'),
	], string='Anesthesia Type',
		compute='_compute_anesthesia', store=True, readonly=False)

	# ── Section: To Bring ─────────────────────────────────────────────────
	bring_green_form = fields.Boolean(string='Green Form (completed)')
	bring_id_card = fields.Boolean(string='Identity Card')
	bring_mutual_approval = fields.Boolean(
		string='Mutuality / Insurance Approval')
	bring_sport_bra = fields.Boolean(
		string='Sturdy Sport Bra (Lipoelastic/Anita)')
	bring_compression_garments = fields.Boolean(
		string='Compression Garments (Lipoelastic)')
	bring_crutches = fields.Boolean(string='Crutches')
	bring_other = fields.Char(string='Other (To Bring)')

	# ── Section: To Arrange ───────────────────────────────────────────────
	arrange_rx = fields.Boolean(string='RX (Radiograph)')
	arrange_ultrasound_mammo = fields.Boolean(
		string='Ultrasound + Mammography')
	arrange_ultrasound = fields.Boolean(string='Ultrasound')
	arrange_blood_test = fields.Boolean(string='Blood Test (Lab)')
	arrange_ecg = fields.Boolean(string='ECG')
	arrange_pac = fields.Boolean(
		string='Pre-op Anesthesia Consult (PAC)',
		help='Phone: 015 50 52 39')
	arrange_ent = fields.Boolean(
		string='Pre-op ENT (NKO) Consult')
	arrange_shave = fields.Boolean(
		string='Shave Surgical Area the Day Before')
	arrange_sign_ic = fields.Boolean(
		string='Read and Sign Informed Consent')
	arrange_payment = fields.Boolean(
		string='Payment as Stated on Invoice')
	arrange_read_brochure = fields.Boolean(
		string='Read Information Brochure')
	arrange_other = fields.Char(string='Other (To Arrange)')

	# ── Section: Medication ───────────────────────────────────────────────
	blood_thinner = fields.Boolean(string='Takes Blood Thinners')
	blood_thinner_type = fields.Selection([
		('aspirin', 'Aspirin'),
		('anticoagulant', 'Anticoagulant'),
		('other', 'Other'),
	], string='Blood Thinner Type')

	description = fields.Html(
		string='Description',
		help='Additional information to include in the admission document '
		     '(PDF) and in the email sent to the patient.')

	admission_time = fields.Selection(
		related='surgery_case_id.admission_time', readonly=True,
		string='Admission Time')

	# ═══════════ COMPUTES ═══════════════════════════════════════════════════

	@api.depends('surgery_case_id.procedure_id.location_type')
	def _compute_checkin_place(self):
		for rec in self:
			loc = rec.surgery_case_id.procedure_id.location_type \
				if rec.surgery_case_id.procedure_id else False
			rec.checkin_place = 'hospital' if loc == 'hospital' else 'practice'

	@api.depends('surgery_case_id.procedure_id.anesthesia_type')
	def _compute_anesthesia(self):
		for rec in self:
			a = rec.surgery_case_id.procedure_id.anesthesia_type \
				if rec.surgery_case_id.procedure_id else False
			rec.anesthesia_type = a if a in ('local', 'general') else 'local'

	# ═══════════ ACTION ═════════════════════════════════════════════════════

	def action_generate_and_send(self):
		self.ensure_one()
		case = self.surgery_case_id

		if not case.patient_id or not case.patient_id.email:
			raise UserError(_(
				'Patient must have a valid email address to send the admission document.'))

		# 1. Generate PDF
		pdf_content, content_type = self.env['ir.actions.report']._render_qweb_pdf(
			'surgery_case_management.admission_document_template', [self.id])

		# 2. Store as attachment on surgery case
		filename = f'Admission_{case.name.replace("/", "_")}.pdf'
		attachment = self.env['ir.attachment'].create({
			'name': filename,
			'type': 'binary',
			'datas': base64.b64encode(pdf_content),
			'mimetype': 'application/pdf',
			'res_model': 'clinic.surgery.case',
			'res_id': case.id,
		})

		# 3. Send email to patient
		mail = self.env['mail.mail'].create({
			'subject': f'Admission document – {case.name}',
			'email_to': case.patient_id.email,
			'body_html': self._build_email_body(attachment),
			'attachment_ids': [(4, attachment.id)],
		})
		mail.send()
		case.admission_document_sent = True

		# 4. Post to chatter of surgery case
		case.message_post(
			body=_('Admission document generated and sent to patient.'),
			attachment_ids=[attachment.id],
		)

		# 5. Spawn to-dos based on ticked items
		self._spawn_todos()

		return {
			'type': 'ir.actions.client',
			'tag': 'display_notification',
			'params': {
				'title': _('Admission Document Sent'),
				'message': _('Admission document generated and sent to %s.') % case.patient_id.name,
				'type': 'success',
				'sticky': False,
				'next': {'type': 'ir.actions.act_window_close'},
			},
		}

	# ═══════════ EMAIL BODY ══════════════════════════════════════════════════

	def _build_email_body(self, attachment):
		self.ensure_one()
		case = self.surgery_case_id
		patient_name = case.patient_id.name
		procedure = case.procedure_id.name if case.procedure_id else ''
		surgery_dt = (case.surgery_date.strftime('%A %d %B %Y at %H:%M')
					  if case.surgery_date else 'to be confirmed')
		doctor = case.surgeon_id.name if case.surgeon_id else 'Dr. Julien Colle'

		description_html = ''
		if self.description:
			description_html = (
					'<p>%s</p>' % self.description.replace('\n', '<br/>')
			)

		return f"""
				<p>Dear {patient_name},</p>
				<p>Please find attached your admission document for your planned procedure:
				<strong>{procedure}</strong>.</p>
				<p>Surgery date: <strong>{surgery_dt}</strong></p>
				{description_html}
				<p>Please read this document carefully and arrange all required items
				in time before your surgery date.</p>
				<p>If you have any questions, please do not hesitate to contact us at
				<a href="mailto:info@drcolle.be">info@drcolle.be</a>.</p>
				<br/>
				<p>Kind regards,<br/>
				<strong>{doctor}</strong><br/>
				BV Colle Clinic<br/>
				Achiel Cleynhenslaan 150, 3140 Keerbergen<br/>
				BE 0803.222.059 | info@drcolle.be</p>
				"""

	# ═══════════ SPAWN TO-DOS ════════════════════════════════════════════════

	def _spawn_todos(self):
		"""Create secretary/patient tasks for ticked admission items."""
		self.ensure_one()
		case = self.surgery_case_id
		project = self._get_or_create_project()
		secretary = case.secretary_id or case.surgeon_id
		todos = []

		if self.bring_mutual_approval:
			todos.append((
				'Verify mutuality/insurance approval received',
				secretary,
				'Secretariat must verify that the mutuality/insurance approval '
				'has been received before surgery proceeds.',
			))
		if self.bring_sport_bra:
			todos.append((
				f'Send sport bra size & order link to {case.patient_id.name}',
				secretary,
				'Send the measured size and Lipoelastic/Anita order link to the patient.',
			))
		if self.bring_compression_garments:
			todos.append((
				f'Send compression garment order link to {case.patient_id.name}',
				secretary,
				'Send the Lipoelastic order link (www.lipoelastic.nl) to the patient.',
			))
		if self.arrange_pac:
			todos.append((
				f'Patient to arrange PAC (015 50 52 39) – {case.name}',
				secretary,
				'Patient must contact 015 50 52 39 to arrange pre-op anesthesia consult.',
			))

		for task_name, user, description in todos:
			self.env['project.task'].create({
				'name': task_name,
				'project_id': project.id,
				'surgery_case_id': case.id,
				'user_ids': [(4, user.id)] if user else [],
				'description': description,
			})

	def _get_or_create_project(self):
		case = self.surgery_case_id
		name = f'Surgery – {case.patient_id.name} – {case.name}'
		project = self.env['project.project'].search(
			[('name', '=', name)], limit=1)
		if not project:
			project = self.env['project.project'].create({
				'name': name,
				'partner_id': case.patient_id.id,
			})
		return project
