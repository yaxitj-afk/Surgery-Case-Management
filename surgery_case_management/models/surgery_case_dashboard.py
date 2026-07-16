# -*- coding: utf-8 -*-
from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.tools import html2plaintext


class ClinicSurgeryCaseDashboard(models.Model):
    """Pure ADDITION to clinic.surgery.case — only get_dashboard_data()
    and its private helpers. No new fields (emergency concept removed
    per updated requirements)."""
    _inherit = 'clinic.surgery.case'

    # ══════════════════════════════════════════════════════════════════
    # DOMAIN BUILDER
    # ══════════════════════════════════════════════════════════════════
    @api.model
    def _dashboard_build_domain(self, filters):
        filters = filters or {}
        domain = []
        if filters.get('date_from'):
            domain.append(('surgery_date', '>=', filters['date_from']))
        if filters.get('date_to'):
            domain.append(('surgery_date', '<=', filters['date_to']))
        if filters.get('surgeon_id'):
            domain.append(('surgeon_id', '=', filters['surgeon_id']))
        if filters.get('operating_block_id'):
            domain.append(('operating_block_id', '=', filters['operating_block_id']))
        if filters.get('procedure_id'):
            domain.append(('procedure_id', '=', filters['procedure_id']))
        if filters.get('state'):
            domain.append(('state', '=', filters['state']))
        if filters.get('hospital_id'):
            domain.append(('hospital_location_id', '=', filters['hospital_id']))
        if filters.get('patient_id'):
            domain.append(('patient_id', '=', filters['patient_id']))
        return domain

    # ══════════════════════════════════════════════════════════════════
    # MAIN AGGREGATION ENDPOINT
    # ══════════════════════════════════════════════════════════════════
    @api.model
    def get_dashboard_data(self, filters=None):
        filters = filters or {}
        today = fields.Date.context_today(self)

        domain = self._dashboard_build_domain(filters)
        cases = self.sudo().search(domain)
        completed_states = ('done',)
        surgery_finished_states = ('surgery_completed', 'post_follow_ups', 'done')
        active_states = ('draft', 'confirmed', 'planned', 'reschedule', 'in_progress')

        completed = cases.filtered(lambda c: c.state in completed_states)
        surgery_finished = cases.filtered(lambda c: c.state in surgery_finished_states)
        cancelled = cases.filtered(lambda c: c.state == 'cancelled')
        reimbursed = cases.filtered('is_reimbursed_surgery')
        today_cases = cases.filtered(lambda c: c.surgery_date == today)

        upcoming_filters = dict(filters, date_from=False, date_to=False)
        upcoming_domain = self._dashboard_build_domain(upcoming_filters) + [
            ('surgery_date', '>=', today),
            ('state', 'in', list(active_states)),
        ]
        upcoming = self.sudo().search(upcoming_domain)

        # "Surgery Completed" — cases whose surgery itself is finished
        # (state == 'surgery_completed'), distinct from the "Completed
        # Cases" KPI above which only counts the fully-closed 'done' state.
        # Scoped by the same domain as the rest of the KPIs (date range,
        # surgeon, procedure, state, hospital filters all apply).
        surgery_completed_only = cases.filtered(lambda c: c.state == 'surgery_completed')

        prev = self._dash_previous_period(filters)

        def delta(current, prev_val):
            if prev_val:
                return round((current - prev_val) / prev_val * 100)
            return 100 if current else 0

        kpis = {
            'total_cases': {'value': len(cases), 'delta': delta(len(cases), prev['total'])},
            'today_surgeries': {'value': len(today_cases), 'delta': None},
            'upcoming_surgeries': {'value': len(upcoming), 'delta': None},
            'completed_cases': {'value': len(completed), 'delta': delta(len(completed), prev['completed'])},
            'cancelled_cases': {'value': len(cancelled), 'delta': delta(len(cancelled), prev['cancelled'])},
            'reimbursed_cases': {'value': len(reimbursed), 'delta': delta(len(reimbursed), prev['reimbursed'])},
            'reimbursed_amount': round(sum(reimbursed.mapped('reimbursed_supplement_amount')), 2),
            'surgery_completed_cases': {
                'value': len(surgery_completed_only),
                'delta': delta(len(surgery_completed_only), prev['surgery_completed']),
            },
        }

        return {
            'kpis': kpis,
            'trend': self._dash_monthly_trend(cases, filters),
            'status_distribution': self._dash_status_distribution(cases),
            'procedures_by_type': self._dash_procedures_by_type(cases),
            'surgeon_workload': self._dash_surgeon_workload(cases),
            'week_calendar': self._dash_week_calendar(cases, today),
            'today_schedule': self._dash_today_schedule(today_cases),
            'upcoming_admissions': self._dash_upcoming_admissions(upcoming),
            # NOTE: "Recent Completed Surgeries" must only ever show cases whose
            # state is actually 'done' — using surgery_finished here previously
            # also pulled in 'surgery_completed' and 'post_follow_ups' cases,
            # which inflated the count and showed cases that aren't really done.
            'recent_completed': self._dash_recent_completed(completed),
            'pending_postop': self._dash_pending_postop(cases, today),
            'pipeline': self._dash_pipeline(cases),
            'alerts': self._dash_alerts(cases, today),
            'pending_signatures': self._dash_pending_signatures(cases),
            'upcoming_activities': self._dash_upcoming_activities(cases),
            # 'analytics': self._dash_analytics(cases, surgery_finished, prev),
            'financial': self._dash_financial(cases),
            'filter_options': self._dash_filter_options(filters),
        }

    # ── Previous-period counts, for the "vs last period" deltas ─────────
    def _dash_previous_period(self, filters):
        date_from = filters.get('date_from')
        date_to = filters.get('date_to')
        today = fields.Date.context_today(self)
        if date_from and date_to:
            d_from = fields.Date.from_string(date_from)
            d_to = fields.Date.from_string(date_to)
        else:
            d_to = today
            d_from = today - timedelta(days=30)
        span = (d_to - d_from).days + 1
        prev_to = d_from - timedelta(days=1)
        prev_from = prev_to - timedelta(days=span - 1)

        domain = [('surgery_date', '>=', prev_from), ('surgery_date', '<=', prev_to)]
        for key, val in (
            ('surgeon_id', filters.get('surgeon_id')),
            ('operating_block_id', filters.get('operating_block_id')),
            ('procedure_id', filters.get('procedure_id')),
            ('hospital_location_id', filters.get('hospital_id')),
            ('patient_id', filters.get('patient_id')),
        ):
            if val:
                domain.append((key, '=', val))

        prev_cases = self.sudo().search(domain)
        completed_states = ('done',)
        return {
            'total': len(prev_cases),
            'completed': len(prev_cases.filtered(lambda c: c.state in completed_states)),
            'cancelled': len(prev_cases.filtered(lambda c: c.state == 'cancelled')),
            'reimbursed': len(prev_cases.filtered('is_reimbursed_surgery')),
            'surgery_completed': len(prev_cases.filtered(lambda c: c.state == 'surgery_completed')),
            'cases': prev_cases,
        }
    # ── Monthly trend (last 6 months, by surgery_date) ──────────────────
        # ── Monthly trend — follows the selected date_from/date_to filter.
        # Falls back to "last 6 months from today" only when no date range is
        # set (e.g. right after Reset Filters). Capped at 36 months so an
        # accidental multi-year range can't blow up the chart.
    def _dash_monthly_trend(self, cases, filters=None):
        filters = filters or {}
        today = fields.Date.context_today(self)
        date_from = filters.get('date_from')
        date_to = filters.get('date_to')

        if date_from and date_to:
            start = fields.Date.from_string(date_from).replace(day=1)
            end = fields.Date.from_string(date_to).replace(day=1)
            if start > end:
                start, end = end, start
        else:
            end = today.replace(day=1)
            cursor = end
            for _i in range(5):
                cursor = (cursor - timedelta(days=1)).replace(day=1)
            start = cursor

        buckets = []
        m = start
        while m <= end:
            buckets.append(m)
            if m.month == 12:
                m = m.replace(year=m.year + 1, month=1)
            else:
                m = m.replace(month=m.month + 1)
            if len(buckets) >= 36:
                break

        multi_year = len({b.year for b in buckets}) > 1

        counts = defaultdict(int)
        for c in cases:
            if c.surgery_date:
                key = c.surgery_date.replace(day=1)
                counts[key] += 1

        # AFTER
        def _month_end(d):
            nxt = d.replace(year=d.year + 1, month=1, day=1) if d.month == 12 \
                else d.replace(month=d.month + 1, day=1)
            return nxt - timedelta(days=1)

        return [
            {
                'label': b.strftime('%b %y') if multi_year else b.strftime('%b'),
                'count': counts.get(b, 0),
                'date_from': fields.Date.to_string(b),
                'date_to': fields.Date.to_string(_month_end(b)),
            }
            for b in buckets
        ]
    # ── Donut: status distribution ───────────────────────────────────────
    def _dash_status_distribution(self, cases):
        labels = {
            'draft': _('Draft'), 'confirmed': _('Confirmed'), 'planned': _('Scheduled'),
            'in_progress': _('In Progress'), 'surgery_completed': _('Surgery Completed'),
            'post_follow_ups': _('Post Follow-up'), 'done': _('Done'),
            'cancelled': _('Cancelled'),
        }
        # NOTE: keyed by the untranslated state code (not the label) so the
        # color lookup still matches once the label above is translated.
        colors = {
            'draft': '#94a3b8', 'confirmed': '#3b82f6', 'planned': '#0ea5e9',
            'in_progress': '#f59e0b', 'surgery_completed': '#0d9488', 'done': '#10b981',
            'post_follow_ups': '#8b5cf6', 'cancelled': '#ef4444',
        }
        counts = defaultdict(int)
        for c in cases:
            if c.state == 'reschedule':
                continue
            counts[c.state] += 1
        total = sum(counts.values()) or 1
        return [
            {
                'state': state, 'label': labels.get(state, state), 'value': count,
                'pct': round(count / total * 100, 1),
                'color': colors.get(state, '#94a3b8'),
            }
            for state, count in sorted(counts.items(), key=lambda x: -x[1])
        ]

    # ── Bar: procedures by type ──────────────────────────────────────────
    def _dash_procedures_by_type(self, cases):
        counts = defaultdict(int)
        proc_ids = {}
        for c in cases:
            if c.procedure_id:
                counts[c.procedure_id.name] += 1
                proc_ids[c.procedure_id.name] = c.procedure_id.id
        rows = sorted(counts.items(), key=lambda x: -x[1])[:7]
        return [{'name': name, 'count': count, 'procedure_id': proc_ids[name]}
                for name, count in rows]

    # ── Horizontal bar: surgeon workload (current month) ────────────────
    def _dash_surgeon_workload(self, cases):
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)
        counts = defaultdict(int)
        surgeon_ids = {}
        for c in cases:
            if c.surgeon_id and c.surgery_date and c.surgery_date >= month_start:
                counts[c.surgeon_id.name] += 1
                surgeon_ids[c.surgeon_id.name] = c.surgeon_id.id
        rows = sorted(counts.items(), key=lambda x: -x[1])[:8]
        return [{'name': name, 'count': count, 'surgeon_id': surgeon_ids[name]}
                for name, count in rows]

    def _dash_week_calendar(self, cases, today):
        week_start = today - timedelta(days=today.weekday())
        days = [week_start + timedelta(days=i) for i in range(7)]
        LOCATION_LABELS = {'hospital': _('Hospital'), 'practice': _('Private Practice')}
        LOC_ORDER = ['hospital', 'practice', False]

        grid = defaultdict(lambda: defaultdict(int))
        seen = set()
        for c in cases:
            if c.surgery_date and week_start <= c.surgery_date <= days[-1]:
                loc_type = c.block_location_type or c.procedure_location_type or False
                grid[loc_type][c.surgery_date.isoformat()] += 1
                seen.add(loc_type)

        rows_order = [t for t in LOC_ORDER if t in seen]
        if not rows_order:
            return {
                'days': [d.isoformat() for d in days],
                'day_labels': [d.strftime('%a %d') for d in days],
                'rows': [{'location': _('No data'), 'loc_type': False,
                          'cells': [{'count': 0} for _ in range(7)]}],
            }

        return {
            'days': [d.isoformat() for d in days],
            'day_labels': [d.strftime('%a %d') for d in days],
            'rows': [
                {
                    'location': LOCATION_LABELS.get(t, _('Unassigned')),
                    'loc_type': t,
                    'cells': [{'count': grid[t].get(d.isoformat(), 0)} for d in days],
                }
                for t in rows_order
            ],
        }

    # ── Table: today's schedule ──────────────────────────────────────────
    def _dash_today_schedule(self, today_cases):
        rows = sorted(today_cases, key=lambda c: (c.surgery_time_slot or ''))
        return [{
            'id': c.id,
            # Only the slot's start time (e.g. "9:30") — not the
            # "9:30 – 10:00" range from surgery_time_slot_display.
            'time': c.surgery_time_slot or '-',
            'patient': c.patient_id.name or '-',
            'procedure': c.procedure_id.name or '-',
            'surgeon': c.surgeon_id.name or '-',
            'room': c.block_location_id.name or '-',
            'state': c.state,
        } for c in rows]

    # ── Table: upcoming admissions (next 7 days) ────────────────────────
    def _dash_upcoming_admissions(self, upcoming):
        rows = sorted(upcoming, key=lambda c: (c.surgery_date or fields.Date.today()))[:10]
        return [{
            'id': c.id,
            'date': c.surgery_date.isoformat() if c.surgery_date else '-',
            'patient': c.patient_id.name or '-',
            'procedure': c.procedure_id.name or '-',
            'surgeon': c.surgeon_id.name or '-',
            'state': c.state,
        } for c in rows]

    # ── Table: recent completed surgeries ───────────────────────────────
    def _dash_recent_completed(self, completed):
        rows = sorted(completed, key=lambda c: (c.surgery_date or fields.Date.today()), reverse=True)[:8]
        return [{
            'id': c.id,
            'date': c.surgery_date.isoformat() if c.surgery_date else '-',
            'patient': c.patient_id.name or '-',
            'procedure': c.procedure_id.name or '-',
            'surgeon': c.surgeon_id.name or '-',
        } for c in rows]

    # ── Table: pending post-op consultations ────────────────────────────
    def _dash_pending_postop(self, cases, today):
        Consult = self.env['clinic.postop.consult'].sudo()
        consults = Consult.search([
            ('surgery_case_id', 'in', cases.ids),
            ('consult_done', '=', False),
        ], order='planned_date', limit=8)
        return [{
            'id': c.id,
            'case_id': c.surgery_case_id.id,
            'date': c.planned_date.isoformat() if c.planned_date else '-',
            'patient': c.patient_id.name or '-',
            'procedure': c.surgery_case_id.procedure_id.name or '-',
            'surgeon': c.surgery_case_id.surgeon_id.name or '-',
            'overdue': bool(c.planned_date and c.planned_date < today),
        } for c in consults]

    # ── Pipeline ──────────────────────────────────────────────────────
    def _dash_pipeline(self, cases):
        return {
            'admission': len(cases.filtered(lambda c: c.state in ('draft', 'confirmed'))),
            'scheduled': len(cases.filtered(lambda c: c.state == 'planned')),
            'in_progress': len(cases.filtered(lambda c: c.state == 'in_progress')),
            'recovery': len(cases.filtered(lambda c: c.state in ('surgery_completed', 'post_follow_ups'))),
            'completed': len(cases.filtered(lambda c: c.state == 'done')),
        }

    # ── Alerts & notifications ───────────────────────────────────────────
    def _dash_alerts(self, cases, today):
        alerts = []
        at_risk = cases.filtered('surgery_at_risk')
        for c in at_risk[:5]:
            reason = c.surgery_at_risk_reason or _('Review required')
            surgery_date_str = c.surgery_date.strftime('%d %b %Y') if c.surgery_date else _('TBC')
            alerts.append({
                'id': f'risk-{c.id}',
                'case_id': c.id,
                'type': 'warning',
                'title': _('%s — At Risk') % c.name,
                'body': _('%(reason)s (surgery on %(date)s)') % {
                    'reason': reason, 'date': surgery_date_str,
                },
            })
        overdue_admissions = cases.filtered(
            lambda c: c.state == 'planned' and c.surgery_date and c.surgery_date < today)
        for c in overdue_admissions[:3]:
            alerts.append({
                'id': f'overdue-{c.id}',
                'case_id': c.id,
                'type': 'danger',
                'title': _('%s — Overdue') % c.name,
                'body': _('Surgery date %s has passed and the case is still Scheduled.') % (
                    c.surgery_date.strftime('%d %b %Y')
                ),
            })
        return alerts

    # ── Pending signatures ───────────────────────────────────────────────
    def _dash_pending_signatures(self, cases):
        SignRequest = self.env['sign.request'].sudo()
        requests = SignRequest.search([
            ('surgery_case_id', 'in', cases.ids),
        ])
        pending = requests.filtered(
            lambda r: any(item.state != 'completed' for item in r.request_item_ids)
        )[:8]
        return [{
            'id': r.id,
            'reference': r.reference,
            'case_id': r.surgery_case_id.id,
            'case_name': r.surgery_case_id.name,
            'pending_signers': ', '.join(
                item.partner_id.name
                for item in r.request_item_ids.filtered(lambda i: i.state != 'completed')
                if item.partner_id
            ) or False,
            'request_date': r.create_date.date().isoformat() if r.create_date else False,
        } for r in pending]

    @api.model
    def get_pending_postop_consult_ids(self, filters=None):
        domain = self._dashboard_build_domain(filters)
        cases = self.sudo().search(domain)
        Consult = self.env['clinic.postop.consult'].sudo()
        consults = Consult.search([
            ('surgery_case_id', 'in', cases.ids),
            ('consult_done', '=', False),
        ])
        return consults.ids

    @api.model
    def get_pending_sign_request_ids(self):
        SignRequest = self.env['sign.request'].sudo()
        requests = SignRequest.search([('surgery_case_id', '!=', False)])
        pending = requests.filtered(
            lambda r: any(item.state != 'completed' for item in r.request_item_ids)
        )
        return pending.ids

    # ── Upcoming activities ──────────────────────────────────────────────
    def _dash_upcoming_activities(self, cases):
        Activity = self.env['mail.activity'].sudo()
        activities = Activity.search([
            ('res_model', '=', 'clinic.surgery.case'),
            ('res_id', 'in', cases.ids),
        ], order='date_deadline', limit=8)
        return [{
            'id': a.id,
            'summary': a.summary or a.activity_type_id.name,
            'res_id': a.res_id,
            'date_deadline': a.date_deadline.isoformat() if a.date_deadline else '-',
        } for a in activities]

    # ── Bottom analytics strip ───────────────────────────────────────────
    # def _dash_analytics(self, cases, completed, prev=None):
    #     # Move = self.env['account.move'].sudo()
    #
    #     def compute(case_set, completed_set):
    #         # invoices = Move.search([
    #         #     ('surgery_case_id', 'in', case_set.ids),
    #         #     ('move_type', '=', 'out_invoice'),
    #         #     ('state', '=', 'posted'),
    #         # ])
    #         # revenue = sum(invoices.mapped('amount_total'))
    #
    #         durations = [c.surgery_duration_hours for c in case_set if c.surgery_duration_hours]
    #         avg_duration_hours = (sum(durations) / len(durations)) if durations else 0.0
    #
    #         recovery_days = []
    #         for c in completed_set:
    #             days_list = c.postop_consult_ids.mapped('days_after_surgery')
    #             if days_list:
    #                 recovery_days.append(max(days_list))
    #         avg_recovery = (sum(recovery_days) / len(recovery_days)) if recovery_days else 0.0
    #
    #         overnight_active = case_set.filtered(
    #             lambda c: c.admission_type in ('overnight', 'daycare')
    #             and c.state not in ('cancelled', 'done'))
    #         active_total = len(case_set.filtered(lambda c: c.state not in ('cancelled',))) or 1
    #         overnight_share = round(len(overnight_active) / active_total * 100)
    #
    #         cancelled_count = len(case_set.filtered(lambda c: c.state == 'cancelled'))
    #         completed_count = len(completed_set)
    #         denom = (completed_count + cancelled_count) or 1
    #         completion_rate = round(completed_count / denom * 100)
    #
    #         return {
    #             'revenue': revenue,
    #             'avg_duration_hours': avg_duration_hours,
    #             'avg_recovery_days': avg_recovery,
    #             'overnight_share_pct': overnight_share,
    #             'completion_rate_pct': completion_rate,
    #         }
    #
    #     curr = compute(cases, completed)
    #
    #     def pct_delta(now_val, prev_val):
    #         if prev_val:
    #             return round((now_val - prev_val) / prev_val * 100)
    #         return 100 if now_val else 0
    #
    #     deltas = {k: None for k in curr}
    #     if prev and prev.get('cases') is not None:
    #         prev_cases = prev['cases']
    #         prev_completed = prev_cases.filtered(lambda c: c.state == 'done')
    #         prior = compute(prev_cases, prev_completed)
    #         deltas = {k: pct_delta(curr[k], prior[k]) for k in curr}
    #
    #     return {
    #         'revenue': round(curr['revenue'], 2),
    #         'avg_duration_hours': round(curr['avg_duration_hours'], 2),
    #         'avg_recovery_days': round(curr['avg_recovery_days'], 1),
    #         'overnight_share_pct': curr['overnight_share_pct'],
    #         'completion_rate_pct': curr['completion_rate_pct'],
    #         'deltas': deltas,
    #     }

    # ── Invoices linked to a set of cases (self-healing) ──────────────────

    def _dash_case_invoices(self, cases):
        Move = self.env['account.move'].sudo()
        invoices = Move.search([
            ('surgery_case_id', 'in', cases.ids),
            ('move_type', '=', 'out_invoice'),
            ('state', '!=', 'cancel'),
        ])
        linked_ids = set(invoices.ids)
        to_backfill = Move.browse()
        for case in cases:
            legacy = case.invoice_ids.filtered(
                lambda m: m.id not in linked_ids
                and m.move_type == 'out_invoice'
                and m.state != 'cancel'
            )
            for m in legacy:
                if not m.surgery_case_id:
                    to_backfill |= m
                elif m.surgery_case_id.id != case.id:
                    # linked via invoice_ids to a different case than the
                    # one surgery_case_id points to — leave it alone,
                    # don't silently reassign, just surface it as-is.
                    invoices |= m
                    linked_ids.add(m.id)
        if to_backfill:
            # one invoice can only legitimately belong to one case, so this
            # is safe: we just set the field the search relies on.
            for m in to_backfill:
                owning_case = cases.filtered(lambda c: m.id in c.invoice_ids.ids)[:1]
                if owning_case:
                    m.surgery_case_id = owning_case.id
            invoices |= to_backfill
        return invoices.sorted(key=lambda m: (m.invoice_date or fields.Date.today(), m.id), reverse=True)

    # ── Financial overview: invoices & payments ──────────────────────────
    def _dash_financial(self, cases):
        today = fields.Date.context_today(self)
        invoices = self._dash_case_invoices(cases)
        PAID_STATES = ('paid', 'in_payment')
        PAYMENT_LABELS = {
            'paid': _('Paid'),
            'not_paid': _('Pending'),
            'partial': _('Partially Paid'),
            'in_payment': _('In Payment'),
            'reversed': _('Reversed'),
            'invoicing_legacy': _('Legacy'),
        }

        def is_overdue(inv):
            return bool(
                inv.payment_state not in PAID_STATES
                and inv.amount_residual > 0
                and inv.invoice_date_due
                and inv.invoice_date_due < today
            )

        overdue_invoices = invoices.filtered(is_overdue)

        total_invoiced = 0.0
        total_outstanding = 0.0
        rows = []
        for inv in invoices:
            if inv.payment_state in PAID_STATES:
                amount_paid = inv.amount_total
                amount_due = 0.0
            else:
                amount_paid = inv.amount_total - inv.amount_residual
                amount_due = inv.amount_residual
            total_invoiced += inv.amount_total
            total_outstanding += amount_due

            if len(rows) < 8:
                overdue = is_overdue(inv)
                rows.append({
                    'id': inv.id,
                    'number': inv.name or _('Draft'),
                    'case_id': inv.surgery_case_id.id,
                    'patient': inv.surgery_case_id.patient_id.name or inv.partner_id.name or '-',
                    'date': inv.invoice_date.isoformat() if inv.invoice_date else '-',
                    'due_date': inv.invoice_date_due.isoformat() if inv.invoice_date_due else '-',
                    'amount_total': inv.amount_total,
                    'amount_paid': round(amount_paid, 2),
                    'amount_due': round(amount_due, 2),
                    'payment_state': 'overdue' if overdue else inv.payment_state,
                    'payment_label': _('Overdue') if overdue else PAYMENT_LABELS.get(inv.payment_state, (inv.payment_state or '-').title()),
                })

        total_paid = total_invoiced - total_outstanding
        total_overdue = sum(overdue_invoices.mapped('amount_residual'))

        return {
            'total_invoiced': round(total_invoiced, 2),
            'total_paid': round(total_paid, 2),
            'total_outstanding': round(total_outstanding, 2),
            'total_overdue': round(total_overdue, 2),
            'invoice_count': len(invoices),
            'overdue_count': len(overdue_invoices),
            'rows': rows,
        }

    @api.model
    def get_invoice_ids(self, filters=None):
        domain = self._dashboard_build_domain(filters)
        cases = self.sudo().search(domain)
        invoices = self._dash_case_invoices(cases)
        return invoices.ids

    # ── Options for the filter dropdowns ─────────────────────────────────
    def _dash_filter_options(self, filters=None):
        # Surgeon list comes from the "Doctor" field configured on each
        # Surgery Procedure (clinic.surgery.procedure.surgeon_id) — this is
        # the authoritative list of surgeons the clinic works with, so a
        # surgeon shows up in the filter as soon as they're set on a
        # procedure, even before they have any surgery case yet.
        procedures = self.env['clinic.surgery.procedure'].sudo().search([])
        surgeons = procedures.mapped('surgeon_id').sorted(key=lambda u: u.name or '')
        blocks = self.env['clinic.operating.block'].sudo().search([])
        hospitals = blocks.mapped('location_id')
        return {
            'surgeons': [{'id': s.id, 'name': s.name} for s in surgeons],
            'procedures': [{'id': p.id, 'name': p.name} for p in procedures],
            'operating_blocks': [{'id': b.id, 'name': b.name} for b in blocks],
            'hospitals': [{'id': h.id, 'name': h.name} for h in hospitals],
            'patients': self._dash_patient_options(filters),
            'states': [
                {'id': 'draft', 'name': _('Draft')},
                {'id': 'confirmed', 'name': _('Confirmed')},
                {'id': 'planned', 'name': _('Scheduled')},
                {'id': 'in_progress', 'name': _('In Progress')},
                {'id': 'surgery_completed', 'name': _('Surgery Completed')},
                {'id': 'post_follow_ups', 'name': _('Post Follow-ups')},
                {'id': 'done', 'name': _('Done')},
                {'id': 'cancelled', 'name': _('Cancelled')},
            ],
        }

    # ── Patient dropdown options ──────────────────────────────────────────
    # Lists every patient who has at least one surgery case matching the
    # current filters — most importantly the selected date range — so the
    # dropdown only ever offers patients actually relevant to what's being
    # viewed, instead of requiring the user to type a name from memory.
    # The patient filter itself is excluded when building this list so
    # picking a patient doesn't collapse the dropdown down to just them.
    def _dash_patient_options(self, filters):
        filters = dict(filters or {})
        filters.pop('patient_id', None)
        domain = self._dashboard_build_domain(filters)
        cases = self.sudo().search(domain)
        patients = cases.mapped('patient_id').sorted(key=lambda p: p.name or '')
        return [{'id': p.id, 'name': p.name} for p in patients]

    # ══════════════════════════════════════════════════════════════════
    # CASE-LEVEL DASHBOARD — used by the "Dashboard" smart button on a
    # single Surgery Case. Purely additive: does not alter, call, or
    # depend on any of the main-dashboard aggregation above, and reads
    # only the one case requested (never leaks other cases' data).
    # ══════════════════════════════════════════════════════════════════
    @api.model
    def get_case_dashboard_data(self, case_id):
        case = self.sudo().browse(case_id)
        if not case.exists():
            return {}

        STATE_LABELS = {
            'draft': _('Draft'), 'confirmed': _('Confirmed'), 'planned': _('Scheduled'),
            'reschedule': _('Reschedule'), 'in_progress': _('In Progress'),
            'surgery_completed': _('Surgery Completed'),
            'post_follow_ups': _('Post Follow-up'), 'done': _('Done'),
            'cancelled': _('Cancelled'),
        }

        # Selection fields can define `selection` either as a static list of
        # (value, label) tuples or as a callable (common for related fields
        # like procedure_anesthesia_type) — fields_get() always resolves it
        # to a plain list either way, so use that instead of reading
        # `field.selection` directly.
        selection_fields = case.fields_get(['procedure_anesthesia_type', 'admission_type'])

        def selection_label(field_name, value):
            if not value:
                return False
            return dict(selection_fields[field_name]['selection']).get(value, value)

        # ── Case summary ────────────────────────────────────────────
        case_info = {
            'id': case.id,
            'name': case.name,
            'state': case.state,
            'state_label': STATE_LABELS.get(case.state, case.state),
            'patient': case.patient_id.name or '-',
            'patient_id': case.patient_id.id or False,
            'patient_email': case.patient_id.email or False,
            'patient_phone': case.patient_id.phone or False,
            'surgeon': case.surgeon_id.name or '-',
            'surgeon_id': case.surgeon_id.id or False,
            'surgeon_email': case.surgeon_id.partner_id.email or False,
            'surgeon_phone': case.surgeon_id.partner_id.phone or False,
            'secretary': case.secretary_id.name or '-',
            'secretary_id': case.secretary_id.id or False,
            'procedure': case.procedure_id.name or '-',
            'anesthesia': selection_label('procedure_anesthesia_type', case.procedure_anesthesia_type),
            'surgery_date': case.surgery_date.isoformat() if case.surgery_date else False,
            'hospital': case.hospital_location_id.name or '-',
            'at_risk': bool(case.surgery_at_risk),
            'at_risk_reason': case.surgery_at_risk_reason or False,
            'notes': html2plaintext(case.notes) if case.notes else '',
        }

        # ── Schedule & admission ─────────────────────────────────────
        schedule_info = {
            # Show only the slot's start time here (e.g. "9:30"). The full
            # "9:30 – 10:00" range lives in surgery_time_slot_display and is
            # used by the slot picker dropdown, not this read-only summary —
            # the End Time row below already covers the "10:00" part.
            'time_slot': case.surgery_time_slot or False,
            'end_time': case.surgery_end_time or False,
            'duration_hours': case.surgery_duration_hours or 0.0,
            'operating_block': case.operating_block_id.name or False,
            'admission_type': selection_label('admission_type', case.admission_type),
            'admission_point': case.admission_point_id.name or False,
        }

        # ── Additional (combined) procedures ─────────────────────────
        additional_procedures = [p.name for p in case.additional_procedure_ids]

        # ── Tasks (total / done / by secretary) ─────────────────────
        tasks = case.task_ids
        done_tasks = tasks.filtered(lambda t: t.state in ('1_done',))
        secretary_tasks = tasks.filtered(
            lambda t: 'secretary' in t.tag_ids.mapped('name')
            or (case.secretary_id and case.secretary_id in t.user_ids)
        )
        secretary_done = secretary_tasks.filtered(lambda t: t.state in ('1_done',))

        task_rows = [{
            'id': t.id,
            'name': t.name,
            'assignees': ', '.join(t.user_ids.mapped('name')) or '-',
            'deadline': t.date_deadline.isoformat() if t.date_deadline else False,
            'done': t.state in ('1_done',),
        } for t in tasks.sorted(key=lambda t: t.date_deadline or fields.Datetime.from_string('9999-12-31'), reverse=False)]

        # ── Brochures (from the procedure) ──────────────────────────
        info_brochures = case.procedure_id.info_brochures
        postop_brochures = case.procedure_id.postop_brochure_ids
        brochure_rows = (
            [{'id': a.id, 'name': a.name, 'kind': _('Info Brochure')} for a in info_brochures]
            + [{'id': a.id, 'name': a.name, 'kind': _('Post-op Brochure')} for a in postop_brochures]
        )

        # ── Consents / signatures ────────────────────────────────────
        sign_requests = case.sign_request_ids
        consent_rows = [{
            'id': r.id,
            'reference': r.reference,
            'completed': all(item.state == 'completed' for item in r.request_item_ids) if r.request_item_ids else False,
        } for r in sign_requests]

        # ── Post-op consults ──────────────────────────────────────────
        postop_rows = [{
            'id': p.id,
            'label': p.label,
            'planned_date': p.planned_date.isoformat() if p.planned_date else False,
            'done': bool(p.consult_done),
        } for p in case.postop_consult_ids.sorted(key=lambda p: p.planned_date or fields.Date.today())]

        # ── Financial (invoices linked to this case) ────────────────
        # Uses the same self-healing lookup as the main dashboard, so an
        # invoice linked only via the old invoice_ids field (surgery_case_id
        # left empty) is still found and shows up here too.
        invoices = self._dash_case_invoices(case)

        PAYMENT_LABELS = {
            'paid': _('Paid'), 'not_paid': _('Pending'), 'partial': _('Partially Paid'),
            'in_payment': _('In Payment'), 'reversed': _('Reversed'),
            'invoicing_legacy': _('Legacy'),
        }

        PAID_STATES = ('paid', 'in_payment')
        financial_rows = []
        total_invoiced = 0.0
        total_outstanding = 0.0
        for inv in invoices:
            if inv.payment_state in PAID_STATES:
                amount_paid = inv.amount_total
                amount_due = 0.0
            else:
                amount_paid = round(inv.amount_total - inv.amount_residual, 2)
                amount_due = round(inv.amount_residual, 2)
            total_invoiced += inv.amount_total
            total_outstanding += amount_due
            financial_rows.append({
                'id': inv.id,
                'number': inv.name or _('Draft'),
                'date': inv.invoice_date.isoformat() if inv.invoice_date else False,
                'amount_total': inv.amount_total,
                'amount_paid': amount_paid,
                'amount_due': amount_due,
                'payment_state': inv.payment_state,
                'payment_label': PAYMENT_LABELS.get(inv.payment_state, (inv.payment_state or '-').title()),
            })

        financial_detail = {
            'doctor_fee': case.doctor_fee,
            'hospital_fee': case.hospital_fee,
            'expected_settlement': case.expected_settlement,
            'hospital_fee_paid': bool(case.hospital_fee_paid),
            'honorarium_paid': bool(case.honorarium_paid),
            'is_reimbursed_surgery': bool(case.is_reimbursed_surgery),
            'reimbursed_supplement_description': case.reimbursed_supplement_description or False,
            'reimbursed_supplement_amount': case.reimbursed_supplement_amount or 0.0,
        }

        return {
            'case': case_info,
            'schedule': schedule_info,
            'additional_procedures': additional_procedures,
            'kpis': {
                'tasks_total': len(tasks),
                'tasks_done': len(done_tasks),
                'secretary_total': len(secretary_tasks),
                'secretary_done': len(secretary_done),
                'brochure_count': len(brochure_rows),
                'consent_count': len(sign_requests),
                'consent_signed': bool(consent_rows) and all(r['completed'] for r in consent_rows),
                'invoice_count': len(invoices),
            },
            'tasks': {'rows': task_rows},
            'brochures': {'rows': brochure_rows, 'sent': bool(case.info_brochure_sent)},
            'consents': {'rows': consent_rows},
            'postop': {'rows': postop_rows},
            'financial': {
                'total_invoiced': round(total_invoiced, 2),
                'total_paid': round(total_invoiced - total_outstanding, 2),
                'total_outstanding': round(total_outstanding, 2),
                'rows': financial_rows,
                'detail': financial_detail,
            },
        }

    # NOTE: the old free-text "search patient by name" endpoint
    # (dashboard_search_patients) has been replaced by the Patient filter
    # dropdown, which is now populated from _dash_patient_options() as part
    # of get_dashboard_data()/_dash_filter_options() above.
