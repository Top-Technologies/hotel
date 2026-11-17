import logging
from datetime import datetime, timedelta

try:
    from dateutil.relativedelta import relativedelta
except ImportError:
    # Fallback if dateutil is not available
    def relativedelta(**kwargs):
        if 'months' in kwargs:
            # Simple month calculation fallback
            return timedelta(days=kwargs['months'] * 30)
        return timedelta(**kwargs)

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class HotelDashboard(models.AbstractModel):
    _name = "hotel.dashboard"
    _description = "Hotel Reservations Dashboard"

    @api.model
    def _company_domain(self):
        """Domain to match records for the current allowed companies or global records."""
        return ['|', ('company_id', '=', False), ('company_id', 'in', self.env.companies.ids)]

    @api.model
    def _safe_count(self, model_name, domain):
        """Count records, or zero when the current role cannot read them or table is empty/uninitialized."""
        try:
            return self.env[model_name].search_count(domain)
        except Exception:
            return 0

    @api.model
    def _format_datetime_safe(self, dt_val, fmt="%b %d, %Y"):
        """Safely format a date/datetime whether it comes as a datetime object or string."""
        if not dt_val:
            return ""
        if isinstance(dt_val, str):
            try:
                dt_val = fields.Datetime.from_string(dt_val)
            except Exception:
                return str(dt_val)
        if hasattr(dt_val, "strftime"):
            return dt_val.strftime(fmt)
        return str(dt_val)

    @api.model
    def _room_numbers(self, room_ids):
        """Room numbers keyed by id, for the front desk tables."""
        room_ids = [room_id for room_id in room_ids if room_id]
        if not room_ids:
            return {}
        try:
            rows = self.env["hotel.room"].search_read(
                [("id", "in", list(set(room_ids)))], fields=["number"],
            )
            return {row["id"]: row["number"] for row in rows}
        except Exception:
            return {}

    @api.model
    def get_dashboard_data(self, date_from=False, date_to=False, period_type='this_month'):
        """
        Get comprehensive dashboard data for the specified date range.

        Args:
            date_from: Start date for the period
            date_to: End date for the period
            period_type: 'today', 'this_week', 'this_month', 'this_year', 'custom'
        """
        today = fields.Date.context_today(self)

        try:
            # Set default period based on period_type
            if not date_from or not date_to:
                date_from, date_to = self._get_period_dates(period_type, today)

            # Convert string dates to date objects if needed
            if isinstance(date_from, str):
                date_from = fields.Date.from_string(date_from)
            if isinstance(date_to, str):
                date_to = fields.Date.from_string(date_to)

            reservation_model = self.env["hotel.reservation"]
            try:
                reservation_model.check_access("read")
            except AccessError:
                # Roles outside the hotel departments still get a usable screen
                # instead of a traceback; no figures are exposed to them.
                return self._get_restricted_data(date_from, date_to, period_type, today)

            # One aggregate query for the balances shown in the front desk tables.
            company_domain = self._company_domain()
            in_house = reservation_model.search(company_domain + [("state", "=", "checked_in")])
            paid_invoices = self._get_paid_invoices(
                in_house | reservation_model.search(
                    company_domain + [
                        ("state", "in", ["confirmed", "checked_in", "checked_out"]),
                        ("checkout", ">=", datetime.combine(today, datetime.min.time())),
                        ("checkout", "<=", datetime.combine(today, datetime.max.time())),
                    ],
                ),
            )

            return {
                "period": {
                    "date_from": date_from,
                    "date_to": date_to,
                    "period_type": period_type,
                    "today": today,
                },
                "kpis": self._get_kpi_data(date_from, date_to, today),
                "occupancy": self._get_occupancy_data(today),
                "room_status": self._get_room_status_data(),
                "front_desk": self._get_front_desk_data(today),
                "arrivals": self._get_arrivals_list(today),
                "departures": self._get_departures_list(today, paid_invoices),
                "recent_reservations": self._get_recent_reservations(),
                "revenue": self._get_revenue_data(date_from, date_to),
                "operations": self._get_operations_kpis(date_from, date_to),
                "trend_chart": self._get_reservation_trend_data(date_from, date_to),
                "revenue_chart": self._get_revenue_trend_data(date_from, date_to),
                "property": self._get_property_data(),
                "alerts": self._get_operational_alerts(paid_invoices),
            }
        except Exception as e:
            _logger.exception("Error loading hotel dashboard data: %s", e)
            fallback = self._get_restricted_data(date_from, date_to, period_type, today)
            fallback["error"] = str(e)
            return fallback

    @api.model
    def _get_restricted_data(self, date_from, date_to, period_type, today):
        """Empty but well-shaped payload for users without hotel access."""
        return {
            "restricted": True,
            "period": {
                "date_from": date_from,
                "date_to": date_to,
                "period_type": period_type,
                "today": today,
            },
            "kpis": {},
            "occupancy": {"total": 0, "occupied": 0, "rate": 0.0, "label": "0 / 0"},
            "room_status": [],
            "front_desk": {},
            "arrivals": [],
            "departures": [],
            "recent_reservations": [],
            "revenue": {"total": 0.0, "source": "", "available": False, "series": []},
            "operations": {},
            "trend_chart": [],
            "revenue_chart": [],
            "property": {},
            "alerts": [],
        }

    # ------------------------------------------------------------------
    # Front desk detail lists
    # ------------------------------------------------------------------
    @api.model
    def _get_arrivals_list(self, today, limit=10):
        """Arrivals expected today, with the data reception needs."""
        try:
            reservations = self.env["hotel.reservation"].search_read(
                self._company_domain() + [
                    ("checkin", ">=", datetime.combine(today, datetime.min.time())),
                    ("checkin", "<=", datetime.combine(today, datetime.max.time())),
                    ("state", "in", ["confirmed", "checked_in"]),
                ],
                fields=[
                    "name", "guest_id", "room_id", "adults", "children",
                    "checkin", "state", "actual_checkin",
                ],
                order="checkin asc, id asc",
                limit=limit,
            )
            room_numbers = self._room_numbers(
                [row["room_id"][0] if row["room_id"] else False for row in reservations],
            )
            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "guest_id": row["guest_id"][0] if row["guest_id"] else False,
                    "guest_name": row["guest_id"][1] if row["guest_id"] else "",
                    "room_id": row["room_id"][0] if row["room_id"] else False,
                    "room_number": room_numbers.get(row["room_id"][0], "") if row["room_id"] else "",
                    "guests": (row.get("adults") or 0) + (row.get("children") or 0),
                    "checkin": self._format_datetime_safe(row.get("checkin"), "%b %d, %Y"),
                    "state": row["state"],
                    "state_label": self._reservation_state_label(row["state"]),
                    "checked_in": bool(row.get("actual_checkin")),
                }
                for row in reservations
            ]
        except Exception:
            return []

    @api.model
    def _get_departures_list(self, today, paid_invoices, limit=10):
        """Departures due today, with the outstanding folio balance."""
        try:
            reservations = self.env["hotel.reservation"].search(
                self._company_domain() + [
                    ("checkout", ">=", datetime.combine(today, datetime.min.time())),
                    ("checkout", "<=", datetime.combine(today, datetime.max.time())),
                    ("state", "in", ["confirmed", "checked_in", "checked_out"]),
                ],
                order="checkout asc, id asc",
                limit=limit,
            )
            departures = []
            for reservation in reservations:
                outstanding = 0.0
                try:
                    outstanding = reservation.folio_outstanding
                except Exception:
                    pass
                departures.append({
                    "id": reservation.id,
                    "name": reservation.name,
                    "guest_id": reservation.guest_id.id,
                    "guest_name": reservation.guest_id.display_name or "",
                    "room_id": reservation.room_id.id,
                    "room_number": reservation.room_id.number or "",
                    "checkout": self._format_datetime_safe(reservation.checkout, "%b %d, %Y"),
                    "state": reservation.state,
                    "state_label": self._reservation_state_label(reservation.state),
                    "checked_out": bool(reservation.actual_checkout),
                    "total": reservation.total or 0.0,
                    "outstanding": round(outstanding or 0.0, 2),
                })
            return departures
        except Exception:
            return []

    @api.model
    def _reservation_state_label(self, state):
        try:
            selection = self.env["hotel.reservation"]._fields["state"].selection
            return dict(selection).get(state, state or "")
        except Exception:
            return state or ""

    @api.model
    def _get_paid_invoices(self, reservations):
        """Posted guest invoice totals keyed by reservation id.

        Roles without accounting rights simply get no figures instead of an
        access error, so the dashboard stays usable for reception.
        """
        if not reservations:
            return {}
        try:
            rows = self.env["account.move"]._read_group(
                [
                    ("move_type", "=", "out_invoice"),
                    ("state", "=", "posted"),
                    ("hotel_reservation_id", "in", reservations.ids),
                ],
                ["hotel_reservation_id"],
                ["amount_total:sum"],
            )
            return {
                (rid.id if hasattr(rid, 'id') else rid): (amount or 0.0)
                for rid, amount in rows
                if rid
            }
        except Exception:
            return {}

    @api.model
    def _get_period_dates(self, period_type, today):
        """Get start and end dates for predefined periods."""
        if period_type == 'today':
            return today, today
        if period_type == 'yesterday':
            yesterday = today - timedelta(days=1)
            return yesterday, yesterday
        if period_type == 'this_week':
            start_of_week = today - timedelta(days=today.weekday())
            return start_of_week, start_of_week + timedelta(days=6)
        if period_type == 'this_month':
            start_of_month = today.replace(day=1)
            next_month = start_of_month + relativedelta(months=1)
            return start_of_month, next_month - timedelta(days=1)
        if period_type == 'this_year':
            return today.replace(month=1, day=1), today.replace(month=12, day=31)
        # Default to this month
        start_of_month = today.replace(day=1)
        next_month = start_of_month + relativedelta(months=1)
        return start_of_month, next_month - timedelta(days=1)

    @api.model
    def _get_kpi_data(self, date_from, date_to, today):
        """Get main KPI data with trend calculations."""
        reservation_model = self.env["hotel.reservation"]

        # Active reservation states
        active_states = ['draft', 'confirmed', 'checked_in', 'checked_out']
        comp_dom = self._company_domain()

        # Total reservations in period (by checkin date)
        period_domain = comp_dom + [
            ("checkin", ">=", datetime.combine(date_from, datetime.min.time())),
            ("checkin", "<=", datetime.combine(date_to, datetime.max.time())),
            ("state", "in", active_states),
        ]
        total_reservations = reservation_model.search_count(period_domain)

        # Get comparison period for trends
        period_days = (date_to - date_from).days + 1
        prev_from = date_from - timedelta(days=period_days)
        prev_to = date_from - timedelta(days=1)

        prev_period_domain = comp_dom + [
            ("checkin", ">=", datetime.combine(prev_from, datetime.min.time())),
            ("checkin", "<=", datetime.combine(prev_to, datetime.max.time())),
            ("state", "in", active_states),
        ]
        prev_total_reservations = reservation_model.search_count(prev_period_domain)

        total_change = self._calculate_percentage_change(total_reservations, prev_total_reservations)

        # Today's arrivals (checkin date = today)
        arrivals_domain = comp_dom + [
            ("checkin", ">=", datetime.combine(today, datetime.min.time())),
            ("checkin", "<=", datetime.combine(today, datetime.max.time())),
            ("state", "in", ["confirmed", "checked_in"]),
        ]
        arrivals_today = reservation_model.search_count(arrivals_domain)

        # Yesterday's arrivals for comparison
        yesterday = today - timedelta(days=1)
        yesterday_arrivals_domain = comp_dom + [
            ("checkin", ">=", datetime.combine(yesterday, datetime.min.time())),
            ("checkin", "<=", datetime.combine(yesterday, datetime.max.time())),
            ("state", "in", ["confirmed", "checked_in"]),
        ]
        arrivals_yesterday = reservation_model.search_count(yesterday_arrivals_domain)
        arrivals_change = self._calculate_percentage_change(arrivals_today, arrivals_yesterday)

        # Today's departures (checkout date = today)
        departures_domain = comp_dom + [
            ("checkout", ">=", datetime.combine(today, datetime.min.time())),
            ("checkout", "<=", datetime.combine(today, datetime.max.time())),
            ("state", "in", ["confirmed", "checked_in", "checked_out"]),
        ]
        departures_today = reservation_model.search_count(departures_domain)

        # Yesterday's departures for comparison
        yesterday_departures_domain = comp_dom + [
            ("checkout", ">=", datetime.combine(yesterday, datetime.min.time())),
            ("checkout", "<=", datetime.combine(yesterday, datetime.max.time())),
            ("state", "in", ["confirmed", "checked_in", "checked_out"]),
        ]
        departures_yesterday = reservation_model.search_count(yesterday_departures_domain)
        departures_change = self._calculate_percentage_change(departures_today, departures_yesterday)

        # Pending confirmations (draft state)
        pending_confirmations = reservation_model.search_count(comp_dom + [("state", "=", "draft")])

        # Same length period right before the selected one, for comparison
        prev_pending = reservation_model.search_count(prev_period_domain + [("state", "=", "draft")])
        pending_change = self._calculate_percentage_change(pending_confirmations, prev_pending)

        return {
            "total_reservations": {
                "value": total_reservations,
                "change": total_change,
                "label": f"vs. previous {period_days} days",
            },
            "arrivals_today": {
                "value": arrivals_today,
                "change": arrivals_change,
                "label": "vs. yesterday",
            },
            "departures_today": {
                "value": departures_today,
                "change": departures_change,
                "label": "vs. yesterday",
            },
            "pending_confirmations": {
                "value": pending_confirmations,
                "change": pending_change,
                "label": "vs. last month avg",
            },
        }

    @api.model
    def _calculate_percentage_change(self, current, previous):
        """Calculate percentage change between two values."""
        if previous == 0:
            return 100 if current > 0 else 0
        return round(((current - previous) / previous) * 100, 1)

    @api.model
    def _room_status_counts(self):
        """Room counts per status in a single aggregation."""
        try:
            rows = self.env["hotel.room"]._read_group(
                self._company_domain() + [("active", "=", True)], ["status"], ["__count"],
            )
            return {status or "available": count for status, count in rows}
        except Exception:
            return {}

    @api.model
    def _get_occupancy_data(self, today=None):
        """Get occupancy rate and room breakdown."""
        if not today:
            today = fields.Date.context_today(self)

        status_counts = self._room_status_counts()
        total_rooms = sum(status_counts.values())
        # Sellable rooms: active rooms that are not taken out of service.
        sellable_rooms = total_rooms - status_counts.get("out_of_service", 0)
        occupied_rooms = status_counts.get("occupied", 0)
        # Rooms reception can hand over right now.
        available_rooms = sum(
            status_counts.get(status, 0)
            for status in ("available", "clean", "inspected")
        )

        occupancy_rate = 0
        if sellable_rooms > 0:
            occupancy_rate = round((occupied_rooms / sellable_rooms) * 100, 1)

        return {
            "occupancy_rate": occupancy_rate,
            "occupied_rooms": occupied_rooms,
            "available_rooms": available_rooms,
            "total_rooms": total_rooms,
            "sellable_rooms": sellable_rooms,
            "total_operational": sellable_rooms,
        }

    @api.model
    def _get_room_status_data(self):
        """Get room status counts and percentages."""
        status_counts = self._room_status_counts()
        total_rooms = sum(status_counts.values())

        def percentage(status):
            if not total_rooms:
                return 0
            return round((status_counts.get(status, 0) / total_rooms) * 100, 1)

        display_statuses = (
            "available", "reserved", "occupied", "dirty",
            "cleaning", "clean", "inspected", "out_of_service",
        )
        return {
            "total_rooms": total_rooms,
            "status_counts": {
                "available": status_counts.get("available", 0),
                "reserved": status_counts.get("reserved", 0),
                "occupied": status_counts.get("occupied", 0),
                "dirty": status_counts.get("dirty", 0),
                "cleaning": status_counts.get("cleaning", 0),
                "clean": status_counts.get("clean", 0),
                "inspected": status_counts.get("inspected", 0),
                "out_of_service": status_counts.get("out_of_service", 0),
                "maintenance": status_counts.get("out_of_service", 0),
            },
            "status_percentages": {
                status: percentage(status) for status in display_statuses
            },
        }

    @api.model
    def _get_front_desk_data(self, today):
        """Get front desk operations data for today."""
        reservation_model = self.env["hotel.reservation"]
        comp_dom = self._company_domain()

        # Today's arrivals
        arrivals = reservation_model.search_count(comp_dom + [
            ("checkin", ">=", datetime.combine(today, datetime.min.time())),
            ("checkin", "<=", datetime.combine(today, datetime.max.time())),
            ("state", "in", ["confirmed", "checked_in"]),
        ])

        # Today's departures
        departures = reservation_model.search_count(comp_dom + [
            ("checkout", ">=", datetime.combine(today, datetime.min.time())),
            ("checkout", "<=", datetime.combine(today, datetime.max.time())),
            ("state", "in", ["confirmed", "checked_in", "checked_out"]),
        ])

        # Currently checked-in guests
        checked_in = reservation_model.search_count(comp_dom + [("state", "=", "checked_in")])

        # Guests checked out today (actual checkout today)
        checked_out_today = reservation_model.search_count(comp_dom + [
            ("actual_checkout", ">=", datetime.combine(today, datetime.min.time())),
            ("actual_checkout", "<=", datetime.combine(today, datetime.max.time())),
            ("state", "=", "checked_out"),
        ])

        # Pending confirmations
        pending_confirmations = reservation_model.search_count(comp_dom + [("state", "=", "draft")])

        # Books Today = walk-in reservations registered at the desk today
        # (create date), regardless of planned stay dates.
        day_start = datetime.combine(today, datetime.min.time())
        day_end = datetime.combine(today, datetime.max.time())
        books_today = reservation_model.search_count(comp_dom + [
            ("source", "=", "walkin"),
            ("create_date", ">=", day_start),
            ("create_date", "<=", day_end),
            ("state", "not in", ["cancelled"]),
        ])
        # Arrived Today = guests who completed check-in today (any source).
        arrived_today = reservation_model.search_count(comp_dom + [
            ("actual_checkin", ">=", day_start),
            ("actual_checkin", "<=", day_end),
            ("state", "in", ["checked_in", "checked_out"]),
        ])

        # In-house folio balances — same formula as departures and billing alerts.
        in_house = reservation_model.search(comp_dom + [("state", "=", "checked_in")])
        outstanding = 0.0
        try:
            outstanding = round(sum(in_house.mapped("folio_outstanding")), 2)
        except Exception:
            pass

        return {
            "arrivals": arrivals,
            "departures": departures,
            "checked_in": checked_in,
            "checked_out_today": checked_out_today,
            "pending_confirmations": pending_confirmations,
            "books_today": books_today,
            "walkins_today": books_today,  # backward-compatible alias
            "arrived_today": arrived_today,
            "outstanding": outstanding,
        }

    @api.model
    def get_availability_data(self, date=None, group_by=None):
        """Build the pretty one-day room availability board.

        Every active room is shown as a coloured card. The card reflects
        the stay that is blocking the room on the selected date (reserved /
        occupied with the guest name) or, when nobody stays that day, the
        housekeeping status of the room (available / clean / dirty / ...).

        ``group_by`` selects how rooms are grouped: by room type (default,
        with the floors nested inside) or by floor.
        """
        date_obj = fields.Date.to_date(date) or fields.Date.context_today(self)
        day_start = datetime.combine(date_obj, datetime.min.time())
        day_end = datetime.combine(date_obj, datetime.max.time())

        comp_dom = self._company_domain()
        rooms = self.env["hotel.room"].search(
            comp_dom + [("active", "=", True)], order="floor, sequence, number",
        )
        stays = self.env["hotel.reservation"].search(
            comp_dom + [
                ("room_id", "!=", False),
                ("state", "in", ["confirmed", "checked_in"]),
                ("checkin", "<", day_end),
                ("checkout", ">", day_start),
            ],
            order="checkin",
        )
        stays_by_room = {}
        for stay in stays:
            stays_by_room.setdefault(stay.room_id.id, []).append(stay)

        status_labels = dict(self.env["hotel.room"]._fields["status"].selection)
        card = []
        for room in rooms:
            active_stays = stays_by_room.get(room.id, [])
            booked = bool(active_stays)
            stay = active_stays[0] if active_stays else False

            if booked:
                availability = "occupied" if any(s.state == "checked_in" for s in active_stays) else "reserved"
                # Show primary/current stay info, but also include all stays
                guests_names = ", ".join(s.guest_id.name for s in active_stays if s.guest_id)
                checkins = [s.checkin.date().isoformat() for s in active_stays if s.checkin]
                checkouts = [s.checkout.date().isoformat() for s in active_stays if s.checkout]
                info = {
                    "availability": availability,
                    "reservation_id": stay.id,
                    "reservation_name": "; ".join(s.name for s in active_stays),
                    "guest_name": guests_names or (stay.guest_id.name if stay.guest_id else ""),
                    "guests": sum(s.adults + s.children for s in active_stays),
                    "checkin": min(checkins) if checkins else (stay.checkin.date().isoformat() if stay.checkin else False),
                    "checkout": max(checkouts) if checkouts else (stay.checkout.date().isoformat() if stay.checkout else False),
                    "arriving": bool(stay.checkin and stay.checkin.date() == date_obj),
                    "departing": bool(
                        stay.checkout and stay.checkout.date() == date_obj,
                    ),
                    "stays": [
                        {
                            "id": s.id,
                            "name": s.name,
                            "guest_name": s.guest_id.name if s.guest_id else "",
                            "checkin": s.checkin.date().isoformat() if s.checkin else False,
                            "checkout": s.checkout.date().isoformat() if s.checkout else False,
                            "state": s.state,
                        }
                        for s in active_stays
                    ],
                }
            else:
                availability = (
                    "available" if room.status in ("available", "clean", "inspected", "reserved") else room.status
                )
                next_stay = False
                if availability == "available":
                    next_stay = self.env["hotel.reservation"].search(
                        comp_dom + [
                            ("room_id", "=", room.id),
                            ("state", "in", ["confirmed", "checked_in"]),
                            ("checkin", ">", day_start),
                        ],
                        order="checkin",
                        limit=1,
                    )
                info = {
                    "availability": availability,
                    "next_stay": {
                        "id": next_stay.id,
                        "name": next_stay.name,
                        "guest_name": next_stay.guest_id.name if next_stay and next_stay.guest_id else "",
                        "checkin": next_stay.checkin.date().isoformat() if next_stay and next_stay.checkin else False,
                        "checkout": next_stay.checkout.date().isoformat() if next_stay and next_stay.checkout else False,
                    } if next_stay else False,
                }

            card.append({
                "id": room.id,
                "number": room.number,
                "room_type": room.room_type_id.name,
                "room_type_id": room.room_type_id.id,
                "floor": room.floor or 1,
                "capacity": room.capacity,
                "status": room.status,
                "status_label": status_labels.get(room.status, room.status),
                "is_sellable": room.is_sellable,
                **info,
            })

        groups = self._build_availability_groups(card, group_by or "type")

        counts = {}
        for room in card:
            key = room["availability"]
            counts[key] = counts.get(key, 0) + 1

        return {
            "date": date_obj.isoformat(),
            "group_by": group_by or "type",
            "groups": groups,
            "counts": counts,
        }

    @api.model
    def _build_availability_groups(self, card, group_by):
        """Group the availability cards by floor or by room type."""
        if group_by == "floor":
            groups = []
            for floor in sorted({r["floor"] for r in card}):
                groups.append(
                    {
                        "key": "floor-%s" % floor,
                        "title": _("Floor %s") % floor,
                        "rooms": [r for r in card if r["floor"] == floor],
                        "floors": [],
                    },
                )
            return groups

        type_ids = []
        type_names = {}
        for room in card:
            type_id = room["room_type_id"]
            if type_id not in type_names:
                type_names[type_id] = room["room_type"]
                type_ids.append(type_id)
        groups = []
        for type_id in type_ids:
            rooms = [r for r in card if r["room_type_id"] == type_id]
            floors = []
            for floor in sorted({r["floor"] for r in rooms}):
                floors.append(
                    {
                        "floor": floor,
                        "title": _("Floor %s") % floor,
                        "rooms": [r for r in rooms if r["floor"] == floor],
                    },
                )
            groups.append(
                {
                    "key": "type-%s" % (type_id or 0),
                    "title": type_names.get(type_id) or _("Unassigned"),
                    "room_type_id": type_id,
                    "rooms": rooms,
                    "floors": floors,
                },
            )
        groups.sort(key=lambda group: group["title"] or "")
        return groups

    @api.model
    def _get_recent_reservations(self, limit=10):
        """Newest reservations with the fields reception needs."""
        try:
            rows = self.env["hotel.reservation"].search_read(
                self._company_domain() + [("state", "not in", ["cancelled", "no_show"])],
                fields=[
                    "name", "guest_id", "room_id", "checkin", "checkout",
                    "state", "total",
                ],
                order="create_date desc, id desc",
                limit=limit,
            )
            room_numbers = self._room_numbers(
                [row["room_id"][0] if row["room_id"] else False for row in rows],
            )
            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "guest_id": row["guest_id"][0] if row["guest_id"] else False,
                    "guest_name": row["guest_id"][1] if row["guest_id"] else "",
                    "room_id": row["room_id"][0] if row["room_id"] else False,
                    "room_number": room_numbers.get(row["room_id"][0], "") if row["room_id"] else "",
                    "checkin": self._format_datetime_safe(row.get("checkin"), "%b %d"),
                    "checkout": self._format_datetime_safe(row.get("checkout"), "%b %d"),
                    "total": row["total"] or 0.0,
                    "state": row["state"],
                    "state_label": self._reservation_state_label(row["state"]),
                }
                for row in rows
            ]
        except Exception:
            return []

    @api.model
    def _get_revenue_data(self, date_from, date_to):
        """Get revenue data with trend calculation."""
        invoice_model = self.env["account.move"]
        invoice_domain = [
            ("move_type", "=", "out_invoice"),
            ("hotel_reservation_id", "!=", False),
            ("state", "=", "posted"),
            ("invoice_date", ">=", date_from),
            ("invoice_date", "<=", date_to),
        ]

        revenue_from_invoices, invoice_count = self._sum_aggregate(
            invoice_model, invoice_domain, "amount_total",
        )
        accounting_readable = True
        try:
            self.env["account.move"].check_access("read")
        except AccessError:
            accounting_readable = False

        # Reservations settled during the period, used when no invoice was posted.
        revenue_from_reservations = 0.0
        try:
            reservation_rows = self.env["hotel.reservation"]._read_group(
                self._company_domain() + [
                    ("actual_checkout", ">=", datetime.combine(date_from, datetime.min.time())),
                    ("actual_checkout", "<=", datetime.combine(date_to, datetime.max.time())),
                    ("state", "=", "checked_out"),
                ],
                [],
                ["total:sum"],
            )
            revenue_from_reservations = reservation_rows[0][0] or 0.0 if reservation_rows else 0.0
        except Exception:
            pass

        if invoice_count:
            total_revenue = revenue_from_invoices
            source = "invoices"
        else:
            total_revenue = revenue_from_reservations
            source = "reservations"

        # Same length period right before the selected one, for comparison
        period_days = (date_to - date_from).days + 1
        prev_revenue, _prev_count = self._sum_aggregate(
            invoice_model,
            invoice_domain[:-2] + [
                ("invoice_date", ">=", date_from - timedelta(days=period_days)),
                ("invoice_date", "<=", date_from - timedelta(days=1)),
            ],
            "amount_total",
        )

        currency_symbol = "$"
        try:
            currency_symbol = self.env.company.currency_id.symbol or "$"
        except Exception:
            pass

        return {
            "revenue": total_revenue,
            "total_revenue": total_revenue,
            "invoice_revenue": revenue_from_invoices,
            "reservation_revenue": revenue_from_reservations,
            "invoice_count": invoice_count,
            "source": source,
            "available": accounting_readable,
            "currency_symbol": currency_symbol,
            "change": self._calculate_percentage_change(total_revenue, prev_revenue),
            "label": _("vs. previous %s days") % period_days,
        }

    @api.model
    def _get_operations_kpis(self, date_from, date_to):
        """Cost and control KPIs taken from the hotel operational records.

        Every figure is aggregated server side and degrades to zero when the
        current role cannot read the underlying model, so reception and the
        different department screens keep working.
        """
        day_start = datetime.combine(date_from, datetime.min.time())
        day_end = datetime.combine(date_to, datetime.max.time())
        comp_dom = self._company_domain()

        minibar_revenue, minibar_count = self._sum_aggregate(
            self.env["hotel.room.consumption"],
            comp_dom + [
                ("state", "=", "posted"),
                ("stay_date", ">=", date_from),
                ("stay_date", "<=", date_to),
            ],
            "total_charge",
        )
        discount_amount, discount_count = self._sum_aggregate(
            self.env["hotel.discount.approval"],
            comp_dom + [
                ("state", "=", "approved"),
                ("action_date", ">=", day_start),
                ("action_date", "<=", day_end),
            ],
            "discount_amount",
        )
        credit_sales, credit_count = self._sum_aggregate(
            self.env["hotel.credit.approval"],
            comp_dom + [
                ("state", "=", "approved"),
                ("approval_date", ">=", day_start),
                ("approval_date", "<=", day_end),
            ],
            "requested_amount",
        )

        currency_symbol = "$"
        try:
            currency_symbol = self.env.company.currency_id.symbol or "$"
        except Exception:
            pass

        return {
            "currency_symbol": currency_symbol,
            "minibar_revenue": {
                "value": minibar_revenue,
                "count": minibar_count,
            },
            "discount_amount": {
                "value": discount_amount,
                "count": discount_count,
            },
            "credit_sales": {
                "value": credit_sales,
                "count": credit_count,
            },
        }

    # ------------------------------------------------------------------
    # Operational KPI drill-downs
    # ------------------------------------------------------------------
    @api.model
    def action_open_room_consumption_report(self, date_from=None, date_to=None):
        """Open the posted minibar / room consumption of the period."""
        domain = [("state", "=", "posted")]
        if date_from and date_to:
            d_from = fields.Date.to_date(date_from)
            d_to = fields.Date.to_date(date_to)
            domain += [
                ("stay_date", ">=", d_from),
                ("stay_date", "<=", d_to),
            ]
        return self._act_window(
            name=_("Minibar / Room Consumption"),
            res_model="hotel.room.consumption",
            view_mode="list,form",
            domain=domain,
        )

    @api.model
    def action_open_discount_approvals(self, date_from=None, date_to=None):
        """Open the approved discounts of the period."""
        domain = [("state", "=", "approved")]
        if date_from and date_to:
            d_from = fields.Date.to_date(date_from)
            d_to = fields.Date.to_date(date_to)
            domain += [
                ("action_date", ">=", datetime.combine(d_from, datetime.min.time())),
                ("action_date", "<=", datetime.combine(d_to, datetime.max.time())),
            ]
        return self._act_window(
            name=_("Discounts"),
            res_model="hotel.discount.approval",
            view_mode="list,form",
            domain=domain,
        )

    @api.model
    def action_open_credit_approvals(self, date_from=None, date_to=None):
        """Open the approved credit sales of the period."""
        domain = [("state", "=", "approved")]
        if date_from and date_to:
            d_from = fields.Date.to_date(date_from)
            d_to = fields.Date.to_date(date_to)
            domain += [
                ("approval_date", ">=", datetime.combine(d_from, datetime.min.time())),
                ("approval_date", "<=", datetime.combine(d_to, datetime.max.time())),
            ]
        return self._act_window(
            name=_("Credit Sales"),
            res_model="hotel.credit.approval",
            view_mode="list,form",
            domain=domain,
        )

    @api.model
    def _sum_aggregate(self, model, domain, field):
        """Return (sum, record_count) for a numeric field over a domain."""
        try:
            rows = model._read_group(domain, [], [f"{field}:sum", "__count"])
            if not rows:
                return 0.0, 0
            total, count = rows[0]
            return total or 0.0, count
        except Exception:
            return 0.0, 0

    @api.model
    def _trend_granularity(self, date_from, date_to):
        """Daily for short periods, weekly for a quarter, monthly beyond."""
        days = (date_to - date_from).days + 1
        if days <= 31:
            return "day"
        if days <= 92:
            return "week"
        return "month"

    @api.model
    def _trend_buckets(self, date_from, date_to, granularity):
        """Every bucket start in the range, so empty periods still show a zero."""
        buckets = []
        current = date_from
        while current <= date_to:
            if granularity == "day":
                buckets.append(current)
                current += timedelta(days=1)
            elif granularity == "week":
                start_of_week = current - timedelta(days=current.weekday())
                if start_of_week not in buckets:
                    buckets.append(start_of_week)
                current += timedelta(days=1)
            else:
                month_start = current.replace(day=1)
                if month_start not in buckets:
                    buckets.append(month_start)
                current = month_start + relativedelta(months=1)
        return buckets

    @api.model
    def _trend_label(self, bucket, granularity):
        if granularity == "day":
            return bucket.strftime("%b %d")
        if granularity == "week":
            return _("W%s") % bucket.isocalendar()[1]
        return bucket.strftime("%b %Y")

    @api.model
    def _trend_series_safe(self, model, domain, field, granularity, aggregate="__count"):
        """Trend series that yields no data instead of raising on access."""
        try:
            return self._trend_series(model, domain, field, granularity, aggregate)
        except Exception:
            return {}

    @api.model
    def _trend_series(self, model, domain, field, granularity, aggregate="__count"):
        """Aggregate a domain per time bucket, keyed by bucket start date."""
        try:
            groupby = f"{field}:{granularity}"
            rows = model._read_group(domain, [groupby], [aggregate])
            # Datetime fields come back as datetimes, date fields as dates.
            result = {}
            for bucket, value in rows:
                if not bucket:
                    continue
                if isinstance(bucket, datetime):
                    key = bucket.date()
                elif isinstance(bucket, str):
                    try:
                        key = fields.Date.from_string(bucket[:10])
                    except Exception:
                        key = bucket
                else:
                    key = bucket
                result[key] = value or 0
            return result
        except Exception:
            return {}

    @api.model
    def _get_reservation_trend_data(self, date_from, date_to):
        """Reservation trend chart, aggregated on the server."""
        granularity = self._trend_granularity(date_from, date_to)
        reservation_model = self.env["hotel.reservation"]
        start = datetime.combine(date_from, datetime.min.time())
        end = datetime.combine(date_to, datetime.max.time())
        counted_states = ["draft", "confirmed", "checked_in", "checked_out"]
        comp_dom = self._company_domain()

        reservations = self._trend_series(
            reservation_model,
            comp_dom + [
                ("checkin", ">=", start), ("checkin", "<=", end),
                ("state", "in", counted_states),
            ],
            "checkin", granularity,
        )
        arrivals = self._trend_series(
            reservation_model,
            comp_dom + [
                ("checkin", ">=", start), ("checkin", "<=", end),
                ("state", "in", ["confirmed", "checked_in"]),
            ],
            "checkin", granularity,
        )
        departures = self._trend_series(
            reservation_model,
            comp_dom + [
                ("checkout", ">=", start), ("checkout", "<=", end),
                ("state", "in", ["confirmed", "checked_in", "checked_out"]),
            ],
            "checkout", granularity,
        )

        buckets = self._trend_buckets(date_from, date_to, granularity)
        return {
            "granularity": granularity,
            "labels": [self._trend_label(bucket, granularity) for bucket in buckets],
            "datasets": [
                {"label": _("Reservations"),
                 "data": [reservations.get(bucket, 0) for bucket in buckets]},
                {"label": _("Arrivals"),
                 "data": [arrivals.get(bucket, 0) for bucket in buckets]},
                {"label": _("Departures"),
                 "data": [departures.get(bucket, 0) for bucket in buckets]},
            ],
        }

    @api.model
    def _get_revenue_trend_data(self, date_from, date_to):
        """Revenue trend chart, aggregated on the server."""
        granularity = self._trend_granularity(date_from, date_to)
        revenue = self._trend_series_safe(
            self.env["account.move"],
            [("move_type", "=", "out_invoice"),
             ("hotel_reservation_id", "!=", False),
             ("state", "=", "posted"),
             ("invoice_date", ">=", date_from),
             ("invoice_date", "<=", date_to)],
            "invoice_date", granularity, aggregate="amount_total:sum",
        )

        buckets = self._trend_buckets(date_from, date_to, granularity)
        return {
            "granularity": granularity,
            "labels": [self._trend_label(bucket, granularity) for bucket in buckets],
            "datasets": [
                {"label": _("Revenue"),
                 "data": [revenue.get(bucket, 0) for bucket in buckets]},
            ],
        }

    @api.model
    def _get_operational_alerts(self, paid_invoices=None):
        """Get comprehensive operational alerts, all backed by real records."""
        alerts = []
        today = fields.Date.context_today(self)
        reservation_model = self.env["hotel.reservation"]
        comp_dom = self._company_domain()

        try:
            # 1. Reservations due today that were never checked in
            late_arrivals = self._safe_count("hotel.reservation", comp_dom + [
                ("checkin", "<", datetime.combine(today, datetime.min.time())),
                ("state", "=", "confirmed"),
            ])
            if late_arrivals > 0:
                alerts.append({
                    "type": "reservations",
                    "priority": "high",
                    "message": _("%d confirmed arrivals still not checked in") % late_arrivals,
                    "count": late_arrivals,
                    "action": "action_open_late_arrivals",
                    "icon": "fa-user-clock",
                })

            # 2. Guests still in house after their check-out date
            pending_departures = self._safe_count("hotel.reservation", comp_dom + [
                ("checkout", "<", datetime.combine(today, datetime.min.time())),
                ("state", "=", "checked_in"),
            ])
            if pending_departures > 0:
                alerts.append({
                    "type": "reservations",
                    "priority": "high",
                    "message": _("%d check-outs not completed") % pending_departures,
                    "count": pending_departures,
                    "action": "action_open_pending_departures",
                    "icon": "fa-sign-out",
                })

            # 3. Guest folios still carrying a balance (same figure as Front Desk).
            open_folios = reservation_model.search(
                comp_dom + [("state", "in", ["checked_in", "checked_out"])],
            )
            outstanding_balance = 0.0
            try:
                outstanding_balance = round(
                    sum(open_folios.mapped("folio_outstanding")), 2,
                )
            except Exception:
                pass

            if outstanding_balance > 0:
                currency_sym = "$"
                try:
                    currency_sym = self.env.company.currency_id.symbol or "$"
                except Exception:
                    pass
                alerts.append({
                    "type": "billing",
                    "priority": "medium",
                    "message": _("%s outstanding on guest folios")
                    % f"{currency_sym} {outstanding_balance:,.2f}",
                    "count": len(open_folios.filtered(lambda r: (r.folio_outstanding or 0) > 0)),
                    "action": "action_open_outstanding_balances",
                    "icon": "fa-money",
                })

            # 4. Rooms waiting for cleaning (dirty status)
            dirty_rooms = self._safe_count(
                "hotel.room",
                comp_dom + [
                    ("active", "=", True),
                    ("status", "=", "dirty"),
                ],
            )
            if dirty_rooms > 0:
                alerts.append({
                    "type": "housekeeping",
                    "priority": "medium",
                    "message": _("%d rooms waiting for cleaning") % dirty_rooms,
                    "count": dirty_rooms,
                    "action": "action_open_dirty_rooms",
                    "icon": "fa-broom",
                })

            # 5. Rooms taken out of service
            maintenance_rooms = self._safe_count(
                "hotel.room",
                comp_dom + [
                    ("active", "=", True),
                    ("status", "=", "out_of_service"),
                ],
            )
            if maintenance_rooms > 0:
                alerts.append({
                    "type": "maintenance",
                    "priority": "high",
                    "message": _("%d rooms under maintenance") % maintenance_rooms,
                    "count": maintenance_rooms,
                    "action": "action_open_maintenance_rooms",
                    "icon": "fa-wrench",
                })

            # 6. High priority complaints
            high_priority_complaints = self._safe_count(
                "hotel.complaint",
                comp_dom + [
                    ("state", "in", ["new", "in_progress"]),
                    ("priority", "in", ["high", "critical"]),
                ],
            )
            if high_priority_complaints > 0:
                alerts.append({
                    "type": "complaints",
                    "priority": "high",
                    "message": _("%d high-priority complaints") % high_priority_complaints,
                    "count": high_priority_complaints,
                    "action": "action_open_high_priority_complaints",
                    "icon": "fa-exclamation-triangle",
                })

            # 7. Reservations awaiting confirmation
            pending_reservations = self._safe_count("hotel.reservation", comp_dom + [("state", "=", "draft")])
            if pending_reservations > 0:
                alerts.append({
                    "type": "reservations",
                    "priority": "medium",
                    "message": _("%d reservations awaiting confirmation") % pending_reservations,
                    "count": pending_reservations,
                    "action": "action_open_pending_reservations",
                    "icon": "fa-clock-o",
                })

            # 8. Overdue housekeeping tasks
            overdue_date = today - timedelta(days=1)
            overdue_cleaning = self._safe_count(
                "hotel.housekeeping.task",
                comp_dom + [
                    ("state", "in", ["pending", "in_progress"]),
                    ("date", "<=", overdue_date),
                ],
            )
            if overdue_cleaning > 0:
                alerts.append({
                    "type": "housekeeping",
                    "priority": "high",
                    "message": _("%d overdue cleaning tasks") % overdue_cleaning,
                    "count": overdue_cleaning,
                    "action": "action_open_overdue_cleaning",
                    "icon": "fa-calendar-times-o",
                })

            # 9. Open maintenance requests
            open_maintenance = self._safe_count(
                "maintenance.request",
                [
                    ("room_id", "!=", False),
                    ("stage_id.done", "=", False),
                    ("archive", "=", False),
                ],
            )
            if open_maintenance > 0:
                alerts.append({
                    "type": "maintenance",
                    "priority": "medium",
                    "message": _("%d open maintenance requests") % open_maintenance,
                    "count": open_maintenance,
                    "action": "action_open_open_maintenance",
                    "icon": "fa-tools",
                })

            alerts.extend(self._get_property_alerts())

            # Sort by priority (high first) then by count (descending)
            priority_order = {"high": 1, "medium": 2, "low": 3}
            alerts.sort(key=lambda x: (priority_order.get(x["priority"], 3), -x["count"]))
        except Exception:
            pass

        return alerts

    # ------------------------------------------------------------------
    # Guest assets / safe deposit block (kept in sync with the security desk)
    # ------------------------------------------------------------------
    @api.model
    def _get_property_data(self):
        """Guest property, safe deposit and lost & found summary."""
        held_states = ("received", "stored", "ready_return")
        today = fields.Date.context_today(self)
        comp_dom = self._company_domain()

        try:
            return {
                "total_properties": self._safe_count("hotel.guest.property", comp_dom),
                "with_guest": self._safe_count("hotel.guest.property", comp_dom + [("state", "=", "guest_possession")]),
                "awaiting_deposit": self._safe_count("hotel.guest.property", comp_dom + [("state", "=", "deposit_requested")]),
                "in_safe": self._safe_count("hotel.guest.property", comp_dom + [("state", "in", held_states)]),
                "ready_return": self._safe_count("hotel.guest.property", comp_dom + [("state", "=", "ready_return")]),
                "open_deposits": self._safe_count("hotel.safe.deposit", comp_dom + [("state", "in", ["received", "stored"])]),
                "returns_due_today": self._safe_count("hotel.guest.property", comp_dom + [
                    ("state", "in", held_states),
                    ("expected_return_date", "=", today),
                ]),
                "overdue_returns": self._safe_count("hotel.guest.property", comp_dom + [
                    ("state", "in", held_states),
                    ("expected_return_date", "<", today),
                ]),
                "open_lost_found": self._safe_count("hotel.lost.found", comp_dom + [
                    ("state", "in", ["found", "stored", "claim_requested", "verified", "unclaimed"]),
                ]),
                "pending_claims": self._safe_count(
                    "hotel.lost.found", comp_dom + [("state", "=", "claim_requested")],
                ),
                "pending_custody": self._safe_count(
                    "hotel.property.custody", comp_dom + [("state", "=", "pending")],
                ),
            }
        except Exception:
            return {
                "total_properties": 0, "with_guest": 0, "awaiting_deposit": 0,
                "in_safe": 0, "ready_return": 0, "open_deposits": 0,
                "returns_due_today": 0, "overdue_returns": 0, "open_lost_found": 0,
                "pending_claims": 0, "pending_custody": 0,
            }

    @api.model
    def _get_property_alerts(self):
        """Security desk alerts, based on the same models as the KPI block."""
        alerts = []
        try:
            property_data = self._get_property_data()

            if property_data.get("returns_due_today"):
                alerts.append({
                    "type": "property",
                    "priority": "medium",
                    "message": _("%d guest items expected back today")
                    % property_data["returns_due_today"],
                    "count": property_data["returns_due_today"],
                    "action": "action_open_returns_due_today",
                    "icon": "fa-calendar-check-o",
                })
            if property_data.get("overdue_returns"):
                alerts.append({
                    "type": "property",
                    "priority": "high",
                    "message": _("%d guest items past their expected return date")
                    % property_data["overdue_returns"],
                    "count": property_data["overdue_returns"],
                    "action": "action_open_overdue_properties",
                    "icon": "fa-exclamation-triangle",
                })
            if property_data.get("awaiting_deposit"):
                alerts.append({
                    "type": "property",
                    "priority": "medium",
                    "message": _("%d items awaiting deposit at reception")
                    % property_data["awaiting_deposit"],
                    "count": property_data["awaiting_deposit"],
                    "action": "action_open_deposit_requested",
                    "icon": "fa-hand-holding-o",
                })
            if property_data.get("pending_custody"):
                alerts.append({
                    "type": "property",
                    "priority": "medium",
                    "message": _("%d custody handovers pending confirmation")
                    % property_data["pending_custody"],
                    "count": property_data["pending_custody"],
                    "action": "action_open_pending_custody",
                    "icon": "fa-exchange",
                })
            if property_data.get("pending_claims"):
                alerts.append({
                    "type": "lost_found",
                    "priority": "medium",
                    "message": _("%d lost & found claims to verify") % property_data["pending_claims"],
                    "count": property_data["pending_claims"],
                    "action": "action_open_pending_claims",
                    "icon": "fa-question-circle",
                })
            old_cutoff = datetime.combine(
                fields.Date.context_today(self) - timedelta(days=30), datetime.min.time(),
            )
            old_items = self._safe_count("hotel.lost.found", self._company_domain() + [
                ("state", "in", ["stored", "unclaimed"]),
                ("found_date", "<", old_cutoff),
            ])
            if old_items:
                alerts.append({
                    "type": "lost_found",
                    "priority": "medium",
                    "message": _("%d items held longer than 30 days") % old_items,
                    "count": old_items,
                    "action": "action_open_old_lost_found",
                    "icon": "fa-archive",
                })
        except Exception:
            pass
        return alerts

    # Helper for building complete act_window dictionaries
    @api.model
    def _act_window(self, name, res_model, view_mode="list,form", domain=None, context=None, res_id=None, target="current"):
        modes = [m.strip() for m in view_mode.split(",") if m.strip()]
        views = [[False, mode] for mode in modes]
        action = {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": res_model,
            "view_mode": view_mode,
            "views": views,
            "target": target,
            "domain": domain or [],
            "context": context or {},
        }
        if res_id:
            action["res_id"] = res_id
        return action

    # Action methods for drill-down functionality
    @api.model
    def action_open_reservations(self, domain=None):
        """Open reservations view with optional domain filter."""
        return self._act_window(
            name=_("Reservations"),
            res_model="hotel.reservation",
            view_mode="list,form",
            domain=domain,
        )

    @api.model
    def action_open_rooms(self, domain=None):
        """Open rooms view with optional domain filter."""
        return self._act_window(
            name=_("Rooms"),
            res_model="hotel.room",
            view_mode="kanban,list,form",
            domain=domain,
        )

    @api.model
    def action_open_housekeeping(self, domain=None):
        """Open housekeeping tasks view with optional domain filter."""
        return self._act_window(
            name=_("Housekeeping Tasks"),
            res_model="hotel.housekeeping.task",
            view_mode="kanban,list,form",
            domain=domain,
        )

    @api.model
    def action_open_complaints(self, domain=None):
        """Open complaints view with optional domain filter."""
        return self._act_window(
            name=_("Guest Complaints"),
            res_model="hotel.complaint",
            view_mode="list,form",
            domain=domain,
        )

    @api.model
    def action_open_maintenance(self, domain=None):
        """Open maintenance requests view with optional domain filter."""
        return self._act_window(
            name=_("Maintenance Requests"),
            res_model="maintenance.request",
            view_mode="list,form",
            domain=domain,
        )

    @api.model
    def action_open_invoices(self, domain=None):
        """Open invoices view with optional domain filter."""
        return self._act_window(
            name=_("Guest Invoices"),
            res_model="account.move",
            view_mode="list,form",
            domain=domain or [("move_type", "=", "out_invoice")],
        )

    # Specific KPI and alert actions
    @api.model
    def action_open_total_reservations(self, date_from=None, date_to=None):
        """Open reservations for the selected period."""
        d_from = fields.Date.to_date(date_from) or fields.Date.context_today(self)
        d_to = fields.Date.to_date(date_to) or d_from

        return self.action_open_reservations([
                ("checkin", ">=", datetime.combine(d_from, datetime.min.time())),
                ("checkin", "<=", datetime.combine(d_to, datetime.max.time())),
                ("state", "in", ["draft", "confirmed", "checked_in", "checked_out"]),
        ])

    @api.model
    def action_open_todays_arrivals(self, date_from=None):
        """Open today's arrivals."""
        target_date = fields.Date.to_date(date_from) or fields.Date.context_today(self)
        return self.action_open_reservations([
                ("checkin", ">=", datetime.combine(target_date, datetime.min.time())),
                ("checkin", "<=", datetime.combine(target_date, datetime.max.time())),
                ("state", "in", ["confirmed", "checked_in"]),
        ])

    @api.model
    def action_open_todays_departures(self, date_from=None):
        """Open today's departures."""
        target_date = fields.Date.to_date(date_from) or fields.Date.context_today(self)
        return self.action_open_reservations([
                ("checkout", ">=", datetime.combine(target_date, datetime.min.time())),
                ("checkout", "<=", datetime.combine(target_date, datetime.max.time())),
                ("state", "in", ["confirmed", "checked_in", "checked_out"]),
        ])

    @api.model
    def action_open_pending_reservations(self):
        """Open reservations awaiting confirmation."""
        return self.action_open_reservations([("state", "=", "draft")])

    @api.model
    def action_open_book_guest(self):
        """Open the Book Guest (walk-in) registration wizard from the dashboard."""
        return self.env["res.partner"].action_open_walkin_wizard()

    @api.model
    def action_open_walkins_today(self):
        """Open walk-in books registered at the desk today."""
        today = fields.Date.context_today(self)
        return self.action_open_reservations([
            ("source", "=", "walkin"),
            ("create_date", ">=", datetime.combine(today, datetime.min.time())),
            ("create_date", "<=", datetime.combine(today, datetime.max.time())),
            ("state", "not in", ["cancelled"]),
        ])

    @api.model
    def action_open_arrived_today(self):
        """Open guests who completed check-in today (any booking source)."""
        today = fields.Date.context_today(self)
        return self.action_open_reservations([
            ("actual_checkin", ">=", datetime.combine(today, datetime.min.time())),
            ("actual_checkin", "<=", datetime.combine(today, datetime.max.time())),
            ("state", "in", ["checked_in", "checked_out"]),
        ])

    @api.model
    def action_open_available_rooms(self):
        """Open available rooms."""
        return self.action_open_rooms([
                ("active", "=", True),
                ("status", "in", ["available", "clean", "inspected"]),
        ])

    @api.model
    def action_open_reserved_rooms(self):
        """Open reserved rooms."""
        return self.action_open_rooms([
                ("active", "=", True),
                ("status", "=", "reserved"),
        ])

    @api.model
    def action_open_occupied_rooms(self):
        """Open occupied rooms."""
        return self.action_open_rooms([
                ("active", "=", True),
                ("status", "=", "occupied"),
        ])

    @api.model
    def action_open_dirty_rooms(self):
        """Open dirty rooms for cleaning."""
        return self.action_open_rooms([
                ("active", "=", True),
                ("status", "=", "dirty"),
        ])

    @api.model
    def action_open_maintenance_rooms(self):
        """Open rooms under maintenance."""
        return self.action_open_rooms([
                ("active", "=", True),
                ("status", "=", "out_of_service"),
        ])

    @api.model
    def action_open_checked_in_guests(self):
        """Open checked-in guests."""
        return self.action_open_reservations([("state", "=", "checked_in")])

    @api.model
    def action_open_checked_out_today(self):
        """Open guests checked out today."""
        today = fields.Date.context_today(self)
        return self.action_open_reservations([
                ("actual_checkout", ">=", datetime.combine(today, datetime.min.time())),
                ("actual_checkout", "<=", datetime.combine(today, datetime.max.time())),
                ("state", "=", "checked_out"),
        ])

    @api.model
    def action_open_high_priority_complaints(self):
        """Open high priority complaints."""
        return self.action_open_complaints([
                ("state", "in", ["new", "in_progress"]),
                ("priority", "in", ["high", "critical"]),
        ])

    @api.model
    def action_open_overdue_cleaning(self):
        """Open overdue cleaning tasks."""
        overdue_date = fields.Date.context_today(self) - timedelta(days=1)
        return self.action_open_housekeeping([
                ("state", "in", ["pending", "in_progress"]),
                ("date", "<=", overdue_date),
        ])

    @api.model
    def action_open_open_maintenance(self):
        """Open unresolved maintenance requests."""
        return self.action_open_maintenance([
                ("room_id", "!=", False),
                ("stage_id.done", "=", False),
                ("archive", "=", False),
        ])

    @api.model
    def action_open_hotel_invoices(self, date_from=None, date_to=None):
        """Open hotel invoices for the period."""
        domain = [
                ("move_type", "=", "out_invoice"),
                ("hotel_reservation_id", "!=", False),
                ("state", "=", "posted"),
        ]

        if date_from and date_to:
            d_from = fields.Date.to_date(date_from)
            d_to = fields.Date.to_date(date_to)
            domain.extend([
                    ("invoice_date", ">=", d_from),
                    ("invoice_date", "<=", d_to),
            ])

        return self.action_open_invoices(domain)

    @api.model
    def action_open_late_arrivals(self):
        """Open confirmed reservations whose guest never showed up to check in."""
        today = fields.Date.context_today(self)
        return self.action_open_reservations([
                ("checkin", "<", datetime.combine(today, datetime.min.time())),
                ("state", "=", "confirmed"),
        ])

    @api.model
    def action_open_pending_departures(self):
        """Open guests still in house after their check-out date."""
        today = fields.Date.context_today(self)
        return self.action_open_reservations([
                ("checkout", "<", datetime.combine(today, datetime.min.time())),
                ("state", "=", "checked_in"),
        ])

    @api.model
    def action_open_outstanding_balances(self):
        """Open guest folios that still carry a balance."""
        stays = self.env["hotel.reservation"].search(
            [("state", "in", ["checked_in", "checked_out"])],
        )
        owing = stays.filtered(lambda reservation: reservation.folio_outstanding > 0)
        return self.action_open_reservations([("id", "in", owing.ids)])

    @api.model
    def action_open_guest_form(self, partner_id):
        """Open the guest profile behind a dashboard row."""
        return self._act_window(
            name=_("Guest"),
            res_model="res.partner",
            view_mode="form",
            res_id=partner_id,
        )

    @api.model
    def action_open_room_form(self, room_id):
        """Open the room behind a dashboard row."""
        return self._act_window(
            name=_("Room"),
            res_model="hotel.room",
            view_mode="form",
            res_id=room_id,
        )

    # ------------------------------------------------------------------
    # Guest assets / safe deposit drill-downs
    # ------------------------------------------------------------------
    @api.model
    def action_open_properties(self, domain=None):
        """Open guest assets with an optional domain filter."""
        return self._act_window(
            name=_("Guest Assets"),
            res_model="hotel.guest.property",
            view_mode="list,form,kanban",
            domain=domain,
        )

    @api.model
    def action_open_safe_deposits(self, domain=None):
        """Open safe deposits with an optional domain filter."""
        return self._act_window(
            name=_("Safe Deposits"),
            res_model="hotel.safe.deposit",
            view_mode="list,form",
            domain=domain or [("state", "in", ["received", "stored"])],
        )

    @api.model
    def action_open_custody_records(self, domain=None):
        """Open custody records with an optional domain filter."""
        return self._act_window(
            name=_("Custody Records"),
            res_model="hotel.property.custody",
            view_mode="list,form",
            domain=domain,
        )

    @api.model
    def action_open_lost_found(self, domain=None):
        """Open lost & found items with an optional domain filter."""
        return self._act_window(
            name=_("Lost & Found"),
            res_model="hotel.lost.found",
            view_mode="kanban,list,form",
            domain=domain,
        )

    @api.model
    def action_open_properties_with_guest(self):
        """Open items currently held by the guest."""
        return self.action_open_properties([("state", "=", "guest_possession")])

    @api.model
    def action_open_held_deposits(self):
        """Open deposits actually held in the safe."""
        return self.action_open_safe_deposits([("state", "in", ["received", "stored"])])

    @api.model
    def action_open_open_properties(self):
        """Open items currently held by the hotel."""
        return self.action_open_properties(
            [("state", "in", ["received", "stored", "ready_return"])],
        )

    @api.model
    def action_open_deposit_requested(self):
        """Open items waiting to be deposited at reception."""
        return self.action_open_properties([("state", "=", "deposit_requested")])

    @api.model
    def action_open_ready_return(self):
        """Open items approved for return to their guest."""
        return self.action_open_properties([("state", "=", "ready_return")])

    @api.model
    def action_open_returns_due_today(self):
        """Open guest items whose expected return date is today."""
        return self.action_open_properties([
            ("state", "in", ["received", "stored", "ready_return"]),
            ("expected_return_date", "=", fields.Date.context_today(self)),
        ])

    @api.model
    def action_open_overdue_properties(self):
        """Open items past their expected return date."""
        return self.action_open_properties([
            ("state", "in", ["received", "stored", "ready_return"]),
            ("expected_return_date", "<", fields.Date.context_today(self)),
        ])

    @api.model
    def action_open_pending_custody(self):
        """Open custody handovers waiting for confirmation."""
        return self.action_open_custody_records([("state", "=", "pending")])

    @api.model
    def action_open_pending_claims(self):
        """Open lost & found claims waiting for verification."""
        return self.action_open_lost_found([("state", "=", "claim_requested")])

    @api.model
    def action_open_old_lost_found(self):
        """Open lost & found items kept for more than 30 days."""
        cutoff = datetime.combine(
            fields.Date.context_today(self) - timedelta(days=30), datetime.min.time(),
        )
        return self.action_open_lost_found([
                ("state", "in", ["stored", "unclaimed"]),
                ("found_date", "<", cutoff),
        ])

    @api.model
    def action_open_reservation_form(self, reservation_id):
        """Open specific reservation form."""
        return self._act_window(
            name=_("Reservation"),
            res_model="hotel.reservation",
            view_mode="form",
            res_id=reservation_id,
        )
