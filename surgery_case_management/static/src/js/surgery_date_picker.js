/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onMounted, onWillUpdateProps, onWillUnmount, useState, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const { DateTime } = luxon;

class SurgeryDatePickerWidget extends Component {

    static template = "surgery_case_management.SurgeryDatePicker";

    static props = { ...standardFieldProps };

    static fieldDependencies = [
        { name: "available_surgery_dates", type: "text" },
        { name: "surgeon_id", type: "many2one", relation: "res.users" },
        { name: "procedure_id", type: "many2one", relation: "clinic.surgery.procedure" },
        { name: "procedure_location_type", type: "selection" },
    ];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.wrapperRef = useRef("wrapper");
        this._lastLoadedSurgeonId      = null;  // tracks surgeon used in last _loadDates call
        this._lastLoadedLocationType   = null;  // tracks location type used in last _loadDates call
        this._wasDirty = false;  // tracks dirty state across props updates

        const today = new Date();
        this.state = useState({
            availableDates: [],
            dateMap: {},
            selectedDate: null,
            currentYear: today.getFullYear(),
            currentMonth: today.getMonth(),
            isOpen: false,
            loading: false,
            noSurgeon: true,
            noDates: false,
            locationFilterWarning: null,
        });

        // Click-outside to close calendar
        this._onDocumentClick = (ev) => {
            if (!this.state.isOpen) return;
            const wrapper = this.wrapperRef.el;
            if (wrapper && !wrapper.contains(ev.target)) {
                this.state.isOpen = false;
            }
        };

        onMounted(async () => {
            document.addEventListener("mousedown", this._onDocumentClick, true);
            const surgeonId = this.props.record.data.surgeon_id?.id;
            this.state.noSurgeon = !surgeonId;
            if (surgeonId) {
                await this._loadDates(this.props);
            }
            // Sync selected date from existing field value on mount
            this._syncSelectedDate(this.props);
        });

        onWillUnmount(() => {
            document.removeEventListener("mousedown", this._onDocumentClick, true);
        });

