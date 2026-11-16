from odoo import fields, models

# Charging policies shared by the product configuration and the consumption
# line snapshot. Kept in one place so both models stay in sync.
CONSUMPTION_POLICIES = [
    ("complimentary", "Complimentary"),
    ("chargeable", "Chargeable"),
    ("allowance", "Allowance-based"),
]

CONSUMPTION_SCOPES = [
    ("stay", "Per Stay"),
    ("day", "Per Day"),
    ("guest", "Per Guest"),
]

# How the room is prepared for the next guest after a check-out inspection.
TURNOVER_POLICIES = [
    ("replenish", "Replenish to Standard Quantity"),
    ("carry_forward", "Carry Forward Verified Remaining Stock"),
]


class ProductTemplate(models.Model):
    """Room-consumption configuration carried by the standard product.

    The products themselves, their category, unit of measure, sales price and
    stock tracking stay standard Odoo. Hotel room consumables are configured
    under Hotel -> Configuration -> Room Consumables (or Room Types -> Standard
    Consumables), and only products marked/configured for hotel room consumption
    can be added to room consumption lines.
    """

    _inherit = "product.template"

    hotel_consumption_ok = fields.Boolean(
        string="Allowed for Room Consumption",
        default=False,
        index=True,
        help="When checked, the product can be recorded on a hotel room "
        "consumption line. This flag is automatically managed when configuring "
        "Room Consumables.",
    )
    hotel_consumption_policy = fields.Selection(
        selection=CONSUMPTION_POLICIES,
        string="Default Consumption Policy",
        default="chargeable",
        required=True,
        help="Complimentary: recorded but never charged. Chargeable: the "
        "whole consumed quantity is charged. Allowance-based: a configured "
        "quantity is complimentary and the excess may be charged.",
    )
    hotel_allowance_qty = fields.Float(
        string="Complimentary Allowance",
        digits="Product Unit",
        default=0.0,
        help="Quantity offered to the guest before any excess is charged.",
    )
    hotel_allowance_scope = fields.Selection(
        selection=CONSUMPTION_SCOPES,
        string="Allowance Scope",
        default="stay",
        help="Whether the allowance is consumed once per stay or refreshed "
        "every stay day.",
    )
    hotel_allowance_charge_excess = fields.Boolean(
        string="Charge Excess Quantity",
        default=True,
        help="When unchecked the quantity above the allowance stays "
        "complimentary and is never charged.",
    )
    hotel_allowance_price = fields.Monetary(
        string="Excess Unit Price",
        currency_field="currency_id",
        help="Unit price applied to the quantity above the allowance. Empty "
        "means the product sales price.",
    )

    def _recompute_hotel_consumption_ok(self):
        Consumable = self.env["hotel.room.consumable"].sudo()
        for tmpl in self:
            has_consumable = bool(
                Consumable.search_count([
                    ("product_id.product_tmpl_id", "=", tmpl.id),
                    ("active", "=", True),
                ])
            )
            tmpl.hotel_consumption_ok = has_consumable


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _recompute_hotel_consumption_ok(self):
        templates = self.mapped("product_tmpl_id")
        templates._recompute_hotel_consumption_ok()

