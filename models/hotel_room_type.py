from odoo import api, fields, models

from .product_template import TURNOVER_POLICIES


class HotelAmenity(models.Model):
    _name = "hotel.amenity"
    _description = "Hotel Room Amenity"
    _order = "sequence, name"
    _inherit = ["mail.thread"]

    name = fields.Char(string="Amenity", required=True, translate=True)
    sequence = fields.Integer(string="Sequence", default=10)
    active = fields.Boolean(string="Active", default=True)


class HotelRoomType(models.Model):
    _name = "hotel.room.type"
    _description = "Hotel Room Type"
    _order = "sequence, name"
    _inherit = ["mail.thread", "mail.activity.mixin", "hotel.config"]

    name = fields.Char(string="Room Type", required=True, translate=True)
    code = fields.Char(string="Code", copy=False)
    sequence = fields.Integer(string="Sequence", default=10)
    active = fields.Boolean(string="Active", default=True)
    capacity = fields.Integer(
        string="Capacity",
        default=2,
        help="Maximum number of adults a room of this type may host.",
    )
    child_capacity = fields.Integer(
        string="Children Capacity",
        default=0,
        help="Maximum number of children a room of this type may host.",
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
    base_price = fields.Monetary(
        string="Base Rate / Night",
        currency_field="currency_id",
        help="Standard rate per night, used as the default reservation rate.",
    )
    amenity_ids = fields.Many2many(
        comodel_name="hotel.amenity",
        string="Standard Amenities",
        help="Amenities copied by default on the rooms of this type.",
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Room Revenue Product",
        domain="[('type', '=', 'service')]",
        help="Sellable service product invoiced for room revenue. Its income "
        "account and taxes are used on the guest folio.",
    )
    income_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Room Revenue Account",
        domain="[('account_type', '=', 'income')]",
        help="Specific income account for this room type. If empty, uses the "
        "product or hotel default room revenue account.",
    )
    tax_ids = fields.Many2many(
        comodel_name="account.tax",
        string="Customer Taxes",
        domain="[('type_tax_use', '=', 'sale')]",
        help="Customer taxes applied to this room type. If empty, uses the "
        "product or hotel default taxes.",
    )
    analytic_account_id = fields.Many2one(
        comodel_name="account.analytic.account",
        string="Analytic Account",
        help="Analytic account (e.g. Rooms department) tagged on room revenue "
        "lines so the P&L splits Rooms from Food and Bar.",
    )
    consumable_ids = fields.One2many(
        comodel_name="hotel.room.consumable",
        inverse_name="room_type_id",
        string="Standard Consumables",
        domain="[('room_id', '=', False)]",
        help="Consumables placed in a room of this type, with their par level, "
        "free allowance and charging behaviour.",
    )
    turnover_policy = fields.Selection(
        selection=TURNOVER_POLICIES,
        string="Turnover Policy",
        help="How a room of this type is prepared for the next guest. Empty "
        "means the hotel default configured in the settings.",
    )
    note = fields.Text(string="Description")

    _sql_constraints = [
        (
            "code_unique",
            "unique(code, company_id)",
            "Room type codes must be unique per company.",
        ),
        (
            "capacity_positive",
            "check (capacity >= 0)",
            "Room capacity cannot be negative.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("code") in (False, ""):
                vals["code"] = self.env["ir.sequence"].next_by_code(
                    "hotel.room.type"
                ) or False
        return super().create(vals_list)
