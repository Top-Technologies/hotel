from collections import OrderedDict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.tools import format_date

PAID_PAYMENT_STATES = ("in_process", "paid")


class HotelDepositLedger(models.AbstractModel):
    _name = "hotel.deposit.ledger"
    _description = "Hotel Deposit Ledger"

    @api.model
    def _reservation_domain(self, options):
        states = ["draft", "confirmed"]
        # Include in-house (checked-in) stays by default so deposits are tracked until check-out
        if options.get("include_checked_in", True):
            states.append("checked_in")
        if options.get("include_checked_out"):
            states.append("checked_out")
        if options.get("include_no_show"):
            states.append("no_show")
        if options.get("include_cancelled"):
            states.append("cancelled")
        domain = [
            ("state", "in", states),
            ("company_id", "in", self.env.companies.ids),
        ]
        if options.get("date_from"):
            domain.append(("checkin", ">=", options["date_from"]))
        if options.get("date_to"):
            domain.append(("checkin", "<=", options["date_to"]))
        return domain

    @api.model
    def get_report_data(self, options=None):
        options = options or {}
        today = fields.Date.context_today(self)
        window = 7
        try:
            window = int(
                self.env["hotel.config"]._hotel_param(
                    "deposit_ledger_window_days", 7
                )
            )
        except (TypeError, ValueError):
            window = 7
        group_by = options.get("group_by", "arrival")

        channel_filter = options.get("paid_by")  # all/desk/online/None

        reservations = self.env["hotel.reservation"].search(
            self._reservation_domain(options), order="checkin, id"
        )
        state_labels = {
            "draft": _("Draft"),
            "confirmed": _("Confirmed"),
            "checked_in": _("In-House"),
            "checked_out": _("Checked Out"),
            "cancelled": _("Cancelled"),
            "no_show": _("No-Show"),
        }
        rows = []
        for res in reservations:
            held = res.deposit_paid or res.deposit
            if res.currency_id.is_zero(held):
                continue
            company = res.company_id
            rate_date = (
                res.create_date.date() if res.create_date else today
            )
            def to_company(amount):
                return res.currency_id._convert(
                    amount, company.currency_id, company, rate_date
                )

            stay = to_company(res.total)
            held_c = to_company(held)
            key, channel_label = self._paid_by(res)
            if channel_filter and channel_filter != "all":
                if channel_filter == "desk" and key != "desk":
                    continue
                if channel_filter == "online" and key not in ("online", "mixed"):
                    continue
            arrival = fields.Datetime.context_timestamp(
                res, res.checkin
            ).date()
            booked = fields.Datetime.context_timestamp(
                res, res.create_date
            ).date() if res.create_date else arrival
            still_to_pay = max(0.0, stay - held_c)
            remaining_deposit = max(0.0, held_c - stay)
            rows.append(
                {
                    "id": res.id,
                    "guest": res.guest_id.name or "",
                    "booking": res.name,
                    "status": state_labels.get(res.state, res.state.title()),
                    "status_key": res.state,
                    "arrival": arrival,
                    "nights": res.nights,
                    "stay_value": stay,
                    "deposit_held": held_c,
                    "remaining_deposit": remaining_deposit,
                    "still_to_pay": still_to_pay,
                    "paid_by": channel_label,
                    "paid_by_key": key,
                    "group_date": booked if group_by == "booking" else arrival,
                }
            )

        groups = OrderedDict()
        for row in sorted(rows, key=lambda r: (r["group_date"], r["booking"])):
            key = row["group_date"].strftime("%Y-%m")
            label = format_date(
                self.env, row["group_date"], date_format="MMMM yyyy"
            )
            groups.setdefault(
                key, {"key": key, "label": label, "rows": []}
            )
            groups[key]["rows"].append(row)

        for group in groups.values():
            group["count"] = len(group["rows"])
            for field in ("stay_value", "deposit_held", "remaining_deposit", "still_to_pay"):
                group[field] = sum(r[field] for r in group["rows"])

        arriving = sum(
            1
            for r in rows
            if today <= r["arrival"] <= today + timedelta(days=window)
        )
        currency = self.env.company.currency_id
        return {
            "company": self.env.company.name,
            "currency": {
                "id": currency.id,
                "symbol": currency.symbol,
                "position": currency.position,
                "decimals": currency.decimal_places,
            },
            "kpis": {
                "deposits_held": sum(r["deposit_held"] for r in rows),
                "remaining_deposits": sum(r["remaining_deposit"] for r in rows),
                "bookings": len(rows),
                "in_house": sum(1 for r in rows if r["status_key"] == "checked_in"),
                "arriving_soon": arriving,
                "window_days": window,
            },
            "groups": list(groups.values()),
            "totals": {
                "stay_value": sum(r["stay_value"] for r in rows),
                "deposit_held": sum(r["deposit_held"] for r in rows),
                "remaining_deposit": sum(r["remaining_deposit"] for r in rows),
                "still_to_pay": sum(r["still_to_pay"] for r in rows),
            },
            "options": options,
        }

    @api.model
    def _paid_by(self, reservation):
        payments = reservation.deposit_payment_ids.filtered(
            lambda p: p.state in PAID_PAYMENT_STATES
        )
        channels = (
            set(payments.mapped("hotel_deposit_channel")) or {"desk"}
        )
        if channels == {"desk"}:
            return "desk", _("Desk")
        if channels == {"online"}:
            return "online", _("Online")
        return "mixed", _("Online + Desk")


class ReportDepositLedger(models.AbstractModel):
    _name = "report.hotel.report_deposit_ledger"
    _description = "Deposit Ledger PDF"

    @api.model
    def _get_report_values(self, docids, data=None):
        options = (data or {}).get("options", {})
        # state and payment channel options may arrive as JSON strings
        if isinstance(options, str):
            import json
            try:
                options = json.loads(options)
            except Exception:
                options = {}
        return {
            "data": self.env["hotel.deposit.ledger"].get_report_data(options),
            "options": options,
        }