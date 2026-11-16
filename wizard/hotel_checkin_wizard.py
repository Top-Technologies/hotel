from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import formatLang


class HotelCheckinWizard(models.TransientModel):
    _name = "hotel.checkin.wizard"
    _description = "Hotel Guest Check-in"

    reservation_id = fields.Many2one(
        comodel_name="hotel.reservation",
        string="Reservation",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    guest_id = fields.Many2one(
        comodel_name="res.partner",
        string="Guest",
        readonly=True,
    )
    room_id = fields.Many2one(
        comodel_name="hotel.room",
        string="Room",
        readonly=True,
    )
    checkin = fields.Datetime(
        string="Arrival", related="reservation_id.checkin", readonly=True
    )
    checkout = fields.Datetime(
        string="Departure", related="reservation_id.checkout", readonly=True
    )
    id_type = fields.Selection(
        selection=[
            ("national_id", "National ID"),
            ("passport", "Passport"),
            ("driver_license", "Driver License"),
            ("other", "Other"),
        ],
        string="ID Type",
        required=True,
        default="passport",
    )
    id_number = fields.Char(string="ID Number", required=True)
    id_document = fields.Binary(
        string="ID Document",
        attachment=True,
        help="Scan or photo of the guest ID presented at check-in.",
    )
    id_document_filename = fields.Char(string="ID Filename")
    nationality_id = fields.Many2one(
        comodel_name="res.country", string="Nationality", ondelete="restrict"
    )
    phone = fields.Char(string="Phone")
    adults = fields.Integer(string="Adults", default=1, required=True)
    children = fields.Integer(string="Children", default=0)
    registered_guests = fields.Integer(
        string="Guests Registered",
        default=1,
        required=True,
        help="Number of guests physically registered at the desk.",
    )
    deposit = fields.Monetary(
        string="Deposit / Advance",
        currency_field="currency_id",
        help="Total advance held for this stay, including a booking deposit. "
        "The amount not yet booked is collected now as a payment and deducted "
        "from the folio at check-out.",
    )
    deposit_paid = fields.Monetary(
        string="Already Paid",
        currency_field="currency_id",
        compute="_compute_deposit_paid",
        readonly=True,
        help="Advance payments already posted for this reservation.",
    )
    amount_to_collect = fields.Monetary(
        string="Collect Now",
        currency_field="currency_id",
        compute="_compute_deposit_paid",
        readonly=True,
        help="Deposit minus what is already booked. Recorded as a customer "
        "payment on the chosen journal.",
    )
    payment_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Bank or Cash",
        domain="[('type', 'in', ('bank', 'cash', 'credit'))]",
        help="Journal receiving the advance. Empty means the hotel default "
        "payment journal.",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="reservation_id.currency_id",
        readonly=True,
    )
    print_card = fields.Boolean(
        string="Print Registration Card", default=True
    )
    notes = fields.Text(string="Notes")

    @api.depends("deposit", "reservation_id.deposit_paid")
    def _compute_deposit_paid(self):
        for wizard in self:
            already_paid = wizard.reservation_id.deposit_paid
            wizard.deposit_paid = already_paid
            wizard.amount_to_collect = max(0.0, wizard.deposit - already_paid)

    @api.model
    def default_get(self, fields_list):
        result = super().default_get(fields_list)
        reservation = self.env["hotel.reservation"].browse(
            result.get("reservation_id")
            or self.env.context.get("default_reservation_id")
        )
        if reservation:
            result.update(
                {
                    "guest_id": reservation.guest_id.id,
                    "room_id": reservation.room_id.id,
                    "phone": reservation.guest_phone
                    or reservation.guest_id.phone
                    or "",
                    "id_type": reservation.id_type or result.get("id_type"),
                    "id_number": reservation.id_number
                    or result.get("id_number")
                    or "",
                    "id_document": reservation.id_document
                    or result.get("id_document"),
                    "id_document_filename": reservation.id_document_filename
                    or result.get("id_document_filename"),
                    "nationality_id": reservation.nationality_id.id
                    or result.get("nationality_id"),
                    "adults": reservation.adults,
                    "children": reservation.children,
                    "registered_guests": reservation.adults + reservation.children,
                    "deposit": reservation.deposit,
                    "payment_journal_id": (
                        reservation.deposit_journal_id.id
                        or reservation.payment_journal_id.id
                        or self.env["hotel.config"]
                        .with_company(reservation.company_id)
                        ._hotel_deposit_journal()
                        .id
                    ),
                }
            )
        return result

    def action_confirm_checkin(self):
        self.ensure_one()
        reservation = self.reservation_id
        if reservation.state != "confirmed":
            raise ValidationError(
                _("Only confirmed reservations can be checked in.")
            )
        room = reservation.room_id
        sellable = ("clean", "inspected", "available", "reserved")
        if room.status not in sellable:
            raise ValidationError(
                _(
                    "Room %(room)s is currently \"%(status)s\". "
                    "Finish housekeeping (or release maintenance) so the room "
                    "is clean, inspected, available or reserved before check-in.",
                    room=room.number,
                    status=dict(room._fields["status"].selection).get(
                        room.status, room.status
                    ),
                )
            )
        if self.adults + self.children > room.capacity:
            raise ValidationError(
                _("Room %s hosts %d guests.")
                % (room.number, room.capacity)
            )
        now = fields.Datetime.now()
        reservation.write(
            {
                "state": "checked_in",
                "actual_checkin": now,
                "id_type": self.id_type,
                "id_number": self.id_number,
                "id_document": self.id_document,
                "id_document_filename": self.id_document_filename,
                "nationality_id": self.nationality_id.id,
                "guest_phone": self.phone,
                "adults": self.adults,
                "children": self.children,
                "registered_guests": self.registered_guests,
                "deposit": self.deposit,
            }
        )
        if self.amount_to_collect > 0:
            reservation._action_register_deposit_payment(
                self.amount_to_collect,
                journal=self.payment_journal_id,
                memo=_("Check-in advance %(name)s", name=reservation.name),
            )
            reservation.message_post(
                body=_(
                    "Advance of %(amount)s collected at check-in.",
                    amount=formatLang(
                        self.env,
                        self.amount_to_collect,
                        currency_obj=self.currency_id,
                    ),
                )
            )
        room._sync_status_for_stay(
            "occupied",
            _("Occupied by %s (%s).")
            % (reservation.guest_id.name, reservation.name),
        )
        # Snapshot the room consumables and their verified opening stock for
        # this stay (idempotent on retry).
        session = reservation._create_checkin_consumption_session()
        if session and session.id:
            session.action_verify_opening_stock()
        reservation.message_post(
            body=_(
                "Guest registered: %(guest)s, %(id_type)s %(id_number)s, "
                "%(guests)d guest(s).",
                guest=reservation.guest_id.name,
                id_type=self.id_type,
                id_number=self.id_number,
                guests=self.registered_guests,
            )
        )
        if self.notes:
            reservation.message_post(body=_("Check-in note: %s") % self.notes)
        if self.print_card:
            return reservation.action_print_registration_card()
        return True
