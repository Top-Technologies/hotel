from odoo import _, api, fields, models


class HotelPropertyCategory(models.Model):
    """Configurable categories used to classify guest property and lost items."""

    _name = "hotel.property.category"
    _description = "Guest Property Category"
    _order = "sequence, name"
    _inherit = ["mail.thread"]

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, copy=False, readonly=True, index=True)
    sequence = fields.Integer(default=10)
    description = fields.Text()
    active = fields.Boolean(default=True)
    requires_deposit = fields.Boolean(
        help="Mark items of this category as items the hotel usually asks "
        "the guest to deposit in the safe."
    )
    is_sensitive = fields.Boolean(
        help="Sensitive items (passports, jewellery, cash...) are excluded "
        "from the custody report totals shown to non-manager roles."
    )
    property_count = fields.Integer(compute="_compute_property_count")
    lost_found_count = fields.Integer(compute="_compute_lost_found_count")

    _sql_constraints = [
        (
            "code_unique",
            "unique(code)",
            "Property category codes must be unique.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("code"):
                vals["code"] = self.env["ir.sequence"].next_by_code(
                    "hotel.property.category"
                )
        return super().create(vals_list)

    def _compute_property_count(self):
        counts = dict(
            self.env["hotel.guest.property"]._read_group(
                [("category_id", "in", self.ids)],
                groupby=["category_id"],
                aggregates=["__count"],
            )
        )
        for category in self:
            category.property_count = counts.get(category, 0)

    def _compute_lost_found_count(self):
        counts = dict(
            self.env["hotel.lost.found"]._read_group(
                [("category_id", "in", self.ids)],
                groupby=["category_id"],
                aggregates=["__count"],
            )
        )
        for category in self:
            category.lost_found_count = counts.get(category, 0)

    def action_open_properties(self):
        self.ensure_one()
        return {
            "name": _("Guest Assets"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.guest.property",
            "view_mode": "list,form",
            "domain": [("category_id", "=", self.id)],
            "context": {"default_category_id": self.id},
        }

    def action_open_lost_found(self):
        self.ensure_one()
        return {
            "name": _("Lost & Found"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.lost.found",
            "view_mode": "list,form,kanban",
            "domain": [("category_id", "=", self.id)],
            "context": {"default_category_id": self.id},
        }


class HotelStorageLocation(models.Model):
    """Configurable storage locations: safes, deposit boxes, storage rooms."""

    _name = "hotel.storage.location"
    _description = "Property Storage Location"
    _order = "sequence, name"
    _inherit = ["mail.thread"]

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, copy=False, readonly=True, index=True)
    location_type = fields.Selection(
        selection=[
            ("safe", "Hotel Safe"),
            ("deposit_box", "Guest Deposit Box"),
            ("storage_room", "Storage Room"),
            ("front_desk", "Front Desk"),
            ("lost_found", "Lost & Found Store"),
            ("other", "Other"),
        ],
        string="Type",
        required=True,
        default="safe",
    )
    sequence = fields.Integer(default=10)
    capacity = fields.Integer(
        help="Optional expected capacity, only used as an operational hint.",
    )
    notes = fields.Text()
    active = fields.Boolean(default=True)
    property_count = fields.Integer(compute="_compute_property_count")
    deposit_count = fields.Integer(compute="_compute_deposit_count")

    _sql_constraints = [
        (
            "code_unique",
            "unique(code)",
            "Storage location codes must be unique.",
        ),
        (
            "capacity_positive",
            "check (capacity >= 0)",
            "Storage location capacity cannot be negative.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("code"):
                vals["code"] = self.env["ir.sequence"].next_by_code(
                    "hotel.storage.location"
                )
        return super().create(vals_list)

    def _compute_property_count(self):
        counts = dict(
            self.env["hotel.guest.property"]._read_group(
                [("current_location_id", "in", self.ids)],
                groupby=["current_location_id"],
                aggregates=["__count"],
            )
        )
        for location in self:
            location.property_count = counts.get(location, 0)

    def _compute_deposit_count(self):
        counts = dict(
            self.env["hotel.safe.deposit"]._read_group(
                [
                    ("location_id", "in", self.ids),
                    ("state", "in", ["received", "stored"]),
                ],
                groupby=["location_id"],
                aggregates=["__count"],
            )
        )
        for location in self:
            location.deposit_count = counts.get(location, 0)

    def action_open_deposits(self):
        self.ensure_one()
        return {
            "name": _("Safe Deposits"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.safe.deposit",
            "view_mode": "list,form",
            "domain": [
                ("location_id", "=", self.id),
                ("state", "in", ["received", "stored"]),
            ],
            "context": {"default_location_id": self.id},
        }

    def action_open_properties(self):
        self.ensure_one()
        return {
            "name": _("Guest Assets"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.guest.property",
            "view_mode": "list,form",
            "domain": [("current_location_id", "=", self.id)],
            "context": {"default_current_location_id": self.id},
        }