from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HotelRoomServiceOrder(models.Model):
    """Food / beverage order taken for an in-house guest.

    The order is sent to the Point of Sale (kitchen, stock, restaurant
    history) and the amount is charged to the guest folio, exactly like a
    minibar consumption: the guest pays at check-out.

    Accounting: the POS session debits the *Room Charge Clearing* account
    (the "Charge to Room" payment method outstanding account) and credits
    the food income accounts once. The folio line credits the same clearing
    account and debits the guest receivable, so the clearing account always
    nets to zero and revenue is never recognized twice.
    """

    _name = "hotel.room.service.order"
    _description = "Room Service Order"
    _inherit = ["mail.thread", "mail.activity.mixin", "hotel.config"]
    _order = "order_date desc, id desc"

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
        domain="[('state', '=', 'checked_in')]",
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
        index=True,
        ondelete="restrict",
        domain="[('active', '=', True), ('reservation_ids.state', '=', 'checked_in')]",
        help="Only active rooms with a checked-in guest. Pick the room first: "
        "the in-house reservation is looked up automatically and the order "
        "is charged to that guest's folio.",
    )
    order_date = fields.Datetime(
        string="Ordered On",
        required=True,
        default=fields.Datetime.now,
        tracking=True,
    )
    employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Employee",
        tracking=True,
        index=True,
        default=lambda self: self.env.user.employee_id,
    )
    config_id = fields.Many2one(
        comodel_name="pos.config",
        string="Point of Sale",
        required=True,
        default=lambda self: self._default_config_id(),
        tracking=True,
        help="Point of Sale receiving the order. Its session must be open.",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("sent", "Sent to POS"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        readonly=True,
        index=True,
        tracking=True,
    )
    line_ids = fields.One2many(
        comodel_name="hotel.room.service.line",
        inverse_name="order_id",
        string="Items",
        copy=True,
    )
    amount_total = fields.Monetary(
        string="Total",
        compute="_compute_amount_total",
        store=True,
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="reservation_id.currency_id",
        readonly=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        related="reservation_id.company_id",
        readonly=True,
    )
    pos_order_id = fields.Many2one(
        comodel_name="pos.order",
        string="POS Order",
        readonly=True,
        copy=False,
        index=True,
        ondelete="set null",
    )
    pos_reference = fields.Char(
        related="pos_order_id.pos_reference",
        string="Receipt Number",
        readonly=True,
    )
    folio_line_ids = fields.One2many(
        comodel_name="hotel.reservation.line",
        inverse_name="room_service_order_id",
        string="Folio Lines",
        readonly=True,
        copy=False,
    )
    note = fields.Text(string="Notes")

    @api.model
    def _default_config_id(self):
        return self._hotel_pos_room_service_config()

    @api.model
    def _resolve_active_reservation(self, room):
        """Return the checked-in stay of a room (empty recordset if none)."""
        if not room:
            return self.env["hotel.reservation"]
        return self.env["hotel.reservation"].search(
            [("room_id", "=", room.id), ("state", "=", "checked_in")],
        )

    @api.onchange("reservation_id")
    def _onchange_reservation_id(self):
        for order in self:
            order.room_id = order.reservation_id.room_id

    @api.onchange("room_id")
    def _onchange_room_id(self):
        """Order by room: look up the in-house reservation automatically."""
        warnings = {}
        for order in self:
            if not order.room_id:
                order.reservation_id = False
                continue
            stays = order._resolve_active_reservation(order.room_id)
            if len(stays) == 1:
                order.reservation_id = stays
            else:
                order.reservation_id = False
                if not stays:
                    warnings["warning"] = {
                        "title": _("No in-house guest"),
                        "message": _(
                            "Room %s has no checked-in guest. Food can only be "
                            "charged to an in-house room.",
                        )
                        % order.room_id.number,
                    }
                else:
                    warnings["warning"] = {
                        "title": _("Several active stays"),
                        "message": _(
                            "Several in-house reservations use room %s. "
                            "Pick the reservation explicitly.",
                        )
                        % order.room_id.number,
                    }
        return warnings or None

    @api.constrains("room_id", "reservation_id")
    def _check_room_matches_reservation(self):
        for order in self:
            if (
                order.reservation_id
                and order.room_id
                and order.reservation_id.room_id != order.room_id
            ):
                raise ValidationError(
                    _("The room does not match the selected reservation."),
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name") in (False, None, "New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code(
                        "hotel.room.service.order",
                    )
                    or "New"
                )
            if not vals.get("reservation_id") and vals.get("room_id"):
                room = self.env["hotel.room"].browse(vals["room_id"])
                stays = self._resolve_active_reservation(room)
                if len(stays) == 1:
                    vals["reservation_id"] = stays.id
                elif not stays:
                    raise UserError(
                        _("Room %s has no checked-in guest.") % room.number,
                    )
                else:
                    raise UserError(
                        _("Several in-house reservations use room %s.")
                        % room.number,
                    )
            if not vals.get("room_id") and vals.get("reservation_id"):
                reservation = self.env["hotel.reservation"].browse(
                    vals["reservation_id"],
                )
                vals["room_id"] = reservation.room_id.id
        return super().create(vals_list)

    def write(self, vals):
        if "reservation_id" in vals and not vals.get("room_id"):
            reservation = self.env["hotel.reservation"].browse(vals["reservation_id"])
            vals["room_id"] = reservation.room_id.id
        return super().write(vals)

    @api.depends("line_ids.price_subtotal")
    def _compute_amount_total(self):
        for order in self:
            order.amount_total = sum(order.line_ids.mapped("price_subtotal"))

    # ------------------------------------------------------------------
    # Sending to the Point of Sale
    # ------------------------------------------------------------------
    def action_send_to_pos(self):
        for order in self:
            order._send_to_pos()
        return True

    def _send_to_pos(self):
        """Create the POS order and charge the amount to the guest folio."""
        self.ensure_one()
        if self.state != "draft":
            raise UserError(
                _("Room service order %s has already been sent.") % self.name,
            )
        if not self.line_ids:
            raise UserError(
                _("Add at least one item to room service order %s.")
                % self.name,
            )
        if self.reservation_id.state != "checked_in":
            raise UserError(
                _("The guest of %s is not checked in, nothing to order.")
                % self.reservation_id.name,
            )
        self.env["hotel.config"].validate_pos_config(self.company_id or self.env.company)
        config = self.config_id
        session = self._open_session(config)
        method = self._room_charge_payment_method()
        self._ensure_payment_method_on_config(config, method)

        # The folio charge first: it raises before anything is created when
        # the guest invoice is already posted.
        try:
            self._post_folio_charge()
        except UserError:
            raise
        except Exception as error:
            raise UserError(
                _(
                    "Could not charge room service %(order)s to the guest folio "
                    "of %(reservation)s:\n%(error)s",
                    order=self.name,
                    reservation=self.reservation_id.name,
                    error=error,
                )
            ) from error
        try:
            pos_order = self._create_pos_order(session, method)
        except UserError:
            raise
        except Exception as error:
            raise UserError(
                _(
                    "Folio was charged for %(order)s, but the Point of Sale "
                    "order could not be created on %(pos)s:\n%(error)s\n\n"
                    "Check the POS session and products, then retry or cancel "
                    "and recreate the order.",
                    order=self.name,
                    pos=config.display_name,
                    error=error,
                )
            ) from error
        self.write({"state": "sent", "pos_order_id": pos_order.id})
        return True

    @api.model
    def _room_charge_payment_method(self):
        company = self.company_id if hasattr(self, "company_id") and self.company_id else self.env.company
        method = self.env["hotel.config"]._hotel_room_charge_payment_method(company=company)
        if not method:
            raise UserError(
                _(
                    "The \"Charge to Room\" payment method is missing. "
                    "Configure it in Hotel Settings or upgrade the Hotel module.",
                ),
            )
        return method

    def _open_session(self, config):
        """Return an opened POS session, auto-opening one when possible."""
        if not config:
            raise UserError(
                _(
                    "No Point of Sale is set on this room service order.\n"
                    "Choose a POS on the order, or set the hotel Room Service "
                    "POS in Settings.",
                ),
            )
        PosSession = self.env["pos.session"].sudo()
        session = PosSession.search(
            [
                ("config_id", "=", config.id),
                ("state", "=", "opened"),
                ("rescue", "=", False),
            ],
            limit=1,
            order="id desc",
        )
        if session:
            return session

        # A session mid-close blocks creating a new one — ask cashier to finish.
        blocking = PosSession.search(
            [
                ("config_id", "=", config.id),
                ("state", "=", "closing_control"),
                ("rescue", "=", False),
            ],
            limit=1,
            order="id desc",
        )
        if blocking:
            raise UserError(
                _(
                    "Point of Sale %(pos)s has a session in Closing Control.\n"
                    "Finish closing that session (Point of Sale > %(pos)s), "
                    "then send the room service order again. A new session "
                    "will open automatically if needed.",
                    pos=config.display_name,
                ),
            )

        session = PosSession.search(
            [
                ("config_id", "=", config.id),
                ("state", "=", "opening_control"),
                ("rescue", "=", False),
            ],
            limit=1,
            order="id desc",
        )
        if not session:
            try:
                session = PosSession.create(
                    {
                        "config_id": config.id,
                        "user_id": self.env.uid,
                    }
                )
            except Exception as error:
                raise UserError(
                    _(
                        "Could not create a Point of Sale session on %(pos)s:\n"
                        "%(error)s\n\n"
                        "Open Point of Sale > %(pos)s manually, start a session, "
                        "then send the room service order again.",
                        pos=config.display_name,
                        error=error,
                    )
                ) from error

        if session.state == "opening_control":
            try:
                session.set_opening_control(
                    0, _("Auto-opened for hotel room service"),
                )
            except Exception as error:
                raise UserError(
                    _(
                        "Could not open the Point of Sale session on %(pos)s:\n"
                        "%(error)s\n\n"
                        "Open Point of Sale > %(pos)s, complete Opening Control, "
                        "then send the room service order again.",
                        pos=config.display_name,
                        error=error,
                    )
                ) from error

        if session.state != "opened":
            raise UserError(
                _(
                    "Point of Sale %(pos)s has no open session (current state: "
                    "%(state)s).\n"
                    "Open Point of Sale > %(pos)s and start a session before "
                    "sending room service orders.",
                    pos=config.display_name,
                    state=session.state,
                ),
            )
        return session

    def _ensure_payment_method_on_config(self, config, method):
        """Make the method selectable on the POS (harmless if already there)."""
        if method not in config.payment_method_ids:
            config.sudo().write(
                {"payment_method_ids": [Command.link(method.id)]},
            )

    def _ensure_picking_type_sequence(self, config):
        """Make sure the POS picking type can number its pickings.

        A picking type without a sequence makes ``stock.picking`` keep the
        default ``"/"`` reference.  The first room service order then stores a
        picking named ``"/"`` and the next one violates the
        ``unique(name, company_id)`` constraint, surfacing as the validation
        error *"Reference must be unique per company!"*.  Recreate the missing
        sequence the same way ``stock.picking.type.create`` does.
        """
        self.ensure_one()
        picking_type = config.picking_type_id
        if not picking_type or picking_type.sequence_id:
            return
        sequence_code = picking_type.sequence_code or picking_type.code or "POS"
        if picking_type.warehouse_id:
            sequence_name = _(
                "%(warehouse)s Sequence %(code)s",
                warehouse=picking_type.warehouse_id.name,
                code=sequence_code,
            )
            prefix = "%s/%s/" % (picking_type.warehouse_id.code, sequence_code)
            company = picking_type.warehouse_id.company_id
        else:
            sequence_name = _("Sequence %(code)s", code=sequence_code)
            prefix = sequence_code
            company = picking_type.company_id
        picking_type.sudo().sequence_id = self.env["ir.sequence"].sudo().create(
            {
                "name": sequence_name,
                "prefix": prefix,
                "padding": 5,
                "company_id": (company or self.env.company).id,
            },
        )

    def _create_pos_order(self, session, method):
        """Build a paid POS order paid with the Charge to Room method."""
        self.ensure_one()
        config = session.config_id
        currency = config.currency_id or self.env.company.currency_id
        fpos = config.default_fiscal_position_id
        partner = self.guest_id
        line_vals = []
        amount_total = 0.0
        amount_tax = 0.0
        for line in self.line_ids:
            product = line.product_id
            qty = line.qty
            price = line._pos_price(config, currency)
            product_taxes = product.taxes_id.filtered(
                lambda tax: tax.company_id == self.env.company,
            )
            taxes = fpos.map_tax(product_taxes) if fpos else product_taxes
            tax_details = taxes.compute_all(
                price, currency, qty, product=product, partner=partner,
            )
            subtotal = tax_details["total_excluded"]
            subtotal_incl = tax_details["total_included"]
            line_vals.append(
                Command.create(
                    {
                        "name": product.display_name,
                        "full_product_name": product.display_name,
                        "product_id": product.id,
                        "qty": qty,
                        "price_unit": price,
                        "discount": 0.0,
                        "price_type": "original",
                        "tax_ids": [Command.set(taxes.ids)],
                        "price_subtotal": subtotal,
                        "price_subtotal_incl": subtotal_incl,
                        "customer_note": line.note or "",
                    },
                ),
            )
            amount_total += subtotal_incl
            amount_tax += subtotal_incl - subtotal

        amount_total = currency.round(amount_total)
        amount_tax = currency.round(amount_tax)
        vals = {
            "session_id": session.id,
            "config_id": config.id,
            "partner_id": partner.id or False,
            "date_order": fields.Datetime.now(),
            "floating_order_name": _(
                "Room %(room)s - %(reservation)s",
                room=self.room_id.number,
                reservation=self.reservation_id.name,
            ),
            "lines": line_vals,
            "payment_ids": [
                Command.create(
                    {
                        "name": method.name,
                        "payment_method_id": method.id,
                        "amount": amount_total,
                        "payment_date": fields.Datetime.now(),
                    },
                ),
            ],
            "amount_tax": amount_tax,
            "amount_total": amount_total,
            "amount_paid": amount_total,
            "amount_return": 0.0,
            "amount_difference": 0.0,
        }
        note = self._pos_internal_note()
        if "general_note" in self.env["pos.order"]._fields:
            vals["general_note"] = note
        elif "internal_note" in self.env["pos.order"]._fields:
            vals["internal_note"] = note
        pos_order = self.env["pos.order"].create(vals)
        pos_order.action_pos_order_paid()
        self._ensure_picking_type_sequence(config)
        pos_order._create_order_picking()
        pos_order._compute_total_cost_in_real_time()
        return pos_order

    def _pos_internal_note(self):
        self.ensure_one()
        items = ", ".join(
            "%s x%s" % (line.product_id.display_name, line.qty)
            for line in self.line_ids
        )
        return _(
            "%(order)s - room %(room)s (%(items)s)",
            order=self.name,
            room=self.room_id.number,
            items=items,
        )

    # ------------------------------------------------------------------
    # Guest folio
    # ------------------------------------------------------------------
    def _folio_product(self):
        company = self.company_id if hasattr(self, "company_id") and self.company_id else self.env.company
        product = self.env["hotel.config"]._hotel_room_service_product(company=company)
        if not product:
            raise UserError(
                _(
                    "The room service folio product is missing. "
                    "Configure it in Hotel Settings or upgrade the Hotel module.",
                ),
            )
        return product

    def _charge_description(self):
        self.ensure_one()
        items = "; ".join(
            "%s x%s" % (line.product_id.display_name, line.qty)
            for line in self.line_ids
        )
        return _(
            "%(order)s - room %(room)s: %(items)s",
            order=self.name,
            room=self.room_id.number,
            items=items,
        )

    def _post_folio_charge(self):
        """Bill the order on the guest folio exactly once.

        The reservation line is the source of truth: check-out turns every
        billable line into a folio invoice line. When a draft folio invoice
        already exists, the charge is added to it right away instead.
        """
        self.ensure_one()
        order = self.sudo()
        reservation = order.reservation_id
        if order.folio_line_ids:
            return False
        product = order._folio_product()
        description = order._charge_description()
        order.env["hotel.reservation.line"].create(
            {
                "reservation_id": reservation.id,
                "room_service_order_id": order.id,
                "service_type": "room_service",
                "name": description,
                "product_id": product.id,
                "qty": 1.0,
                "price_unit": order.amount_total,
                "billable": True,
            },
        )
        invoice = reservation.invoice_ids[:1]
        if invoice:
            if invoice.state != "draft":
                raise UserError(
                    _(
                        "The guest folio of %s is already posted: room "
                        "service charges cannot be added anymore.",
                    )
                    % reservation.name,
                )
            account = (
                product.property_account_income_id
                or (hasattr(product, "product_tmpl_id") and product.product_tmpl_id.property_account_income_id)
                or (hasattr(product, "categ_id") and product.categ_id.property_account_income_categ_id)
            )
            if not account:
                account = self.env["hotel.config"].with_company(invoice.company_id)._hotel_income_account()
            vals = {
                "move_id": invoice.id,
                "name": description,
                "product_id": product.id,
                "quantity": 1.0,
                "price_unit": order.amount_total,
                "tax_ids": [],
            }
            if account:
                vals["account_id"] = account.id
            order.env["account.move.line"].create(vals)
        return True

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------
    def action_cancel(self):
        for order in self:
            if order.state == "sent":
                raise UserError(
                    _(
                        "%s has already been sent to the Point of Sale. "
                        "Cancel it from the Point of Sale instead.",
                    )
                    % order.name,
                )
            order.state = "cancelled"
        return True

    def action_reset_to_draft(self):
        for order in self:
            if order.state != "cancelled":
                raise UserError(_("Only cancelled orders can be reset."))
            order.state = "draft"
        return True

    def action_print_ticket(self):
        self.ensure_one()
        return self.env.ref(
            "hotel.action_print_room_service_ticket",
        ).report_action(self)

    def action_open_pos_order(self):
        self.ensure_one()
        if not self.pos_order_id:
            raise UserError(_("No Point of Sale order for %s.") % self.name)
        return {
            "type": "ir.actions.act_window",
            "name": _("Point of Sale Order"),
            "res_model": "pos.order",
            "res_id": self.pos_order_id.id,
            "view_mode": "form",
            "target": "current",
        }


class HotelRoomServiceLine(models.Model):
    _name = "hotel.room.service.line"
    _description = "Room Service Order Line"
    _order = "sequence, id"

    order_id = fields.Many2one(
        comodel_name="hotel.room.service.order",
        string="Room Service Order",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(string="Sequence", default=10)
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        required=True,
        domain="[('available_in_pos', '=', True), ('sale_ok', '=', True)]",
    )
    qty = fields.Float(string="Quantity", default=1.0, required=True)
    price_unit = fields.Monetary(
        string="Unit Price",
        compute="_compute_price_unit",
        store=True,
        readonly=False,
        precompute=True,
        currency_field="currency_id",
    )
    price_subtotal = fields.Monetary(
        string="Subtotal",
        compute="_compute_price_subtotal",
        store=True,
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="order_id.currency_id",
        readonly=True,
    )
    note = fields.Char(string="Note")

    @api.depends("product_id", "qty")
    def _compute_price_unit(self):
        for line in self:
            if not line.product_id:
                continue
            config = line.order_id.config_id
            currency = config.currency_id if config else False
            line.price_unit = line._pos_price(config, currency)

    @api.depends("qty", "price_unit")
    def _compute_price_subtotal(self):
        for line in self:
            line.price_subtotal = line.qty * line.price_unit

    def _pos_price(self, config, currency):
        """Price the POS would charge for this item."""
        self.ensure_one()
        product = self.product_id
        pricelist = config.pricelist_id if config else False
        if pricelist and config.use_pricelist and currency:
            return pricelist._get_product_price(
                product, self.qty or 1.0, currency=currency,
            )
        return product.list_price


class HotelReservationLine(models.Model):
    _inherit = "hotel.reservation.line"

    room_service_order_id = fields.Many2one(
        comodel_name="hotel.room.service.order",
        string="Room Service Order",
        readonly=True,
        copy=False,
        index=True,
        ondelete="set null",
        help="Room service order that produced this charge. Guarantees that "
        "an order is never billed twice.",
    )
