from datetime import datetime, time, timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError

# States that hold a room: they take part in the double-booking check and block
# the room in the availability views.
BLOCKING_STATES = ("confirmed", "checked_in")

# Account payment states that mean the money was actually collected.
PAID_PAYMENT_STATES = ("in_process", "paid")


class HotelReservation(models.Model):
    _name = "hotel.reservation"
    _description = "Hotel Reservation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "checkin desc, id desc"

    name = fields.Char(
        string="Reference",
        required=False,
        default=lambda self: _("New"),
        readonly=True,
        copy=False,
        index=True,
    )
    guest_id = fields.Many2one(
        comodel_name="res.partner",
        string="Guest",
        required=True,
        ondelete="restrict",
        tracking=True,
        index=True,
    )
    source = fields.Selection(
        selection=[
            ("walkin", "Book"),
            ("website", "Website"),
            ("phone", "Phone"),
            ("email", "Email"),
            ("travel_agent", "Travel Agent"),
            ("corporate", "Corporate"),
            ("other", "Other"),
        ],
        string="Booking Source",
        default="walkin",
        required=True,
        tracking=True,
        index=True,
        help="How this stay was booked. Book means the guest arrived "
        "without an advance reservation and was registered at the desk.",
    )
    guest_line_ids = fields.One2many(
        comodel_name="hotel.reservation.guest",
        inverse_name="reservation_id",
        string="Additional Guests",
        help="Additional people sharing the room with the primary guest. "
        "They stay linked to the same reservation.",
    )
    guest_phone = fields.Char(string="Guest Phone")
    room_type_id = fields.Many2one(
        comodel_name="hotel.room.type",
        string="Room Type",
        required=True,
        ondelete="restrict",
        tracking=True,
        index=True,
    )
    room_id = fields.Many2one(
        comodel_name="hotel.room",
        string="Room",
        ondelete="restrict",
        tracking=True,
        index=True,
        help="Only rooms of the selected type, in service and free for the "
        "stay dates are proposed.",
    )
    checkin = fields.Datetime(
        string="Check-in",
        required=True,
        tracking=True,
        index=True,
        help="Expected arrival date and time.",
    )
    checkout = fields.Datetime(
        string="Check-out",
        required=True,
        tracking=True,
        index=True,
        help="Expected departure date and time.",
    )
    adults = fields.Integer(string="Adults", default=1, required=True)
    children = fields.Integer(string="Children", default=0)
    rate = fields.Monetary(
        string="Rate / Night",
        currency_field="currency_id",
        compute="_compute_rate",
        store=True,
        readonly=False,
        precompute=True,
        tracking=True,
        help="Nightly rate. Defaults to the room type rate, or to the guest "
        "pricelist price when the room type has a revenue product.",
    )
    discount = fields.Float(
        string="Discount (%)",
        digits="Discount",
        default=0.0,
        tracking=True,
        help="Percentage discount applied to the room charge (group, "
        "corporate or coffee/tea program rate).",
    )
    deposit = fields.Monetary(
        string="Deposit",
        currency_field="currency_id",
        tracking=True,
        help="Amount already collected at booking time, deducted at check-out.",
    )
    deposit_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Bank or Cash",
        domain="[('type', 'in', ('bank', 'cash'))]",
        tracking=True,
        help="Journal used to collect advance deposits at booking or check-in. Empty falls back to check-out journal.",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("checked_in", "Checked-in"),
            ("checked_out", "Checked-out"),
            ("cancelled", "Cancelled"),
            ("no_show", "No-show"),
        ],
        string="Status",
        default="draft",
        required=True,
        index=True,
        tracking=True,
    )
    actual_checkin = fields.Datetime(string="Actual Check-in", readonly=True, copy=False)
    actual_checkout = fields.Datetime(string="Actual Check-out", readonly=True, copy=False)
    # Compatibility aliases. When an extra service line is edited from the
    # check-out wizard, the web client sends the wizard's modified fields back
    # as the value of the line's ``reservation_id`` (see ``record.js``
    # ``_getOnchangeValues``). Declaring those fields here keeps such payloads
    # valid instead of raising "Invalid field ... on model hotel.reservation".
    checkin_at = fields.Datetime(
        string="Checked In At",
        related="actual_checkin",
        readonly=True,
        store=False,
    )
    checkout_at = fields.Datetime(
        string="Checked Out At",
        related="actual_checkout",
        readonly=True,
        store=False,
    )
    create_invoice = fields.Boolean(
        string="Create Guest Invoice", readonly=True, copy=False,
    )
    settle_balance = fields.Boolean(
        string="Settle Balance Now", readonly=True, copy=False,
    )
    payment_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Payment Journal",
        related="deposit_journal_id",
        readonly=False,
        store=True,
        copy=False,
    )
    notes = fields.Text(string="Notes", readonly=True, copy=False)
    id_type = fields.Selection(
        selection=[
            ("national_id", "National ID"),
            ("passport", "Passport"),
            ("driver_license", "Driver License"),
            ("other", "Other"),
        ],
        string="ID Type",
        help="Identification presented at check-in.",
    )
    id_number = fields.Char(string="ID Number")
    id_document = fields.Binary(
        string="ID Document",
        attachment=True,
        help="Scanned or photographed ID presented at booking / check-in.",
    )
    id_document_filename = fields.Char(string="ID Filename")
    nationality_id = fields.Many2one(
        comodel_name="res.country", string="Nationality", ondelete="restrict",
    )
    registered_guests = fields.Integer(
        string="Registered Guests",
        help="Number of guests actually registered at check-in.",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    line_ids = fields.One2many(
        comodel_name="hotel.reservation.line",
        inverse_name="reservation_id",
        string="Extra Services",
        copy=True,
    )
    consumption_session_ids = fields.One2many(
        comodel_name="hotel.room.consumption",
        inverse_name="reservation_id",
        string="Room Consumption",
        readonly=True,
    )
    consumption_line_ids = fields.One2many(
        comodel_name="hotel.room.consumption.line",
        inverse_name="reservation_id",
        string="Room Consumption Lines",
        readonly=True,
    )
    inspection_ids = fields.One2many(
        comodel_name="hotel.room.inspection",
        inverse_name="reservation_id",
        string="Room Inspections",
        readonly=True,
    )
    invoice_ids = fields.One2many(
        comodel_name="account.move",
        inverse_name="hotel_reservation_id",
        string="Guest Invoices",
        readonly=True,
    )
    deposit_payment_ids = fields.One2many(
        comodel_name="account.payment",
        inverse_name="hotel_reservation_id",
        string="Advance Payments",
        readonly=True,
        copy=False,
        help="Payments collected before the guest invoice: booking deposit and "
        "check-in advance. They are reconciled against the folio at check-out.",
    )
    deposit_paid = fields.Monetary(
        string="Advance Paid",
        currency_field="currency_id",
        compute="_compute_deposit_paid",
        help="Total posted advance payments already collected for this stay.",
    )
    invoice_count = fields.Integer(string="Invoices", compute="_compute_invoice_count")
    feedback_count = fields.Integer(
        string="Feedback", compute="_compute_feedback_count",
    )
    booked_room_ids = fields.Many2many(
        comodel_name="hotel.room",
        string="Rooms Unavailable",
        compute="_compute_booked_room_ids",
        help="Rooms already taken for the stay dates, excluded from the room "
        "selection.",
    )
    color_index = fields.Integer(
        string="Colour Index", compute="_compute_color_index",
    )
    room_number = fields.Char(
        string="Room Number",
        related="room_id.number",
        readonly=True,
        store=True,
    )
    calendar_display_name = fields.Char(
        string="Calendar Display Name",
        compute="_compute_calendar_display_name",
    )
    nights = fields.Integer(string="Nights", compute="_compute_nights", store=True)
    actual_nights = fields.Integer(
        string="Actual Nights",
        compute="_compute_actual_nights",
        store=True,
        help="Nights actually stayed, computed from the real check-in and "
        "check-out stamps. Zero while the guest is still in house.",
    )
    billable_nights = fields.Integer(
        string="Billable Nights",
        compute="_compute_billable_nights",
        help="Actual nights when the stay is over, otherwise the booked nights.",
    )
    room_total = fields.Monetary(
        string="Room Charge",
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
    )
    service_total = fields.Monetary(
        string="Services",
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
    )
    total = fields.Monetary(
        string="Total",
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
        help="Room charge after discount plus extra services, taxes excluded.",
    )
    balance_due = fields.Monetary(
        string="Balance Due",
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
        help="Remaining amount payable by the guest after deducting advance deposit.",
    )
    refund_due = fields.Monetary(
        string="Refund / Excess Deposit",
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
        help="Excess deposit amount to be refunded to the guest.",
    )
    folio_outstanding = fields.Monetary(
        string="Folio Outstanding",
        currency_field="currency_id",
        compute="_compute_folio_outstanding",
        help="Amount still owed on this stay. Uses open invoice residual when a "
        "guest folio invoice is posted; otherwise stay total minus advances. "
        "Front desk, departures and billing alerts all read this figure.",
    )

    _sql_constraints = [
        (
            "checkout_after_checkin",
            "check (checkout > checkin)",
            "Check-out must be later than check-in.",
        ),
        (
            "discount_positive",
            "check (discount >= 0 and discount <= 100)",
            "The discount must be between 0 and 100 percent.",
        ),
        (
            "guests_positive",
            "check (adults > 0 and children >= 0)",
            "A reservation needs at least one adult and no negative child count.",
        ),
    ]

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        company = self.env.company
        hotel_config = self.env["hotel.config"].with_company(company)

        if "checkin" in fields_list and not res.get("checkin"):
            checkin_hour = hotel_config._hotel_default_checkin_time()
            today = fields.Date.context_today(self)
            h = int(checkin_hour)
            m = int(round((checkin_hour - h) * 60))
            checkin_dt = datetime.combine(today, time(hour=min(23, max(0, h)), minute=min(59, max(0, m))))
            res["checkin"] = checkin_dt

        if "checkout" in fields_list and not res.get("checkout"):
            checkin_val = res.get("checkin")
            if checkin_val:
                if isinstance(checkin_val, str):
                    checkin_dt = fields.Datetime.to_datetime(checkin_val)
                else:
                    checkin_dt = checkin_val
            else:
                checkin_dt = datetime.combine(fields.Date.context_today(self), time(14, 0))
            duration = max(1, hotel_config._hotel_default_booking_duration())
            checkout_hour = hotel_config._hotel_default_checkout_time()
            h = int(checkout_hour)
            m = int(round((checkout_hour - h) * 60))
            checkout_date = (checkin_dt + timedelta(days=duration)).date()
            res["checkout"] = datetime.combine(checkout_date, time(hour=min(23, max(0, h)), minute=min(59, max(0, m))))

        if "state" in fields_list and not res.get("state"):
            default_state = hotel_config._hotel_default_reservation_state()
            if default_state in ("draft", "confirmed"):
                res["state"] = default_state

        if "name" in fields_list and not res.get("name"):
            res["name"] = _("New")

        return res

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") in ("New", _("New"), "/"):
                company_id = vals.get("company_id") or self.env.company.id
                seq_obj = self.env["ir.sequence"].with_company(company_id).sudo()
                name = seq_obj.next_by_code("hotel.reservation")
                if not name:
                    seq = self.env["ir.sequence"].sudo().search(
                        [("code", "=", "hotel.reservation")], limit=1
                    )
                    if not seq:
                        seq = self.env["ir.sequence"].sudo().create(
                            {
                                "name": "Hotel Reservation",
                                "code": "hotel.reservation",
                                "prefix": "RES/",
                                "padding": 5,
                                "company_id": False,
                            }
                        )
                    name = seq.with_company(company_id).next_by_id() or _("New")
                vals["name"] = name
            if not vals.get("room_type_id") and vals.get("room_id"):
                room = self.env["hotel.room"].browse(vals["room_id"])
                vals["room_type_id"] = room.room_type_id.id
        records = super().create(vals_list)
        for res in records:
            policy = self.env["hotel.config"].with_company(res.company_id)._hotel_reservation_confirmation_policy()
            if policy == "auto" and res.state == "draft":
                res.action_confirm()
        return records

    @api.depends("room_type_id", "guest_id", "checkin")
    def _compute_rate(self):
        for reservation in self:
            product = reservation.room_type_id.product_id
            price = False
            pricelist = reservation.guest_id.property_product_pricelist
            if product and pricelist:
                price = pricelist._get_product_price(
                    product,
                    1.0,
                    currency=reservation.currency_id,
                    uom=product.uom_id,
                    date=(
                        reservation.checkin.date()
                        if reservation.checkin
                        else fields.Date.context_today(reservation)
                    ),
                )
            reservation.rate = price or reservation.room_type_id.base_price

    @api.model
    def _stay_nights(self, start, end):
        """Nights between two datetimes, counted by calendar day.

        A stay from 14 Oct 03:06 to 17 Oct 03:00 is three nights, even though
        the raw timedelta is just under three days.
        """
        if not start or not end:
            return 0
        return max(1, (end.date() - start.date()).days)

    @api.depends("checkin", "checkout")
    def _compute_nights(self):
        for reservation in self:
            reservation.nights = reservation._stay_nights(
                reservation.checkin, reservation.checkout,
            )

    @api.depends("actual_checkin", "actual_checkout")
    def _compute_actual_nights(self):
        for reservation in self:
            reservation.actual_nights = reservation._stay_nights(
                reservation.actual_checkin, reservation.actual_checkout,
            )

    @api.depends("actual_nights", "nights")
    def _compute_billable_nights(self):
        for reservation in self:
            reservation.billable_nights = reservation.actual_nights or reservation.nights

    @api.depends(
        "billable_nights",
        "rate",
        "discount",
        "deposit",
        "deposit_paid",
        "line_ids.price_subtotal",
        "line_ids.billable",
    )
    def _compute_amounts(self):
        for reservation in self:
            room_charge = reservation.billable_nights * reservation.rate
            room_charge -= room_charge * reservation.discount / 100.0
            services = sum(
                line.price_subtotal
                for line in reservation.line_ids
                if line.billable
            )
            total = room_charge + services
            deposit_effective = reservation.deposit_paid or reservation.deposit or 0.0
            reservation.room_total = room_charge
            reservation.service_total = services
            reservation.total = total
            reservation.balance_due = max(0.0, total - deposit_effective)
            reservation.refund_due = max(0.0, deposit_effective - total)

    @api.depends(
        "total",
        "deposit",
        "deposit_paid",
        "invoice_ids.state",
        "invoice_ids.move_type",
        "invoice_ids.amount_residual",
    )
    def _compute_folio_outstanding(self):
        """Single source of truth for what the guest still owes."""
        for reservation in self:
            posted = reservation.invoice_ids.filtered(
                lambda move: (
                    move.state == "posted"
                    and move.move_type == "out_invoice"
                ),
            )
            if posted:
                reservation.folio_outstanding = sum(
                    posted.mapped("amount_residual"),
                )
            else:
                deposit = reservation.deposit_paid or reservation.deposit or 0.0
                reservation.folio_outstanding = max(
                    (reservation.total or 0.0) - deposit, 0.0,
                )

    @api.depends("state")
    def _compute_color_index(self):
        colors = {
            "draft": 0,
            "confirmed": 4,
            "checked_in": 2,
            "checked_out": 1,
            "cancelled": 9,
            "no_show": 9,
        }
        for reservation in self:
            reservation.color_index = colors.get(reservation.state, 0)

    @api.depends("name", "room_id", "room_id.number", "room_id.name", "guest_id", "guest_id.name")
    def _compute_calendar_display_name(self):
        for reservation in self:
            res_num = reservation.name or ""
            room_no = reservation.room_id.number or reservation.room_id.name or _("Unassigned")
            guest_name = reservation.guest_id.name or _("Guest")
            reservation.calendar_display_name = f"{res_num} - Room {room_no} - Reserved By: {guest_name}"

    @api.depends("checkin", "checkout")
    def _compute_booked_room_ids(self):
        for reservation in self:
            if not reservation.checkin or not reservation.checkout:
                reservation.booked_room_ids = [Command.set([])]
                continue
            others = self.search(
                [
                    ("id", "!=", reservation.id),
                    ("room_id", "!=", False),
                    ("state", "in", BLOCKING_STATES),
                    ("checkin", "<", reservation.checkout),
                    ("checkout", ">", reservation.checkin),
                ],
            )
            reservation.booked_room_ids = [Command.set(others.room_id.ids)]

    @api.depends("deposit_payment_ids.amount", "deposit_payment_ids.state")
    def _compute_deposit_paid(self):
        for reservation in self:
            reservation.deposit_paid = sum(
                reservation.deposit_payment_ids.filtered(
                    lambda payment: payment.state in PAID_PAYMENT_STATES,
                ).mapped("amount"),
            )

    def _compute_invoice_count(self):
        for reservation in self:
            reservation.invoice_count = len(
                reservation.invoice_ids.filtered(
                    lambda move: move.state == "posted",
                ),
            )

    def _compute_feedback_count(self):
        responses = dict(
            self.env["survey.user_input"]._read_group(
                [("reservation_id", "in", self.ids)],
                groupby=["reservation_id"],
                aggregates=["__count"],
            ),
        )
        for reservation in self:
            reservation.feedback_count = responses.get(reservation, 0)

    def _invalidate_stay_feedback(self):
        """Refresh the feedback smart button after responses changed."""
        if self:
            self.invalidate_recordset(["feedback_count"])

    def action_open_survey_feedback(self):
        self.ensure_one()
        return {
            "name": _("Guest Feedback"),
            "type": "ir.actions.act_window",
            "res_model": "survey.user_input",
            "view_mode": "list,form",
            "views": [[False, "list"], [False, "form"]],
            "domain": [("reservation_id", "=", self.id)],
            "context": {"default_reservation_id": self.id},
        }

    @api.onchange("room_type_id")
    def _onchange_room_type_id(self):
        for reservation in self:
            if reservation.room_id.room_type_id != reservation.room_type_id:
                reservation.room_id = False

    @api.onchange("room_id")
    def _onchange_room_id(self):
        for reservation in self:
            if reservation.room_id and reservation.room_type_id != reservation.room_id.room_type_id:
                reservation.room_type_id = reservation.room_id.room_type_id
            if reservation.adults > reservation.room_id.capacity:
                reservation.adults = reservation.room_id.capacity
                reservation.children = 0

    @api.constrains("checkin", "checkout")
    def _check_dates(self):
        for reservation in self:
            if (
                reservation.checkin
                and reservation.checkout
                and reservation.checkout <= reservation.checkin
            ):
                raise ValidationError(
                    _("Check-out (%s) must be later than check-in (%s).")
                    % (reservation.checkout, reservation.checkin),
                )

    @api.constrains("room_id", "checkin", "checkout", "state")
    def _check_overlap(self):
        """Reject a reservation overlapping another stay in the same room."""
        for reservation in self:
            if reservation.state not in BLOCKING_STATES or not reservation.room_id:
                continue
            domain = [
                ("id", "!=", reservation.id),
                ("room_id", "=", reservation.room_id.id),
                ("state", "in", BLOCKING_STATES),
                ("checkin", "<", reservation.checkout),
                ("checkout", ">", reservation.checkin),
            ]
            if self.search_count(domain):
                raise ValidationError(
                    _("Room %s is already booked for these dates.")
                    % reservation.room_id.number,
                )

    @api.constrains("room_id", "room_type_id", "adults", "children")
    def _check_capacity(self):
        for reservation in self:
            room = reservation.room_id
            if not room:
                continue
            if room.room_type_id != reservation.room_type_id:
                raise ValidationError(
                    _("Room %s is not of type %s.")
                    % (room.number, reservation.room_type_id.name),
                )
            adults = reservation.adults
            children = reservation.children
            if adults > room.capacity:
                raise ValidationError(
                    _("Room %s hosts %d guests but %d adults are booked.")
                    % (room.number, room.capacity, adults),
                )
            max_children = room.room_type_id.child_capacity
            if max_children and children > max_children:
                raise ValidationError(
                    _("Room %s accepts at most %d children.")
                    % (room.number, max_children),
                )

    def _action_set_state(self, state):
        for reservation in self:
            reservation.state = state

    def action_confirm(self):
        for reservation in self:
            if reservation.state != "draft":
                raise ValidationError(
                    _("Only draft reservations can be confirmed."),
                )
            if not reservation.room_id:
                raise ValidationError(
                    _("Select a room before confirming reservation %s.")
                    % reservation.name,
                )
            if reservation.room_id.status == "out_of_service":
                raise ValidationError(
                    _("Room %s is out of service and cannot be booked.")
                    % reservation.room_id.number,
                )
        self._action_set_state("confirmed")
        self.mapped("room_id")._sync_status_for_stay(
            "reserved", _("Reserved for a confirmed stay."),
        )
        return True

    def action_cancel(self):
        for reservation in self:
            if reservation.state not in ("draft", "confirmed"):
                raise ValidationError(
                    _("Only draft or confirmed reservations can be cancelled."),
                )
            if reservation.state == "confirmed" and reservation.room_id:
                reservation.room_id._sync_status_for_stay(
                    "available", _("Reservation cancelled, room released."),
                )
            policy = self.env["hotel.config"].with_company(reservation.company_id)._hotel_cancellation_policy()
            if policy == "deposit_forfeit" and reservation.deposit_paid > 0:
                reservation.message_post(body=_("Reservation cancelled under Forfeit Deposit policy. Retained deposit: %s", reservation.deposit_paid))
            elif policy == "penalty":
                reservation.message_post(body=_("Reservation cancelled under Cancellation Penalty policy."))
        self._action_set_state("cancelled")
        return True

    def action_no_show(self):
        for reservation in self:
            if reservation.state != "confirmed":
                raise ValidationError(
                    _("Only confirmed reservations can be marked as no-show."),
                )
            if reservation.room_id:
                reservation.room_id._sync_status_for_stay(
                    "available", _("Guest did not show up, room released."),
                )
        self._action_set_state("no_show")
        return True

    def action_checkin(self):
        self.ensure_one()
        if self.state != "confirmed":
            raise ValidationError(
                _("Only confirmed reservations can be checked in."),
            )
        if self.room_id.status not in ("clean", "inspected", "available", "reserved"):
            raise ValidationError(
                _(
                    "Room %(room)s is currently \"%(status)s\". "
                    "Finish housekeeping (or release maintenance) so the room "
                    "is clean, inspected, available or reserved before check-in.",
                    room=self.room_id.number,
                    status=dict(self.room_id._fields["status"].selection).get(
                        self.room_id.status, self.room_id.status
                    ),
                )
            )
        return {
            "name": _("Guest Check-in"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.checkin.wizard",
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
            "context": {
                **self.env.context,
                "default_reservation_id": self.id,
            },
        }

    def action_checkout(self):
        self.ensure_one()
        if self.state != "checked_in":
            raise ValidationError(
                _("Only checked-in reservations can be checked out."),
            )
        if self.env["hotel.config"]._hotel_require_checkout_inspection() and self._checkout_room_has_consumables():
            inspection = self._get_or_create_checkout_inspection()
            if inspection and inspection.state != "approved":
                return inspection._open_form()
        return {
            "name": _("Guest Check-out"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.checkout.wizard",
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
            "context": {
                **self.env.context,
                "default_reservation_id": self.id,
            },
        }

    def action_open_invoices(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "account.action_move_in_invoice_type",
        )
        action["domain"] = [("id", "in", self.invoice_ids.ids)]
        action["context"] = {"create": False}
        action["name"] = _("Guest Invoices")
        return action

    def action_open_complaints(self):
        self.ensure_one()
        return {
            "name": _("Complaints"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.complaint",
            "view_mode": "list,form",
            "views": [[False, "list"], [False, "form"]],
            "domain": [("reservation_id", "=", self.id)],
            "context": {"default_reservation_id": self.id, "default_room_id": self.room_id.id},
        }

    def _get_income_account_for_product(self, product=None):
        account = False
        if product:
            accounts = product.product_tmpl_id.get_product_accounts() if hasattr(product.product_tmpl_id, "get_product_accounts") else {}
            account = (
                accounts.get("income")
                or product.property_account_income_id
                or (hasattr(product, "product_tmpl_id") and product.product_tmpl_id.property_account_income_id)
                or (hasattr(product, "categ_id") and product.categ_id.property_account_income_categ_id)
            )
        if not account:
            account = self.env["hotel.config"].with_company(self.company_id)._hotel_income_account()
        return account

    def _folio_invoice_lines(self):
        """Invoice lines for the guest folio: room charge plus extra services."""
        self.ensure_one()
        lines = [Command.create(self._room_invoice_line_vals())]
        for line in self.line_ids.filtered("billable"):
            vals = {
                "name": line.name,
                "quantity": line.qty,
                "price_unit": line.price_unit,
                "discount": line.discount,
            }
            if line.product_id:
                vals["product_id"] = line.product_id.id
            account = self._get_income_account_for_product(line.product_id)
            if account:
                vals["account_id"] = account.id
            lines.append(Command.create(vals))
        return lines

    def _room_invoice_line_vals(self):
        """Values of the room revenue line, posting to the room income account."""
        self.ensure_one()
        start = self.actual_checkin or self.checkin
        end = self.actual_checkout or self.checkout
        vals = {
            "name": _(
                "%(room_type)s - room %(room)s, %(checkin)s to %(checkout)s",
                room_type=self.room_type_id.name,
                room=self.room_id.number,
                checkin=fields.Date.to_string(start),
                checkout=fields.Date.to_string(end),
            ),
            "quantity": self.billable_nights,
            "price_unit": self.rate,
            "discount": self.discount,
        }
        product = (
            self.room_type_id.product_id
            or self.env["hotel.config"].with_company(self.company_id)._hotel_default_product()
        )
        if product:
            vals["product_id"] = product.id
        account = (
            self.room_type_id.income_account_id
            or self._get_income_account_for_product(product)
        )
        if account:
            vals["account_id"] = account.id
        analytic = self.room_type_id.analytic_account_id
        if analytic:
            vals["analytic_distribution"] = {str(analytic.id): 100}
        taxes = (
            self.room_type_id.tax_ids
            or (product and product.taxes_id)
            or self.env["hotel.config"].with_company(self.company_id)._hotel_default_taxes()
        )
        if taxes:
            vals["tax_ids"] = [Command.set(taxes.ids)]
        return vals

    def _bill_pending_room_consumption(self):
        """Push every chargeable room consumption sheet of the stay to the folio.

        Daily consumption is billed as soon as it is recorded or posted, but a
        stay can be closed while a sheet is still draft or assigned (reception
        filled the quantities but never clicked Record) or merely reviewed.
        Every sheet that is not posted yet is billed here, so the guest never
        leaves without paying for what was consumed. Sheets that were already
        billed keep their ``folio_line_id`` and are skipped, so this is safe to
        call more than once.
        """
        self.ensure_one()
        consumptions = self.env["hotel.room.consumption"].search(
            [
                ("reservation_id", "=", self.id),
                ("state", "in", ("draft", "assigned", "recorded", "reviewed")),
            ],
        )
        for consumption in consumptions:
            consumption._post_folio_charges()

    def _action_create_folio_invoice(self):
        """Create the draft guest invoice for this stay."""
        self.ensure_one()
        if self.invoice_ids:
            raise UserError(
                _("Reservation %s is already invoiced.") % self.name,
            )
        if self.state not in ("checked_in", "checked_out"):
            raise UserError(
                _("Reservation %s is not checked in, nothing to invoice.")
                % self.name,
            )
        self.env["hotel.config"].validate_accounting_config(self.company_id, check_sales=True)
        # Make sure the clearing account is typed correctly and a receivable
        # account exists, so the invoice and its payment-term line post.
        self.env["hotel.config"]._create_room_charge_clearing_account(self.company_id)
        rec_account = self.env["hotel.config"].with_company(self.company_id)._hotel_receivable_account()
        if not self.guest_id.property_account_receivable_id and rec_account:
            self.guest_id.property_account_receivable_id = rec_account
        journal = self.env["hotel.config"].with_company(self.company_id)._hotel_sales_journal()
        return self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "journal_id": journal.id,
                "partner_id": self.guest_id.id,
                "company_id": self.company_id.id,
                "currency_id": self.currency_id.id,
                "invoice_date": fields.Date.context_today(self),
                "hotel_reservation_id": self.id,
                "invoice_origin": self.name,
                "invoice_line_ids": self._folio_invoice_lines(),
            },
        )

    def _action_register_deposit_payment(self, amount, journal=None, memo=None):
        """Collect ``amount`` now and book it as an advance on the guest folio.

        Creates a posted inbound customer payment linked to this reservation so
        the cash/transfer shows in the journal at once. The payment is later
        reconciled against the guest invoice at check-out.
        """
        self.ensure_one()
        if self.currency_id.is_zero(amount):
            return self.env["account.payment"]
        self.env["hotel.config"].validate_accounting_config(self.company_id, check_deposit=True)
        journal = (
            journal
            or self.deposit_journal_id
            or self.payment_journal_id
            or self.env["hotel.config"].with_company(self.company_id)._hotel_deposit_journal()
        )
        if not journal:
            raise UserError(
                _(
                    "No bank, cash or credit card journal is available to "
                    "collect the advance. Set one on the booking or the check-out journal.",
                ),
            )
        rec_account = self.env["hotel.config"].with_company(self.company_id)._hotel_receivable_account()
        if not self.guest_id.property_account_receivable_id and rec_account:
            self.guest_id.property_account_receivable_id = rec_account
        payment = self.env["account.payment"].create(
            {
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": self.guest_id.id,
                "amount": amount,
                "journal_id": journal.id,
                "currency_id": self.currency_id.id,
                "date": fields.Date.context_today(self),
                "memo": memo or _("Advance %(name)s", name=self.name),
                "hotel_reservation_id": self.id,
            },
        )
        payment.action_post()
        self.invalidate_recordset(["deposit_payment_ids", "deposit_paid"])
        policy = self.env["hotel.config"].with_company(self.company_id)._hotel_reservation_confirmation_policy()
        if policy == "deposit" and self.state == "draft" and self.deposit_paid >= self.deposit:
            self.action_confirm()
        return payment

    def action_register_deposit(self):
        """Collect the unpaid booking deposit on the chosen Bank/Cash journal."""
        for reservation in self:
            amount = reservation.deposit - reservation.deposit_paid
            if amount <= 0:
                raise UserError(
                    _("No unpaid deposit balance for reservation %s.")
                    % reservation.name,
                )
            reservation._action_register_deposit_payment(
                amount,
                journal=reservation.deposit_journal_id,
                memo=_("Advance deposit %(name)s", name=reservation.name),
            )
        return True

    def _reconcile_deposit_payments(self, invoice):
        """Apply the collected advance payments to ``invoice``.

        Returns the total amount reconciled against the invoice.
        """
        self.ensure_one()
        payments = self.env["account.payment"].search(
            [
                ("hotel_reservation_id", "=", self.id),
                ("state", "in", PAID_PAYMENT_STATES),
            ],
        )
        applied = 0.0
        for payment in payments:
            if not payment.move_id:
                if payment not in invoice.matched_payment_ids:
                    invoice.matched_payment_ids |= payment
                applied += min(payment.amount, max(0.0, invoice.amount_total - applied))
                continue
            receivable = invoice.line_ids.filtered(
                lambda line: line.account_id.account_type == "asset_receivable"
                and not line.reconciled,
            )
            credit = payment.move_id.line_ids.filtered(
                lambda line: line.account_id.account_type == "asset_receivable"
                and not line.reconciled,
            )
            matched = min(
                abs(sum(receivable.mapped("amount_residual"))),
                abs(sum(credit.mapped("amount_residual"))),
            )
            if not matched:
                if payment not in invoice.matched_payment_ids:
                    invoice.matched_payment_ids |= payment
                applied += min(payment.amount, max(0.0, invoice.amount_total - applied))
                continue
            (receivable + credit).reconcile()
            applied += matched
        return applied

    def _hotel_require_checkout_inspection(self):
        """Convenience accessor (the reservation is not a hotel.config)."""
        return self.env["hotel.config"]._hotel_require_checkout_inspection()

    def _return_unused_room_supplies(self):
        """Collect the reusable supplies left in the room by the leaving guest.

        Only the most recent consumption record of the stay is used: the unused
        quantities of the earlier days were carried over to it, so nothing is
        returned twice. Returns the created ``stock.picking`` or ``False``.
        """
        self.ensure_one()
        consumption = self.env["hotel.room.consumption"].search(
            [("reservation_id", "=", self.id)],
            order="stay_date desc, id desc",
            limit=1,
        )
        if not consumption:
            return False
        return consumption._return_unused_supplies()

    def _create_checkin_consumption_session(self):
        """Snapshot the room consumables at check-in (idempotent).

        One session per reservation is created from the effective consumable
        configuration of the room. Its ``opening_qty`` defaults to the
        physically expected stock, which is adjusted when the opening stock
        is verified; when the room is turned over by carrying the remaining
        stock, that verified quantity is reused instead of the par level.
        """
        self.ensure_one()
        room = self.room_id
        configs = room._effective_consumables().filtered(
            lambda config: config.included_in_setup and config.active,
        )
        if not configs:
            return self.env["hotel.room.consumption"].browse()
        existing = self.env["hotel.room.consumption"].search(
            [
                ("reservation_id", "=", self.id),
                ("is_checkin_session", "=", True),
            ],
            limit=1,
        )
        if existing:
            return existing
        # Reuse the verified remainder of the last stay when the hotel
        # carries stock forward, instead of the par level.
        last_inspection = self.env["hotel.room.inspection"].search(
            [("room_id", "=", room.id), ("state", "=", "approved")],
            order="inspection_at desc, id desc",
            limit=1,
        )
        carry_forward = bool(
            last_inspection and last_inspection.turnover_policy == "carry_forward",
        )
        carry_map = {}
        if carry_forward:
            for line in last_inspection.line_ids:
                if (
                    line.consumption_line_id
                    and line.consumption_line_id.product_id
                ):
                    carry_map[
                        line.consumption_line_id.product_id.id
                    ] = line.actual_remaining_qty
        now = self.actual_checkin or self.checkin or fields.Datetime.now()
        try:
            stay_date = fields.Date.to_date(now.date())
        except Exception:
            stay_date = fields.Date.context_today(self)
        line_commands = []
        for config in configs:
            product = config.product_id
            standard = config.standard_qty or 0.0
            if carry_forward:
                opening = carry_map.get(product.id, standard)
            else:
                opening = standard
            line_commands.append(
                __import__("odoo", fromlist=["Command"]).Command.create(
                    {
                        "product_id": product.id,
                        "standard_qty": standard,
                        "opening_qty": opening,
                        "provided_qty": 0.0,
                        "consumed_qty": 0.0,
                        "policy": config.policy or "chargeable",
                        "allowance_qty": config.allowance_qty or 0.0,
                        "allowance_scope": config.allowance_scope or "stay",
                        "charge_excess": config.charge_excess,
                        "allowance_price": config.allowance_price or 0.0,
                        "price_unit": (config.allowance_price or product.list_price or product.standard_price or 0.0),
                        "charge_product_id": product.id,
                        "is_billable": (config.policy or "chargeable") in ("chargeable", "allowance"),
                    },
                ),
            )
        consumption = self.env["hotel.room.consumption"].create(
            {
                "reservation_id": self.id,
                "stay_date": stay_date,
                "session_type": "checkin",
                "is_checkin_session": True,
                "employee_id": self.env.user.employee_id.id
                or self.env["hr.employee"].search([], limit=1).id,
                "turnover_policy": room._hotel_turnover_policy(),
                "line_ids": line_commands,
            },
        )
        return consumption

    def _get_or_create_checkout_inspection(self):
        """Return an open, approved inspection for this stay (idempotent)."""
        self.ensure_one()
        consumptions = self.env["hotel.room.consumption"].search(
            [("reservation_id", "=", self.id)],
            order="stay_date desc, id desc",
        )
        consumption = consumptions[:1] if consumptions else False
        open_inspections = self.inspection_ids.filtered(
            lambda inspection: inspection.state not in ("cancelled", "approved"),
        )
        if open_inspections:
            inspection = open_inspections[-1]
            if inspection.consumption_id and not inspection.consumption_id.inspection_id:
                inspection.consumption_id.inspection_id = inspection.id
            return inspection
        approved = self.inspection_ids.filtered(lambda i: i.state == "approved")
        if approved:
            return approved[-1]
        if not consumption:
            return False
        inspection = self.env["hotel.room.inspection"].create(
            {
                "reservation_id": self.id,
                "consumption_id": consumption.id,
                "turnover_policy": self.room_id._hotel_turnover_policy(),
            },
        )
        consumption.inspection_id = inspection.id
        return inspection

    def _checkout_room_has_consumables(self):
        self.ensure_one()
        return bool(self.room_id._effective_consumables())

    def action_print_registration_card(self):
        """Download the guest registration card PDF."""
        self.ensure_one()
        return self.env.ref(
            "hotel.action_print_registration_card",
        ).report_action(self)

    def action_open_guest_folio(self):
        """Open the guest's customer invoice (charges to invoice).

        Creates a draft folio invoice when none exists yet, after pushing any
        pending room-consumption charges onto the stay. Use Print > Guest Folio
        for the PDF statement.
        """
        self.ensure_one()
        if self.state not in ("checked_in", "checked_out"):
            raise UserError(
                _("Guest folio is only available after check-in."),
            )
        self._bill_pending_room_consumption()
        invoices = self.invoice_ids
        if not invoices:
            invoices = self._action_create_folio_invoice()
        if len(invoices) == 1:
            return {
                "name": _("Guest Folio"),
                "type": "ir.actions.act_window",
                "res_model": "account.move",
                "view_mode": "form",
                "views": [[False, "form"]],
                "res_id": invoices.id,
                "target": "current",
                "context": {"create": False},
            }
        return self.action_open_invoices()

    def action_print_folio(self):
        """Print the guest folio PDF statement."""
        return self.env.ref("hotel.action_print_folio").report_action(self)

    def action_walkin(self):
        """Open the front-desk walk-in registration wizard."""
        return self.env["res.partner"].action_open_walkin_wizard()


class HotelReservationLine(models.Model):
    _name = "hotel.reservation.line"
    _description = "Hotel Reservation Extra Service"
    _order = "reservation_id, sequence, id"

    reservation_id = fields.Many2one(
        comodel_name="hotel.reservation",
        string="Reservation",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(string="Sequence", default=10)
    service_type = fields.Selection(
        selection=[
            ("breakfast", "Breakfast"),
            ("lunch", "Lunch"),
            ("dinner", "Dinner"),
            ("laundry", "Laundry"),
            ("minibar", "Minibar"),
            ("late_checkout", "Late Checkout"),
            ("early_checkin", "Early Check-in"),
            ("transfer", "Airport Transfer"),
            ("room_service", "Room Service"),
            ("other", "Other"),
        ],
        string="Service",
        default="other",
        required=True,
    )
    name = fields.Char(string="Description", required=True)
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        domain="[('type', '=', 'service')]",
        help="Product invoiced for this service (its income account and "
        "taxes are used on the folio).",
    )
    qty = fields.Float(string="Quantity", default=1.0)
    price_unit = fields.Monetary(
        string="Unit Price",
        currency_field="currency_id",
        compute="_compute_price_unit",
        store=True,
        readonly=False,
        precompute=True,
    )
    discount = fields.Float(string="Discount (%)", digits="Discount", default=0.0)
    price_subtotal = fields.Monetary(
        string="Subtotal",
        currency_field="currency_id",
        compute="_compute_price_subtotal",
        store=True,
    )
    billable = fields.Boolean(
        string="Billable",
        default=True,
        help="Unbillable services (complimentary welcome gift) stay out of "
        "the guest folio.",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="reservation_id.currency_id",
        readonly=True,
    )
    note = fields.Char(string="Note")

    @api.depends("product_id", "service_type")
    def _compute_price_unit(self):
        for line in self:
            if line.product_id:
                line.price_unit = line.product_id.list_price
            elif not line.price_unit:
                line.price_unit = 0.0

    @api.depends("qty", "price_unit", "discount")
    def _compute_price_subtotal(self):
        for line in self:
            subtotal = line.qty * line.price_unit
            line.price_subtotal = subtotal - subtotal * line.discount / 100.0

    @api.onchange("service_type")
    def _onchange_service_type(self):
        labels = dict(self._fields["service_type"].selection)
        for line in self:
            if not line.name:
                line.name = labels.get(line.service_type, line.service_type)


class HotelReservationGuest(models.Model):
    """Additional person sharing a room on a reservation.

    The primary guest is ``hotel.reservation.guest_id``; these lines record
    the other people staying in the same room so the whole party stays
    linked to one reservation (no duplicate bookings per person).
    """

    _name = "hotel.reservation.guest"
    _description = "Reservation Additional Guest"
    _order = "reservation_id, id"

    reservation_id = fields.Many2one(
        comodel_name="hotel.reservation",
        string="Reservation",
        required=True,
        ondelete="cascade",
        index=True,
    )
    guest_id = fields.Many2one(
        comodel_name="res.partner",
        string="Customer",
        ondelete="restrict",
        help="Existing customer linked to this additional guest, when known.",
    )
    name = fields.Char(string="Full Name", required=True)
    phone = fields.Char(string="Phone")
    id_type = fields.Selection(
        selection=[
            ("national_id", "National ID"),
            ("passport", "Passport"),
            ("driver_license", "Driver License"),
            ("other", "Other"),
        ],
        string="ID Type",
    )
    id_number = fields.Char(string="ID Number")
    nationality_id = fields.Many2one(
        comodel_name="res.country", string="Nationality", ondelete="restrict",
    )
    gender = fields.Selection(
        selection=[
            ("male", "Male"),
            ("female", "Female"),
            ("other", "Other"),
        ],
        string="Gender",
    )
    birth_date = fields.Date(string="Date of Birth")
    notes = fields.Char(string="Notes")
