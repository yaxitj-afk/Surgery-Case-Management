/** @odoo-module **/

import {registry} from "@web/core/registry";
import {useService} from "@web/core/utils/hooks";
import {browser} from "@web/core/browser/browser";
import {router} from "@web/core/browser/router";
import {Component, useState, onWillStart} from "@odoo/owl";
import {_t} from "@web/core/l10n/translation";

const DASH_FILTERS_STORAGE_KEY = "surgery_case_management.dashboard_filters";
const DASH_LAST_CASE_STORAGE_KEY = "surgery_case_management.dashboard_last_case_id";

let isFirstMountSincePageLoad = true;

const STATE_LABELS = {
    draft: _t("Draft"),
    confirmed: _t("Confirmed"),
    planned: _t("Scheduled"),
    in_progress: _t("In Progress"),
    surgery_completed: _t("Surgery Completed"),
    post_follow_ups: _t("Post Follow-ups"),
    done: _t("Done"),
    cancelled: _t("Cancelled"),
};
const PROCEDURE_BAR_COLORS = [
    "#4f76c5", "#e3991a", "#309e78", "#46a2cc",
    "#8b5cf6", "#ec4899", "#14b8a6", "#f97316",
];

const STATE_BADGE_CLASS = {
    draft: "sd-badge-grey",
    confirmed: "sd-badge-blue",
    planned: "sd-badge-blue",
    in_progress: "sd-badge-amber",
    surgery_completed: "sd-badge-teal",
    post_follow_ups: "sd-badge-purple",
    done: "sd-badge-teal",
    cancelled: "sd-badge-red",
};

export class SurgeryDashboard extends Component {
    static template = "surgery_case_management.SurgeryDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        const actionParams = (this.props.action && this.props.action.params) || {};
        let caseId = actionParams.case_id || false;
        if (!caseId && router.current && router.current.case_id) {
            caseId = parseInt(router.current.case_id, 10) || false;
        }

        const isPageReload = isFirstMountSincePageLoad &&
            window.performance &&
            window.performance.getEntriesByType &&
            window.performance.getEntriesByType("navigation")[0] &&
            window.performance.getEntriesByType("navigation")[0].type === "reload";
        isFirstMountSincePageLoad = false;
        if (!caseId && isPageReload) {
            const savedCaseId = browser.sessionStorage.getItem(DASH_LAST_CASE_STORAGE_KEY);
            if (savedCaseId) {
                caseId = parseInt(savedCaseId, 10) || false;
            }
        }
        this.caseId = caseId;

        if (this.caseId) {
            browser.sessionStorage.setItem(DASH_LAST_CASE_STORAGE_KEY, String(this.caseId));
        } else {
            browser.sessionStorage.removeItem(DASH_LAST_CASE_STORAGE_KEY);
        }

        const defaultFilters = {
            date_from: this._monthsAgo(1),
            date_to: this._today(),
            surgeon_id: false,
            operating_block_id: false,
            procedure_id: false,
            state: false,
            hospital_id: false,
            patient_id: false,
        };
        const persisted = this.caseId ? null : this._loadPersistedState();

        this.state = useState({
            loading: true,
            data: null,
            filters: (persisted && persisted.filters) || defaultFilters,
            caseMode: !!this.caseId,
            caseData: null,
            noteText: "",
            postingNote: false,
        });

