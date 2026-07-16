# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError
from datetime import date, time, datetime, timedelta
from dateutil.relativedelta import relativedelta

class ClinicOperatingBlock(models.Model):
    """
    Master weekly operating schedule per doctor.
    e.g. Every Wednesday 08:00-18:00 at Imelda Ziekenhuis
         Every Friday    09:00-12:00 at Villa Medici
    """
    _name = 'clinic.operating.block'
    _description = 'Operating Block (Weekly Schedule)'
    _order = 'doctor_id, day_of_week'

    doctor_id = fields.Many2one(
        'res.users', string='Doctor', required=True,
        default=lambda self: self.env.user,
        tracking=True)

    day_of_week = fields.Selection([
        ('0', 'Monday'),
        ('1', 'Tuesday'),
        ('2', 'Wednesday'),
        ('3', 'Thursday'),
        ('4', 'Friday'),
        ('5', 'Saturday'),
        ('6', 'Sunday'),
    ], string='Day of Week', required=True)

    location_id = fields.Many2one(
        'res.partner', string='Location',
        help='Hospital or practice for this block.')
    location_type = fields.Selection([
        ('hospital', 'Hospital'),
        ('practice', 'Private Practice'),
    ], string='Location Type')

    open_time_hour = fields.Integer(string='Start Hour', default=8)
    open_time_minute = fields.Integer(string='Start Minute', default=0)
    close_time_hour = fields.Integer(string='End Hour', default=18)
    close_time_minute = fields.Integer(string='End Minute', default=0)

    active = fields.Boolean(default=True)
    notes = fields.Char(string='Notes')

    # ── Closures and extras ───────────────────────────────────────────────
    closure_ids = fields.One2many(
        'clinic.operating.block.closure', 'block_id',
        string='Closed Days')
    extra_ids = fields.One2many(
        'clinic.operating.block.extra', 'block_id',
        string='Extra Slots')

    # ── Display ───────────────────────────────────────────────────────────
    name = fields.Char(
        string='Block', compute='_compute_name', store=True)

    @api.depends('doctor_id', 'day_of_week', 'location_id')
    def _compute_name(self):
        days = dict(self._fields['day_of_week'].selection)
        for rec in self:
            day = days.get(rec.day_of_week, '')
            loc = rec.location_id.name or ''
            doc = rec.doctor_id.name or ''
            rec.name = f'{doc} – {day} – {loc}'

    @api.constrains('open_time_hour', 'close_time_hour',
                    'open_time_minute', 'close_time_minute')
    def _check_times(self):
        for rec in self:
            if not 0 <= rec.open_time_hour <= 23:
                raise ValidationError('Start hour must be 0–23.')
            if not 0 <= rec.close_time_hour <= 23:
                raise ValidationError('End hour must be 0–23.')
            if not 0 <= rec.open_time_minute <= 59:
                raise ValidationError('Start minute must be 0–59.')
            if not 0 <= rec.close_time_minute <= 59:
                raise ValidationError('End minute must be 0–59.')
            start = rec.open_time_hour * 60 + rec.open_time_minute
            end = rec.close_time_hour * 60 + rec.close_time_minute
            if end <= start:
                raise ValidationError('End time must be after start time.')

    # ═══════════════════════════ PUBLIC API ════════════════════════════════

    @api.model
    def get_available_dates_for_doctor(self, doctor_id, months_ahead=6, location_type=None):
        """
        Return available operating dates for a doctor within `months_ahead` months.

        Args:
            doctor_id (int): res.users ID of the doctor.
            months_ahead (int): how many months ahead to scan.
            location_type (str|None): 'hospital', 'practice', or None for all.

        Returns list of dicts:
          [{'date': '2026-07-06', 'block_id': 1, 'location': '...', 'location_type': 'hospital',
            'location_id': 142, 'start': '08:00', 'end': '18:00', 'note': ''}, ...]
        """
        domain = [('doctor_id', '=', doctor_id), ('active', '=', True)]
        if location_type:
            domain.append(('location_type', '=', location_type))

        blocks = self.search(domain)
        if not blocks:
            return []

        today = date.today()
        limit = today + relativedelta(months=months_ahead)
        available = []

        for block in blocks:
            weekday = int(block.day_of_week)
            closed_ranges = [
                (c.from_date, c.to_date)
                for c in block.closure_ids
                if c.from_date and c.to_date
            ]
            current = today
            while current <= limit:
                if current.weekday() == weekday:
                    if not block._is_date_closed(current, closed_ranges):
                        available.append(block._build_date_entry(current))
                current += timedelta(days=1)

            for extra in block.extra_ids:
                if extra.extra_date and today <= extra.extra_date <= limit:
                    available.append(block._build_date_entry(
                        extra.extra_date,
                        override_open_h=extra.open_time_hour,
                        override_open_m=extra.open_time_minute,
                        override_close_h=extra.close_time_hour,
                        override_close_m=extra.close_time_minute,
                        extra_note=extra.notes,
                    ))

        available.sort(key=lambda x: x['date'])
        return available

    @api.model
    def get_location_ids_for_doctor(self, doctor_id, location_type=None):
        """
        Return the res.partner IDs of all locations configured in operating
        blocks for this doctor. Used to restrict the hospital_location_id
        domain on the surgery case form.

        Args:
            doctor_id (int): res.users ID.
            location_type (str|None): filter by 'hospital' / 'practice' or None for all.

        Returns:
            list[int]: list of res.partner IDs.
        """
        domain = [('doctor_id', '=', doctor_id), ('active', '=', True)]
        if location_type:
            domain.append(('location_type', '=', location_type))
        blocks = self.search(domain)
        ids = list({b.location_id.id for b in blocks if b.location_id})
        return ids

    # @api.model
    # def get_available_dates_for_doctor(self, doctor_id, months_ahead=6):
    #     """
    #     Return all available operating dates for a doctor
    #     within the next `months_ahead` months.

    #     Returns list of dicts:
    #       [{
    #         'date': '2025-09-03',
    #         'block_id': 5,
    #         'location': 'Imelda Ziekenhuis',
    #         'location_type': 'hospital',
    #         'start': '08:00',
    #         'end': '18:00',
    #       }, ...]
    #     """
    #     blocks = self.search([
    #         ('doctor_id', '=', doctor_id),
    #         ('active', '=', True),
    #     ])
    #     if not blocks:
    #         return []

    #     today = date.today()
    #     limit = today + relativedelta(months=months_ahead)
    #     available = []

    #     for block in blocks:
    #         weekday = int(block.day_of_week)

    #         # Collect all closed date ranges for this block
    #         closed_ranges = [
    #             (c.from_date, c.to_date)
    #             for c in block.closure_ids
    #             if c.from_date and c.to_date
    #         ]

    #         # Walk every day in range
    #         current = today
    #         while current <= limit:
    #             if current.weekday() == weekday:
    #                 if not block._is_date_closed(current, closed_ranges):
    #                     available.append(
    #                         block._build_date_entry(current))
    #             current += timedelta(days=1)

    #         # Add extra (one-off) slots
    #         for extra in block.extra_ids:
    #             if extra.extra_date and today <= extra.extra_date <= limit:
    #                 available.append(block._build_date_entry(
    #                     extra.extra_date,
    #                     override_open_h=extra.open_time_hour,
    #                     override_open_m=extra.open_time_minute,
    #                     override_close_h=extra.close_time_hour,
    #                     override_close_m=extra.close_time_minute,
    #                     extra_note=extra.notes,
    #                 ))

    #     # Sort by date
    #     available.sort(key=lambda x: x['date'])
    #     return available

    def _is_date_closed(self, check_date, closed_ranges):
        for from_d, to_d in closed_ranges:
            if from_d <= check_date <= to_d:
                return True
        return False

    def _build_date_entry(self, d, override_open_h=None, override_open_m=None,
                          override_close_h=None, override_close_m=None,
                          extra_note=None):
        return {
            'date': d.strftime('%Y-%m-%d'),
            'block_id': self.id,
            'location': self.location_id.name or '',
            'location_id': self.location_id.id or False,
            'location_type': self.location_type or '',
            'start': '{:02d}:{:02d}'.format(
                override_open_h if override_open_h is not None else self.open_time_hour,
                override_open_m if override_open_m is not None else self.open_time_minute,
            ),
            'end': '{:02d}:{:02d}'.format(
                override_close_h if override_close_h is not None else self.close_time_hour,
                override_close_m if override_close_m is not None else self.close_time_minute,
            ),
            'note': extra_note or self.notes or '',
        }


