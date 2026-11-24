from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import formatLang


class HotelCheckoutWizard(models.TransientModel):
    _name = "hotel.checkout.wizard"
    _description = "Hotel Guest Check-out"

    reservation_id = fields.Many2one(
        comodel_name="hotel.reservation",
        string="Reservation",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    reservation_type = fields.Selection(
        related="reservation_id.reservation_type",
        string="Reservation Category",
        readonly=True,
    )
    staff_id = fields.Many2one(
        comodel_name="hr.employee",
        related="reservation_id.staff_id",
        string="Staff Member",
        readonly=True,
    )
    staff_company_id = fields.Many2one(
        comodel_name="res.company",
        related="reservation_id.staff_company_id",
        string="Staff Company",
        readonly=True,
    )
    staff_work_location_id = fields.Many2one(
        comodel_name="hr.work.location",
        related="reservation_id.staff_work_location_id",
        string="Staff Branch / Location",
        readonly=True,
    )
    staff_is_cross_company = fields.Boolean(
        related="reservation_id.staff_is_cross_company",
        string="Cross-Company / Branch Stay",
        readonly=True,
    )
    internal_cost = fields.Monetary(
        related="reservation_id.internal_cost",
        string="Internal Staff Cost",
        currency_field="currency_id",
        readonly=True,
    )
    guest_id = fields.Many2one(
        comodel_name="res.partner", string="Guest", readonly=True
    )
    room_id = fields.Many2one(comodel_name="hotel.room", string="Room", readonly=True)
    checkin_at = fields.Datetime(
        string="Check-in", related="reservation_id.actual_checkin", readonly=True
    )
    checkout_at = fields.Datetime(
        string="Check-out", required=True, default=lambda self: fields.Datetime.now()
    )
    rate = fields.Monetary(
        string="Rate / Night",
        currency_field="currency_id",
        related="reservation_id.rate",
        readonly=True,
    )
    discount = fields.Float(
        string="Discount (%)",
        digits="Discount",
        required=True,
        default=0.0,
        help="Percentage discount applied to the room charge. Adjust it for a "
        "negotiated rate, then confirm.",
    )
    line_ids = fields.One2many(
        comodel_name="hotel.reservation.line",
        related="reservation_id.line_ids",
        string="Extra Services",
        readonly=False,
    )
    consumption_line_ids = fields.One2many(
        comodel_name="hotel.room.consumption.line",
        related="reservation_id.consumption_line_ids",
        string="Room Consumption",
        readonly=True,
    )
    consumption_total = fields.Monetary(
        string="Room Consumption Total",
        currency_field="currency_id",
        compute="_compute_consumption_total",
        help="Total chargeable room consumption added to the bill.",
    )
    nights = fields.Integer(string="Nights", compute="_compute_charges")
    room_charge = fields.Monetary(
        string="Room Charge", currency_field="currency_id", compute="_compute_charges"
    )
    discount_amount = fields.Monetary(
        string="Discount", currency_field="currency_id", compute="_compute_charges"
    )
    late_checkout_minutes = fields.Integer(
        string="Late Check-out (Mins)",
        compute="_compute_charges",
        help="Minutes late past scheduled check-out time.",
    )
    late_checkout_penalty = fields.Monetary(
        string="Late Check-out Fee",
        currency_field="currency_id",
        compute="_compute_charges",
        help="Surcharge calculated for late check-out.",
    )
    late_checkout_desc = fields.Char(
        string="Late Details",
        compute="_compute_charges",
    )
    service_total = fields.Monetary(
        string="Services", currency_field="currency_id", compute="_compute_charges"
    )
    charges_total = fields.Monetary(
        string="Charges (excl. tax)",
        currency_field="currency_id",
        compute="_compute_charges",
    )
    deposit = fields.Monetary(
        string="Deposit to Deduct",
        currency_field="currency_id",
        help="Deposit already collected for this stay.",
    )
    balance_due = fields.Monetary(
        string="Balance After Deposit",
        currency_field="currency_id",
        compute="_compute_charges",
        help="Charges minus the deposit, taxes excluded. The customer invoice "
        "adds the configured taxes.",
    )
    refund_due = fields.Monetary(
        string="Refund to Guest",
        currency_field="currency_id",
        compute="_compute_charges",
        help="Excess deposit to be refunded to the guest.",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="reservation_id.currency_id",
        readonly=True,
    )
    create_invoice = fields.Boolean(
        string="Create Guest Invoice", default=True
    )
    settle_balance = fields.Boolean(
        string="Settle Balance Now",
        default=False,
        help="Register the deposit as a payment and the remaining balance on "
        "the chosen journal.",
    )
    payment_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Payment Journal",
        domain="[('type', 'in', ('bank', 'cash', 'credit'))]",
        help="Journal used to settle the balance. Empty means the hotel "
        "default payment journal.",
    )
    notes = fields.Text(string="Notes")
    inspection_blocking = fields.Boolean(
        string="Inspection Required",
        compute="_compute_checkout_gates",
        help="True when checkout is blocked until room consumption inspection "
        "is approved.",
    )
    discount_blocking = fields.Boolean(
        string="Discount Approval Required",
        compute="_compute_checkout_gates",
        help="True when the discount needs an approved discount request.",
    )
    checkout_warning = fields.Text(
        string="Checkout Checklist",
        compute="_compute_checkout_gates",
    )

    @api.depends(
        "reservation_id",
        "discount",
        "consumption_line_ids",
        "reservation_id.inspection_ids",
        "reservation_id.inspection_ids.state",
        "reservation_id.discount_approval_count",
    )
    def _compute_checkout_gates(self):
        config = self.env["hotel.config"]
        Approval = self.env["hotel.discount.approval"]
        for wizard in self:
            reservation = wizard.reservation_id
            inspection_blocking = False
            discount_blocking = False
            warnings = []
            if reservation:
                if (
                    config._hotel_require_checkout_inspection()
                    and reservation._checkout_room_has_consumables()
                ):
                    approved = reservation.inspection_ids.filtered(
                        lambda inspection: inspection.state == "approved",
                    )
                    if not approved:
                        inspection_blocking = True
                        warnings.append(
                            _(
                                "Room consumption inspection is required and not "
                                "approved yet. Open the inspection from Check-out "
                                "on the reservation (or Housekeeping > Room "
                                "Inspection), approve it, then confirm check-out."
                            )
                        )
                discount = wizard.discount or 0.0
                if (
                    config._hotel_require_discount_approval()
                    and config._discount_level(discount) != "none"
                ):
                    approval = Approval.search(
                        [
                            ("reservation_id", "=", reservation.id),
                            ("state", "=", "approved"),
                            ("discount_pct", ">=", discount),
                        ],
                        limit=1,
                    )
                    if not approval:
                        discount_blocking = True
                        warnings.append(
                            _(
                                "A %(discount)s%% discount needs an approved "
                                "discount request (Approvals > Discount Requests) "
                                "before check-out, or lower the discount to the "
                                "free threshold.",
                                discount=discount,
                            )
                        )
                held_props_count = self.env["hotel.guest.property"].search_count([
                    ("reservation_id", "=", reservation.id),
                    ("state", "in", ("received", "stored", "ready_return", "deposit_requested")),
                ])
                if held_props_count:
                    warnings.append(
                        _(
                            "Notice: The guest has %(count)s asset(s) held in custody/safe. Please return them to the guest from Guest Property.",
                            count=held_props_count,
                        )
                    )
            wizard.inspection_blocking = inspection_blocking
            wizard.discount_blocking = discount_blocking
            wizard.checkout_warning = "\n".join(warnings) if warnings else False

    @api.depends(
        "consumption_line_ids.guest_charge",
        "consumption_line_ids.chargeable_qty",
        "consumption_line_ids.is_billable",
    )
    def _compute_consumption_total(self):
        for wizard in self:
            wizard.consumption_total = sum(
                line.guest_charge for line in wizard.consumption_line_ids if line.is_billable
            )

    @api.depends(
        "checkout_at",
        "discount",
        "deposit",
        "line_ids.price_subtotal",
        "line_ids.billable",
        "reservation_id.reservation_type",
        "reservation_id.checkout",
        "reservation_id.room_type_id",
        "reservation_id.room_id",
    )
    def _compute_charges(self):
        from datetime import datetime, time
        import math
        for wizard in self:
            reservation = wizard.reservation_id
            start = wizard.checkin_at or reservation.actual_checkin or reservation.checkin
            end = wizard.checkout_at
            nights = reservation._stay_nights(start, end) or reservation.nights
            room_charge = nights * reservation.rate
            discount_amount = room_charge * wizard.discount / 100.0

            # Calculate Late Check-out Penalty
            late_minutes = 0
            late_penalty = 0.0
            late_desc = False
            room_type = reservation.room_type_id or reservation.room_id.room_type_id
            scheduled = reservation.checkout
            if room_type and room_type.checkout_time and scheduled:
                h = int(room_type.checkout_time)
                m = int(round((room_type.checkout_time - h) * 60))
                scheduled = datetime.combine(scheduled.date(), time(hour=min(23, max(0, h)), minute=min(59, max(0, m))))

            if scheduled and end and end > scheduled:
                diff_seconds = (end - scheduled).total_seconds()
                late_minutes = int(diff_seconds / 60)
                grace = room_type.late_checkout_grace_minutes if room_type else 15
                if late_minutes > grace:
                    if room_type:
                        late_penalty = room_type.compute_late_checkout_penalty(reservation.rate, late_minutes)
                    else:
                        blocks = math.ceil(late_minutes / 30.0)
                        late_penalty = reservation.rate * 0.10 * blocks
                    late_desc = _("%(mins)s mins late", mins=late_minutes)

            wizard.late_checkout_minutes = late_minutes
            wizard.late_checkout_penalty = late_penalty
            wizard.late_checkout_desc = late_desc

            services = sum(
                line.price_subtotal for line in wizard.line_ids if line.billable
            )
            if reservation.reservation_type == "staff":
                # For staff stays, accommodation is tracked internally; total includes staff stay cost + services
                charges = (reservation.internal_cost or (room_charge - discount_amount)) + services + late_penalty
            else:
                charges = room_charge - discount_amount + services + late_penalty
            wizard.nights = nights
            wizard.room_charge = room_charge
            wizard.discount_amount = discount_amount
            wizard.service_total = services
            wizard.charges_total = charges
            wizard.balance_due = max(0.0, charges - wizard.deposit)
            wizard.refund_due = max(0.0, wizard.deposit - charges)

    def _suggest_checkout_at(self, reservation):
        """Booked departure, never earlier than the real arrival."""
        now = fields.Datetime.now()
        return max(reservation.checkout or now, now)

    def _suggest_values(self, reservation):
        """Defaults proposed to reception for ``reservation``."""
        discount = reservation.discount or 0.0
        # If reservation discount is not set, look up any approved discount request
        if not discount:
            approved = self.env["hotel.discount.approval"].search(
                [
                    ("reservation_id", "=", reservation.id),
                    ("state", "=", "approved"),
                ],
                order="discount_pct desc",
                limit=1,
            )
            if approved:
                discount = approved.discount_pct
                if not reservation.discount and reservation.state not in ('checked_out', 'cancelled'):
                    reservation.sudo().write({"discount": discount})

        vals = {
            "checkout_at": self._suggest_checkout_at(reservation),
            "discount": discount,
            "deposit": reservation.deposit_paid or reservation.deposit,
            "payment_journal_id": self.env["hotel.config"]
            ._hotel_payment_journal()
            .id,
        }
        if reservation.reservation_type == "staff":
            vals["create_invoice"] = False
            vals["settle_balance"] = False
        return vals

    @api.model
    def default_get(self, fields_list):
        result = super().default_get(fields_list)
        res_id = (
            result.get("reservation_id")
            or self.env.context.get("default_reservation_id")
            or (self.env.context.get("active_model") == "hotel.reservation" and self.env.context.get("active_id"))
        )
        reservation = self.env["hotel.reservation"].browse(res_id) if res_id else self.env["hotel.reservation"]
        if reservation:
            result["reservation_id"] = reservation.id
            reservation._bill_pending_room_consumption()
            vals = {
                "guest_id": reservation.guest_id.id,
                "room_id": reservation.room_id.id,
                **self._suggest_values(reservation),
            }
            if reservation.reservation_type == "staff":
                vals["create_invoice"] = False
                vals["settle_balance"] = False
            result.update(vals)
        return result

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            reservation = self.env["hotel.reservation"].browse(
                vals.get("reservation_id")
            )
            if not reservation:
                continue
            reservation._bill_pending_room_consumption()
            suggested = self._suggest_values(reservation)
            for field_name, value in suggested.items():
                if vals.get(field_name) in (None, False):
                    vals[field_name] = value
        return super().create(vals_list)

    @api.onchange("reservation_id")
    def _onchange_reservation_id(self):
        for wizard in self:
            reservation = wizard.reservation_id
            if reservation:
                reservation._bill_pending_room_consumption()
                wizard.guest_id = reservation.guest_id
                wizard.room_id = reservation.room_id
                for field_name, value in self._suggest_values(reservation).items():
                    setattr(wizard, field_name, value)

    def _action_register_payment(self, invoice, amount, communication):
        """Register ``amount`` on ``invoice`` through the payment register wizard."""
        self.ensure_one()
        reservation = self.reservation_id
        if self.currency_id.is_zero(amount):
            return self.env["account.payment"]
        company = reservation.company_id or self.env.company
        self.env["hotel.config"].validate_accounting_config(company, check_checkout=True)
        journal = self.payment_journal_id or self.env["hotel.config"]._hotel_payment_journal(company=company)
        if not journal:
            raise UserError(
                _(
                    "No bank, cash or credit card journal is available to "
                    "settle the balance. Set one on %s > Settings, or in "
                    "Invoicing > Configuration > Journals."
                )
            )
        return (
            self.env["account.payment.register"]
            .with_context(active_model="account.move", active_ids=invoice.ids)
            .create(
                {
                    "payment_date": fields.Date.context_today(self),
                    "amount": amount,
                    "journal_id": journal.id,
                    "currency_id": invoice.currency_id.id,
                    "communication": communication,
                }
            )
            ._create_payments()
        )

    def action_open_checkout_inspection(self):
        """Open or create the room inspection that blocks this check-out."""
        self.ensure_one()
        reservation = self.reservation_id
        if not reservation:
            return False
        inspection = reservation._get_or_create_checkout_inspection()
        if inspection:
            return inspection._open_form()
        raise UserError(
            _("No room consumption inspection is required for %s.")
            % reservation.name
        )

    def action_confirm_checkout(self):
        self.ensure_one()
        reservation = self.reservation_id
        if reservation.state != "checked_in":
            raise ValidationError(
                _("Only checked-in reservations can be checked out.")
            )
        config = reservation.env["hotel.config"]
        if (
            config._hotel_require_checkout_inspection()
            and reservation._checkout_room_has_consumables()
        ):
            approved = reservation.inspection_ids.filtered(
                lambda inspection: inspection.state == "approved",
            )
            if not approved:
                raise UserError(
                    _(
                        "Cannot check out %(reservation)s yet.\n\n"
                        "Room consumption inspection must be approved first.\n"
                        "Use \"Open Inspection\" on this wizard, or open "
                        "Housekeeping > Room Inspection, approve the inspection, "
                        "then confirm check-out again.",
                        reservation=reservation.name,
                    )
                )
        if self.checkout_at <= (reservation.actual_checkin or reservation.checkin):
            raise ValidationError(
                _("Check-out must be later than check-in.")
            )
        # Validate discount approval before mutating the stay.
        try:
            reservation._check_discount_approval(self.discount)
        except UserError as error:
            raise UserError(
                _(
                    "Cannot check out %(reservation)s with a %(discount)s%% "
                    "discount yet.\n\n%(detail)s\n\n"
                    "Create/approve a discount request under Approvals > "
                    "Discount Requests, or reduce the discount to the free "
                    "threshold, then try again.",
                    reservation=reservation.name,
                    discount=self.discount,
                    detail=error.args[0] if error.args else error,
                )
            ) from error
        reservation.write(
            {
                "discount": self.discount,
                "actual_checkout": self.checkout_at,
                "late_checkout_minutes": self.late_checkout_minutes,
                "late_checkout_penalty": self.late_checkout_penalty,
                "state": "checked_out",
            }
        )
        # Bill any chargeable consumption sheet the housekeeping has not posted
        # yet, so the guest folio (and its invoice) carries every charge.
        reservation._bill_pending_room_consumption()
        invoice = self.env["account.move"]
        if self.create_invoice and reservation.reservation_type != "staff":
            invoice = reservation._action_create_folio_invoice()
            # If reception explicitly requested immediate settlement at checkout,
            # post the invoice and register the settlement payment.
            # Otherwise, keep the invoice as standard Odoo Draft so accounting/front desk
            # can review, confirm/post, and register payments in standard Odoo.
            if self.settle_balance:
                invoice.action_post()
                applied = reservation._reconcile_deposit_payments(invoice)
                deposit_to_deduct = self.deposit
                if not applied and deposit_to_deduct > 0:
                    deposit_amt = min(deposit_to_deduct, invoice.amount_total)
                    self._action_register_payment(
                        invoice,
                        deposit_amt,
                        _("Deposit %(name)s", name=reservation.name),
                    )
                    applied = deposit_amt
                balance_to_settle = max(0.0, invoice.amount_total - applied)
                if balance_to_settle > 0:
                    self._action_register_payment(
                        invoice,
                        balance_to_settle,
                        _("Settlement %(name)s", name=reservation.name),
                    )
        # Collect the reusable amenities left in the room and return them to
        # the warehouse storage (pure internal transfer).
        reservation._return_unused_room_supplies()
        has_open_maintenance = self.env["maintenance.request"].search_count([
            ("room_id", "=", reservation.room_id.id),
            ("stage_id.done", "=", False),
            ("archive", "=", False),
        ])
        if has_open_maintenance:
            reservation.room_id._sync_status_for_stay(
                "out_of_service",
                _("Out of service: guest checked out (%s), but maintenance request is pending.")
                % reservation.name,
            )
        else:
            reservation.room_id._sync_status_for_stay(
                "dirty", _("Dirty: guest checked out (%s).") % reservation.name
            )
            if self.env["hotel.config"]._hotel_auto_housekeeping():
                self.env["hotel.housekeeping.task"]._action_create_for_room(
                    reservation.room_id,
                    reservation=reservation,
                    notes=_("Automatic cleaning after check-out of %s.")
                    % reservation.name,
                )
        if reservation.reservation_type == "staff":
            staff_info = ""
            if reservation.staff_company_id:
                branch_str = f" - {reservation.staff_work_location_id.name}" if reservation.staff_work_location_id else ""
                staff_info = f" [{reservation.staff_company_id.name}{branch_str}]"
            reservation.message_post(
                body=_(
                    "Staff member%(staff_info)s checked out. Internal stay cost: %(internal_cost)s (%(nights)s nights). "
                    "No guest invoice generated.",
                    staff_info=staff_info,
                    internal_cost=self._format_amount(reservation.internal_cost or reservation.room_total),
                    nights=reservation.billable_nights or reservation.nights,
                )
            )
        else:
            reservation.message_post(
                body=_(
                    "Checked out. %(room_charge)s room charge + %(services)s services, "
                    "deposit %(deposit)s deducted. Invoice: %(invoice)s.",
                    room_charge=self._format_amount(reservation.room_total),
                    services=self._format_amount(reservation.service_total),
                    deposit=self._format_amount(self.deposit),
                    invoice=invoice.name or _("not created"),
                )
            )
        if self.notes:
            reservation.message_post(body=_("Check-out note: %s") % self.notes)
        if invoice:
            return {
                "name": _("Guest Invoice"),
                "type": "ir.actions.act_window",
                "res_model": "account.move",
                "view_mode": "form",
                "res_id": invoice.id,
            }
        return True

    def _format_amount(self, amount):
        """Amount with its currency, for chatter messages."""
        self.ensure_one()
        return formatLang(self.env, amount, currency_obj=self.currency_id)
