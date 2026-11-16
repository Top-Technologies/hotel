from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

OPEN_STATES = ("received", "stored")


class HotelSafeDeposit(models.Model):
    """Physical safe deposit box holding a guest item."""

    _name = "hotel.safe.deposit"
    _description = "Safe Deposit"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "received_date desc, id desc"

    name = fields.Char(
        string="Reference",
        required=True,
        default="New",
        readonly=True,
        copy=False,
        index=True,
    )
    property_id = fields.Many2one(
        comodel_name="hotel.guest.property",
        string="Property",
        required=True,
        ondelete="restrict",
        tracking=True,
        index=True,
    )
    guest_id = fields.Many2one(
        related="property_id.guest_id",
        store=True,
        readonly=True,
        index=True,
    )
    reservation_id = fields.Many2one(
        related="property_id.reservation_id",
        store=True,
        readonly=True,
        index=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        related="property_id.company_id",
        store=True,
        index=True,
    )
    room_id = fields.Many2one(related="property_id.room_id", store=True, readonly=True)
    location_id = fields.Many2one(
        comodel_name="hotel.storage.location",
        string="Storage Location",
        required=True,
        ondelete="restrict",
        tracking=True,
        index=True,
    )
    received_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Received By",
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
    )
    received_date = fields.Datetime(
        required=True, default=fields.Datetime.now, tracking=True
    )
    released_by_id = fields.Many2one(
        comodel_name="res.users", string="Released By", tracking=True
    )
    released_date = fields.Datetime(tracking=True)
    state = fields.Selection(
        selection=[
            ("received", "Received"),
            ("stored", "Stored"),
            ("released", "Released"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="received",
        required=True,
        tracking=True,
        index=True,
    )
    notes = fields.Text()
    custody_count = fields.Integer(compute="_compute_custody_count")

    _sql_constraints = [
        (
            "name_unique",
            "unique(name)",
            "Safe deposit references must be unique.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name") in (False, None, "New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("hotel.safe.deposit")
        return super().create(vals_list)

    def _compute_custody_count(self):
        counts = dict(
            self.env["hotel.property.custody"]._read_group(
                [("property_id", "in", self.property_ids.ids)],
                groupby=["property_id"],
                aggregates=["__count"],
            )
        )
        for deposit in self:
            deposit.custody_count = counts.get(deposit.property_id, 0)

    @api.onchange("property_id")
    def _onchange_property_id(self):
        for deposit in self:
            if deposit.property_id.current_location_id:
                deposit.location_id = deposit.property_id.current_location_id

    @api.constrains("property_id", "state")
    def _check_property_state(self):
        for deposit in self:
            prop = deposit.property_id
            if not prop:
                raise ValidationError(
                    _("Safe deposit %s must reference a guest property.")
                    % (deposit.name or _("new"))
                )
            if deposit.state in ("received", "stored") and prop.state in (
                "guest_possession",
                "deposit_requested",
            ):
                raise ValidationError(
                    _("Receive property %s before opening safe deposit %s.")
                    % (prop.name, deposit.name)
                )

    @api.constrains("property_id", "state")
    def _check_single_open_deposit(self):
        for deposit in self:
            if deposit.state not in OPEN_STATES:
                continue
            others = self.search_count(
                [
                    ("id", "!=", deposit.id),
                    ("property_id", "=", deposit.property_id.id),
                    ("state", "in", OPEN_STATES),
                ]
            )
            if others:
                raise ValidationError(
                    _(
                        "Property %s already has an open safe deposit (%s)."
                    )
                    % (deposit.property_id.name, deposit.name)
                )

    @api.constrains("received_date", "released_date")
    def _check_release_after_receipt(self):
        for deposit in self:
            if deposit.released_date and deposit.released_date < deposit.received_date:
                raise ValidationError(
                    _("Safe deposit %s cannot be released before it was received.")
                    % deposit.name
                )

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_store(self):
        for deposit in self:
            if deposit.state != "received":
                raise ValidationError(
                    _("Only received deposits can be marked as stored.")
                )
        self.write({"state": "stored"})
        for deposit in self:
            deposit.message_post(body=_("Deposit stored in the safe."))
            deposit.property_id._log_custody(
                "store",
                to_location_id=deposit.location_id.id,
                to_user_id=self.env.user.id,
                notes=_("Safe deposit %s stored.") % deposit.name,
            )
        return True

    def action_release(self):
        for deposit in self:
            if deposit.state not in OPEN_STATES:
                raise ValidationError(
                    _("Safe deposit %s is not open anymore.") % deposit.name
                )
            if deposit.property_id.state in ("returned", "cancelled"):
                raise ValidationError(
                    _("Property %s is closed; the deposit cannot be released.")
                    % deposit.property_id.name
                )
        self.write(
            {
                "state": "released",
                "released_by_id": self.env.user.id,
                "released_date": fields.Datetime.now(),
            }
        )
        for deposit in self:
            deposit.message_post(body=_("Safe deposit released."))
        return True

    def action_cancel(self):
        for deposit in self:
            if deposit.state == "released":
                raise ValidationError(
                    _("A released deposit cannot be cancelled.")
                )
        self.write({"state": "cancelled"})
        return True

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def action_print_deposit_receipt(self):
        self.ensure_one()
        return self.env.ref("hotel.action_report_safe_deposit").report_action(self)