from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

DISCOUNT_APPROVE_RIGHTS = (
    "hotel.group_hotel_manager",
    "hotel.group_general_manager",
)
DISCOUNT_GM_RIGHTS = ("hotel.group_general_manager",)
LEVELS = ("none", "manager", "general_manager")


class HotelDiscountRule(models.Model):
    """Discount program: how much a group, corporate or loyalty programme
    may take off the room charge and who authorizes it."""

    _name = "hotel.discount.rule"
    _description = "Hotel Discount Rule"
    _order = "max_discount_pct, id"

    name = fields.Char(string="Program", required=True, translate=True)
    program = fields.Selection(
        selection=[
            ("corporate", "Corporate Contract"),
            ("group", "Group Booking"),
            ("travel_agent", "Travel Agent / Tour Operator"),
            ("government", "Government"),
            ("loyalty", "Loyalty / Repeat Guest"),
            ("promotional", "Promotional Offer"),
            ("other", "Other"),
        ],
        string="Program Type",
        default="other",
        required=True,
    )
    max_discount_pct = fields.Float(
        string="Maximum Discount (%)",
        digits="Discount",
        required=True,
        default=10.0,
        help="Discounts up to this percentage are allowed under the program. "
        "Anything above needs its own approval.",
    )
    approver_level = fields.Selection(
        selection=[
            ("manager", "Hotel Manager"),
            ("general_manager", "General Manager"),
        ],
        string="Authorized By",
        default="manager",
        required=True,
        help="Authorization level required to approve a discount of this "
        "program above the free threshold.",
    )
    active = fields.Boolean(string="Active", default=True)
    note = fields.Text(string="Notes")
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
        index=True,
    )

    _sql_constraints = [
        (
            "max_discount_positive",
            "check (max_discount_pct >= 0 and max_discount_pct <= 100)",
            "The maximum discount must be between 0 and 100 percent.",
        ),
    ]


