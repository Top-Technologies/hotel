from datetime import timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError

# Reservation states that hold a room on the availability check.
BLOCKING_STATES = ("confirmed", "checked_in")


class HotelWalkinWizard(models.TransientModel):
    _name = "hotel.walkin.wizard"
    _description = "Hotel Book Guest Registration"

    customer_type = fields.Selection(
        selection=[
            ("individual", "Individual"),
            ("corporate", "Corporate"),
        ],
        string="Customer Type",
        default="individual",
        required=True,
        help="Individual: the staying guest is the customer. Corporate: the "
        "company is the billing customer and a contact person stays.",
    )
    guest_id = fields.Many2one(
        comodel_name="res.partner",
        string="Customer",
        required=True,
        ondelete="cascade",
        domain="[('is_company', '=', customer_type == 'corporate')]",
        help="Pick an existing customer or type a name to create one on "
        "the fly. Books reuse the normal partner database.",
    )
    phone = fields.Char(string="Phone")
    email = fields.Char(string="Email")
    id_type = fields.Selection(
        selection=[
            ("national_id", "National ID"),
            ("passport", "Passport"),
            ("driver_license", "Driver License"),
            ("other", "Other"),
        ],
        string="ID Type",
        help="Identification presented at the desk. Carried over to the "
        "check-in wizard so reception does not re-enter it.",
    )
    id_number = fields.Char(string="ID Number")
    id_document = fields.Binary(
        string="ID Document",
        attachment=True,
        help="Scan or photo of the guest ID. Copied to the reservation and "
        "check-in screen.",
    )
    id_document_filename = fields.Char(string="ID Filename")
    nationality_id = fields.Many2one(
        comodel_name="res.country", string="Nationality", ondelete="restrict"
    )
    contact_name = fields.Char(
        string="Staying Contact",
        help="For corporate customers: the person staying at the hotel on "
        "behalf of the company. Recorded as the primary additional guest.",
    )
    room_type_id = fields.Many2one(
        comodel_name="hotel.room.type",
        string="Room Type",
        required=True,
        ondelete="restrict",
    )
    room_id = fields.Many2one(
        comodel_name="hotel.room",
        string="Room",
        required=True,
        ondelete="restrict",
        domain="[('room_type_id', '=', room_type_id),"
        "('status', 'in', ['clean', 'inspected', 'available', 'reserved']),"
        "('id', 'not in', booked_room_ids)]",
        help="Rooms of the selected type that are free for the stay dates.",
    )
    checkin = fields.Datetime(
        string="Check-in",
        default=lambda self: fields.Datetime.now(),
        required=True,
        index=True,
    )
    nights = fields.Integer(string="Nights", default=1, required=True)
    checkout = fields.Datetime(
        string="Check-out",
        required=True,
        compute="_compute_checkout",
        readonly=True,
    )
    adults = fields.Integer(string="Adults", default=1, required=True)
    children = fields.Integer(string="Children", default=0)
    source = fields.Selection(
        selection=[("walkin", "Book")],
        string="Booking Source",
        default="walkin",
        required=True,
    )
    guest_line_ids = fields.One2many(
        comodel_name="hotel.walkin.guest.line",
        inverse_name="wizard_id",
        string="Additional Guests",
        help="Other people sharing the room with the primary guest.",
    )
    deposit = fields.Monetary(
        string="Deposit",
        currency_field="currency_id",
        help="Amount collected at the desk at registration time. Deducted "
        "from the final invoice at check-out.",
    )
    deposit_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Bank or Cash",
        domain="[('type', 'in', ('bank', 'cash'))]",
        help="Journal used to collect advance deposits. Empty falls back to check-out journal.",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id,
        readonly=True,
    )
    booked_room_ids = fields.Many2many(
        comodel_name="hotel.room",
        string="Rooms Unavailable",
        compute="_compute_booked_room_ids",
        compute_sudo=True,
        help="Rooms already taken by a confirmed or in-house stay for the "
        "wizard dates, excluded from the room selection.",
    )

    @api.depends("checkin", "nights")
    def _compute_checkout(self):
        for wizard in self:
            if wizard.checkin and wizard.nights:
                wizard.checkout = wizard.checkin + timedelta(days=wizard.nights)
            else:
                wizard.checkout = False

    @api.depends("checkin", "checkout")
    def _compute_booked_room_ids(self):
        reservation = self.env["hotel.reservation"]
        for wizard in self:
            if not wizard.checkin or not wizard.checkout:
                wizard.booked_room_ids = [Command.set([])]
                continue
            taken = reservation.search(
                [
                    ("room_id", "!=", False),
                    ("state", "in", BLOCKING_STATES),
                    ("checkin", "<", wizard.checkout),
                    ("checkout", ">", wizard.checkin),
                ]
            )
            wizard.booked_room_ids = [Command.set(taken.room_id.ids)]

    @api.onchange("customer_type")
    def _onchange_customer_type(self):
        for wizard in self:
            wizard.guest_id = False
            if wizard.customer_type == "individual":
                wizard.contact_name = False

    @api.onchange("guest_id")
    def _onchange_guest_id(self):
        for wizard in self:
            guest = wizard.guest_id
            if not guest:
                continue
            wizard.phone = guest.phone or ""
            wizard.email = guest.email or ""
            wizard.nationality_id = guest.nationality_id or (
                guest.country_id if guest.country_id else False
            )
            if guest.name and not wizard.contact_name and wizard.customer_type == "corporate":
                wizard.contact_name = guest.name

    @api.onchange("room_type_id")
    def _onchange_room_type_id(self):
        for wizard in self:
            if wizard.room_id.room_type_id != wizard.room_type_id:
                wizard.room_id = False

    @api.onchange("room_id")
    def _onchange_room_id(self):
        for wizard in self:
            if not wizard.room_id:
                continue
            if wizard.room_type_id != wizard.room_id.room_type_id:
                wizard.room_type_id = wizard.room_id.room_type_id
            if wizard.adults > wizard.room_id.capacity:
                wizard.adults = wizard.room_id.capacity
                wizard.children = 0

    def action_confirm_walkin(self):
        self.ensure_one()
        if not self.checkin or not self.checkout or self.checkout <= self.checkin:
            raise ValidationError(
                _("Check-out must be later than check-in.")
            )
        room = self.room_id
        if not room:
            raise ValidationError(_("Select a room for the walk-in guest."))
        sellable = ("available", "clean", "inspected", "reserved")
        if room.status not in sellable:
            raise ValidationError(
                _("Room %(room)s is %(status)s and cannot be sold as a "
                  "walk-in right now.",
                  room=room.number,
                  status=dict(room._fields["status"].selection).get(
                      room.status, room.status
                  ),
                )
            )
        guests = self.adults + self.children + len(self.guest_line_ids)
        if guests > room.capacity:
            raise ValidationError(
                _("Room %s hosts %d guests but %d are booked.")
                % (room.number, room.capacity, guests)
            )
        if self.env["hotel.reservation"].search_count(
            [
                ("room_id", "=", room.id),
                ("state", "in", BLOCKING_STATES),
                ("checkin", "<", self.checkout),
                ("checkout", ">", self.checkin),
            ]
        ):
            raise ValidationError(
                _("Room %s is already booked for these dates.")
                % room.number
            )

        if self.customer_type != "corporate":
            if not self.id_type or not self.id_number or not self.id_document:
                raise ValidationError(
                    _("ID Type, ID Number, and ID Document are required for walk-in guest registration.")
                )

        guest = self.guest_id
        guest.write(
            {
                "is_guest": True,
                "is_walkin": True,
                "hotel_customer_type": self.customer_type,
                "nationality_id": self.nationality_id.id,
            }
        )
        if self.phone and not guest.phone:
            guest.phone = self.phone
        if self.email and not guest.email:
            guest.email = self.email

        reservation = self.env["hotel.reservation"].create(
            {
                "guest_id": guest.id,
                "guest_phone": self.phone or guest.phone or "",
                "source": "walkin",
                "room_type_id": self.room_type_id.id,
                "room_id": room.id,
                "checkin": self.checkin,
                "checkout": self.checkout,
                "adults": self.adults,
                "children": self.children,
                "deposit": self.deposit,
                "deposit_journal_id": self.deposit_journal_id.id,
                "id_type": self.id_type,
                "id_number": self.id_number,
                "id_document": self.id_document,
                "id_document_filename": self.id_document_filename,
                "nationality_id": self.nationality_id.id,
            }
        )
        extra_guests = []
        if self.customer_type == "corporate" and self.contact_name:
            extra_guests.append({"name": self.contact_name})
        for line in self.guest_line_ids:
            extra_guests.append(
                {
                    "name": line.name,
                    "phone": line.phone,
                    "gender": line.gender,
                    "birth_date": line.birth_date,
                }
            )
        if extra_guests:
            reservation.guest_line_ids = [
                Command.create(vals) for vals in extra_guests
            ]
        reservation.message_post(
            body=_(
                "Book guest registered at the front desk. Customer type: "
                "%(type)s, %(guests)d additional guest(s).",
                type=dict(self._fields["customer_type"].selection)[
                    self.customer_type
                ],
                guests=len(extra_guests),
            )
        )
        reservation.action_confirm()
        return reservation.action_checkin()


class HotelWalkinGuestLine(models.TransientModel):
    _name = "hotel.walkin.guest.line"
    _description = "Book Additional Guest"

    wizard_id = fields.Many2one(
        comodel_name="hotel.walkin.wizard",
        string="Book",
        required=True,
        ondelete="cascade",
        index=True,
    )
    name = fields.Char(string="Full Name", required=True)
    phone = fields.Char(string="Phone")
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