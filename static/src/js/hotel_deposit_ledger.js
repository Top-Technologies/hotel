/** @odoo-module **/
import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { download } from "@web/core/network/download";

class HotelDepositLedger extends Component {
    static template = "hotel.DepositLedger";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            data: null,
            search: "",
            collapsed: {},
            options: { group_by: "arrival", include_checked_in: true, include_checked_out: false, include_no_show: false, include_cancelled: false, paid_by: "all" },
            optionsOpen: false,
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.data = await this.orm.call(
            "hotel.deposit.ledger", "get_report_data", [this.state.options]
        );
    }

    get groups() {
        const q = (this.state.search || "").trim().toLowerCase();
        if (!q || !this.state.data) return this.state.data ? this.state.data.groups : [];
        return this.state.data.groups
            .map((g) => ({
                ...g,
                rows: g.rows.filter((r) =>
                    (r.guest + " " + r.booking).toLowerCase().includes(q)),
            }))
            .filter((g) => g.rows.length);
    }

    get collapsed() {
        return this.state.collapsed;
    }

    money(value) {
        if (!this.state.data) return "";
        const c = this.state.data.currency;
        const n = Number(value || 0).toLocaleString(undefined, {
            minimumFractionDigits: c.decimals,
            maximumFractionDigits: c.decimals,
        });
        return c.position === "before" ? `${c.symbol} ${n}` : `${n} ${c.symbol}`;
    }

    toggle(key) {
        this.state.collapsed[key] = !this.state.collapsed[key];
    }

    async setOption(name, value) {
        this.state.options[name] = value;
        await this.load();
    }

    openBooking(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hotel.reservation",
            res_id: id,
            views: [[false, "form"]],
        });
    }

    printPdf() {
        return this.action.doAction({
            type: "ir.actions.report",
            report_type: "qweb-pdf",
            report_name: "hotel.report_deposit_ledger",
            report_file: "hotel.report_deposit_ledger",
            data: { options: this.state.options },
        });
    }

    exportExcel() {
        return download({
            url: "/hotel/deposit_ledger/xlsx",
            data: { options: JSON.stringify(this.state.options) },
        });
    }

    schedule() {
        this.action.doAction("hotel.action_hotel_deposit_ledger_schedule");
    }
}

registry.category("actions").add("hotel.deposit_ledger", HotelDepositLedger);