class ClinicOperatingBlockClosure(models.Model):
    """
    Closed periods for an operating block.
    e.g. Public holiday 01/11/2025 – 01/11/2025
    """
    _name = 'clinic.operating.block.closure'
    _description = 'Operating Block Closure'
    _order = 'from_date'

    block_id = fields.Many2one(
        'clinic.operating.block', string='Operating Block',
        ondelete='cascade', required=True)
    from_date = fields.Date(string='From Date', required=True)
    to_date = fields.Date(string='To Date', required=True)
    reason = fields.Char(string='Reason', help='e.g. Public holiday, vacation')

    @api.constrains('from_date', 'to_date')
    def _check_dates(self):
        for rec in self:
            if rec.from_date > rec.to_date:
                raise ValidationError('From Date must be before or equal to To Date.')


class ClinicOperatingBlockExtra(models.Model):
    """
    Extra one-off operating slots outside the weekly schedule.
    e.g. Tuesday 15/10/2025 at Imelda (additional slot)
    """
    _name = 'clinic.operating.block.extra'
    _description = 'Operating Block Extra Slot'
    _order = 'extra_date'

    block_id = fields.Many2one(
        'clinic.operating.block', string='Operating Block',
        ondelete='cascade', required=True)
    extra_date = fields.Date(string='Extra Date', required=True)
    open_time_hour = fields.Integer(string='Start Hour', default=8)
    open_time_minute = fields.Integer(string='Start Minute', default=0)
    close_time_hour = fields.Integer(string='End Hour', default=18)
    close_time_minute = fields.Integer(string='End Minute', default=0)
    notes = fields.Char(string='Notes')
