# -*- coding: utf-8 -*-
# Add to clinic.operating.block model
# 1. slot_duration Selection field
# 2. get_timeslots_for_date @api.model method

from odoo import api, fields, models
from datetime import date, time, datetime, timedelta


class ClinicOperatingBlock(models.Model):
    _inherit = 'clinic.operating.block'

    slot_duration = fields.Selection(
        selection=[
            ('15', '15 min'),
            ('30', '30 min'),
            ('45', '45 min'),
            ('60', '60 min'),
            ('75', '75 min'),
            ('90', '90 min'),
            ('120', '120 min'),
            ('180', '180 min'),
        ],
        string='Slot Duration',
        default='30',
        help='Duration of each surgery slot within this operating block.',
    )

    # ── IMPORTANT: @api.model means self = empty recordset (no record id).
    # The JS must call it as:
    #   this.orm.call('clinic.operating.block', 'get_timeslots_for_date',
    #                 [], { doctor_id: X, date_str: 'YYYY-MM-DD' })
    # NOT as:
    #   this.orm.call('clinic.operating.block', 'get_timeslots_for_date',
    #                 [X, 'YYYY-MM-DD'], {})
    # because @api.model passes args as keyword arguments after self.
    @api.model
    def get_timeslots_for_date(self, doctor_id, date_str):
        """
        Return time slots for a doctor on a specific date.
        Extra one-off slots always take priority over regular weekday slots,
        checked across ALL of the doctor's blocks — not just the first match.
        """
        target = date.fromisoformat(date_str)
        blocks = self.search([('doctor_id', '=', doctor_id), ('active', '=', True)])

        open_h = open_m = close_h = close_m = None
        duration = 60

        # ── Pass 1: check every block for an extra slot on this date first ──
        extra_found = None
        for block in blocks:
            extra = block.extra_ids.filtered(lambda e: e.extra_date == target)
            if extra:
                extra_found = (block, extra[0])
                break

        if extra_found:
            block, e = extra_found
            open_h, open_m = e.open_time_hour, e.open_time_minute
            close_h, close_m = e.close_time_hour, e.close_time_minute
            duration = int(block.slot_duration or 60)
        else:
            # ── Pass 2: no extra slot anywhere — fall back to regular weekday ──
            for block in blocks:
                if int(block.day_of_week) == target.weekday():
                    closed_ranges = [
                        (c.from_date, c.to_date)
                        for c in block.closure_ids if c.from_date and c.to_date
                    ]
                    if not block._is_date_closed(target, closed_ranges):
                        open_h, open_m = block.open_time_hour, block.open_time_minute
                        close_h, close_m = block.close_time_hour, block.close_time_minute
                        duration = int(block.slot_duration or 60)
                        break

        if open_h is None:
            return []

        slots  = []
        cursor = datetime.combine(target, time(open_h, open_m))
        end_dt = datetime.combine(target, time(close_h, close_m))
        step   = timedelta(minutes=duration)

        while cursor + step <= end_dt:
            slot_end  = cursor + step
            start_str = cursor.strftime('%H:%M')
            end_str   = slot_end.strftime('%H:%M')
            slots.append((start_str, f'{start_str} – {end_str}'))
            cursor = slot_end

        return slots