        onWillStart(async () => {
            if (this.caseId) {
                router.pushState({case_id: this.caseId});
                await this.loadCaseData();
            } else {
                // Make sure a stale case_id from a previous visit doesn't
                // leak into the main dashboard's URL.
                router.pushState({case_id: undefined});
                await this.loadData();
            }
        });
    }

    // ── filter persistence (sessionStorage) ─────────────────────────────
    // Keeps date range / dropdown filters intact when navigating into a
    // record and back to the dashboard (breadcrumb), since Owl destroys
    // and recreates this component on every navigation.
    _loadPersistedState() {
        try {
            const raw = browser.sessionStorage.getItem(DASH_FILTERS_STORAGE_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch {
            return null;
        }
    }

    _persistState() {
        try {
            browser.sessionStorage.setItem(
                DASH_FILTERS_STORAGE_KEY,
                JSON.stringify({
                    filters: this.state.filters,
                })
            );
        } catch {
            // sessionStorage unavailable (e.g. private browsing) — ignore.
        }
    }

    // ── date helpers ──────────────────────────────────────────────────
    _today() {
        return new Date().toISOString().slice(0, 10);
    }

    _monthsAgo(n) {
        const d = new Date();
        d.setMonth(d.getMonth() - n);
        return d.toISOString().slice(0, 10);
    }

    stateLabel(s) {
        return STATE_LABELS[s] || s;
    }

    stateBadgeClass(s) {
        return STATE_BADGE_CLASS[s] || "sd-badge-grey";
    }

    // ── formatting helpers ───────────────────────────────────────────
    maxWorkload() {
        const rows = (this.state.data && this.state.data.surgeon_workload) || [];
        return Math.max(1, ...rows.map((r) => r.count));
    }

    barWidthPct(count) {
        return Math.round((count / this.maxWorkload()) * 100);
    }

    formatDuration(hours) {
        if (!hours) return "-";
        const h = Math.floor(hours);
        const m = Math.round((hours - h) * 60);
        return m ? `${h}h ${m}m` : `${h}h`;
    }

    formatDate(dateStr) {
        if (!dateStr || dateStr === "-") return "-";
        const d = new Date(dateStr);
        return d.toLocaleDateString(undefined, {day: "2-digit", month: "short", year: "numeric"});
    }

    formatMoney(v) {
        if (v === undefined || v === null) return "-";
        return "€" + Number(v).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
    }

    // ── data loading ──────────────────────────────────────────────────
    async loadData() {
        this.state.loading = true;
        const data = await this.orm.call(
            "clinic.surgery.case",
            "get_dashboard_data",
            [],
            {filters: {...this.state.filters}}
        );
        this.state.data = data;
        this.state.loading = false;
        this._persistState();
    }

    async onFilterChange(key, ev) {
        let value = ev.target.value;
        if (value === "") {
            value = false;
        } else if (["surgeon_id", "operating_block_id", "procedure_id", "hospital_id", "patient_id"].includes(key)) {
            value = value ? parseInt(value, 10) : false;
        }
        this.state.filters[key] = value;
        await this.loadData();
    }

    async resetFilters() {
        Object.assign(this.state.filters, {
            date_from: this._monthsAgo(1),
            date_to: this._today(),
            surgeon_id: false,
            operating_block_id: false,
            procedure_id: false,
            state: false,
            hospital_id: false,
            patient_id: false,
        });
        await this.loadData();
    }

    async refresh() {
        if (this.caseId) {
            await this.loadCaseData();
        } else {
            await this.loadData();
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // CASE-LEVEL DASHBOARD (opened from a Surgery Case smart button)
    // Purely additive: only used when this.caseId is set.
    // ══════════════════════════════════════════════════════════════════
    async loadCaseData() {
        this.state.loading = true;
        const data = await this.orm.call(
            "clinic.surgery.case",
            "get_case_dashboard_data",
            [this.caseId]
        );
        this.state.caseData = data;
        // Quick Note mirrors the case's "Notes" tab (the `notes` field) —
        // prefill it with whatever is already there so edits made here
        // and edits made on the form view stay in sync.
        this.state.noteText = (data && data.case && data.case.notes) || "";
        this.state.loading = false;
    }

    backToSurgery() {
        router.pushState({case_id: undefined});
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "clinic.surgery.case",
            res_id: this.caseId,
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    openTask(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.task",
            res_id: id,
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    openCasePatient() {
        const id = this.state.caseData && this.state.caseData.case && this.state.caseData.case.patient_id;
        if (!id) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: id,
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    openCaseUser(userId) {
        if (!userId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "res.users",
            res_id: userId,
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    // Previously this opened the documents.document *record form* (a dialog
    // with Name / URL / Folder fields and Save & Discard buttons) — that's
    // Odoo's generic edit form for the Documents app, not a viewer, so
    // clicking a brochure looked like it was asking you to edit/create a
    // document instead of just showing you the PDF. Open the file itself
    // instead: a link-type document goes to its external URL, everything
    // else opens/downloads its actual content in a new tab.
    async openBrochure(id) {
        if (!id) return;
        let doc;
        try {
            [doc] = await this.orm.read("documents.document", [id], ["type", "url", "name"]);
        } catch {
            doc = null;
        }
        if (doc && doc.type === "url" && doc.url) {
            window.open(doc.url, "_blank");
        } else {
            const filename = (doc && doc.name) || "";
            window.open(
                `/web/content/documents.document/${id}/datas?download=false&filename=${encodeURIComponent(filename)}`,
                "_blank"
            );
        }
    }

    scrollToSchedule() {
        const el = document.getElementById("scd-schedule-panel");
        if (el) {
            el.scrollIntoView({behavior: "smooth", block: "start"});
            el.classList.add("scd-panel-flash");
            browser.setTimeout(() => el.classList.remove("scd-panel-flash"), 900);
        }
    }

    // Escapes text before it goes into the HTML `notes` field, so the note
    // can never inject markup — line breaks are preserved as <br/>.
    _textToNotesHtml(text) {
        const div = document.createElement("div");
        div.textContent = text;
        const escaped = div.innerHTML;
        return "<p>" + escaped.split("\n").join("<br/>") + "</p>";
    }

    async postQuickNote() {
        const body = (this.state.noteText || "").trim();
        if (!body || this.state.postingNote) return;
        this.state.postingNote = true;
        try {
            await this.orm.write(
                "clinic.surgery.case",
                [this.caseId],
                {notes: this._textToNotesHtml(body)}
            );
            await this.loadCaseData();
            this.notification.add(_t("Note saved."), {type: "success"});
        } catch {
            this.notification.add(_t("Could not save the note. Please try again."), {type: "danger"});
        } finally {
            this.state.postingNote = false;
        }
    }

    openCaseNewTask() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "New Task",
            res_model: "project.task",
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
            context: {default_surgery_case_id: this.caseId},
        });
    }

    openCaseTasks(doneOnly = false) {
        const domain = [["surgery_case_id", "=", this.caseId]];
        if (doneOnly) domain.push(["state", "=", "1_done"]);
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Tasks",
            res_model: "project.task",
            view_mode: "list,form,kanban",
            views: [[false, "list"], [false, "form"], [false, "kanban"]],
            domain,
        });
    }

    openCaseConsents() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Consent Documents",
            res_model: "sign.request",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [["surgery_case_id", "=", this.caseId]],
        });
    }

    openCaseInvoices() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Invoices",
            res_model: "account.move",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [["surgery_case_id", "=", this.caseId]],
        });
    }

    // ── Case Readiness checklist (fills the sidebar — built entirely from
    // data already loaded for the KPI cards / brochures / consents /
    // post-op / financial panels, so no extra server round-trip) ────────
    caseReadinessItems() {
        const c = this.state.caseData;
        if (!c) return [];
        const k = c.kpis || {};
        const postopRows = (c.postop && c.postop.rows) || [];
        const postopDone = postopRows.filter((r) => r.done).length;
        const outstanding = (c.financial && c.financial.total_outstanding) || 0;
        return [
            {
                icon: "fa-tasks",
                label: "Tasks",
                done: !!k.tasks_total && k.tasks_done === k.tasks_total,
                detail: `${k.tasks_done || 0}/${k.tasks_total || 0} done`,
            },
            {
                icon: "fa-user",
                label: "Secretary Tasks",
                done: !!k.secretary_total && k.secretary_done === k.secretary_total,
                detail: `${k.secretary_done || 0}/${k.secretary_total || 0} done`,
            },
            {
                icon: "fa-file-pdf-o",
                label: "Brochures",
                done: !!(c.brochures && c.brochures.sent),
                detail: c.brochures && c.brochures.sent ? "Sent to patient" : "Not sent yet",
            },
            {
                icon: "fa-pencil-square-o",
                label: "Consent",
                done: !!k.consent_signed,
                detail: !k.consent_count ? "Not requested" : (k.consent_signed ? "Signed" : "Pending signature"),
            },
            {
                icon: "fa-stethoscope",
                label: "Post-Op Consults",
                done: !!postopRows.length && postopDone === postopRows.length,
                detail: postopRows.length ? `${postopDone}/${postopRows.length} done` : "Not scheduled",
            },
            {
                icon: "fa-eur",
                label: "Invoice",
                done: !!k.invoice_count && outstanding <= 0,
                detail: !k.invoice_count ? "Not invoiced yet" : (outstanding > 0 ? `${this.formatMoney(outstanding)} due` : "Fully paid"),
            },
        ];
    }

    caseReadinessPct() {
        const items = this.caseReadinessItems();
        if (!items.length) return 0;
        return Math.round((items.filter((i) => i.done).length / items.length) * 100);
    }

    // ── Next Post-Op Consult reminder ────────────────────────────────────
    nextPostopConsult() {
        const c = this.state.caseData;
        const rows = (c && c.postop && c.postop.rows) || [];
        return rows.find((r) => !r.done) || null;
    }

    postopCountdownLabel(dateStr) {
        if (!dateStr) return "Date TBD";
        const target = new Date(dateStr);
        target.setHours(0, 0, 0, 0);
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const diffDays = Math.round((target - today) / 86400000);
        if (diffDays === 0) return "Today";
        if (diffDays === 1) return "Tomorrow";
        if (diffDays > 1) return `In ${diffDays} days`;
        return diffDays === -1 ? "1 day overdue" : `${Math.abs(diffDays)} days overdue`;
    }

    // ── navigation helpers ────────────────────────────────────────────
    _baseDomain(opts = {}) {
        const f = this.state.filters;
        const domain = [];
        if (!opts.excludeDateRange) {
            if (f.date_from) domain.push(["surgery_date", ">=", f.date_from]);
            if (f.date_to) domain.push(["surgery_date", "<=", f.date_to]);
        }
        if (f.surgeon_id) domain.push(["surgeon_id", "=", f.surgeon_id]);
        if (f.operating_block_id) domain.push(["operating_block_id", "=", f.operating_block_id]);
        if (f.procedure_id) domain.push(["procedure_id", "=", f.procedure_id]);
        if (f.state) domain.push(["state", "=", f.state]);
        if (f.hospital_id) domain.push(["hospital_location_id", "=", f.hospital_id]);
        if (f.patient_id) domain.push(["patient_id", "=", f.patient_id]);
        return domain;
    }

    openCases(extraDomain, name, opts = {}) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name || _t("Surgery Cases"),
            res_model: "clinic.surgery.case",
            view_mode: "kanban,list,form,calendar",
            views: [
                [false, "kanban"],
                [false, "list"],
                [false, "form"],
                [false, "calendar"],
            ],
            domain: [...this._baseDomain(opts), ...(extraDomain || [])],
        });
    }

    // AFTER
    trendStats() {
        const trend = (this.state.data && this.state.data.trend) || [];
        if (!trend.length) return {current: 0, avg: 0, peakLabel: "-", peakValue: 0};

        const todayKey = this._today().slice(0, 7); // "YYYY-MM"
        const thisMonthBucket = trend.find((t) => t.date_from && t.date_from.slice(0, 7) === todayKey);
        const current = thisMonthBucket ? thisMonthBucket.count : 0;

        const total = trend.reduce((s, t) => s + t.count, 0);
        const avg = Math.round((total / trend.length) * 10) / 10;
        const peak = trend.reduce((a, b) => (b.count > a.count ? b : a), trend[0]);
        return {current, avg, peakLabel: peak.label, peakValue: peak.count};
    }

    _daysFromToday(n) {
        const d = new Date();
        d.setDate(d.getDate() + n);
        return d.toISOString().slice(0, 10);
    }

    openCaseForm(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "clinic.surgery.case",
            res_id: id,
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    openPostopConsult(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "clinic.postop.consult",
            res_id: id,
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    openSignRequest(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sign.request",
            res_id: id,
            view_mode: "form",
            views: [[false, "form"]],
            target: "new",
        });
    }

    async openAllSignRequests() {
        const ids = await this.orm.call(
            "clinic.surgery.case",
            "get_pending_sign_request_ids",
            []
        );
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Pending Signatures"),
            res_model: "sign.request",
            view_mode: "list,form",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: [["id", "in", ids]],
        });
    }

    openActivity(resId) {
        this.openCaseForm(resId);
    }

    // View All → Alerts & Notifications (at-risk + overdue-scheduled cases)
    onViewAllAlerts() {
        const today = this._today();
        this.openCases(
            [
                "|",
                ["surgery_at_risk", "=", true],
                "&", ["state", "=", "planned"], ["surgery_date", "<", today],
            ],
            _t("Alerts & Notifications"),
            {excludeDateRange: true}
        );
    }

    // View All → Pending Post-Op Consultations
    async openPostopConsultList() {
        const ids = await this.orm.call(
            "clinic.surgery.case",
            "get_pending_postop_consult_ids",
            [],
            {filters: {...this.state.filters}}
        );
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Pending Post-Op Consultations"),
            res_model: "clinic.postop.consult",
            view_mode: "list,form",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: [["id", "in", ids]],
        });
    }

    // ── Financial (invoices & payments) ─────────────────────────────────
    openInvoice(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "account.move",
            res_id: id,
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    async openAllInvoices() {
        const ids = await this.orm.call(
            "clinic.surgery.case",
            "get_invoice_ids",
            [],
            {filters: {...this.state.filters}}
        );
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Surgery Invoices"),
            res_model: "account.move",
            view_mode: "list,form",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: [["id", "in", ids]],
        });
    }

    paymentBadgeClass(state) {
        const map = {
            paid: "sd-badge-teal",
            not_paid: "sd-badge-amber",
            partial: "sd-badge-blue",
            in_payment: "sd-badge-blue",
            overdue: "sd-badge-red",
            reversed: "sd-badge-grey",
            invoicing_legacy: "sd-badge-grey",
        };
        return map[state] || "sd-badge-grey";
    }

    // ── KPI card click handlers ───────────────────────────────────────
    onKpiClick(kind) {
        const today = this._today();
        switch (kind) {
            case "total":
                return this.openCases([], _t("Total Surgery Cases"));
            case "today":
                return this.openCases([["surgery_date", "=", today]], _t("Today's Surgeries"));
            case "upcoming":
                return this.openCases(
                    [
                        ["state", "in", ["draft", "confirmed", "planned", "reschedule", "in_progress"]],
                        ["surgery_date", ">=", today],
                    ],
                    _t("Upcoming Surgeries"),
                    {excludeDateRange: true}
                );
            case "completed":
                return this.openCases([["state", "=", "done"]], _t("Completed Cases"));
            case "cancelled":
                return this.openCases([["state", "=", "cancelled"]], _t("Cancelled Cases"));
            case "reimbursed":
                return this.openCases([["is_reimbursed_surgery", "=", true]], _t("Reimbursed Surgeries"));
            case "surgery_completed":
                return this.openCases([["state", "=", "surgery_completed"]], _t("Surgery Completed Cases"));
        }
    }

    onStatusSliceClick(state, label) {
        if (state) this.openCases([["state", "in", [state]]], label);
    }

    onProcedureBarClick(procedureId, name) {
        this.openCases([["procedure_id", "=", procedureId]], name);
    }

    onSurgeonBarClick(surgeonId, name) {
        this.openCases([["surgeon_id", "=", surgeonId]], name);
    }

    onCalendarCellClick(location, locType, dateStr) {
        const extraDomain = [["surgery_date", "=", dateStr]];
        if (locType) {
            extraDomain.push(["block_location_type", "=", locType]);
        }
        this.openCases(extraDomain, _t("%s — %s", location, dateStr));
    }

    // ── Week calendar cell shading ───────────────────────────────────────
    // Cells are shaded purely by how busy they are (a simple intensity
    // scale), not by surgery status — the earlier blue/orange/green/red
    // status-color legend has been removed per requirements.
    calMaxCount() {
        const wc = (this.state.data && this.state.data.week_calendar) || {};
        let max = 0;
        (wc.rows || []).forEach((row) =>
            (row.cells || []).forEach((c) => {
                if (c.count > max) max = c.count;
            })
        );
        return max || 1;
    }

    calCellClass(count) {
        if (!count) return "";
        const ratio = count / this.calMaxCount();
        if (ratio > 0.75) return "sd-cal-cell-4";
        if (ratio > 0.5) return "sd-cal-cell-3";
        if (ratio > 0.25) return "sd-cal-cell-2";
        return "sd-cal-cell-1";
    }

    workloadStats() {
        const rows = (this.state.data && this.state.data.surgeon_workload) || [];
        const total = rows.reduce((s, r) => s + r.count, 0);
        return {total, surgeons: rows.length};
    }

    weekCalendarStats() {
        const wc = (this.state.data && this.state.data.week_calendar) || {};
        const rows = wc.rows || [];
        const dayLabels = wc.day_labels || [];
        const perDay = new Array(dayLabels.length).fill(0);
        let total = 0;

        const locations = rows.map((row) => {
            const count = (row.cells || []).reduce((s, c) => s + (c.count || 0), 0);
            (row.cells || []).forEach((c, idx) => {
                perDay[idx] = (perDay[idx] || 0) + (c.count || 0);
            });
            total += count;
            return {name: row.location, count};
        });

        let busiestIdx = -1, busiestValue = 0;
        perDay.forEach((v, idx) => {
            if (v > busiestValue) {
                busiestValue = v;
                busiestIdx = idx;
            }
        });

        locations.forEach((loc) => {
            loc.pct = total ? Math.round((loc.count / total) * 100) : 0;
        });

        return {
            total,
            busiestLabel: busiestIdx >= 0 ? dayLabels[busiestIdx] : "—",
            busiestValue,
            locations,
        };
    }

    workloadSharePct(count) {
        const total = (this.state.data && this.state.data.surgeon_workload || []).reduce((s, r) => s + r.count, 0);
        return total ? Math.round((count / total) * 100) : 0;
    }

    initials(name) {
        if (!name) return "?";
        return name.split(" ").filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join("");
    }

    // ── Pipeline (stage totals + per-stage share, used by the progress bars) ──
    pipelineTotal() {
        const p = (this.state.data && this.state.data.pipeline) || {};
        return ["admission", "scheduled", "in_progress", "recovery", "completed"]
            .reduce((sum, key) => sum + (p[key] || 0), 0);
    }

    pipelinePct(count) {
        const total = this.pipelineTotal();
        return total ? Math.round(((count || 0) / total) * 100) : 0;
    }

    onPipelineClick(stage) {
        const domainByStage = {
            admission: [["state", "in", ["draft", "confirmed"]]],
            scheduled: [["state", "=", "planned"]],
            in_progress: [["state", "=", "in_progress"]],
            recovery: [["state", "in", ["surgery_completed", "post_follow_ups"]]],
            completed: [["state", "=", "done"]],
        };
        this.openCases(domainByStage[stage] || [], _t("Surgery Progress"));
    }

    // ── quick actions ─────────────────────────────────────────────────
    quickNewSurgery() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("New Surgery Case"),
            res_model: "clinic.surgery.case",
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    quickNewPatient() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("New Patient"),
            res_model: "res.partner",
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
            context: {default_is_company: false},
        });
    }

    quickScheduleSurgery() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Schedule Surgery"),
            res_model: "clinic.surgery.case",
            view_mode: "calendar,list,form",
            views: [
                [false, "calendar"],
                [false, "list"],
                [false, "form"],
            ],
        });
    }

    quickPostopConsultation() {
        this.action.doAction("surgery_case_management.action_clinic_postop_consult_calendar");
    }

    // ── SVG line chart geometry (monthly trend) ─────────────────────────
    // ── SVG line chart geometry (monthly trend) ─────────────────────────
    lineChartPoints() {
        const trend = (this.state.data && this.state.data.trend) || [];
        const w = 560, h = 200, padX = 34, padY = 20;
        const rawMax = Math.max(1, ...trend.map((t) => t.count));
        const {niceMax} = this._axisTicks(rawMax, 4);
        const n = trend.length || 1;
        const stepX = (w - padX * 2) / Math.max(1, n - 1);
        return trend.map((t, i) => ({
            x: Math.round(padX + i * stepX),
            y: Math.round(h - padY - (t.count / niceMax) * (h - padY * 2)),
            label: t.label,
            count: t.count,
            dateFrom: t.date_from,
            dateTo: t.date_to,
        }));
    }

    lineChartYTicks() {
        const trend = (this.state.data && this.state.data.trend) || [];
        const rawMax = Math.max(1, ...trend.map((t) => t.count));
        const {ticks, niceMax} = this._axisTicks(rawMax, 4);
        const h = 200, padY = 20;
        return ticks.map((v) => ({
            value: v,
            y: Math.round(h - padY - (v / niceMax) * (h - padY * 2)),
        }));
    }

    lineChartPolyline() {
        return this.lineChartPoints().map((p) => `${p.x},${p.y}`).join(" ");
    }

    lineChartAreaPath() {
        const pts = this.lineChartPoints();
        if (!pts.length) return "";
        const h = 200, padY = 20;
        const first = pts[0], last = pts[pts.length - 1];
        const line = pts.map((p) => `${p.x},${p.y}`).join(" L ");
        return `M ${first.x},${h - padY} L ${line} L ${last.x},${h - padY} Z`;
    }

    onLinePointClick(dateFrom, dateTo, label) {
        this.openCases(
            [["surgery_date", ">=", dateFrom], ["surgery_date", "<=", dateTo]],
            _t("Surgeries — %s", label),
            {excludeDateRange: true}
        );
    }

    // ── SVG donut chart geometry (status distribution) ─────────────────
    donutSegments() {
        const dist = (this.state.data && this.state.data.status_distribution) || [];
        const r = 60, circumference = 2 * Math.PI * r;
        let offset = 0;
        const segments = [];
        for (const d of dist) {
            const len = (d.pct / 100) * circumference;
            segments.push({
                state: d.state,
                color: d.color,
                label: d.label,
                value: d.value,
                pct: d.pct,
                dasharray: `${len} ${circumference - len}`,
                dashoffset: -offset,
            });
            offset += len;
        }
        return segments;
    }

    // ── shared axis-scale helper (rounds max to a "nice" number so the
    // y-axis reads 0/20/40/60/80 instead of 0/32/45/71...) ──────────────
    _niceStep(rawStep) {
        if (!rawStep || rawStep <= 0) return 1;
        const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
        const residual = rawStep / magnitude;
        let niceResidual;
        if (residual <= 1) niceResidual = 1;
        else if (residual <= 2) niceResidual = 2;
        else if (residual <= 5) niceResidual = 5;
        else niceResidual = 10;
        return niceResidual * magnitude;
    }

    _axisTicks(rawMax, count = 4) {
        const step = this._niceStep(rawMax / count) || 1;
        const niceMax = step * count;
        const ticks = [];
        for (let i = 0; i <= count; i++) ticks.push(step * i);
        return {ticks, niceMax};
    }

    // ── Bar chart geometry (procedures by type) ─────────────────────────
    procedureBars() {
        const rows = (this.state.data && this.state.data.procedures_by_type) || [];
        const rawMax = Math.max(1, ...rows.map((r) => r.count));
        const {niceMax} = this._axisTicks(rawMax, 4);
        const w = 560, h = 200, padX = 34, padY = 20, gap = 14;
        const n = rows.length || 1;
        const barW = (w - padX * 2 - gap * (n - 1)) / n;
        return rows.map((r, i) => {
            const barH = Math.round((r.count / niceMax) * (h - padY * 2));
            return {
                ...r,
                x: Math.round(padX + i * (barW + gap)),
                y: Math.round(h - padY - barH),
                width: Math.round(barW),
                height: barH,
                labelY: h - 4,
                color: PROCEDURE_BAR_COLORS[i % PROCEDURE_BAR_COLORS.length],
            };
        });
    }

    procedureYTicks() {
        const rows = (this.state.data && this.state.data.procedures_by_type) || [];
        const rawMax = Math.max(1, ...rows.map((r) => r.count));
        const {ticks, niceMax} = this._axisTicks(rawMax, 4);
        const h = 200, padY = 20;
        return ticks.map((v) => ({
            value: v,
            y: Math.round(h - padY - (v / niceMax) * (h - padY * 2)),
        }));
    }

    procedureStats() {
        const rows = (this.state.data && this.state.data.procedures_by_type) || [];
        const total = rows.reduce((s, r) => s + r.count, 0);
        const top = rows[0];
        return {
            total,
            topName: top ? top.name : "-",
            topPct: top && total ? Math.round((top.count / total) * 100) : 0,
        };
    }
}

registry.category("actions").add("surgery_dashboard", SurgeryDashboard);
