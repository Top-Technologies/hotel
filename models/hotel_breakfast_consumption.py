from odoo import _, api, fields, models


class HotelBreakfastConsumption(models.Model):
    """Daily breakfast entitlement and consumption tracking per reservation and guest."""

    _name = "hotel.breakfast.consumption"
    _description = "Hotel Breakfast Consumption"
    _order = "date desc, id desc"
    _inherit = ["mail.thread"]

    name = fields.Char(string="Reference", compute="_compute_name", store=True)
    reservation_id = fields.Many2one(
        comodel_name="hotel.reservation",
        string="Reservation",
        required=True,
        ondelete="cascade",
        index=True,
    )
    guest_id = fields.Many2one(
        comodel_name="res.partner",
        string="Guest",
        index=True,
        help="Specific guest entitled to breakfast.",
    )
    guest_name = fields.Char(
        string="Guest Name",
        help="Name of the guest if individual partner record is not created.",
    )
    room_id = fields.Many2one(
        comodel_name="hotel.room",
        string="Room",
        related="reservation_id.room_id",
        store=True,
        index=True,
    )
    date = fields.Date(
        string="Breakfast Date",
        required=True,
        index=True,
        help="Date for which the breakfast is entitled/served.",
    )
    day_number = fields.Integer(
        string="Stay Day",
        help="Sequential day number of the stay (e.g. Day 1, Day 2...).",
    )
    is_entitled = fields.Boolean(
        string="Entitled",
        default=True,
        help="Whether this breakfast was included/purchased in the stay.",
    )
    state = fields.Selection(
        selection=[
            ("not_used", "Not Used"),
            ("used", "Used"),
        ],
        string="Status",
        default="not_used",
        required=True,
        tracking=True,
        index=True,
        help="Whether the entitled breakfast has been consumed.",
    )
    quantity = fields.Float(
        string="Quantity",
        default=1.0,
        digits="Product Unit",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Recorded By",
        readonly=True,
        copy=False,
        help="User who marked the breakfast as consumed or not used.",
    )
    recorded_at = fields.Datetime(
        string="Recorded At",
        readonly=True,
        copy=False,
        help="Timestamp when the consumption status was updated.",
    )
    notes = fields.Text(string="Notes")
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        related="reservation_id.company_id",
        store=True,
        index=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="reservation_id.currency_id",
        string="Currency",
    )

    @api.depends("reservation_id.name", "date", "guest_name", "guest_id.name")
    def _compute_name(self):
        for rec in self:
            gname = rec.guest_name or (rec.guest_id.name if rec.guest_id else _("Guest"))
            res_ref = rec.reservation_id.name or _("New")
            date_str = fields.Date.to_string(rec.date) if rec.date else ""
            rec.name = f"{res_ref} - {date_str} - {gname}"

    def action_mark_used(self):
        """Mark breakfast as consumed by the guest."""
        self.write(
            {
                "state": "used",
                "user_id": self.env.user.id,
                "recorded_at": fields.Datetime.now(),
            }
        )
        for rec in self:
            rec.message_post(
                body=_(
                    "Breakfast on %(date)s marked as Used by %(user)s.",
                    date=rec.date,
                    user=self.env.user.name,
                )
            )

    def action_mark_not_used(self):
        """Reset breakfast status back to not used."""
        self.write(
            {
                "state": "not_used",
                "user_id": self.env.user.id,
                "recorded_at": fields.Datetime.now(),
            }
        )
        for rec in self:
            rec.message_post(
                body=_(
                    "Breakfast on %(date)s marked as Not Used by %(user)s.",
                    date=rec.date,
                    user=self.env.user.name,
                )
            )
