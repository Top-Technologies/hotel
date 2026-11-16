from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

from .product_template import TURNOVER_POLICIES

APPROVAL_RIGHTS = (
    "hotel.group_housekeeping_supervisor",
    "hotel.group_hotel_manager",
    "hotel.group_general_manager",
)


class HotelRoomInspection(models.Model):
    """Check-out inspection of the consumables left in a room.

    The inspection compares the physically verified remaining quantities with
    the quantities the consumption session expects, records every discrepancy
    with a reason, and only charges the guest for the consumption an
    authorized reviewer has explicitly confirmed.
    """

    _name = "hotel.room.inspection"
    _description = "Hotel Room Consumption Inspection"
    _inherit = ["mail.thread", "mail.activity.mixin", "hotel.config"]
    _order = "create_date desc, id desc"

    name = fields.Char(
        string="Reference",
        required=True,
        default="New",
        readonly=True,
        copy=False,
        index=True,
    )
    reservation_id = fields.Many2one(
        comodel_name="hotel.reservation",
        string="Reservation",
        required=True,
        ondelete="cascade",
        tracking=True,
        index=True,
    )
    room_id = fields.Many2one(
        comodel_name="hotel.room",
        string="Room",
        related="reservation_id.room_id",
        store=True,
        index=True,
    )
    guest_id = fields.Many2one(
        comodel_name="res.partner",
        string="Guest",
        related="reservation_id.guest_id",
        store=True,
        index=True,
    )
    consumption_id = fields.Many2one(
        comodel_name="hotel.room.consumption",
        string="Consumption Session",
        ondelete="set null",
        index=True,
    )
    inspector_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Inspected By",
        tracking=True,
        index=True,
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Inspected By User",
        default=lambda self: self.env.user,
        readonly=True,
        copy=False,
    )
    inspection_at = fields.Datetime(
        string="Inspected On", readonly=True, copy=False,
    )
    applied_at = fields.Datetime(
        string="Charges Applied On", readonly=True, copy=False,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("in_progress", "Inspection In Progress"),
            ("pending_review", "Discrepancy Review"),
            ("approved", "Approved"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        index=True,
        tracking=True,
    )
    turnover_policy = fields.Selection(
        selection=TURNOVER_POLICIES,
        string="Turnover Policy",
        required=True,
        default="replenish",
        tracking=True,
    )
    policy_reason = fields.Text(
        string="Policy Exception Reason",
        help="Recorded when the turnover policy differs from the room type or "
        "hotel default.",
    )
    line_ids = fields.One2many(
        comodel_name="hotel.room.inspection.line",
        inverse_name="inspection_id",
        string="Inspection Lines",
    )
    discrepancy_count = fields.Integer(
        string="Discrepancies",
        compute="_compute_discrepancy_count",
        store=True,
    )
    chargeable_total = fields.Monetary(
        string="Confirmed Charges",
        currency_field="currency_id",
        compute="_compute_chargeable_total",
        store=True,
    )
    replenishment_picking_id = fields.Many2one(
        comodel_name="stock.picking",
        string="Replenishment",
        readonly=True,
        copy=False,
    )
    notes = fields.Text(string="Notes")
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="reservation_id.currency_id",
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name") in (False, None, "New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "hotel.room.inspection",
                )
        inspections = super().create(vals_list)
        inspections._fill_from_consumption()
        return inspections

    @api.depends("line_ids.variance_qty", "line_ids.discrepancy_type")
    def _compute_discrepancy_count(self):
        for inspection in self:
            inspection.discrepancy_count = len(
                inspection.line_ids.filtered(
                    lambda line: line.discrepancy_type != "none",
                ),
            )

    @api.depends("line_ids.confirmed_qty", "line_ids.unit_price")
    def _compute_chargeable_total(self):
        for inspection in self:
            inspection.chargeable_total = sum(
                inspection.line_ids.mapped("confirmed_charge"),
            )

    def _fill_from_consumption(self):
        """Create one inspection line per expected remaining item."""
        Line = self.env["hotel.room.inspection.line"]
        for inspection in self:
            if inspection.line_ids or not inspection.consumption_id:
                continue
            commands = []
            for line in inspection.consumption_id.line_ids:
                expected = max(line.unused_qty, 0.0)
                commands.append(
                    Command.create(
                        {
                            "consumption_line_id": line.id,
                            "expected_remaining_qty": expected,
                            "actual_remaining_qty": expected,
                            "discrepancy_type": "none",
                        },
                    )
                )
            if commands:
                inspection.line_ids = commands

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_start(self):
        for inspection in self:
            if inspection.state != "draft":
                raise ValidationError(
                    _("Only draft inspections can be started."),
                )
            inspection.write(
                {
                    "state": "in_progress",
                    "inspector_id": inspection.inspector_id
                    or self.env.user.employee_id,
                    "user_id": self.env.user,
                    "inspection_at": fields.Datetime.now(),
                }
            )
        return True

    def action_submit(self):
        for inspection in self:
            if inspection.state not in ("draft", "in_progress"):
                raise ValidationError(
                    _("Only a running inspection can be submitted."),
                )
            if not inspection.inspection_at:
                inspection.inspection_at = fields.Datetime.now()
            inspection.line_ids._auto_classify()
            if inspection.discrepancy_count:
                inspection.state = "pending_review"
            else:
                inspection._approve_and_apply()
        return True

    def action_approve(self):
        self._check_approval_rights()
        for inspection in self:
            if inspection.state == "approved":
                return True
            if inspection.state not in ("pending_review", "in_progress", "draft"):
                raise ValidationError(
                    _("Only a pending inspection can be approved."),
                )
            inspection.line_ids._mark_approved(self.env.user)
            inspection._approve_and_apply()
        return True

    def action_reject(self):
        self._check_approval_rights()
        for inspection in self:
            if inspection.state != "pending_review":
                raise ValidationError(
                    _("Only a pending inspection can be sent back."),
                )
            inspection.state = "in_progress"
            inspection.message_post(
                body=_("Inspection sent back for correction by %s.")
                % self.env.user.name,
            )
        return True

    def action_cancel(self):
        for inspection in self:
            if inspection.state == "approved":
                raise ValidationError(
                    _("An approved inspection cannot be cancelled."),
                )
            inspection.state = "cancelled"
        return True

    def _check_approval_rights(self):
        if self.env.su or self.env.user.has_group("base.group_system"):
            return
        if any(self.env.user.has_group(xmlid) for xmlid in APPROVAL_RIGHTS):
            return
        raise UserError(
            _("Only a supervisor or hotel manager can approve a consumption "
              "inspection."),
        )

    def _approve_and_apply(self):
        self.ensure_one()
        self._apply_confirmed_consumption()
        self.write({"state": "approved"})
        self.message_post(
            body=_(
                "Inspection approved: %(count)s discrepancy line(s), confirmed "
                "charges %(amount)s.",
                count=self.discrepancy_count,
                amount=self.chargeable_total,
            ),
        )
        return True

    @api.constrains("turnover_policy", "policy_reason")
    def _check_policy_reason(self):
        for inspection in self:
            if not inspection.room_id:
                continue
            default = inspection.room_id._hotel_turnover_policy()
            if (
                inspection.turnover_policy != default
                and not (inspection.policy_reason or "").strip()
            ):
                raise ValidationError(
                    _("Record a reason when the turnover policy differs from "
                      "the room default."),
                )

    def _apply_confirmed_consumption(self):
        """Add the confirmed guest consumption to the session and bill it."""
        self.ensure_one()
        if self.applied_at:
            return True
        consumption = self.consumption_id
        if not consumption:
            return False
        for line in self.line_ids:
            if float_compare(line.confirmed_qty, 0, precision_digits=6) <= 0:
                continue
            target = line.consumption_line_id
            if not target:
                continue
            target.with_context(hotel_skip_realloc=True).write(
                {"consumed_qty": target.consumed_qty + line.confirmed_qty},
            )
        consumption.inspection_id = self.id
        consumption.with_context(hotel_skip_realloc=True)._reallocate_line_charges()
        consumption._post_folio_charges()
        if self.turnover_policy == "replenish":
            self._replenish_room()
        self.applied_at = fields.Datetime.now()
        return True

    # ------------------------------------------------------------------
    # Replenishment (turnover policy A)
    # ------------------------------------------------------------------
    def _replenish_room(self):
        """Bring the room back to the configured standard quantity."""
        self.ensure_one()
        if self.replenishment_picking_id:
            return self.replenishment_picking_id
        source = (
            self._hotel_housekeeping_cart_location()
            or self._hotel_storeroom_location()
        )
        destination = self._hotel_room_location()
        if not source or not destination:
            raise UserError(
                _("Configure the housekeeping cart/storeroom and room locations before "
                  "replenishing a room."),
            )
        picking_type = self._hotel_internal_picking_type()
        if not picking_type:
            raise UserError(
                _("No internal transfer type is configured in the inventory."),
            )
        precision = self.env["decimal.precision"].precision_get("Product Unit")
        move_commands = []
        for line in self.line_ids:
            target = line.consumption_line_id
            if not target or not target.product_id:
                continue
            required = line.standard_qty - line.actual_remaining_qty
            if float_compare(required, 0, precision_digits=precision) <= 0:
                continue
            move_commands.append(
                Command.create(
                    self._hotel_stock_move_vals(
                        target.product_id,
                        required,
                        source,
                        destination,
                        description=target.product_id.display_name or self.name,
                    ),
                ),
            )
        if not move_commands:
            return False
        picking = self.env["stock.picking"].sudo().create(
            {
                "picking_type_id": picking_type.id,
                "origin": self.name,
                "location_id": source.id,
                "location_dest_id": destination.id,
                "move_ids": move_commands,
            },
        )
        try:
            picking.sudo().with_context(skip_backorder=True).button_validate()
        except UserError as error:
            self.message_post(
                body=_(
                    "Replenishment %(picking)s created but not validated: "
                    "%(error)s",
                    picking=picking.name,
                    error=error.args[0] if error.args else error,
                ),
            )
        else:
            self.message_post(
                body=_("Room replenished to standard (%s).") % picking.name,
            )
        self.replenishment_picking_id = picking
        return picking

    def _open_form(self):
        self.ensure_one()
        return {
            "name": _("Room Consumption Inspection"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.room.inspection",
            "view_mode": "form",
            "views": [[False, "form"]],
            "res_id": self.id,
            "target": "current",
        }

    def action_open_reservation(self):
        self.ensure_one()
        return {
            "name": _("Reservation"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.reservation",
            "view_mode": "form",
            "views": [[False, "form"]],
            "res_id": self.reservation_id.id,
        }

    def action_open_replenishment(self):
        self.ensure_one()
        if not self.replenishment_picking_id:
            return False
        return {
            "name": _("Replenishment"),
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "view_mode": "form",
            "views": [[False, "form"]],
            "res_id": self.replenishment_picking_id.id,
        }

    def action_open_checkout(self):
        """Continue the check-out once the inspection is approved."""
        self.ensure_one()
        if self.state != "approved":
            raise UserError(
                _("Approve the inspection before checking the guest out."),
            )
        return self.reservation_id.with_context(
            hotel_inspection_approved=self.id,
        ).action_checkout()


class HotelRoomInspectionLine(models.Model):
    _name = "hotel.room.inspection.line"
    _description = "Hotel Room Inspection Line"
    _order = "inspection_id, id"

    inspection_id = fields.Many2one(
        comodel_name="hotel.room.inspection",
        string="Inspection",
        required=True,
        ondelete="cascade",
        index=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("actual_remaining_qty") is not None and vals.get("actual_remaining_qty") < 0:
                vals["actual_remaining_qty"] = 0.0
            if vals.get("expected_remaining_qty") is not None and vals.get("expected_remaining_qty") < 0:
                vals["expected_remaining_qty"] = 0.0
        return super().create(vals_list)
    consumption_line_id = fields.Many2one(
        comodel_name="hotel.room.consumption.line",
        string="Consumption Line",
        ondelete="set null",
        index=True,
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        related="consumption_line_id.product_id",
        store=True,
        index=True,
    )
    expected_remaining_qty = fields.Float(
        string="Expected Remaining",
        digits="Product Unit",
        default=0.0,
    )
    actual_remaining_qty = fields.Float(
        string="Actual Remaining",
        digits="Product Unit",
        default=0.0,
    )
    variance_qty = fields.Float(
        string="Variance",
        digits="Product Unit",
        compute="_compute_variance_qty",
        store=True,
        help="Actual remaining minus expected remaining. Negative means items "
        "are missing.",
    )
    discrepancy_type = fields.Selection(
        selection=[
            ("none", "No Discrepancy"),
            ("missing", "Missing"),
            ("extra", "Extra"),
            ("damaged", "Damaged"),
            ("unverified", "Unverified"),
        ],
        string="Discrepancy",
        default="none",
        required=True,
    )
    reason = fields.Char(string="Reason")
    confirmed_qty = fields.Float(
        string="Confirmed Guest Consumption",
        digits="Product Unit",
        default=0.0,
        help="Quantity confirmed as guest consumption and chargeable. Remains "
        "zero until an authorized reviewer sets it.",
    )
    approval_state = fields.Selection(
        selection=[
            ("not_required", "Not Required"),
            ("pending", "Pending Review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        string="Review",
        default="not_required",
        required=True,
    )
    approved_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Reviewed By",
        readonly=True,
        copy=False,
    )
    approved_at = fields.Datetime(
        string="Reviewed On", readonly=True, copy=False,
    )
    unit_price = fields.Monetary(
        string="Unit Price",
        currency_field="currency_id",
        related="consumption_line_id.price_unit",
    )
    standard_qty = fields.Float(
        string="Standard Quantity",
        digits="Product Unit",
        related="consumption_line_id.standard_qty",
    )
    confirmed_charge = fields.Monetary(
        string="Confirmed Charge",
        currency_field="currency_id",
        compute="_compute_confirmed_charge",
        store=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="inspection_id.currency_id",
        readonly=True,
    )

    @api.depends("actual_remaining_qty", "expected_remaining_qty")
    def _compute_variance_qty(self):
        for line in self:
            line.variance_qty = line.actual_remaining_qty - line.expected_remaining_qty

    @api.depends("confirmed_qty", "unit_price", "consumption_line_id")
    def _compute_confirmed_charge(self):
        for line in self:
            price = line.unit_price or 0.0
            if line.consumption_line_id:
                try:
                    price = line.consumption_line_id._guest_unit_price()
                except Exception:
                    pass
            line.confirmed_charge = line.confirmed_qty * price

    @api.onchange("actual_remaining_qty", "expected_remaining_qty")
    def _onchange_actual_remaining_qty(self):
        for line in self:
            diff = (line.actual_remaining_qty or 0.0) - (line.expected_remaining_qty or 0.0)
            line.variance_qty = diff
            if float_is_zero(diff, precision_digits=6):
                line.discrepancy_type = "none"
                line.confirmed_qty = 0.0
            elif diff < 0:
                line.discrepancy_type = "missing"
                line.confirmed_qty = abs(diff)
            else:
                line.discrepancy_type = "extra"
                line.confirmed_qty = 0.0
            price = line.unit_price or 0.0
            if line.consumption_line_id:
                try:
                    price = line.consumption_line_id._guest_unit_price()
                except Exception:
                    pass
            line.confirmed_charge = line.confirmed_qty * price


    @api.constrains("actual_remaining_qty", "confirmed_qty")
    def _check_quantities(self):
        for line in self:
            if float_compare(line.actual_remaining_qty, 0, precision_digits=6) < 0:
                raise ValidationError(
                    _("The actual remaining quantity cannot be negative."),
                )
            if float_compare(line.confirmed_qty, 0, precision_digits=6) < 0:
                raise ValidationError(
                    _("The confirmed consumption cannot be negative."),
                )
            if (
                line.variance_qty < 0
                and line.confirmed_qty
                > abs(line.variance_qty) + 1e-6
            ):
                raise ValidationError(
                    _("The confirmed consumption cannot exceed the missing "
                      "quantity."),
                )

    def _auto_classify(self):
        """Default the discrepancy type and flag the lines needing review."""
        for line in self:
            diff = (line.actual_remaining_qty or 0.0) - (line.expected_remaining_qty or 0.0)
            line.variance_qty = diff
            if float_is_zero(diff, precision_digits=6):
                line.discrepancy_type = "none"
                line.approval_state = "not_required"
                line.confirmed_qty = 0.0
            elif diff < 0:
                line.discrepancy_type = "missing"
                line.approval_state = "pending"
                if float_is_zero(line.confirmed_qty, precision_digits=6):
                    line.confirmed_qty = abs(diff)
            else:
                line.discrepancy_type = "extra"
                line.approval_state = "pending"
                line.confirmed_qty = 0.0
            price = line.unit_price or 0.0
            if line.consumption_line_id:
                try:
                    price = line.consumption_line_id._guest_unit_price()
                except Exception:
                    pass
            line.confirmed_charge = line.confirmed_qty * price

    def _mark_approved(self, user):
        for line in self:
            if line.discrepancy_type != "none":
                line.write(
                    {
                        "approval_state": "approved",
                        "approved_by_id": user.id,
                        "approved_at": fields.Datetime.now(),
                    },
                )
            else:
                line.approval_state = "not_required"
