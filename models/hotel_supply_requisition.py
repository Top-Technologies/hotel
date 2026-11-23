from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


class HotelSupplyRequisition(models.Model):
    """Housekeeping staff buffer stock requisition.

    Cleaning staff use this document to manually request room consumables
    and amenities in bulk from the central warehouse storage into their
    Housekeeping Cart / Floor Pantry.
    """

    _name = "hotel.supply.requisition"
    _description = "Hotel Housekeeping Supply Requisition"
    _inherit = ["mail.thread", "mail.activity.mixin", "hotel.config"]
    _order = "request_date desc, id desc"

    name = fields.Char(
        string="Reference",
        required=True,
        default="New",
        readonly=True,
        copy=False,
        index=True,
    )
    employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Requesting Staff",
        required=True,
        tracking=True,
        default=lambda self: self.env.user.employee_id,
    )
    request_date = fields.Date(
        string="Request Date",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    source_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Source (Main Warehouse)",
        required=True,
        domain="[('usage', '=', 'internal')]",
        default=lambda self: self.env["hotel.config"]._hotel_storeroom_location(),
        help="Central warehouse storeroom supplying the goods.",
    )
    dest_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Destination (Staff Cart / Floor)",
        required=True,
        domain="[('usage', '=', 'internal')]",
        default=lambda self: self.env["hotel.config"]._hotel_housekeeping_cart_location(),
        help="Housekeeping trolley, floor pantry or staff buffer location.",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("requested", "Requested"),
            ("done", "Transferred"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )
    line_ids = fields.One2many(
        comodel_name="hotel.supply.requisition.line",
        inverse_name="requisition_id",
        string="Requested Items",
    )
    picking_id = fields.Many2one(
        comodel_name="stock.picking",
        string="Internal Transfer",
        readonly=True,
        copy=False,
    )
    notes = fields.Text(string="Notes")
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name") in (False, None, "New"):
                company_id = vals.get("company_id") or self.env.company.id
                seq_name = self.env["ir.sequence"].with_company(company_id).next_by_code(
                    "hotel.supply.requisition",
                )
                if not seq_name:
                    seq_name = self.env["ir.sequence"].sudo().search([
                        ("code", "=", "hotel.supply.requisition"),
                    ], limit=1).next_by_id()
                vals["name"] = seq_name or "New"
        return super().create(vals_list)

    def _ensure_picking_type_sequence(self, picking_type, company):
        """Ensure the picking type has a sequence whose counter is strictly ahead of existing pickings."""
        if not picking_type:
            return
        company = company or self.env.company
        if not picking_type.sequence_id:
            sequence_code = picking_type.sequence_code or picking_type.code or "HS"
            if picking_type.warehouse_id:
                sequence_name = _(
                    "%(warehouse)s Sequence %(code)s",
                    warehouse=picking_type.warehouse_id.name,
                    code=sequence_code,
                )
                prefix = "%s/%s/" % (picking_type.warehouse_id.code, sequence_code)
                seq_company = picking_type.warehouse_id.company_id
            else:
                sequence_name = _("Sequence %(code)s", code=sequence_code)
                prefix = "%s/" % sequence_code
                seq_company = picking_type.company_id or company
            picking_type.sudo().sequence_id = self.env["ir.sequence"].sudo().create(
                {
                    "name": sequence_name,
                    "prefix": prefix,
                    "padding": 5,
                    "company_id": seq_company.id if seq_company else False,
                },
            )

        seq = picking_type.sequence_id
        if seq and seq.prefix:
            self.env.cr.execute(
                """
                SELECT name FROM stock_picking
                WHERE company_id = %s AND name LIKE %s
                ORDER BY length(name) DESC, name DESC LIMIT 100;
                """,
                (company.id, seq.prefix + "%"),
            )
            rows = self.env.cr.fetchall()
            max_num = 0
            import re
            for (pname,) in rows:
                m = re.search(r"(\d+)$", pname)
                if m:
                    max_num = max(max_num, int(m.group(1)))
            if max_num >= seq.number_next_actual:
                seq.sudo().write({"number_next": max_num + 1})

    def action_request(self):
        """Submit the requisition and create the internal stock transfer."""
        for req in self:
            if not req.line_ids:
                raise ValidationError(
                    _("Add at least one item to request from the warehouse."),
                )
            if req.source_location_id == req.dest_location_id:
                raise ValidationError(
                    _("Source warehouse and destination cart cannot be the same location."),
                )
            picking_type = req._hotel_internal_picking_type(company=req.company_id)
            if not picking_type:
                raise UserError(
                    _("No internal transfer operation type is configured."),
                )
            req._ensure_picking_type_sequence(picking_type, req.company_id)
            precision = self.env["decimal.precision"].precision_get("Product Unit")
            move_commands = []
            for line in req.line_ids:
                if float_compare(line.quantity, 0, precision_digits=precision) <= 0:
                    continue
                move_commands.append(
                    Command.create(
                        req._hotel_stock_move_vals(
                            line.product_id,
                            line.quantity,
                            req.source_location_id,
                            req.dest_location_id,
                            description=_(
                                "Requisition %(req)s - %(product)s",
                                req=req.name,
                                product=line.product_id.display_name,
                            ),
                        ),
                    ),
                )
            if not move_commands:
                raise ValidationError(
                    _("All requested quantities must be greater than zero."),
                )
            picking = self.env["stock.picking"].sudo().create(
                {
                    "picking_type_id": picking_type.id,
                    "company_id": req.company_id.id,
                    "origin": req.name,
                    "location_id": req.source_location_id.id,
                    "location_dest_id": req.dest_location_id.id,
                    "move_ids": move_commands,
                },
            )
            try:
                picking.sudo().with_context(skip_backorder=True).button_validate()
            except Exception:
                # If immediate validation is not possible, keep transfer ready for warehouse confirmation
                pass
            req.picking_id = picking
            req.state = "done" if picking.state == "done" else "requested"
            req.message_post(
                body=_(
                    "Supply requisition submitted: transfer %(transfer)s created.",
                    transfer=picking.name,
                ),
            )
        return True

    def action_validate(self):
        """Validate the pending internal transfer when warehouse supplies arrive."""
        for req in self:
            if not req.picking_id:
                raise UserError(_("No stock transfer is linked to this requisition."))
            if req.picking_id.state == "done":
                req.state = "done"
                continue
            req.picking_id.sudo().with_context(skip_backorder=True).button_validate()
            if req.picking_id.state == "done":
                req.state = "done"
                req.message_post(
                    body=_("Supplies received and transferred to cart (%s).")
                    % req.picking_id.name,
                )
        return True

    def action_cancel(self):
        for req in self:
            if req.picking_id and req.picking_id.state == "done":
                raise ValidationError(
                    _("The stock transfer %s is already validated and cannot be cancelled.")
                    % req.picking_id.name,
                )
            if req.picking_id and req.picking_id.state not in ("cancel", "done"):
                req.picking_id.action_cancel()
            req.state = "cancelled"
        return True

    def action_open_picking(self):
        self.ensure_one()
        if not self.picking_id:
            return False
        return {
            "name": _("Stock Transfer"),
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "view_mode": "form",
            "views": [[False, "form"]],
            "res_id": self.picking_id.id,
        }


