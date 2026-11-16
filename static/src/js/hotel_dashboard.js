/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class HotelReservationsDashboard extends Component {
    static template = "hotel.HotelReservationsDashboardTemplate";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            dashboardData: {
                period: {},
                kpis: {},
                occupancy: {},
                room_status: {},
                front_desk: {},
                arrivals: [],
                departures: [],
                recent_reservations: [],
                revenue: {},
                operations: {},
                trend_chart: {},
                revenue_chart: {},
                property: {},
                alerts: [],
            },
            selectedPeriod: 'this_month',
            customDateFrom: this._getToday(),
            customDateTo: this._getToday(),
            loading: true,
            error: null,
        });

        onWillStart(this.loadDashboardData);
    }

    _getToday() {
        return new Date().toISOString().split('T')[0];
    }

    _getFormattedDate(dateStr) {
        if (!dateStr) return '';
        const date = new Date(dateStr);
        return date.toLocaleDateString('en-US', { 
            month: 'short', 
            day: 'numeric',
            year: 'numeric'
        });
    }

    async loadDashboardData() {
        try {
            this.state.loading = true;
            
            let dateFrom, dateTo;
            
            if (this.state.selectedPeriod === 'custom') {
                dateFrom = this.state.customDateFrom;
                dateTo = this.state.customDateTo;
            } else {
                // Let backend calculate period dates
                dateFrom = null;
                dateTo = null;
            }

            const data = await this.orm.call("hotel.dashboard", "get_dashboard_data", [], {
                date_from: dateFrom,
                date_to: dateTo,
                period_type: this.state.selectedPeriod,
            });

            this.state.dashboardData = data;
            
            // Update custom dates from backend if not custom period
            if (this.state.selectedPeriod !== 'custom' && data.period) {
                this.state.customDateFrom = data.period.date_from;
                this.state.customDateTo = data.period.date_to;
            }
            
        } catch (error) {
            console.error("Error loading dashboard data:", error);
            this.state.error = (error && (error.data?.message || error.message)) || String(error);
            this.notification.add(_t("Dashboard error: ") + this.state.error, {
                type: "danger",
            });
        } finally {
            this.state.loading = false;
        }
    }

    isRestricted() {
        return Boolean(this.state.dashboardData?.restricted);
    }

    hasFigures() {
        const data = this.state.dashboardData || {};
        const total = data.kpis?.total_reservations?.value || 0;
        const arrivals = data.front_desk?.arrivals || 0;
        const departures = data.front_desk?.departures || 0;
        const recent = (data.recent_reservations || []).length;
        return Boolean(total || arrivals || departures || recent);
    }

    async onPeriodChange(event) {
        const newPeriod = event.target.value;
        this.state.selectedPeriod = newPeriod;
        
        if (newPeriod !== 'custom') {
            await this.loadDashboardData();
        }
    }

    async onCustomDateChange() {
        if (this.state.selectedPeriod === 'custom') {
            await this.loadDashboardData();
        }
    }

    async refreshDashboard() {
        await this.loadDashboardData();
        this.notification.add(_t("Dashboard refreshed"), { type: "success" });
    }

    // Utility methods for template
    getPeriodLabel() {
        const periodLabels = {
            'today': _t('Today'),
            'yesterday': _t('Yesterday'),
            'this_week': _t('This Week'),
            'this_month': _t('This Month'),
            'this_year': _t('This Year'),
            'custom': _t('Custom Period'),
        };
        return periodLabels[this.state.selectedPeriod] || _t('This Month');
    }

    formatCurrency(amount) {
        const symbol = this.state.dashboardData.revenue?.currency_symbol || '$';
        return `${symbol}${(amount || 0).toLocaleString()}`;
    }

    formatShortCurrency(amount) {
        const symbol = this.state.dashboardData.revenue?.currency_symbol || '$';
        const num = amount || 0;
        if (num === 0) return `${symbol}0`;
        if (num < 1000) return `${symbol}${num}`;
        if (num < 1000000) return `${symbol}${(num / 1000).toFixed(0)}K`;
        return `${symbol}${(num / 1000).toFixed(0)}K`;
    }

    formatPercentage(value) {
        const num = parseFloat(value || 0);
        if (num === 0) return "0.0%";
        const sign = num > 0 ? "+" : "";
        return `${sign}${num.toFixed(1)}%`;
    }

    getChangeClass(value) {
        const num = parseFloat(value || 0);
        if (num > 0) return 'text-success';
        if (num < 0) return 'text-danger';
        return 'text-muted';
    }

    getChangeIcon(value) {
        const num = parseFloat(value || 0);
        if (num > 0) return 'fa-arrow-up';
        if (num < 0) return 'fa-arrow-down';
        return 'fa-minus';
    }

    getStatusBadgeClass(state) {
        const statusClasses = {
            'draft': 'bg-warning',
            'confirmed': 'bg-primary',
            'checked_in': 'bg-success',
            'checked_out': 'bg-info',
            'cancelled': 'bg-danger',
            'no_show': 'bg-secondary',
        };
        return statusClasses[state] || 'bg-secondary';
    }

    getAlertClass(priority) {
        const alertClasses = {
            'high': 'alert-danger',
            'medium': 'alert-warning',
            'low': 'alert-info',
        };
        return alertClasses[priority] || 'alert-warning';
    }

    // Drill-down actions
    async openDrilldown(actionName, params = {}) {
        try {
            let action;
            
            // Add period parameters for period-based actions
            if (['action_open_total_reservations', 'action_open_hotel_invoices',
                 'action_open_room_consumption_report',
                 'action_open_discount_approvals', 'action_open_credit_approvals'].includes(actionName)) {
                params.date_from = this.state.dashboardData.period?.date_from;
                params.date_to = this.state.dashboardData.period?.date_to;
            }
            
            // Add today parameter for today-based actions
            if (['action_open_todays_arrivals', 'action_open_todays_departures'].includes(actionName)) {
                params.date_from = this.state.dashboardData.period?.today;
            }

            if (params && Object.keys(params).length > 0) {
                action = await this.orm.call("hotel.dashboard", actionName, [], params);
            } else {
                action = await this.orm.call("hotel.dashboard", actionName, []);
            }
            
            if (action && typeof action === 'object') {
                action.type = action.type || 'ir.actions.act_window';
                action.target = action.target || 'current';
                if (!action.views && action.view_mode) {
                    action.views = action.view_mode.split(',').map(m => [false, m.trim()]);
                }
            }

            await this.action.doAction(action);
        } catch (error) {
            console.error("Error opening drill-down:", error);
            const msg = error?.data?.message || error?.message || _t("Could not open the list.");
            this.notification.add(msg, { type: "warning" });
        }
    }

    // Event handlers for clickable elements
    onKpiClick(actionName) {
        this.openDrilldown(actionName);
    }

    onRoomStatusClick(status) {
        const actionMap = {
            'available': 'action_open_available_rooms',
            'reserved': 'action_open_reserved_rooms',
            'occupied': 'action_open_occupied_rooms', 
            'dirty': 'action_open_dirty_rooms',
            'maintenance': 'action_open_maintenance_rooms',
        };
        
        const actionName = actionMap[status];
        if (actionName) {
            this.openDrilldown(actionName);
        }
    }

    onFrontDeskClick(item) {
        const actionMap = {
            'arrivals': 'action_open_todays_arrivals',
            'departures': 'action_open_todays_departures',
            'checked_in': 'action_open_checked_in_guests',
            'checked_out_today': 'action_open_checked_out_today',
            'pending_confirmations': 'action_open_pending_reservations',
            'walkins_today': 'action_open_walkins_today',
            'arrived_today': 'action_open_arrived_today',
            'outstanding': 'action_open_outstanding_balances',
        };

        const actionName = actionMap[item];
        if (actionName) {
            this.openDrilldown(actionName);
        }
    }

    onOperationsClick(kind) {
        const actionMap = {
            'minibar': 'action_open_room_consumption_report',
            'discount': 'action_open_discount_approvals',
            'credit': 'action_open_credit_approvals',
        };
        const actionName = actionMap[kind];
        if (actionName) {
            this.openDrilldown(actionName);
        }
    }

    async onWalkinClick() {
        try {
            // Prefer the XML action so Book Guest works without record ids.
            await this.action.doAction("hotel.hotel_walkin_wizard_action", {
                onClose: () => {
                    this.refreshDashboard();
                },
            });
        } catch (error) {
            console.error("Error opening Book Guest wizard:", error);
            const msg = error?.data?.message || error?.message || _t("Could not open Book Guest registration.");
            this.notification.add(msg, { type: "warning" });
        }
    }

    onAlertClick(alert) {
        if (alert.action) {
            this.openDrilldown(alert.action);
        }
    }

    onReservationClick(reservation) {
        this.openDrilldown('action_open_reservation_form', { reservation_id: reservation.id });
    }

    onGuestClick(row) {
        if (row?.guest_id) {
            this.openDrilldown('action_open_guest_form', { partner_id: row.guest_id });
        }
    }

    onRoomClick(row) {
        if (row?.room_id) {
            this.openDrilldown('action_open_room_form', { room_id: row.room_id });
        }
    }

    onPropertyClick(kind) {
        const actions = {
            'open': 'action_open_open_properties',
            'with_guest': 'action_open_properties_with_guest',
            'deposit_requested': 'action_open_deposit_requested',
            'safe': 'action_open_held_deposits',
            'ready_return': 'action_open_ready_return',
            'due_today': 'action_open_returns_due_today',
            'overdue': 'action_open_overdue_properties',
            'claims': 'action_open_pending_claims',
            'lost_found': 'action_open_lost_found',
        };
        const action = actions[kind];
        if (action) {
            this.openDrilldown(action);
        }
    }

    onViewAllReservations() {
        this.openDrilldown('action_open_total_reservations');
    }

    onViewRevenue() {
        this.openDrilldown('action_open_hotel_invoices');
    }

    // Chart data formatting and rendering
    getOccupancyChartData() {
        const occupancy = this.state.dashboardData.occupancy || {};
        return {
            occupied: occupancy.occupied_rooms || 0,
            available: occupancy.available_rooms || 0,
            total: occupancy.total_rooms || 0,
            percentage: occupancy.occupancy_rate || 0,
        };
    }

    getTrendChartData() {
        return this.state.dashboardData.trend_chart || { labels: [], datasets: [] };
    }

    getRevenueChartData() {
        return this.state.dashboardData.revenue_chart || { labels: [], datasets: [] };
    }

    // Simple chart rendering helpers
    renderTrendChart() {
        const chartData = this.getTrendChartData();
        if (!chartData.labels || chartData.labels.length === 0) {
            return null;
        }
        
        // Find max value for scaling
        let maxValue = 0;
        chartData.datasets.forEach(dataset => {
            const dataMax = Math.max(...dataset.data);
            if (dataMax > maxValue) maxValue = dataMax;
        });
        
        if (maxValue === 0) maxValue = 1; // Prevent division by zero
        
        return {
            labels: chartData.labels,
            datasets: chartData.datasets,
            maxValue: maxValue
        };
    }

    renderRevenueChart() {
        const chartData = this.getRevenueChartData();
        if (!chartData.labels || chartData.labels.length === 0) {
            return null;
        }
        
        // Find max value for scaling
        const maxValue = Math.max(...chartData.datasets[0].data) || 1;
        
        return {
            labels: chartData.labels,
            data: chartData.datasets[0].data,
            maxValue: maxValue
        };
    }

    // Chart bar calculation for CSS rendering
    getBarHeight(value, maxValue) {
        if (!maxValue || maxValue === 0) return 4;
        if (!value || value === 0) return 4;
        const percentage = (value / maxValue) * 100;
        return Math.max(6, Math.min(160, percentage * 1.6));
    }

    formatChartValue(value) {
        if (value === 0) return '0';
        if (value < 1000) return value.toString();
        if (value < 1000000) return (value / 1000).toFixed(1) + 'K';
        return (value / 1000000).toFixed(1) + 'M';
    }

    // Template helper methods
    getOccupancyPercentage() {
        const occupancy = this.state.dashboardData.occupancy || {};
        return `${(occupancy.occupancy_rate || 0).toFixed(1)}%`;
    }

    getOccupancyText() {
        const occupancy = this.state.dashboardData.occupancy || {};
        return `${occupancy.occupied_rooms || 0} / ${occupancy.total_operational || 0}`;
    }

    getReservationStatusClass(state) {
        const statusClasses = {
            'draft': 'bg-warning text-dark',
            'confirmed': 'bg-primary',
            'checked_in': 'bg-success', 
            'checked_out': 'bg-info',
            'cancelled': 'bg-danger',
            'no_show': 'bg-secondary',
        };
        return statusClasses[state] || 'bg-secondary';
    }

    getMaxChartValue() {
        const chartData = this.state.dashboardData.trend_chart || {};
        if (!chartData.datasets || chartData.datasets.length === 0) return 10; // Default for empty state
        
        let maxValue = 0;
        chartData.datasets.forEach(dataset => {
            if (dataset.data && Array.isArray(dataset.data)) {
                const dataMax = Math.max(...dataset.data);
                if (dataMax > maxValue) maxValue = dataMax;
            }
        });
        
        return Math.max(maxValue, 10); // Ensure minimum scale of 10
    }

    getMaxRevenueValue() {
        const chartData = this.state.dashboardData.revenue_chart || {};
        if (!chartData.datasets || chartData.datasets.length === 0) return 1000; // Default for empty state
        
        const maxValue = Math.max(...(chartData.datasets[0]?.data || [0]));
        return Math.max(maxValue, 1000); // Ensure minimum scale of 1000
    }

    // Action method wrappers for template
    openAction(actionName) {
        this.openDrilldown(actionName);
    }

    onOccupancyClick() {
        this.openDrilldown('action_open_rooms');
    }

    onRevenueClick() {
        this.openDrilldown('action_open_hotel_invoices', {
            date_from: this.state.dashboardData.period?.date_from,
            date_to: this.state.dashboardData.period?.date_to,
        });
    }

    getOccupancyKpi() {
        const occupancy = this.state.dashboardData.occupancy || {};
        return {
            value: `${(occupancy.occupancy_rate || 0).toFixed(1)}%`,
            label: `${occupancy.occupied_rooms || 0} of ${occupancy.total_operational || 0} rooms`,
        };
    }

    getRevenueKpi() {
        const revenue = this.state.dashboardData.revenue || {};
        return {
            value: revenue.available === false ? '--' : this.formatCurrency(revenue.total_revenue),
            label: revenue.available === false ? _t('Not available for your role') : (revenue.source || ''),
        };
    }

    getSettledLabel() {
        return _t('Settled');
    }
}

registry.category("actions").add("hotel_reservations_dashboard", HotelReservationsDashboard);