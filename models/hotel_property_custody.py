from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

OPEN_STATES = ("pending",)


class HotelPropertyCustody(models.Model):
    """Chain-of-custody entry: every handover of a guest item is recorded."""

    _name = "hotel.property.custody"
    _description = "Property Custody Record"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "custody_date desc, id desc"

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
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        related="property_id.company_id",
        store=True,
        index=True,
    )
    action = fields.Selection(
        selection=[
            ("deposit", "Deposit Requested"),
            ("receive", "Received"),
            ("store", "Stored"),
            ("transfer", "Transfer"),
            ("inspection", "Inspection"),
            ("return", "Returned"),
            ("dispose", "Disposed"),
        ],
        string="Action",
        required=True,
        default="store",
        index=True,
    )
    from_location_id = fields.Many2one(
        comodel_name="hotel.storage.location",
        string="From Location",
        ondelete="restrict",
    )
    to_location_id = fields.Many2one(
        comodel_name="hotel.storage.location",
        string="To Location",
        ondelete="restrict",
        index=True,
    )
    from_user_id = fields.Many2one(comodel_name="res.users", string="From User")
    to_user_id = fields.Many2one(comodel_name="res.users", string="To User")
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Recorded By",
        required=True,
        default=lambda self: self.env.user,
        index=True,
    )
    custody_date = fields.Datetime(
        required=True, default=fields.Datetime.now, index=True
    )
    condition = fields.Selection(
        selection=[
            ("new", "New"),
            ("good", "Good"),
            ("fair", "Fair"),
            ("damaged", "Damaged"),
            ("broken", "Broken"),
        ],
        string="Condition",
        default="good",
    )
    condition_notes = fields.Char()
    notes = fields.Text()
    state = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="pending",
        required=True,
        index=True,
    )

    _sql_constraints = [
        (
            "name_unique",
            "unique(name)",
            "Custody record references must be unique.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name") in (False, None, "New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "hotel.property.custody"
                )
        return super().create(vals_list)

    @api.constrains("from_location_id", "to_location_id")
    def _check_locations(self):
        for record in self:
            if (
                record.from_location_id
                and record.to_location_id
                and record.from_location_id == record.to_location_id
            ):
                raise ValidationError(
                    _("Custody record %s: source and target locations are identical.")
                    % record.name
                )

    @api.constrains("property_id", "state")
    def _check_single_pending(self):
        for record in self:
            if record.state not in OPEN_STATES:
                continue
            others = self.search_count(
                [
                    ("id", "!=", record.id),
                    ("property_id", "=", record.property_id.id),
                    ("state", "in", OPEN_STATES),
                ]
            )
            if others:
                raise ValidationError(
                    _(
                        "Property %s already has a pending custody handover."
                    )
                    % record.property_id.name
                )

    @api.constrains("state", "action", "to_location_id", "to_user_id")
    def _check_completion(self):
        for record in self:
            if (
                record.state == "completed"
                and record.action in ("receive", "store", "transfer", "return")
                and not (record.to_location_id or record.to_user_id)
            ):
                raise ValidationError(
                    _(
                        "Custody record %s: set the destination location or the "
                        "receiving user before completing the handover."
                    )
                    % record.name
                )

    def action_confirm(self):
        for record in self:
            if record.state != "pending":
                raise ValidationError(
                    _("Only pending custody records can be confirmed.")
                )
        self.write({"state": "completed"})
        return True

    def action_cancel(self):
        for record in self:
            if record.state != "pending":
                raise ValidationError(
                    _("Only pending custody records can be cancelled.")
                )
        self.write({"state": "cancelled"})
        return True

    def action_open_property(self):
        self.ensure_one()
        return {
            "name": _("Guest Property"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.guest.property",
            "view_mode": "form",
            "res_id": self.property_id.id,
        }