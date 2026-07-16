/** @odoo-module **/

import { registry }            from "@web/core/registry";
import { Component, useRef, onPatched } from "@odoo/owl";
import { standardFieldProps }  from "@web/views/fields/standard_field_props";

class SurgeryTimeSlotWidget extends Component {

    static template = "surgery_case_management.SurgeryTimeSlot";

    static props = { ...standardFieldProps };

    setup() {
        this.selectRef = useRef("slotSelect");

        onPatched(() => {
            if (this.selectRef.el) {
                this.selectRef.el.value = this.currentValue;
            }
        });
    }

    get slots() {
        try {
            const raw = this.props.record.data.available_time_slots || "[]";
            const parsed = JSON.parse(raw);
            return Array.isArray(parsed)
                ? parsed.filter(s => s && typeof s === 'object' && 'value' in s && 'label' in s)
                : [];
        } catch {
            return [];
        }
    }

    get currentValue() {
        return this.props.record.data[this.props.name] || "";
    }

    async onChange(ev) {
        const val = ev.target.value || false;
        await this.props.record.update({ [this.props.name]: val });
    }
}

registry.category("fields").add("surgery_time_slot", {
    component: SurgeryTimeSlotWidget,
    supportedTypes: ["char"],
    fieldDependencies: [
        { name: "available_time_slots", type: "text" },
        { name: "surgery_date",         type: "date" },
        { name: "surgeon_id",           type: "many2one", relation: "res.users" },
    ],
});