class HotelSupplyRequisitionLine(models.Model):
    _name = "hotel.supply.requisition.line"
    _description = "Hotel Supply Requisition Line"

    requisition_id = fields.Many2one(
        comodel_name="hotel.supply.requisition",
        string="Requisition",
        required=True,
        ondelete="cascade",
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        required=True,
        domain="[('hotel_consumption_ok', '=', True)]",
    )
    quantity = fields.Float(
        string="Quantity",
        digits="Product Unit",
        default=10.0,
        required=True,
    )
    uom_id = fields.Many2one(
        comodel_name="uom.uom",
        related="product_id.uom_id",
        string="Unit of Measure",
        readonly=True,
    )
    warehouse_qty = fields.Float(
        string="Available in Warehouse",
        compute="_compute_stock_levels",
        digits="Product Unit",
        help="Current quantity of this product in the source warehouse.",
    )
    cart_qty = fields.Float(
        string="Current on Cart",
        compute="_compute_stock_levels",
        digits="Product Unit",
        help="Current quantity of this product in the destination cart/floor.",
    )

    @api.depends("product_id", "requisition_id.source_location_id", "requisition_id.dest_location_id")
    def _compute_stock_levels(self):
        Quant = self.env["stock.quant"]
        for line in self:
            source = line.requisition_id.source_location_id
            dest = line.requisition_id.dest_location_id
            if line.product_id and source:
                quants = Quant.search([
                    ("product_id", "=", line.product_id.id),
                    ("location_id", "child_of", source.id),
                ])
                line.warehouse_qty = sum(quants.mapped("quantity"))
            else:
                line.warehouse_qty = 0.0

            if line.product_id and dest:
                cart_quants = Quant.search([
                    ("product_id", "=", line.product_id.id),
                    ("location_id", "child_of", dest.id),
                ])
                line.cart_qty = sum(cart_quants.mapped("quantity"))
            else:
                line.cart_qty = 0.0
