from datetime import timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

from .product_template import (
    CONSUMPTION_POLICIES,
    CONSUMPTION_SCOPES,
    TURNOVER_POLICIES,
)

POST_RIGHTS = (
    "hotel.group_housekeeping_supervisor",
    "hotel.group_hotel_manager",
    "hotel.group_general_manager",
)

# States whose consumption is considered confirmed for allowance purposes and
# where the historical price and policy snapshots are frozen.
CONFIRMED_STATES = ("recorded", "reviewed", "posted")


class HotelRoomConsumption(models.Model):
    _name = "hotel.room.consumption"
    _description = "Hotel Room Consumption"
    _inherit = ["mail.thread", "mail.activity.mixin", "hotel.config"]
    _order = "stay_date desc, id desc"

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
        ondelete="restrict",
        tracking=True,
        index=True,
    )
    guest_id = fields.Many2one(
        comodel_name="res.partner",
        string="Guest",
        related="reservation_id.guest_id",
        store=True,
        index=True,
    )
    room_id = fields.Many2one(
        comodel_name="hotel.room",
        string="Room",
        related="reservation_id.room_id",
        store=True,
        index=True,
    )
    stay_date = fields.Date(
        string="Stay Date",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        index=True,
    )
    employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Employee",
        tracking=True,
        index=True,
        default=lambda self: self.env.user.employee_id,
    )
    session_type = fields.Selection(
        selection=[
            ("manual", "Manual"),
            ("checkin", "Check-in Opening Stock"),
        ],
        string="Session Type",
        default="manual",
        required=True,
        index=True,
    )
    is_checkin_session = fields.Boolean(
        string="Check-in Session",
        default=False,
        index=True,
        help="Set on the session created when the guest checks in: it holds the "
        "configuration snapshot and the physically verified opening stock.",
    )
    opening_verified_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Opening Stock Verified By",
        readonly=True,
        copy=False,
    )
    opening_verified_at = fields.Datetime(
        string="Opening Stock Verified On",
        readonly=True,
        copy=False,
    )
    inspection_id = fields.Many2one(
        comodel_name="hotel.room.inspection",
        string="Check-out Inspection",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    turnover_policy = fields.Selection(
        selection=TURNOVER_POLICIES,
        string="Turnover Policy",
        copy=False,
        help="Policy snapshot for preparing the room for the next guest.",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("assigned", "Assigned"),
            ("recorded", "Consumption Recorded"),
            ("reviewed", "Reviewed"),
            ("posted", "Posted"),
        ],
        string="Status",
        default="draft",
        required=True,
        index=True,
        tracking=True,
    )
    line_ids = fields.One2many(
        comodel_name="hotel.room.consumption.line",
        inverse_name="consumption_id",
        string="Consumption Lines",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="reservation_id.currency_id",
        readonly=True,
    )
    total_charge = fields.Monetary(
        string="Guest Charge",
        currency_field="currency_id",
        compute="_compute_totals",
        store=True,
        help="Amount billed to the guest: the sum of the line guest charges. "
        "Complimentary quantities are excluded.",
    )
    recorded_total = fields.Monetary(
        string="Recorded Value",
        currency_field="currency_id",
        compute="_compute_totals",
        store=True,
        help="Value of every consumed quantity, whether it is charged to the "
        "guest or offered as a complimentary allowance.",
    )
    billable_line_count = fields.Integer(
        string="Chargeable Lines", compute="_compute_totals", store=True,
    )
    picking_id = fields.Many2one(
        comodel_name="stock.picking",
        string="Inventory Movement",
        readonly=True,
        copy=False,
    )
    return_picking_id = fields.Many2one(
        comodel_name="stock.picking",
        string="Supply Return",
        readonly=True,
        copy=False,
        help="Transfer returning the unused reusable supplies of the room to "
        "the warehouse storage at check-out.",
    )
    refill_picking_id = fields.Many2one(
        comodel_name="stock.picking",
        string="Room Refill Movement",
        readonly=True,
        copy=False,
        help="Transfer replenishing consumed room supplies from the housekeeping staff cart into the room.",
    )
    notes = fields.Text(string="Notes")
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
        index=True,
    )

    _sql_constraints = [
        (
            "stay_unique",
            "unique (reservation_id, stay_date)",
            "A stay already has a consumption record for this date.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name") in (False, None, "New"):
                company_id = vals.get("company_id") or self.env.company.id
                vals["name"] = self.env["ir.sequence"].with_company(company_id).sudo().next_by_code(
                    "hotel.room.consumption",
                ) or _("New")
        self._check_unique_stay(vals_list)
        records = super().create(vals_list)
        records._reallocate_line_charges()
        return records

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("hotel_skip_realloc"):
            self.with_context(hotel_skip_realloc=True)._reallocate_line_charges()
        return result

    def _check_unique_stay(self, vals_list):
        """Refuse a second consumption for the same stay day before it hits
        the database, so the guest gets a readable message."""
        seen = set()
        for vals in vals_list:
            reservation = vals.get("reservation_id")
            stay_date = vals.get("stay_date")
            if not reservation or not stay_date:
                continue
            key = (reservation, str(stay_date)[:10])
            if key in seen:
                raise ValidationError(
                    _(
                        "A consumption record already exists for the stay "
                        "day of %s.",
                    )
                    % self.env["hotel.reservation"].browse(reservation).name,
                )
            seen.add(key)
            if self.search(
                [("reservation_id", "=", reservation), ("stay_date", "=", stay_date)],
                limit=1,
            ):
                raise ValidationError(
                    _(
                        "A consumption record already exists for the stay "
                        "day of %s.",
                    )
                    % self.env["hotel.reservation"].browse(reservation).name,
                )

    @api.depends(
        "line_ids.guest_charge",
        "line_ids.recorded_value",
        "line_ids.chargeable_qty",
    )
    def _compute_totals(self):
        for consumption in self:
            consumption.total_charge = sum(
                consumption.line_ids.mapped("guest_charge"),
            )
            consumption.recorded_total = sum(
                consumption.line_ids.mapped("recorded_value"),
            )
            consumption.billable_line_count = len(
                consumption.line_ids.filtered(
                    lambda line: float_compare(
                        line.chargeable_qty, 0, precision_digits=6,
                    )
                    > 0,
                ),
            )

    def _reallocate_line_charges(self):
        """Split every consumed quantity into complimentary and chargeable.

        The allowance is consumed in a deterministic order: the already
        confirmed records of the reservation first, then the lines of this
        record by creation order. This keeps the remaining allowance of the
        whole stay correct even when several records are involved.
        """
        Line = self.env["hotel.room.consumption.line"]
        for consumption in self:
            used = {}
            res_id = (
                consumption.reservation_id._origin.id
                if consumption.reservation_id._origin
                else consumption.reservation_id.id
            )
            cons_id = (
                consumption._origin.id
                if consumption._origin
                else consumption.id
            )
            if res_id:
                domain = [
                    ("reservation_id", "=", res_id),
                    ("policy", "=", "allowance"),
                ]
                if cons_id:
                    domain.extend([
                        ("consumption_id", "!=", cons_id),
                        ("consumption_id.state", "in", CONFIRMED_STATES),
                    ])
                committed = Line.search(domain)
                for line in committed:
                    key = line._allowance_key()
                    used[key] = used.get(key, 0.0) + line.complimentary_qty

            def _sort_key(l):
                origin_id = l._origin.id if l._origin else 0
                return (isinstance(l.id, int), origin_id or 0)

            for line in consumption.line_ids.sorted(key=_sort_key):
                key = line._allowance_key()
                free, chargeable = line._split_quantities(used.get(key, 0.0))
                used[key] = used.get(key, 0.0) + free
                line.complimentary_qty = free
                line.chargeable_qty = chargeable
                if (
                    isinstance(line.id, int)
                    and not self.env.context.get("hotel_in_onchange")
                    and (
                        line._origin.complimentary_qty != free
                        or line._origin.chargeable_qty != chargeable
                    )
                ):
                    line.with_context(hotel_skip_realloc=True).write(
                        {
                            "complimentary_qty": free,
                            "chargeable_qty": chargeable,
                        },
                    )
                if (
                    isinstance(line.id, int)
                    and not self.env.context.get("hotel_in_onchange")
                ):
                    line._sync_folio_line()

    @api.onchange("line_ids", "reservation_id")
    def _onchange_line_ids_charges(self):
        self.with_context(hotel_in_onchange=True)._reallocate_line_charges()
        self._compute_totals()

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_assign(self):
        for consumption in self:
            if consumption.state != "draft":
                raise ValidationError(
                    _("Only draft consumption records can be assigned."),
                )
            if not consumption.employee_id:
                employee = self.env.user.employee_id
                if not employee:
                    raise UserError(
                        _("Assign an employee before taking the room stock."),
                    )
                consumption.employee_id = employee
            consumption.state = "assigned"
        return True

    def action_verify_opening_stock(self):
        """Record who physically verified the opening stock and when."""
        for consumption in self:
            if consumption.opening_verified_at:
                continue
            consumption.write(
                {
                    "opening_verified_by_id": self.env.user.id,
                    "opening_verified_at": fields.Datetime.now(),
                },
            )
            consumption.message_post(
                body=_("Opening stock physically verified by %s.")
                % self.env.user.name,
            )
        return True

    def action_record(self):
        for consumption in self:
            if consumption.state != "assigned":
                raise ValidationError(
                    _("Only assigned consumption records can be recorded."),
                )
            if not consumption.line_ids:
                raise ValidationError(
                    _("Add at least one consumption line before recording."),
                )
            consumption.state = "recorded"
            # Bill the chargeable consumption right away so it shows on the
            # guest folio (Extra Services) as soon as it is recorded, instead
            # of waiting for the supervisor to post it. When a folio invoice
            # already exists the posting step keeps handling the charge.
            if not consumption.reservation_id.sudo().invoice_ids:
                consumption._post_folio_charges()
        return True

    def action_review(self):
        for consumption in self:
            if consumption.state != "recorded":
                raise ValidationError(
                    _("Only recorded consumption can be reviewed."),
                )
            consumption.state = "reviewed"
        return True

    def action_post(self):
        """Post the consumption: inventory movement plus folio charges."""
        for consumption in self:
            if consumption.state != "reviewed":
                raise ValidationError(
                    _("Only reviewed consumption can be posted."),
                )
            if not consumption.line_ids:
                raise ValidationError(
                    _("Add at least one consumption line before posting."),
                )
            consumption._check_post_rights()
            consumption.with_context(
                hotel_skip_realloc=True,
            )._reallocate_line_charges()
            consumption._post_stock_moves()
            consumption._post_refill_moves()
            consumption._post_folio_charges()
            consumption.write({"state": "posted"})
            consumption.message_post(
                body=_(
                    "Consumption posted: %(lines)d line(s), chargeable total "
                    "%(amount)s.",
                    lines=len(consumption.line_ids),
                    amount=consumption.total_charge,
                ),
            )
        return True

    def action_reset_to_draft(self):
        for consumption in self:
            if consumption.state == "posted":
                raise ValidationError(
                    _("Posted consumption cannot be reset to draft."),
                )
            if consumption.picking_id and consumption.picking_id.state == "done":
                raise ValidationError(
                    _("The inventory movement of %s is already validated.")
                    % consumption.name,
                )
            if consumption.refill_picking_id and consumption.refill_picking_id.state == "done":
                raise ValidationError(
                    _("The room refill movement of %s is already validated.")
                    % consumption.name,
                )
            # The chargeable quantities are going to be corrected, so drop the
            # folio lines they created; recording again bills the new amounts.
            consumption._clear_folio_charges()
            consumption.state = "draft"
        return True

    def _clear_folio_charges(self):
        """Remove the folio lines that have not reached an invoice yet."""
        self.ensure_one()
        stales = self.line_ids.filtered(
            lambda line: line.folio_line_id
            and not line.invoice_line_id
            and not line.folio_line_id.reservation_id.sudo().invoice_ids,
        )
        stales.folio_line_id.sudo().unlink()

    def _check_post_rights(self):
        """Only the housekeeping supervisor or a hotel manager may post."""
        self.ensure_one()
        if self.env.su or self.env.user.has_group("base.group_system"):
            return
        if any(self.env.user.has_group(xmlid) for xmlid in POST_RIGHTS):
            return
        raise UserError(
            _("Only the housekeeping supervisor or the hotel manager can "
              "post room consumption."),
        )

    # ------------------------------------------------------------------
    # Inventory integration (standard Odoo stock)
    # ------------------------------------------------------------------
    def _post_stock_moves(self):
        """Move the consumed quantities out of the Hotel Rooms location."""
        self.ensure_one()
        if self.picking_id:
            return self.picking_id
        # The inventory side effect is executed with elevated rights: the
        # posting right is checked by _check_post_rights(), housekeeping does
        # not carry the stock or accounting security groups.
        company = self.reservation_id.company_id or self.env.company
        self.env["hotel.config"].validate_inventory_config(company, check_supplies=True, check_consumption=True)
        source = self._hotel_room_location(company=company)
        destination = self._hotel_consumption_location(company=company)
        if not source or not destination:
            raise UserError(
                _("Configure the Hotel Rooms and Room Consumption locations "
                  "in the hotel settings before posting."),
            )
        picking_type = self._hotel_internal_picking_type(company=company)
        if not picking_type:
            raise UserError(
                _(
                    "No internal transfer type is configured in the inventory. "
                    "Activate an internal transfer operation type or check the "
                    "hotel settings.",
                ),
            )
        precision = self.env["decimal.precision"].precision_get("Product Unit")
        move_commands = []
        for line in self.line_ids:
            if not line.product_id or float_compare(
                line.consumed_qty, 0, precision_digits=precision,
            ) <= 0:
                continue
            move_commands.append(
                Command.create(
                    self._hotel_stock_move_vals(
                        line.product_id,
                        line.consumed_qty,
                        source,
                        destination,
                        description=line.product_id.display_name or self.name,
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
                    "Inventory movement %(picking)s created but not validated: "
                    "%(error)s",
                    picking=picking.name,
                    error=error.args[0] if error.args else error,
                ),
            )
        else:
            if picking.state == "done":
                self.message_post(
                    body=_("Inventory movement %s validated.") % picking.name,
                )
            else:
                self.message_post(
                    body=_(
                        "Inventory movement %(picking)s created, waiting for "
                        "its validation.",
                        picking=picking.name,
                    ),
                )
        self.picking_id = picking
        return picking

    def _post_refill_moves(self):
        """Refill consumed quantities automatically from the housekeeping staff cart into the room."""
        self.ensure_one()
        if self.refill_picking_id:
            return self.refill_picking_id
        cart_source = (
            self._hotel_housekeeping_cart_location()
            or self._hotel_storeroom_location()
        )
        room_dest = self._hotel_room_location()
        if not cart_source or not room_dest:
            return False
        picking_type = self._hotel_internal_picking_type()
        if not picking_type:
            return False
        precision = self.env["decimal.precision"].precision_get("Product Unit")
        refill_commands = []
        for line in self.line_ids:
            if not line.product_id or float_compare(
                line.consumed_qty, 0, precision_digits=precision,
            ) <= 0:
                continue
            refill_commands.append(
                Command.create(
                    self._hotel_stock_move_vals(
                        line.product_id,
                        line.consumed_qty,
                        cart_source,
                        room_dest,
                        description=_(
                            "%(product)s refill for Room %(room)s",
                            product=line.product_id.display_name,
                            room=self.room_id.number or self.room_id.name or "",
                        ),
                    ),
                ),
            )
        if not refill_commands:
            return False
        refill_picking = self.env["stock.picking"].sudo().create(
            {
                "picking_type_id": picking_type.id,
                "origin": _("%(name)s - Refill", name=self.name),
                "location_id": cart_source.id,
                "location_dest_id": room_dest.id,
                "move_ids": refill_commands,
            },
        )
        try:
            refill_picking.sudo().with_context(skip_backorder=True).button_validate()
        except UserError as error:
            self.message_post(
                body=_(
                    "Room refill %(picking)s from cart created but not validated: %(error)s",
                    picking=refill_picking.name,
                    error=error.args[0] if error.args else error,
                ),
            )
        else:
            if refill_picking.state == "done":
                self.message_post(
                    body=_("Room refilled from housekeeping cart (Transfer %s).") % refill_picking.name,
                )
                for line in self.line_ids:
                    if float_compare(line.consumed_qty, 0, precision_digits=precision) > 0:
                        line.replenished_qty = line.consumed_qty
        self.refill_picking_id = refill_picking
        return refill_picking

    # ------------------------------------------------------------------
    # Reusable supplies collected at check-out
    # ------------------------------------------------------------------
    def _return_unused_supplies(self):
        """Return the unused reusable supplies of the room to storage.

        At check-out the standard amenities left in the room are collected and
        moved from the *Hotel Rooms* location back to the warehouse stock
        location. Only the unused, non-billable quantities leave the room:
        billable products are not returned (the next guest still finds them)
        and the quantities carried over to a following stay day are handled by
        ``action_start_next_day``.
        """
        self.ensure_one()
        if self.return_picking_id:
            return self.return_picking_id
        source = self._hotel_room_location()
        destination = self._hotel_supplies_return_location()
        if not source or not destination:
            raise UserError(
                _("Configure the Hotel Rooms location and its warehouse "
                  "storage before returning the room supplies."),
            )
        picking_type = self._hotel_internal_picking_type()
        if not picking_type:
            raise UserError(
                _(
                    "No internal transfer type is configured in the inventory. "
                    "Activate an internal transfer operation type or check the "
                    "hotel settings.",
                ),
            )
        precision = self.env["decimal.precision"].precision_get("Product Unit")
        move_commands = []
        for line in self.line_ids:
            if (
                not line.product_id
                or line.is_billable
                or float_compare(
                    line.unused_qty, 0, precision_digits=precision,
                ) <= 0
            ):
                continue
            move_commands.append(
                Command.create(
                    self._hotel_stock_move_vals(
                        line.product_id,
                        line.unused_qty,
                        source,
                        destination,
                        description=line.product_id.display_name or self.name,
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
                    "Supply return %(picking)s created but not validated: "
                    "%(error)s",
                    picking=picking.name,
                    error=error.args[0] if error.args else error,
                ),
            )
        else:
            self.message_post(
                body=_("Unused room supplies returned to storage (%s).")
                % picking.name,
            )
        self.return_picking_id = picking
        return picking

    # ------------------------------------------------------------------
    # Minibar / chargeable consumption on the guest folio
    # ------------------------------------------------------------------
    def _post_folio_charges(self):
        """Add every billable line to the folio, exactly once."""
        self.ensure_one()
        record = self.sudo()
        precision = record.env["decimal.precision"].precision_get("Product Unit")
        to_bill = record.line_ids.filtered(
            lambda line: line.is_billable
            and float_compare(line.billable_qty, 0, precision_digits=precision) > 0
            and not line.folio_line_id
            and not line.invoice_line_id,
        )
        if not to_bill:
            return False
        reservation = record.reservation_id
        drafts = reservation.invoice_ids.filtered(
            lambda move: move.state == "draft",
        )
        invoice = drafts[:1] or reservation.invoice_ids[:1]
        if invoice and invoice.state != "draft":
            raise UserError(
                _("The guest folio of %s is already posted: minibar charges "
                  "cannot be added anymore.")
                % record.reservation_id.name,
            )
        if invoice:
            for line in to_bill:
                line.invoice_line_id = record.env["account.move.line"].create(
                    line._invoice_line_vals(invoice),
                )
        else:
            for line in to_bill:
                line.folio_line_id = record.env["hotel.reservation.line"].create(
                    line._reservation_line_vals(),
                )
        return True

    # ------------------------------------------------------------------
    # Carry forward to the next stay day
    # ------------------------------------------------------------------
    def action_start_next_day(self):
        """Open the consumption record of the following stay day."""
        self.ensure_one()
        if self.state != "posted":
            raise UserError(
                _("Post the consumption of %s before starting the next day.")
                % self.stay_date,
            )
        next_date = self.stay_date + timedelta(days=1)
        checkout = self.reservation_id.checkout
        if checkout and next_date > checkout.date():
            raise UserError(
                _("The stay of this reservation ends on %s.")
                % fields.Date.to_string(checkout.date()),
            )
        existing = self.search(
            [
                ("reservation_id", "=", self.reservation_id.id),
                ("stay_date", "=", next_date),
            ],
            limit=1,
        )
        if existing:
            return existing._open_form()
        lines = self.line_ids.filtered(
            lambda line: (
                line.next_opening_qty > 0
                or line.is_billable
                or line.standard_qty > 0
                or line.replenished_qty > 0
                or line.policy == "complimentary"
            ),
        )
        new_lines = []
        for line in lines:
            opening = line.next_opening_qty
            if float_compare(opening, 0, precision_digits=6) <= 0:
                if line.policy == "complimentary" or line.allowance_scope == "day":
                    opening = line.replenished_qty or line.standard_qty
                elif line.standard_qty > 0 and line.replenished_qty > 0:
                    opening = line.replenished_qty
                else:
                    opening = 0.0
            new_lines.append(
                Command.create(
                    {
                        "product_id": line.product_id.id,
                        "standard_qty": line.standard_qty,
                        "opening_qty": opening,
                        "is_billable": line.is_billable,
                        "policy": line.policy,
                        "allowance_qty": line.allowance_qty,
                        "allowance_scope": line.allowance_scope,
                        "charge_excess": line.charge_excess,
                        "allowance_price": line.allowance_price,
                        "charge_product_id": line.charge_product_id.id,
                        "price_unit": line.price_unit,
                    },
                )
            )

        # Include any room consumables configured for the room that were not present on this day
        existing_products = lines.mapped("product_id")
        room_configs = self.room_id._effective_consumables().filtered(
            lambda c: c.included_in_setup and c.active and c.product_id not in existing_products
        )
        for config in room_configs:
            new_lines.append(
                Command.create(
                    {
                        "product_id": config.product_id.id,
                        "standard_qty": config.standard_qty or 0.0,
                        "opening_qty": config.standard_qty or 0.0,
                        "policy": config.policy or "chargeable",
                        "allowance_qty": config.allowance_qty or 0.0,
                        "allowance_scope": config.allowance_scope or "stay",
                        "charge_excess": config.charge_excess,
                        "allowance_price": config.allowance_price or 0.0,
                        "charge_product_id": config.product_id.id,
                        "price_unit": config.allowance_price or config.product_id.list_price or config.product_id.standard_price or 0.0,
                        "is_billable": (config.policy or "chargeable") in ("chargeable", "allowance"),
                    }
                )
            )

        new_consumption = self.create(
            {
                "reservation_id": self.reservation_id.id,
                "stay_date": next_date,
                "employee_id": self.employee_id.id,
                "company_id": self.company_id.id,
                "notes": _("Opening quantities carried forward from %s.")
                % fields.Date.to_string(self.stay_date),
                "line_ids": new_lines,
            },
        )
        return new_consumption._open_form()

    def _open_form(self):
        self.ensure_one()
        return {
            "name": self.name,
            "type": "ir.actions.act_window",
            "res_model": "hotel.room.consumption",
            "view_mode": "form",
            "views": [[False, "form"]],
            "res_id": self.id,
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

    def action_open_picking(self):
        self.ensure_one()
        if not self.picking_id:
            return False
        return {
            "name": _("Inventory Movement"),
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "view_mode": "form",
            "views": [[False, "form"]],
            "res_id": self.picking_id.id,
        }

    def action_open_return_picking(self):
        self.ensure_one()
        if not self.return_picking_id:
            return False
        return {
            "name": _("Supply Return"),
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "view_mode": "form",
            "views": [[False, "form"]],
            "res_id": self.return_picking_id.id,
        }

    def action_open_refill_picking(self):
        self.ensure_one()
        if not self.refill_picking_id:
            return False
        return {
            "name": _("Room Refill Movement"),
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "view_mode": "form",
            "views": [[False, "form"]],
            "res_id": self.refill_picking_id.id,
        }


class HotelRoomConsumptionLine(models.Model):
    _name = "hotel.room.consumption.line"
    _description = "Hotel Room Consumption Line"
    _order = "consumption_id, id"

    consumption_id = fields.Many2one(
        comodel_name="hotel.room.consumption",
        string="Consumption",
        required=True,
        ondelete="cascade",
        index=True,
    )
    reservation_id = fields.Many2one(
        comodel_name="hotel.reservation",
        related="consumption_id.reservation_id",
        store=True,
        index=True,
    )
    room_id = fields.Many2one(
        comodel_name="hotel.room",
        related="consumption_id.room_id",
        store=True,
        index=True,
    )
    stay_date = fields.Date(
        related="consumption_id.stay_date",
        store=True,
        index=True,
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        required=True,
        index=True,
        domain="[('hotel_consumption_ok', '=', True)]",
    )
    product_categ_id = fields.Many2one(
        comodel_name="product.category",
        related="product_id.categ_id",
        string="Product Category",
        store=True,
        index=True,
    )
    standard_qty = fields.Float(
        string="Standard Amount",
        digits="Product Unit",
        default=0.0,
        help="Standard quantity (par level) of the room for this product, "
        "snapshotted from the room consumable configuration at check-in.",
    )
    opening_qty = fields.Float(
        string="Opening Quantity", digits="Product Unit", default=0.0,
    )
    provided_qty = fields.Float(
        string="Transfer",
        digits="Product Unit",
        default=0.0,
        help="Quantity transferred or supplied to the room.",
    )
    consumed_qty = fields.Float(
        string="Used",
        digits="Product Unit",
        default=0.0,
        help="Quantity used or consumed by the guest.",
    )
    unused_qty = fields.Float(
        string="Unused Quantity",
        digits="Product Unit",
        compute="_compute_quantities",
        store=True,
        help="Opening + Provided - Consumed.",
    )
    carried_fwd_qty = fields.Float(
        string="Carried Forward Quantity",
        digits="Product Unit",
        compute="_compute_carried",
        store=True,
        readonly=False,
        help="Part of the unused quantity carried to the next stay day. The "
        "next day opens with this quantity.",
    )
    replenished_qty = fields.Float(
        string="Replenished Quantity", digits="Product Unit", default=0.0,
    )
    next_opening_qty = fields.Float(
        string="Next Day Opening",
        digits="Product Unit",
        compute="_compute_next_opening",
        store=True,
        help="Opening quantity of the same product on the next stay day.",
    )
    policy = fields.Selection(
        selection=CONSUMPTION_POLICIES,
        string="Charging Policy",
        compute="_compute_policy",
        store=True,
        readonly=False,
        precompute=True,
        help="Charging policy snapshot, defaulted from the product.",
    )
    allowance_qty = fields.Float(
        string="Complimentary Allowance",
        digits="Product Unit",
        compute="_compute_allowance",
        store=True,
        readonly=False,
        precompute=True,
        help="Quantity offered before any excess is charged. Snapshot of the "
        "product configuration.",
    )
    allowance_scope = fields.Selection(
        selection=CONSUMPTION_SCOPES,
        string="Allowance Scope",
        compute="_compute_allowance",
        store=True,
        readonly=False,
        precompute=True,
    )
    charge_excess = fields.Boolean(
        string="Charge Excess",
        compute="_compute_allowance",
        store=True,
        readonly=False,
        precompute=True,
    )
    allowance_price = fields.Monetary(
        string="Excess Unit Price",
        currency_field="currency_id",
        compute="_compute_allowance",
        store=True,
        readonly=False,
        precompute=True,
        help="Unit price applied above the allowance. Empty means the "
        "product sales price.",
    )
    complimentary_qty = fields.Float(
        string="Complimentary Quantity",
        digits="Product Unit",
        readonly=True,
        default=0.0,
        copy=False,
        help="Consumed quantity covered by an allowance and not charged.",
    )
    remaining_allowance_qty = fields.Float(
        string="Remaining Free Allowance",
        compute="_compute_remaining_allowance",
        digits="Product Unit",
        help="Complimentary quantity still available to the guest for this scope.",
    )
    chargeable_qty = fields.Float(
        string="Chargeable Quantity",
        digits="Product Unit",
        readonly=True,
        default=0.0,
        copy=False,
        help="Consumed quantity billed to the guest, after the allowance.",
    )
    billable_qty = fields.Float(
        string="Billable Quantity",
        digits="Product Unit",
        related="chargeable_qty",
        store=True,
        help="Kept as an alias of the chargeable quantity.",
    )
    is_billable = fields.Boolean(
        string="Is Billable",
        compute="_compute_is_billable",
        store=True,
        readonly=False,
        help="Set as soon as the line has a chargeable quantity.",
    )
    charge_product_id = fields.Many2one(
        comodel_name="product.product",
        string="Charge Product",
        help="Product invoiced for this consumption. Falls back to the "
        "consumed product when empty.",
    )
    price_unit = fields.Monetary(
        string="Unit Price",
        currency_field="currency_id",
        compute="_compute_price_unit",
        store=True,
        readonly=False,
        precompute=True,
        help="Snapshot of the unit price. It is frozen once set so later "
        "product price changes do not rewrite history.",
    )
    recorded_value = fields.Monetary(
        string="Recorded Value",
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
        help="Consumed quantity valued at the unit price, charged or not.",
    )
    guest_charge = fields.Monetary(
        string="Total Billable Price",
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
        help="Total price of used items that are billable to the guest.",
    )
    subtotal = fields.Monetary(
        string="Subtotal",
        currency_field="currency_id",
        related="guest_charge",
        store=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="consumption_id.currency_id",
        readonly=True,
    )
    folio_line_id = fields.Many2one(
        comodel_name="hotel.reservation.line",
        string="Folio Line",
        readonly=True,
        copy=False,
        index=True,
        ondelete="set null",
    )
    invoice_line_id = fields.Many2one(
        comodel_name="account.move.line",
        string="Invoice Line",
        readonly=True,
        copy=False,
        index=True,
        ondelete="set null",
    )
    notes = fields.Char(string="Notes")

    _sql_constraints = [
        (
            "folio_line_unique",
            "unique (folio_line_id)",
            "This consumption line is already billed on the guest folio.",
        ),
        (
            "invoice_line_unique",
            "unique (invoice_line_id)",
            "This consumption line is already billed on the guest folio.",
        ),
        (
            "carried_forward_valid",
            "check (carried_fwd_qty >= 0 and (unused_qty < 0 or "
            "carried_fwd_qty <= unused_qty))",
            "The carried forward quantity must be between 0 and the unused "
            "quantity.",
        ),
        (
            "quantities_non_negative",
            "check (opening_qty >= 0 and provided_qty >= 0 and consumed_qty >= 0 "
            "and replenished_qty >= 0)",
            "Consumption quantities cannot be negative.",
        ),
        (
            "unit_price_non_negative",
            "check (price_unit >= 0 and allowance_price >= 0)",
            "Unit prices cannot be negative.",
        ),
    ]

    @api.depends("opening_qty", "provided_qty", "consumed_qty")
    def _compute_quantities(self):
        for line in self:
            line.unused_qty = (
                line.opening_qty + line.provided_qty - line.consumed_qty
            )

    @api.depends("opening_qty", "provided_qty", "consumed_qty")
    def _compute_carried(self):
        for line in self:
            line.carried_fwd_qty = max(
                line.opening_qty + line.provided_qty - line.consumed_qty, 0.0,
            )

    @api.depends("carried_fwd_qty")
    def _compute_next_opening(self):
        for line in self:
            line.next_opening_qty = max(line.carried_fwd_qty, 0.0)

    @api.depends("policy")
    def _compute_is_billable(self):
        for line in self:
            line.is_billable = line.policy in ("chargeable", "allowance")

    def _find_room_consumable_config(self):
        self.ensure_one()
        if not self.product_id:
            return self.env["hotel.room.consumable"]
        room = self.room_id or (self.consumption_id and self.consumption_id.room_id)
        room_type = room.room_type_id if room else False
        if room:
            override = self.env["hotel.room.consumable"].search(
                [("room_id", "=", room.id), ("product_id", "=", self.product_id.id), ("active", "=", True)],
                limit=1,
            )
            if override:
                return override
        if room_type:
            type_config = self.env["hotel.room.consumable"].search(
                [("room_type_id", "=", room_type.id), ("room_id", "=", False), ("product_id", "=", self.product_id.id), ("active", "=", True)],
                limit=1,
            )
            if type_config:
                return type_config
        return self.env["hotel.room.consumable"].search(
            [("product_id", "=", self.product_id.id), ("active", "=", True)],
            limit=1,
        )

    @api.depends("product_id", "consumption_id.room_id")
    def _compute_policy(self):
        for line in self:
            config = line._find_room_consumable_config()
            if config and config.policy:
                line.policy = config.policy
            else:
                line.policy = (
                    line.product_id.hotel_consumption_policy or "chargeable"
                )

    @api.depends("product_id", "consumption_id.room_id")
    def _compute_allowance(self):
        for line in self:
            config = line._find_room_consumable_config()
            if config:
                line.allowance_qty = config.allowance_qty or 0.0
                line.allowance_scope = config.allowance_scope or "stay"
                line.charge_excess = config.charge_excess
                line.allowance_price = config.allowance_price or 0.0
            else:
                product = line.product_id
                company = line.consumption_id.reservation_id.company_id or self.env.company
                hotel_config = self.env["hotel.config"].with_company(company)
                line.allowance_qty = (
                    product.hotel_allowance_qty
                    if product and product.hotel_allowance_qty
                    else hotel_config._hotel_consumable_allowance_qty()
                )
                line.allowance_scope = (
                    product.hotel_allowance_scope
                    if product and product.hotel_allowance_scope
                    else hotel_config._hotel_consumable_allowance_scope()
                )
                line.charge_excess = (
                    product.hotel_allowance_charge_excess
                    if product
                    else True
                )
                line.allowance_price = (
                    product.hotel_allowance_price
                    if product and product.hotel_allowance_price
                    else hotel_config._hotel_consumable_allowance_price()
                )

    @api.depends("product_id", "charge_product_id")
    def _compute_price_unit(self):
        for line in self:
            product = line.charge_product_id or line.product_id
            if not product:
                line.price_unit = 0.0
                continue
            line.price_unit = product.list_price or product.standard_price or 0.0

    @api.depends(
        "consumed_qty",
        "chargeable_qty",
        "price_unit",
        "allowance_price",
        "policy",
    )
    def _compute_amounts(self):
        for line in self:
            line.recorded_value = line.consumed_qty * line.price_unit
            line.guest_charge = line.chargeable_qty * line._guest_unit_price()

    @api.depends(
        "allowance_qty",
        "allowance_scope",
        "policy",
        "consumed_qty",
        "complimentary_qty",
        "opening_qty",
        "provided_qty",
        "consumption_id.stay_date",
        "consumption_id.reservation_id",
    )
    def _compute_remaining_allowance(self):
        for line in self:
            if line.policy == "complimentary":
                line.remaining_allowance_qty = max(
                    line.opening_qty + line.provided_qty - line.consumed_qty, 0.0,
                )
            elif line.policy != "allowance":
                line.remaining_allowance_qty = 0.0
            else:
                total_allowance = line._allowance_total()
                if line.allowance_scope == "day":
                    line.remaining_allowance_qty = max(
                        total_allowance - line.complimentary_qty, 0.0,
                    )
                else:
                    res = line.reservation_id
                    used_prior = 0.0
                    if res:
                        cons_id = (
                            line.consumption_id.id
                            or (line.consumption_id._origin.id if line.consumption_id._origin else 0)
                        )
                        prior = self.search([
                            ("reservation_id", "=", res.id),
                            ("product_id", "=", line.product_id.id),
                            ("policy", "=", "allowance"),
                            ("consumption_id", "!=", cons_id),
                            ("consumption_id.state", "in", CONFIRMED_STATES),
                        ])
                        used_prior = sum(prior.mapped("complimentary_qty"))
                    line.remaining_allowance_qty = max(
                        total_allowance - used_prior - line.complimentary_qty, 0.0,
                    )

    def _allowance_key(self):
        """Grouping key used to share an allowance across lines."""
        self.ensure_one()
        prod_id = (
            self.product_id._origin.id
            if self.product_id._origin
            else self.product_id.id
        )
        if self.allowance_scope == "day":
            return (prod_id, self.stay_date)
        return (prod_id, False)

    def _allowance_total(self):
        """Allowance available for this line, expanded by its scope."""
        self.ensure_one()
        allowance = self.allowance_qty or 0.0
        if self.allowance_scope == "guest":
            reservation = self.consumption_id.reservation_id
            guests = reservation.registered_guests or (
                reservation.adults + reservation.children
            )
            allowance *= max(guests, 1)
        return allowance

    def _split_quantities(self, already_used):
        """Return (complimentary, chargeable) for the consumed quantity."""
        self.ensure_one()
        consumed = self.consumed_qty
        if float_compare(consumed, 0, precision_digits=6) <= 0:
            return 0.0, 0.0
        if self.policy == "complimentary":
            return consumed, 0.0
        if self.policy != "allowance":
            return 0.0, consumed
        remaining = max(self._allowance_total() - already_used, 0.0)
        free = min(consumed, remaining)
        if not self.charge_excess:
            # the quantity above the allowance stays complimentary
            return consumed, 0.0
        return free, consumed - free

    def _guest_unit_price(self):
        """Unit price applied to the chargeable quantity."""
        self.ensure_one()
        if self.policy == "complimentary":
            return 0.0
        if self.policy == "allowance" and self.allowance_price:
            return self.allowance_price
        return self.price_unit

    @api.onchange(
        "consumed_qty",
        "provided_qty",
        "opening_qty",
        "policy",
        "allowance_qty",
        "allowance_scope",
        "charge_excess",
        "allowance_price",
        "price_unit",
    )
    def _onchange_consumption_quantities(self):
        for line in self:
            parent = line.consumption_id
            if parent:
                parent.with_context(hotel_in_onchange=True)._reallocate_line_charges()
            else:
                free, chargeable = line._split_quantities(0.0)
                line.complimentary_qty = free
                line.chargeable_qty = chargeable
            line.guest_charge = line.chargeable_qty * line._guest_unit_price()
            line.recorded_value = line.consumed_qty * line.price_unit

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if not self.env.context.get("hotel_skip_realloc"):
            for consumption in lines.mapped("consumption_id"):
                consumption.with_context(
                    hotel_skip_realloc=True,
                )._reallocate_line_charges()
        return lines

    def write(self, vals):
        result = super().write(vals)
        guarded = self.env.context.get("hotel_skip_realloc")
        if not guarded:
            for consumption in self.consumption_id:
                consumption.with_context(
                    hotel_skip_realloc=True,
                )._reallocate_line_charges()
        return result

    @api.constrains("product_id")
    def _check_product_eligible(self):
        for line in self:
            if line.product_id and not line.product_id.hotel_consumption_ok:
                raise ValidationError(
                    _(
                        "%(product)s is not allowed for room consumption.",
                        product=line.product_id.display_name,
                    ),
                )

    def _folio_product(self):
        self.ensure_one()
        return self.charge_product_id or self.product_id

    def _sync_folio_line(self):
        """Keep an already billed folio line in step with the quantities.

        A chargeable consumption is billed as soon as it is recorded. If the
        quantities are corrected afterwards, and before the folio is invoiced,
        the guest charge must follow.
        """
        self.ensure_one()
        folio = self.folio_line_id
        if not folio or self.invoice_line_id:
            return
        if folio.reservation_id.sudo().invoice_ids:
            return
        if float_compare(self.chargeable_qty, 0, precision_digits=6) <= 0:
            folio.sudo().unlink()
            return
        folio.sudo().write(
            {
                "qty": self.chargeable_qty,
                "price_unit": self._guest_unit_price(),
            },
        )

    def _charge_description(self):
        self.ensure_one()
        if self.notes:
            return self.notes
        product = self._folio_product()
        return _("%(product)s - minibar, room %(room)s, %(date)s",
                 product=product.display_name,
                 room=self.room_id.number or "",
                 date=fields.Date.to_string(self.consumption_id.stay_date))

    def _reservation_line_vals(self):
        """Values of the guest folio service line (pre check-out)."""
        self.ensure_one()
        product = self._folio_product()
        return {
            "reservation_id": self.reservation_id.id,
            "service_type": "minibar",
            "name": self._charge_description(),
            "product_id": product.id,
            "qty": self.chargeable_qty,
            "price_unit": self._guest_unit_price(),
            "billable": True,
            "consumption_line_id": self.id,
        }

    def _invoice_line_vals(self, invoice):
        """Values of the folio invoice line (post check-out)."""
        self.ensure_one()
        product = self._folio_product()
        account = (
            product.property_account_income_id
            or (hasattr(product, "product_tmpl_id") and product.product_tmpl_id.property_account_income_id)
            or (hasattr(product, "categ_id") and product.categ_id.property_account_income_categ_id)
        )
        if not account:
            account = self.env["hotel.config"].with_company(invoice.company_id)._hotel_income_account()
        vals = {
            "move_id": invoice.id,
            "name": self._charge_description(),
            "product_id": product.id,
            "quantity": self.chargeable_qty,
            "price_unit": self._guest_unit_price(),
        }
        if account:
            vals["account_id"] = account.id
        return vals


class HotelReservationLine(models.Model):
    _inherit = "hotel.reservation.line"

    consumption_line_id = fields.Many2one(
        comodel_name="hotel.room.consumption.line",
        string="Room Consumption",
        readonly=True,
        copy=False,
        index=True,
        ondelete="set null",
        help="Consumption record that produced this charge. Guarantees that "
        "a consumption line is never billed twice.",
    )