        onWillUpdateProps(async (nextProps) => {
            const oldSurgeon     = this.props.record.data.surgeon_id?.id;
            const newSurgeon     = nextProps.record.data.surgeon_id?.id;
            const oldProcLocType = this.props.record.data.procedure_location_type;
            const newProcLocType = nextProps.record.data.procedure_location_type;
            const oldAvail       = this.props.record.data.available_surgery_dates;
            const newAvail       = nextProps.record.data.available_surgery_dates;

            // Track record ID to detect first-save (new record gets an ID).
            // Also track resId directly — on save it goes from undefined/false → integer.
            const oldResId = this.props.record.resId;
            const newResId = nextProps.record.resId;
            const justGotId = !oldResId && !!newResId;  // new record just saved

            // Detect save of existing record: record had changes, now it doesn't.
            // We store a flag on the instance so we know when we were dirty.
            if (this.props.record.isDirty) {
                this._wasDirty = true;
            }
            const justSaved = this._wasDirty && !nextProps.record.isDirty && !!newResId;
            if (justSaved) {
                this._wasDirty = false;
            }

            const saveHappened = justGotId || justSaved;

            if (oldSurgeon !== newSurgeon) {
                // ── Surgeon changed → full RPC reload ────────────────────
                this.state.noSurgeon = !newSurgeon;
                this.state.availableDates = [];
                this.state.dateMap = {};
                this.state.selectedDate = null;
                this.state.locationFilterWarning = null;
                if (newSurgeon) {
                    await this._loadDates(nextProps);
                }

            } else if (saveHappened && newSurgeon) {
                // ── Record was saved → always do a fresh RPC reload so we
                //    pick up any server-recomputed fields (procedure_location_type,
                //    operating block changes, etc.) without needing a page refresh.
                await this._loadDates(nextProps);

            } else if (oldProcLocType !== newProcLocType && newSurgeon) {
                // ── procedure_location_type changed → reload from server so the
                //    location filter is applied at DB level.
                await this._loadDates(nextProps);

            } else if (oldAvail !== newAvail && newSurgeon) {
                // ── available_surgery_dates changed on server without a surgeon
                //    change (e.g. operating block edited in another tab).
                //    Parse the fresh JSON directly — avoids an extra RPC.
                try {
                    const parsed = JSON.parse(newAvail || "[]");
                    this.state.availableDates = parsed;
                    this._buildDateMap(parsed, nextProps);
                    const firstKey = Object.keys(this.state.dateMap)[0];
                    if (firstKey && !this.state.selectedDate) {
                        const dt = DateTime.fromISO(firstKey);
                        this.state.currentYear  = dt.year;
                        this.state.currentMonth = dt.month - 1;
                    }
                } catch (e) {
                    await this._loadDates(nextProps);
                }
            }

            // Always sync the displayed selected date from the field value
            this._syncSelectedDate(nextProps);
        });
    }

    // ── Loading ─────────────────────────────────────────────────────────────

    async _loadDates(props) {
        const surgeonId    = props.record.data.surgeon_id?.id;
        const locationType = props.record.data.procedure_location_type || null;
        if (!surgeonId) return;
        this.state.loading = true;
        try {
            // Pass location_type to Python — server filters blocks at DB level.
            // Only hospital blocks returned when procedure is hospital type,
            // only practice blocks for practice, all blocks when no procedure set.
            const kwargs = { months_ahead: 6 };
            if (locationType) {
                kwargs.location_type = locationType;
            }
            const dates = await this.orm.call(
                "clinic.operating.block",
                "get_available_dates_for_doctor",
                [surgeonId],
                kwargs
            );
            this.state.availableDates = dates || [];
            // _buildDateMap also filters client-side as a safety net
            this._buildDateMap(this.state.availableDates, props);
            // Remember what this load was for — used by openCalendar to avoid redundant reloads
            this._lastLoadedSurgeonId    = surgeonId;
            this._lastLoadedLocationType = locationType;
            // Navigate calendar to first available month if no date selected yet
            const firstKey = Object.keys(this.state.dateMap)[0];
            if (firstKey && !this.state.selectedDate) {
                const dt = DateTime.fromISO(firstKey);
                this.state.currentYear  = dt.year;
                this.state.currentMonth = dt.month - 1;
            }
        } catch (e) {
            console.error("Failed to load operating dates", e);
            this.state.availableDates = [];
            this.state.noDates = true;
            this.state.dateMap = {};
        } finally {
            this.state.loading = false;
        }
    }

    _buildDateMap(allDates, props) {
        const locationType = props.record.data.procedure_location_type;
        let filtered = allDates;
        let warning  = null;

        this.state.dateMap  = {};
        for (const d of filtered) {
            this.state.dateMap[d.date.substring(0, 10)] = d;
        }
        this.state.noDates = filtered.length === 0;
        this.state.locationFilterWarning = warning;
    }

    // Sync state.selectedDate and calendar month from the field value in props.
    // Also clears selectedDate when the field is empty (e.g. after backspace).
    _syncSelectedDate(props) {
        const iso = this._valueToIso(props.record.data[props.name]);
        if (iso) {
            this.state.selectedDate = iso;
            const dt = DateTime.fromISO(iso);
            this.state.currentYear  = dt.year;
            this.state.currentMonth = dt.month - 1;
        } else {
            // Field was cleared — remove highlight from calendar
            this.state.selectedDate = null;
        }
    }

    // ── Value helpers ────────────────────────────────────────────────────────

    _valueToIso(value) {
        if (!value) return null;
        if (value?.isLuxonDateTime) return value.toISODate();
        if (typeof value === "string") return value.substring(0, 10);
        if (value instanceof Date) return this._toIso(value);
        return null;
    }

    _toIso(jsDate) {
        const y = jsDate.getFullYear();
        const m = String(jsDate.getMonth() + 1).padStart(2, "0");
        const d = String(jsDate.getDate()).padStart(2, "0");
        return `${y}-${m}-${d}`;
    }

    _todayIso() { return this._toIso(new Date()); }

    // ── Date selection & clearing ────────────────────────────────────────────

    async _onDateSelected(isoDate) {
        const info = this.state.dateMap[isoDate];
        await this.props.record.update({ [this.props.name]: DateTime.fromISO(isoDate) });
        this.state.selectedDate = isoDate;
        this.state.isOpen = false;
        if (info) {
            this.notification.add(
                `${info.location} · ${info.start}–${info.end}`,
                { title: `Operating Block: ${isoDate}`, type: "info", sticky: false }
            );
        }
    }

    async clearDate() {
        // Set field to false/null — clears the date
        await this.props.record.update({ [this.props.name]: false });
        this.state.selectedDate = null;
        this.state.isOpen = false;
    }

    async selectDay(day) {
        if (!day.enabled || this.props.readonly) return;
        await this._onDateSelected(day.iso);
    }

    // Handle keyboard on the input:
    // Backspace / Delete → clear the date
    // Enter / Space      → toggle calendar
    async onInputKeydown(ev) {
        if (this.props.readonly) return;
        if (ev.key === "Backspace" || ev.key === "Delete") {
            ev.preventDefault();
            await this.clearDate();
        } else if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.toggleCalendar();
        } else if (ev.key === "Escape") {
            this.state.isOpen = false;
        }
    }

    // ── Calendar open/close ──────────────────────────────────────────────────

    async openCalendar() {
        if (this.props.readonly) return;
        const surgeonId    = this.props.record.data.surgeon_id?.id;
        const locationType = this.props.record.data.procedure_location_type;

        if (surgeonId && !this.state.loading) {
            const locationChanged = locationType !== this._lastLoadedLocationType;
            const surgeonChanged  = surgeonId !== this._lastLoadedSurgeonId;

            if (!this.state.availableDates.length || surgeonChanged || locationChanged) {
                await this._loadDates(this.props);
                this._lastLoadedSurgeonId = surgeonId;
                this._lastLoadedLocationType = locationType;
            }
        }
        this.state.isOpen = true;
    }

    toggleCalendar() {
        if (this.state.isOpen) {
            this.state.isOpen = false;
        } else {
            this.openCalendar();
        }
    }

    // ── Navigation ───────────────────────────────────────────────────────────

    previousMonth() {
        const d = new Date(this.state.currentYear, this.state.currentMonth - 1, 1);
        this.state.currentYear  = d.getFullYear();
        this.state.currentMonth = d.getMonth();
    }

    nextMonth() {
        const d = new Date(this.state.currentYear, this.state.currentMonth + 1, 1);
        this.state.currentYear  = d.getFullYear();
        this.state.currentMonth = d.getMonth();
    }

    // ── Getters ──────────────────────────────────────────────────────────────

    get monthLabel() {
        return new Date(this.state.currentYear, this.state.currentMonth, 1)
            .toLocaleDateString(undefined, { month: "long", year: "numeric" });
    }

    get displayValue() {
        const iso = this._valueToIso(this.props.record.data[this.props.name]);
        if (!iso) return "";
        return DateTime.fromISO(iso).toLocaleString({ year: "numeric", month: "2-digit", day: "2-digit" });
    }

    get inputPlaceholder() {
        if (this.state.noSurgeon) return "Select a doctor first";
        if (this.state.loading)   return "Loading operating schedule...";
        if (this.state.noDates)   return "No operating dates available";
        return "Select surgery date";
    }

    get weekdayLabels() { return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]; }

    get calendarWeeks() {
        const year  = this.state.currentYear;
        const month = this.state.currentMonth;
        const first = new Date(year, month, 1);
        const last  = new Date(year, month + 1, 0);
        const startOffset = (first.getDay() + 6) % 7;
        const totalCells  = Math.ceil((startOffset + last.getDate()) / 7) * 7;
        const todayIso    = this._todayIso();
        const days = [];

        for (let i = 0; i < totalCells; i++) {
            const dayNumber = i - startOffset + 1;
            const date    = new Date(year, month, dayNumber);
            const inMonth = dayNumber >= 1 && dayNumber <= last.getDate();
            const iso     = this._toIso(date);
            const info    = inMonth ? (this.state.dateMap[iso] || null) : null;
            const enabled = inMonth && Boolean(info) && iso >= todayIso;
            days.push({
                key: `${iso}-${i}`,
                iso, inMonth, enabled,
                label:    String(date.getDate()),
                selected: iso === this.state.selectedDate,
                today:    iso === todayIso,
                cssClass: this._getDayCssClass(inMonth, info, iso, todayIso),
                title:    info ? `${info.location}  ${info.start}-${info.end}` : "Not an operating day",
            });
        }

        const weeks = [];
        for (let i = 0; i < days.length; i += 7) weeks.push(days.slice(i, i + 7));
        return weeks;
    }

    _getDayCssClass(inMonth, info, iso, todayIso) {
        const c = ["o_surgery_calendar_day"];
        if (!inMonth) c.push("o_surgery_calendar_day_out");
        if (!info) {
            c.push("o_surgery_calendar_day_disabled");
        } else if (info.location_type === "hospital") {
            c.push("o_surgery_date_hospital");
        } else {
            c.push("o_surgery_date_practice");
        }
        if (iso === this.state.selectedDate) c.push("o_surgery_calendar_day_selected");
        if (iso === todayIso) c.push("o_surgery_calendar_day_today");
        return c.join(" ");
    }

    get selectedInfo() {
        return this.state.selectedDate ? (this.state.dateMap[this.state.selectedDate] || null) : null;
    }

    get availableLocationIds() {
        const ids = new Set();
        for (const d of this.state.availableDates) { if (d.location_id) ids.add(d.location_id); }
        return [...ids];
    }
}

registry.category("fields").add("surgery_date_picker", {
    component: SurgeryDatePickerWidget,
    supportedTypes: ["date"],
    fieldDependencies: [
        { name: "available_surgery_dates", type: "text" },
        { name: "surgeon_id", type: "many2one", relation: "res.users" },
        { name: "procedure_id", type: "many2one", relation: "clinic.surgery.procedure" },
        { name: "procedure_location_type", type: "selection" },
    ],
});