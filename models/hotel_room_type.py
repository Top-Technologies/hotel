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
    breakfast_price = fields.Monetary(
        string="Breakfast Price / Guest",
        currency_field="currency_id",
        help="Breakfast charge per guest per night for this room type. If zero, falls back to hotel configuration.",
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
    # Late check-out policy
    late_checkout_penalty_active = fields.Boolean(
        string="Apply Late Check-out Penalty",
        default=True,
        help="If enabled, check-out after the scheduled check-out time incurs a penalty fee.",
    )
    checkout_time = fields.Float(
        string="Standard Check-out Time",
        default=11.0,
        help="Standard check-out time for rooms of this type (e.g. 11.0 for 11:00 AM, 16.0 for 04:00 PM).",
    )
    late_checkout_grace_minutes = fields.Integer(
        string="Grace Period (Minutes)",
        default=15,
        help="Tolerance in minutes after check-out time before late penalty applies.",
    )
    late_checkout_type = fields.Selection(
        selection=[
            ("per_30min", "Per 30 Minutes Block"),
            ("hourly", "Hourly Rate"),
            ("tiered", "Tiered (Half / Full Day)"),
            ("fixed", "Fixed Surcharge"),
        ],
        string="Penalty Calculation",
        default="per_30min",
        required=True,
        help="Method used to calculate the late check-out fee.",
    )
    late_checkout_rate_pct = fields.Float(
        string="Penalty Rate (%)",
        default=10.0,
        help="Percentage of the room rate charged per block (e.g. 10% per 30 minutes, or 50% for half day).",
    )
    late_checkout_fixed_amount = fields.Monetary(
        string="Fixed Penalty Amount",
        currency_field="currency_id",
        default=0.0,
        help="Fixed fee charged if calculation method is Fixed Surcharge.",
    )
    late_checkout_product_id = fields.Many2one(
        comodel_name="product.product",
        string="Late Check-out Product",
        domain="[('type', '=', 'service')]",
        help="Optional service product used on the folio invoice for late check-out charges.",
    )

    note = fields.Text(string="Description")

    def compute_late_checkout_penalty(self, room_rate, late_minutes):
        """Calculate the late checkout penalty given the room rate and late minutes."""
        self.ensure_one()
        if not self.late_checkout_penalty_active or late_minutes <= self.late_checkout_grace_minutes:
            return 0.0

        penalty_type = self.late_checkout_type or "per_30min"
        rate = room_rate if room_rate is not None and room_rate > 0 else (self.base_price or 0.0)

        if penalty_type == "fixed":
            return self.late_checkout_fixed_amount

        elif penalty_type == "per_30min":
            import math
            blocks = math.ceil(late_minutes / 30.0)
            pct = (self.late_checkout_rate_pct or 10.0) / 100.0
            return rate * pct * blocks

        elif penalty_type == "hourly":
            import math
            hours = math.ceil(late_minutes / 60.0)
            pct = (self.late_checkout_rate_pct or 20.0) / 100.0
            return rate * pct * hours

        elif penalty_type == "tiered":
            if late_minutes <= 120:
                pct = (self.late_checkout_rate_pct or 50.0) / 100.0
                return rate * pct
            else:
                return rate

        return 0.0

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

    def _register_hook(self):
        super()._register_hook()
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    """
                    ALTER TABLE hotel_room_type
                    ADD COLUMN IF NOT EXISTS breakfast_price numeric DEFAULT 0.0,
                    ADD COLUMN IF NOT EXISTS late_checkout_penalty_active boolean DEFAULT true,
                    ADD COLUMN IF NOT EXISTS checkout_time double precision DEFAULT 11.0,
                    ADD COLUMN IF NOT EXISTS late_checkout_grace_minutes integer DEFAULT 15,
                    ADD COLUMN IF NOT EXISTS late_checkout_type varchar DEFAULT 'per_30min',
                    ADD COLUMN IF NOT EXISTS late_checkout_rate_pct double precision DEFAULT 10.0,
                    ADD COLUMN IF NOT EXISTS late_checkout_fixed_amount numeric DEFAULT 0.0;
                    """
                )
        except Exception:
            pass