class HotelDiscountApproval(models.Model):
    """Discount asked for a stay and the authorization behind it."""

    _name = "hotel.discount.approval"
    _description = "Hotel Discount Approval"
    _inherit = ["mail.thread", "mail.activity.mixin"]
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
        ondelete="restrict",
        tracking=True,
        index=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        related="reservation_id.company_id",
        store=True,
        index=True,
    )
    guest_id = fields.Many2one(
        comodel_name="res.partner",
        related="reservation_id.guest_id",
        string="Guest",
        store=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="reservation_id.currency_id",
        readonly=True,
    )
    rule_id = fields.Many2one(
        comodel_name="hotel.discount.rule",
        string="Discount Program",
        ondelete="restrict",
        help="Program or group contract the discount comes from.",
    )
    discount_pct = fields.Float(
        string="Discount (%)",
        digits="Discount",
        required=True,
        default=0.0,
        tracking=True,
    )
    approval_level = fields.Selection(
        selection=[
            ("none", "Automatic / Reception"),
            ("manager", "Hotel Manager"),
            ("general_manager", "General Manager"),
        ],
        string="Approval Level",
        compute="_compute_amounts",
        store=True,
        help="Authorization level required by the discount thresholds and "
        "by the program the discount belongs to.",
    )
    base_amount = fields.Monetary(
        string="Room Charge Before Discount",
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
    )
    discount_amount = fields.Monetary(
        string="Discount Amount",
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
    )
    reason = fields.Text(string="Reason", required=True)
    requested_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Requested By",
        default=lambda self: self.env.user,
        readonly=True,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("pending", "Waiting for Approval"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        string="Status",
        default="draft",
        required=True,
        index=True,
        tracking=True,
    )
    approver_id = fields.Many2one(
        comodel_name="res.users",
        string="Approved By",
        readonly=True,
        copy=False,
        tracking=True,
    )
    action_date = fields.Datetime(
        string="Approval Date", readonly=True, copy=False, tracking=True
    )
    applied = fields.Boolean(
        string="Applied",
        copy=False,
        help="Checked once the approved discount is written on the stay.",
    )

    _sql_constraints = [
        (
            "discount_pct_valid",
            "check (discount_pct >= 0 and discount_pct <= 100)",
            "The discount must be between 0 and 100 percent.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name") in (False, None, "New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "hotel.discount.approval"
                )
        return super().create(vals_list)

    @api.depends("reservation_id.rate", "reservation_id.nights", "discount_pct")
    def _compute_amounts(self):
        config = self.env["hotel.config"]
        for approval in self:
            reservation = approval.reservation_id
            base = (reservation.rate or 0.0) * (reservation.nights or 0.0)
            approval.base_amount = base
            approval.discount_amount = base * approval.discount_pct / 100.0
            approval.approval_level = config._discount_level(
                approval.discount_pct, approval.rule_id.approver_level
            )

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_submit(self):
        for approval in self:
            if approval.state != "draft":
                raise ValidationError(
                    _("Only draft discount requests can be submitted.")
                )
            if not approval.reason:
                raise ValidationError(
                    _("Explain the reason of the discount before submitting.")
                )
            approval.state = "pending"
        return True

    def action_approve(self):
        for approval in self:
            if approval.state != "pending":
                raise ValidationError(
                    _("Only pending discount requests can be approved.")
                )
            approval._check_approve_rights()
            approval._check_not_requester()
            approval.write(
                {
                    "state": "approved",
                    "approver_id": self.env.user,
                    "action_date": fields.Datetime.now(),
                }
            )
            approval.message_post(
                body=_(
                    "%(pct)s%% discount approved on %(reservation)s "
                    "(%(amount)s).",
                    pct=approval.discount_pct,
                    reservation=approval.reservation_id.name,
                    amount=approval.discount_amount,
                )
            )
        return True

    def action_reject(self):
        for approval in self:
            if approval.state != "pending":
                raise ValidationError(
                    _("Only pending discount requests can be rejected.")
                )
            approval._check_approve_rights()
            approval._check_not_requester()
            approval.write(
                {
                    "state": "rejected",
                    "approver_id": self.env.user,
                    "action_date": fields.Datetime.now(),
                    "applied": False,
                }
            )
        return True

    def action_reset(self):
        for approval in self:
            if approval.state not in ("draft", "rejected"):
                raise ValidationError(
                    _("Only draft or rejected discount requests can be reset.")
                )
            approval.write({"state": "draft", "approver_id": False})
        return True

    def _check_approve_rights(self):
        """The discount size and the program decide who signs."""
        self.ensure_one()
        if self.env.su or self.env.user.has_group("base.group_system"):
            return
        allowed = (
            DISCOUNT_GM_RIGHTS
            if self.approval_level == "general_manager"
            else DISCOUNT_APPROVE_RIGHTS
        )
        if any(self.env.user.has_group(xmlid) for xmlid in allowed):
            return
        if self.approval_level == "general_manager":
            raise UserError(
                _(
                    "A %(pct)s%% discount needs the general manager to "
                    "approve it.",
                    pct=self.discount_pct,
                )
            )
        raise UserError(
            _("Only the hotel manager or the general manager can approve "
              "this discount.")
        )

    def _check_not_requester(self):
        if self.env.su or self.env.user.has_group("base.group_system"):
            return
        if self.requested_by_id and self.requested_by_id == self.env.user:
            raise UserError(
                _("You cannot approve a discount you requested yourself.")
            )

    def action_open_reservation(self):
        self.ensure_one()
        return {
            "name": _("Reservation"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.reservation",
            "view_mode": "form",
            "res_id": self.reservation_id.id,
        }


class HotelReservation(models.Model):
    _inherit = "hotel.reservation"

    discount_approval_count = fields.Integer(
        string="Discount Requests",
        compute="_compute_discount_approval_count",
    )

    def _compute_discount_approval_count(self):
        approvals = dict(
            self.env["hotel.discount.approval"]._read_group(
                [("reservation_id", "in", self.ids)],
                groupby=["reservation_id"],
                aggregates=["__count"],
            )
        )
        for reservation in self:
            reservation.discount_approval_count = approvals.get(reservation, 0)

    def action_open_discount_approvals(self):
        self.ensure_one()
        return {
            "name": _("Discount Requests"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.discount.approval",
            "view_mode": "list,form",
            "domain": [("reservation_id", "=", self.id)],
            "context": {"default_reservation_id": self.id},
        }

    def write(self, vals):
        if "discount" in vals:
            for reservation in self:
                reservation._check_discount_approval(vals["discount"])
        return super().write(vals)

    def _check_discount_approval(self, discount):
        """A discount above the free threshold needs an approved document."""
        self.ensure_one()
        if float_compare(discount, 0.0, precision_digits=2) == 0:
            return True
        config = self.env["hotel.config"]
        if not config._hotel_require_discount_approval():
            return True
        if (
            config._discount_level(discount)
            == "none"
        ):
            return True
        approval = self.env["hotel.discount.approval"].search(
            [
                ("reservation_id", "=", self.id),
                ("state", "=", "approved"),
                ("discount_pct", ">=", discount),
            ],
            limit=1,
        )
        if not approval:
            raise UserError(
                _(
                    "A %(discount)s%% discount on %(reservation)s needs an "
                    "approved discount request. Ask for it from "
                    "Approvals > Discount Requests.",
                    discount=discount,
                    reservation=self.name,
                )
            )
        if not approval.applied:
            approval.sudo().write({"applied": True})
        return True
