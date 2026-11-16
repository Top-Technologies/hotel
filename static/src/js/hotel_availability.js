/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class HotelRoomAvailabilityBoard extends Component {
    static template = "hotel.HotelRoomAvailabilityTemplate";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            date: this._todayStr(),
            group_by: "type",
            data: { date: "", group_by: "type", groups: [], counts: {} },
            loading: true,
            error: null,
        });

        onWillStart(this.loadBoard);
    }

    _todayStr() {
        return new Date().toISOString().split("T")[0];
    }

    _shift(offset) {
        const date = new Date(`${this.state.date}T00:00:00`);
        date.setDate(date.getDate() + offset);
        this.state.date = date.toISOString().split("T")[0];
        return this.loadBoard();
    }

    async loadBoard() {
        try {
            this.state.loading = true;
            const data = await this.orm.call(
                "hotel.dashboard",
                "get_availability_data",
                [],
                { date: this.state.date, group_by: this.state.group_by }
            );
            this.state.data = data;
            this.state.error = null;
        } catch (error) {
            console.error("Error loading availability:", error);
            this.state.error =
                (error && (error.data?.message || error.message)) || String(error);
            this.notification.add(_t("Could not load room availability."), {
                type: "danger",
            });
        } finally {
            this.state.loading = false;
        }
    }

    onDateChange(event) {
        this.state.date = event.target.value;
        return this.loadBoard();
    }

    goToday() {
        this.state.date = this._todayStr();
        return this.loadBoard();
    }

    setGroupBy(groupBy) {
        if (this.state.group_by === groupBy) return;
        this.state.group_by = groupBy;
        return this.loadBoard();
    }

    openCard(room) {
        if (room.reservation_id) {
            return this.openStay(room);
        }
        return this.openRoom(room);
    }

    async openRoom(room) {
        try {
            const action = await this.orm.call(
                "hotel.dashboard",
                "action_open_room_form",
                [],
                { room_id: room.id }
            );
            await this.action.doAction(action);
        } catch (error) {
            console.error("Error opening room:", error);
        }
    }

    async openStay(room) {
        if (!room.reservation_id) return;
        try {
            const action = await this.orm.call(
                "hotel.dashboard",
                "action_open_reservation_form",
                [],
                { reservation_id: room.reservation_id }
            );
            await this.action.doAction(action);
        } catch (error) {
            console.error("Error opening stay:", error);
        }
    }

    getLegend() {
        return [
            { key: "available", label: _t("Available"), css: "ra-available" },
            { key: "reserved", label: _t("Reserved"), css: "ra-reserved" },
            { key: "occupied", label: _t("Occupied"), css: "ra-occupied" },
            { key: "clean", label: _t("Clean"), css: "ra-clean" },
            { key: "dirty", label: _t("Dirty"), css: "ra-dirty" },
            { key: "cleaning", label: _t("Cleaning"), css: "ra-cleaning" },
            { key: "out_of_service", label: _t("Out of Service"), css: "ra-out" },
        ];
    }

    avClass(availability) {
        const map = {
            available: "ra-available",
            reserved: "ra-reserved",
            occupied: "ra-occupied",
            clean: "ra-clean",
            inspected: "ra-clean",
            dirty: "ra-dirty",
            cleaning: "ra-cleaning",
            out_of_service: "ra-out",
        };
        return map[availability] || "ra-other";
    }

    countLabel() {
        const counts = this.state.data.counts || {};
        const parts = [];
        if (counts.available) {
            parts.push(`${counts.available} ${_t("available")}`);
        }
        if (counts.reserved) {
            parts.push(`${counts.reserved} ${_t("reserved")}`);
        }
        if (counts.occupied) {
            parts.push(`${counts.occupied} ${_t("occupied")}`);
        }
        const toClean = (counts.cleaning || 0) + (counts.dirty || 0);
        if (toClean) {
            parts.push(`${toClean} ${_t("to clean")}`);
        }
        if (counts.out_of_service) {
            parts.push(`${counts.out_of_service} ${_t("out of service")}`);
        }
        return parts.join(" · ");
    }

    formatDate(iso) {
        if (!iso) return "";
        const date = new Date(`${iso}T00:00:00`);
        return date.toLocaleDateString("en-US", {
            weekday: "short",
            month: "short",
            day: "numeric",
            year: "numeric",
        });
    }
}

registry.category("actions").add(
    "hotel_room_availability_board",
    HotelRoomAvailabilityBoard
);