from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

RATE_STEP1_RIGHTS = (
    "hotel.group_hotel_manager",
    "hotel.group_finance_user",
    "hotel.group_general_manager",
)
RATE_STEP2_RIGHTS = (
    "hotel.group_finance_user",
    "hotel.group_general_manager",
)


class HotelRateChange(models.Model):
    """Request to change the published rate of a room type.

    The hotel manager reviews the request first, then hotel finance gives the
    final approval: only then the new rate lands on ``hotel.room.type.
    base_price``. The room type itself refuses direct rate edits while the
    approval setting is on.
    """

    _name = "hotel.rate.change"
    _description = "Room Rate Change"
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
    room_type_id = fields.Many2one(
        comodel_name="hotel.room.type",
        string="Room Type",
        required=True,
        ondelete="restrict",
        tracking=True,
        index=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        related="room_type_id.company_id",
        store=True,
        index=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="room_type_id.currency_id",
        readonly=True,
    )
    old_rate = fields.Monetary(
        string="Current Rate",
        currency_field="currency_id",
        readonly=True,
        tracking=True,
    )
    new_rate = fields.Monetary(
        string="New Rate",
        currency_field="currency_id",
        required=True,
        tracking=True,
    )
    difference = fields.Monetary(
        string="Difference",
        currency_field="currency_id",
        compute="_compute_change_pct",
        store=True,
    )
    change_pct = fields.Float(
        string="Change (%)",
        compute="_compute_change_pct",
        store=True,
    )
    effective_date = fields.Date(
        string="Effective Date",
        default=fields.Date.context_today,
        help="Date from which the approved rate applies.",
        tracking=True,
    )
    reason = fields.Text(string="Reason", required=True)
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
            ("pending", "Manager Review"),
            ("finance_review", "Finance Review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        string="Status",
        default="draft",
        required=True,
        index=True,
        tracking=True,
    )
    manager_approver_id = fields.Many2one(
        comodel_name="res.users",
        string="Reviewed By",
        readonly=True,
        copy=False,
        tracking=True,
    )
    approver_id = fields.Many2one(
        comodel_name="res.users",
        string="Approved By",
        readonly=True,
        copy=False,
        tracking=True,
    )
    approval_date = fields.Datetime(
        string="Approval Date", readonly=True, copy=False, tracking=True
    )

    _sql_constraints = [
        (
            "new_rate_positive",
            "check (new_rate >= 0)",
            "The new rate cannot be negative.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name") in (False, None, "New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "hotel.rate.change"
                )
            if not vals.get("old_rate") and vals.get("room_type_id"):
                room_type = self.env["hotel.room.type"].browse(
                    vals["room_type_id"]
                )
                vals["old_rate"] = room_type.base_price
        return super().create(vals_list)

    @api.depends("old_rate", "new_rate")
    def _compute_change_pct(self):
        for change in self:
            change.difference = change.new_rate - change.old_rate
            if float_compare(change.old_rate, 0.0, precision_digits=2) <= 0:
                change.change_pct = 0.0
                continue
            change.change_pct = (
                (change.new_rate - change.old_rate) / change.old_rate * 100.0
            )

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_submit(self):
        for change in self:
            if change.state != "draft":
                raise ValidationError(
                    _("Only draft rate changes can be submitted.")
                )
            if not change.reason:
                raise ValidationError(
                    _("Explain why the rate changes before submitting.")
                )
            change.state = "pending"
        return True

    def action_approve(self):
        for change in self:
            if change.state == "pending":
                change._check_approve_rights(RATE_STEP1_RIGHTS)
                change.write(
                    {
                        "state": "finance_review",
                        "manager_approver_id": self.env.user,
                    }
                )
            elif change.state == "finance_review":
                change._check_approve_rights(RATE_STEP2_RIGHTS)
                change.room_type_id.sudo().with_context(
                    rate_change_approved=True
                ).write({"base_price": change.new_rate})
                change.write(
                    {
                        "state": "approved",
                        "approver_id": self.env.user,
                        "approval_date": fields.Datetime.now(),
                        "effective_date": change.effective_date
                        or fields.Date.context_today(change),
                    }
                )
                change.message_post(
                    body=_(
                        "Rate approved: %(old)s -> %(new)s on %(room_type)s, "
                        "effective %(date)s.",
                        old=change.old_rate,
                        new=change.new_rate,
                        room_type=change.room_type_id.name,
                        date=change.effective_date,
                    )
                )
            else:
                raise ValidationError(
                    _("Only pending rate changes can be approved.")
                )
        return True

    def action_reject(self):
        for change in self:
            if change.state not in ("pending", "finance_review"):
                raise ValidationError(
                    _("Only pending rate changes can be rejected.")
                )
            change._check_approve_rights(RATE_STEP1_RIGHTS)
            change.write(
                {
                    "state": "rejected",
                    "approver_id": self.env.user,
                    "approval_date": fields.Datetime.now(),
                }
            )
        return True

    def action_reset(self):
        for change in self:
            if change.state not in ("draft", "rejected"):
                raise ValidationError(
                    _("Only draft or rejected rate changes can be reset.")
                )
            change.write(
                {"state": "draft", "approver_id": False, "manager_approver_id": False}
            )
        return True

    def _check_approve_rights(self, allowed_xmlids):
        """The requester never signs his own rate change."""
        if self.env.su or self.env.user.has_group("base.group_system"):
            return
        if self.requested_by_id and self.requested_by_id == self.env.user:
            raise UserError(
                _("You cannot approve a rate change you requested yourself.")
            )
        if any(
            self.env.user.has_group(xmlid) for xmlid in allowed_xmlids
        ):
            return
        if self.state == "pending":
            raise UserError(
                _("Only the hotel manager, hotel finance or the general "
                  "manager can review a rate change.")
            )
        raise UserError(
            _("Only hotel finance or the general manager can approve "
              "a rate change.")
        )

    def action_open_room_type(self):
        self.ensure_one()
        return {
            "name": self.room_type_id.display_name,
            "type": "ir.actions.act_window",
            "res_model": "hotel.room.type",
            "view_mode": "form",
            "res_id": self.room_type_id.id,
        }


class HotelRoomType(models.Model):
    _inherit = "hotel.room.type"

    def write(self, vals):
        if (
            "base_price" in vals
            and self._hotel_require_rate_approval()
            and not self.env.context.get("rate_change_approved")
        ):
            for room_type in self:
                if (
                    float_compare(
                        room_type.base_price,
                        vals["base_price"],
                        precision_digits=2,
                    )
                    != 0
                ):
                    raise UserError(
                        _(
                            "The rate of %(room_type)s can only be changed "
                            "through a Room Rate Change request that the "
                            "hotel manager and hotel finance approve.",
                            room_type=room_type.name,
                        )
                    )
        return super().write(vals)
