from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare

from .product_template import (
    CONSUMPTION_POLICIES,
    CONSUMPTION_SCOPES,
    TURNOVER_POLICIES,
)


class HotelRoomConsumable(models.Model):
    """Standard room consumable configuration.

    A consumable is configured once per room type. A line that carries a
    ``room_id`` overrides the room-type default for that single room only.
    The configuration describes the *par level* (``standard_qty``) and the
    charging behaviour of an item; the actual, physically verified quantities
    are always recorded on the ``hotel.room.consumption`` session of a stay.
    """

    _name = "hotel.room.consumable"
    _description = "Hotel Room Consumable Configuration"
    _order = "room_type_id, sequence, id"

    name = fields.Char(
        string="Description", compute="_compute_name", store=True,
    )
    active = fields.Boolean(string="Active", default=True)
    sequence = fields.Integer(string="Sequence", default=10)
    room_type_id = fields.Many2one(
        comodel_name="hotel.room.type",
        string="Room Type",
        required=True,
        ondelete="cascade",
        index=True,
    )
    room_id = fields.Many2one(
        comodel_name="hotel.room",
        string="Room Override",
        ondelete="cascade",
        index=True,
        help="Set only to override the room-type configuration for a single "
        "room. Leave empty for the standard configuration of the room type.",
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        required=True,
        ondelete="restrict",
        index=True,
        domain="[('sale_ok', '=', True)]",
    )
    product_type = fields.Selection(
        related="product_id.type",
        string="Product Type",
        readonly=True,
    )
    location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Inventory Location",
        domain="[('usage', '=', 'internal')]",
        help="Warehouse or storeroom location this consumable is issued from.",
    )
    uom_id = fields.Many2one(
        comodel_name="uom.uom",
        string="Unit of Measure",
        compute="_compute_uom_id",
        store=True,
        readonly=False,
        precompute=True,
        required=True,
    )
    standard_qty = fields.Float(
        string="Initial Quantity",
        digits="Product Unit",
        default=0.0,
        help="Par level: quantity placed in the room for a guest.",
    )
    included_in_setup = fields.Boolean(
        string="Included in Standard Setup",
        default=True,
        help="Whether the item is part of the room's standard setup and is "
        "proposed at check-in.",
    )
    policy = fields.Selection(
        selection=CONSUMPTION_POLICIES,
        string="Charging Policy",
        default="chargeable",
        required=True,
    )
    allowance_qty = fields.Float(
        string="Complimentary Quantity",
        digits="Product Unit",
        default=0.0,
        help="Quantity offered before any excess is charged.",
    )
    allowance_scope = fields.Selection(
        selection=CONSUMPTION_SCOPES,
        string="Allowance Scope",
        default="stay",
        required=True,
        help="Whether the allowance is consumed once per stay, refreshed "
        "every stay day, or per registered guest.",
    )
    allowance_scope_multiplier = fields.Integer(
        string="Allowance Multiplier",
        compute="_compute_allowance_scope_multiplier",
        help="Number of times the allowance is available: 1 for a per-stay "
        "allowance, the stay length for a per-day allowance and the number of "
        "registered guests for a per-guest allowance.",
    )
    charge_excess = fields.Boolean(
        string="Charge Excess Quantity",
        default=True,
        help="When unchecked the quantity above the allowance stays "
        "complimentary and is never charged.",
    )
    allowance_price = fields.Monetary(
        string="Chargeable Unit Price",
        currency_field="currency_id",
        help="Unit price applied to the chargeable quantity. Empty means the "
        "product sales price.",
    )
    turnover_policy = fields.Selection(
        selection=TURNOVER_POLICIES,
        string="Turnover Policy",
        default="replenish",
        help="How the room is prepared for the next guest after check-out.",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="company_id.currency_id",
        readonly=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
        index=True,
    )

    @api.depends("product_id", "room_id", "room_type_id")
    def _compute_name(self):
        for consumable in self:
            parts = [consumable.product_id.display_name]
            if consumable.room_id:
                parts.append(_("room %s", consumable.room_id.number))
            elif consumable.room_type_id:
                parts.append(consumable.room_type_id.name)
            consumable.name = " - ".join(part for part in parts if part)

    @api.depends("product_id")
    def _compute_uom_id(self):
        for consumable in self:
            consumable.uom_id = consumable.product_id.uom_id

    @api.depends("allowance_scope")
    def _compute_allowance_scope_multiplier(self):
        for consumable in self:
            consumable.allowance_scope_multiplier = 1

    @api.constrains("standard_qty", "allowance_qty", "allowance_price")
    def _check_non_negative(self):
        for consumable in self:
            if float_compare(consumable.standard_qty, 0, precision_digits=6) < 0:
                raise ValidationError(
                    _("The standard quantity cannot be negative."),
                )
            if float_compare(consumable.allowance_qty, 0, precision_digits=6) < 0:
                raise ValidationError(
                    _("The complimentary allowance cannot be negative."),
                )
            if float_compare(consumable.allowance_price, 0, precision_digits=6) < 0:
                raise ValidationError(_("The unit price cannot be negative."))

    @api.constrains("product_id", "uom_id")
    def _check_uom(self):
        for consumable in self:
            product_uom = consumable.product_id.uom_id
            if (
                product_uom
                and consumable.uom_id
                and consumable.uom_id.id != product_uom.id
                and consumable.uom_id.relative_uom_id not in (product_uom, product_uom.relative_uom_id)
            ):
                raise ValidationError(
                    _(
                        "The unit of measure of %(product)s is not compatible "
                        "with its default unit.",
                        product=consumable.product_id.display_name,
                    ),
                )

    @api.constrains("room_type_id", "room_id", "product_id")
    def _check_unique_override(self):
        for consumable in self:
            if not consumable.product_id:
                continue
            domain = [
                ("room_type_id", "=", consumable.room_type_id.id),
                ("room_id", "=", consumable.room_id.id),
                ("product_id", "=", consumable.product_id.id),
                ("id", "!=", consumable.id),
            ]
            if self.search_count(domain):
                raise ValidationError(
                    _(
                        "%(product)s is already configured for this room or "
                        "room type.",
                        product=consumable.product_id.display_name,
                    ),
                )

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    @api.model
    def _for_room(self, room):
        """Return the effective configuration of ``room`` as a list.

        Room-specific overrides take precedence over the room-type defaults.
        The returned list is ordered by sequence for a stable snapshot.
        """
        if not room or not room.room_type_id:
            return self.browse()
        configs = self.search(
            [
                ("room_type_id", "=", room.room_type_id.id),
                "|",
                ("room_id", "=", False),
                ("room_id", "=", room.id),
                ("active", "=", True),
            ],
        )
        by_product = {}
        for config in configs.sorted(lambda c: (c.room_id.id or 0, c.sequence, c.id)):
            by_product[config.product_id.id] = config
        return self.browse([config.id for config in by_product.values()])

    # ------------------------------------------------------------------
    # Lifecycle & Product Synchronization
    # ------------------------------------------------------------------
    def init(self):
        super().init()
        # Clean up products marked hotel_consumption_ok=True by the old default=True,
        # keeping hotel_consumption_ok=True only for products actively configured in
        # hotel.room.consumable or shipped as hotel demo/data products.
        self.env.cr.execute("""
            UPDATE product_template
            SET hotel_consumption_ok = FALSE
            WHERE hotel_consumption_ok = TRUE
              AND id NOT IN (
                  SELECT DISTINCT p.product_tmpl_id
                  FROM hotel_room_consumable c
                  JOIN product_product p ON p.id = c.product_id
                  WHERE c.active = TRUE
              )
              AND id NOT IN (
                  SELECT res_id FROM ir_model_data
                  WHERE module = 'hotel' AND model = 'product.template'
              )
              AND id NOT IN (
                  SELECT p.product_tmpl_id
                  FROM ir_model_data d
                  JOIN product_product p ON p.id = d.res_id
                  WHERE d.module = 'hotel' AND d.model = 'product.product'
              );
        """)

    def _sync_product_consumption_flags(self):
        for record in self:
            if record.product_id and record.active:
                record.product_id.product_tmpl_id.sudo().write({"hotel_consumption_ok": True})
            elif record.product_id and not record.active:
                record.product_id._recompute_hotel_consumption_ok()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_product_consumption_flags()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "product_id" in vals or "active" in vals:
            self._sync_product_consumption_flags()
        return res

    def unlink(self):
        products = self.mapped("product_id")
        res = super().unlink()
        products._recompute_hotel_consumption_ok()
        return res
