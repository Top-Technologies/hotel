from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

CREDIT_STEP1_RIGHTS = (
    "hotel.group_hotel_manager",
    "hotel.group_finance_user",
    "hotel.group_general_manager",
)
CREDIT_STEP2_RIGHTS = (
    "hotel.group_finance_user",
    "hotel.group_general_manager",
)


class HotelCreditApproval(models.Model):
    """Credit sale asked for a guest or corporate customer.

    The department (hotel manager) reviews it first, then hotel finance gives
    the final approval and raises ``res.partner.credit_limit``, which is
    enforced by the standard Odoo credit check when the folio is posted.
    """

    _name = "hotel.credit.approval"
    _description = "Hotel Credit Approval"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(
        string="Reference",
        required=True,
        default="New",
        readonly=True,
        copy=False,
        index=True,
        tracking=True,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Customer",
        required=True,
        ondelete="restrict",
        tracking=True,
        index=True,
    )
    reservation_id = fields.Many2one(
        comodel_name="hotel.reservation",
        string="Reservation",
        ondelete="set null",
        tracking=True,
        help="Stay the credit is asked for, when it is already known.",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        related="reservation_id.company_id",
        store=True,
        index=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="partner_id.currency_id",
        readonly=True,
    )
    current_limit = fields.Monetary(
        string="Current Credit Limit",
        currency_field="currency_id",
        compute="_compute_current_limit",
        store=True,
        readonly=True,
    )
    requested_amount = fields.Monetary(
        string="Requested Amount",
        currency_field="currency_id",
        help="Amount the customer wants to buy on credit.",
        tracking=True,
    )
    requested_limit = fields.Monetary(
        string="Requested Credit Limit",
        currency_field="currency_id",
        required=True,
        tracking=True,
    )
    payment_term_id = fields.Many2one(
        comodel_name="account.payment.term",
        string="Payment Terms",
        compute="_compute_current_limit",
        store=True,
        readonly=True,
    )
    supporting_document = fields.Binary(
        string="Supporting Document", attachment=True, copy=False
    )
    supporting_document_name = fields.Char(
        string="Document Name", copy=False
    )
    purpose = fields.Text(string="Purpose", required=True)
    reason = fields.Text(string="Reason")
    notes = fields.Text(string="Notes")
    requested_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Requested By",
        default=lambda self: self.env.user,
        readonly=True,
    )
    requested_date = fields.Datetime(
        string="Requested Date", related="create_date", readonly=True
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("pending", "Department Approval"),
            ("finance_review", "Finance Approval"),
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
    finance_approver_id = fields.Many2one(
        comodel_name="res.users",
        string="Finance Approver",
        readonly=True,
        copy=False,
        tracking=True,
    )
    approval_date = fields.Datetime(
        string="Approval Date", readonly=True, copy=False, tracking=True
    )
    applied = fields.Boolean(
        string="Applied",
        copy=False,
        help="Checked once the approved limit has been written on the "
        "customer.",
    )

    _sql_constraints = [
        (
            "limit_positive",
            "check (requested_limit >= 0)",
            "The credit limit cannot be negative.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name") in (False, None, "New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "hotel.credit.approval"
                )
        return super().create(vals_list)

    @api.depends("partner_id")
    def _compute_current_limit(self):
        for approval in self:
            if not approval.partner_id:
                approval.current_limit = 0.0
                approval.payment_term_id = False
                continue
            partner = approval.partner_id.sudo()
            approval.current_limit = partner.credit_limit
            approval.payment_term_id = partner.property_payment_term_id

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_submit(self):
        for approval in self:
            if approval.state != "draft":
                raise ValidationError(
                    _("Only draft credit requests can be submitted.")
                )
            if not approval.purpose:
                raise ValidationError(
                    _("Explain the purpose of the credit request before "
                      "submitting.")
                )
            approval.state = "pending"
        return True

    def action_approve(self):
        for approval in self:
            if approval.state == "pending":
                approval._check_approve_rights(CREDIT_STEP1_RIGHTS)
                approval._check_not_requester()
                approval.write(
                    {
                        "state": "finance_review",
                        "approver_id": self.env.user,
                    }
                )
            elif approval.state == "finance_review":
                approval._check_approve_rights(CREDIT_STEP2_RIGHTS)
                approval._check_not_requester()
                approval._validate_amounts()
                approval.partner_id.sudo().write(
                    {"credit_limit": approval.requested_limit}
                )
                approval.write(
                    {
                        "state": "approved",
                        "finance_approver_id": self.env.user,
                        "approval_date": fields.Datetime.now(),
                        "applied": True,
                    }
                )
                approval.message_post(
                    body=_(
                        "Credit limit of %(partner)s raised to %(limit)s "
                        "(was %(previous)s).",
                        partner=approval.partner_id.name,
                        limit=approval.requested_limit,
                        previous=approval.current_limit,
                    )
                )
            else:
                raise ValidationError(
                    _("Only pending credit requests can be approved.")
                )
        return True

    def action_reject(self):
        for approval in self:
            if approval.state not in ("pending", "finance_review"):
                raise ValidationError(
                    _("Only pending credit requests can be rejected.")
                )
            approval._check_approve_rights(CREDIT_STEP1_RIGHTS)
            approval._check_not_requester()
            approval.write(
                {
                    "state": "rejected",
                    "approver_id": self.env.user,
                    "approval_date": fields.Datetime.now(),
                    "applied": False,
                }
            )
        return True

    def action_reset(self):
        for approval in self:
            if approval.state not in ("draft", "rejected"):
                raise ValidationError(
                    _("Only draft or rejected credit requests can be reset.")
                )
            approval.write(
                {
                    "state": "draft",
                    "approver_id": False,
                    "finance_approver_id": False,
                }
            )
        return True

    def _validate_amounts(self):
        """The approved limit must cover the credit that is asked for."""
        self.ensure_one()
        if (
            self.requested_amount
            and self.requested_amount > self.requested_limit
        ):
            raise UserError(
                _(
                    "The requested amount (%(amount)s) exceeds the credit "
                    "limit (%(limit)s) asked in this request.",
                    amount=self.requested_amount,
                    limit=self.requested_limit,
                )
            )

    def _check_approve_rights(self, allowed_xmlids):
        if self.env.su or self.env.user.has_group("base.group_system"):
            return
        if any(
            self.env.user.has_group(xmlid) for xmlid in allowed_xmlids
        ):
            return
        if self.state == "pending":
            raise UserError(
                _("Only the hotel manager, hotel finance or the general "
                  "manager can review a credit request.")
            )
        raise UserError(
            _("Only hotel finance or the general manager can approve "
              "a credit request.")
        )

    def _check_not_requester(self):
        if self.env.su or self.env.user.has_group("base.group_system"):
            return
        if self.requested_by_id and self.requested_by_id == self.env.user:
            raise UserError(
                _("You cannot approve a credit request you raised yourself.")
            )

    def action_open_partner(self):
        self.ensure_one()
        return {
            "name": self.partner_id.display_name,
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "view_mode": "form",
            "res_id": self.partner_id.id,
        }

    def action_open_reservation(self):
        self.ensure_one()
        return {
            "name": _("Reservation"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.reservation",
            "view_mode": "form",
            "res_id": self.reservation_id.id,
        }
