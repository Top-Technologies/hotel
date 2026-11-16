from odoo import _, api, fields, models


class ResPartner(models.Model):
    """Guest profile integration: assets, deposits and claims of a guest."""

    _inherit = "res.partner"

    is_walkin = fields.Boolean(
        string="Book Guest",
        help="Checked when the guest was registered at the front desk "
        "without a prior reservation.",
    )
    is_guest = fields.Boolean(
        string="Hotel Guest",
        compute="_compute_is_guest",
        store=True,
        readonly=False,
        index=True,
        help="Checked automatically as soon as the contact is linked to a "
        "reservation or registered as a walk-in. Guests are shown in the "
        "hotel's Guests menu, plain contacts are not.",
    )
    reservation_ids = fields.One2many(
        comodel_name="hotel.reservation",
        inverse_name="guest_id",
        string="Reservations",
    )
    hotel_customer_type = fields.Selection(
        selection=[
            ("individual", "Individual"),
            ("corporate", "Corporate"),
        ],
        string="Customer Type",
        default="individual",
        help="Individual guests are people; corporate customers are "
        "companies whose representative stays at the hotel.",
    )
    gender = fields.Selection(
        selection=[
            ("male", "Male"),
            ("female", "Female"),
            ("other", "Other"),
        ],
        string="Gender",
    )
    birth_date = fields.Date(string="Date of Birth")
    nationality_id = fields.Many2one(
        comodel_name="res.country",
        string="Nationality",
        ondelete="restrict",
        help="Country of the guest's nationality, if different from "
        "the country of residence.",
    )
    property_count = fields.Integer(
        string="Guest Assets", compute="_compute_hotel_property_counts"
    )
    safe_deposit_count = fields.Integer(
        string="Safe Deposits", compute="_compute_hotel_property_counts"
    )
    lost_found_claim_count = fields.Integer(
        string="Lost & Found Claims", compute="_compute_hotel_property_counts"
    )
    reservation_count = fields.Integer(
        string="Hotel Stays", compute="_compute_reservation_count"
    )
    credit_approval_count = fields.Integer(
        string="Credit Requests", compute="_compute_credit_approval_count"
    )

    @api.depends("reservation_ids", "is_walkin")
    def _compute_is_guest(self):
        for partner in self:
            partner.is_guest = bool(partner.reservation_ids) or bool(
                partner.is_walkin
            )

    def _compute_credit_approval_count(self):
        approvals = dict(
            self.env["hotel.credit.approval"]._read_group(
                [("partner_id", "in", self.ids)],
                groupby=["partner_id"],
                aggregates=["__count"],
            )
        )
        for partner in self:
            partner.credit_approval_count = approvals.get(partner, 0)

    def action_open_credit_approvals(self):
        self.ensure_one()
        return {
            "name": _("Credit Requests"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.credit.approval",
            "view_mode": "list,form",
            "views": [[False, "list"], [False, "form"]],
            "domain": [("partner_id", "=", self.id)],
            "context": {"default_partner_id": self.id},
        }

    def _compute_reservation_count(self):
        stays = dict(
            self.env["hotel.reservation"]._read_group(
                [("guest_id", "in", self.ids)],
                groupby=["guest_id"],
                aggregates=["__count"],
            )
        )
        for partner in self:
            partner.reservation_count = stays.get(partner, 0)

    def action_open_reservations(self):
        self.ensure_one()
        return {
            "name": _("Stays"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.reservation",
            "view_mode": "list,form",
            "views": [[False, "list"], [False, "form"]],
            "domain": [("guest_id", "=", self.id)],
            "context": {"default_guest_id": self.id},
        }

    def _compute_hotel_property_counts(self):
        properties = dict(
            self.env["hotel.guest.property"]._read_group(
                [("guest_id", "in", self.ids)],
                groupby=["guest_id"],
                aggregates=["__count"],
            )
        )
        deposits = dict(
            self.env["hotel.safe.deposit"]._read_group(
                [("guest_id", "in", self.ids)],
                groupby=["guest_id"],
                aggregates=["__count"],
            )
        )
        claims = dict(
            self.env["hotel.lost.found"]._read_group(
                [("claimed_by_id", "in", self.ids)],
                groupby=["claimed_by_id"],
                aggregates=["__count"],
            )
        )
        previous = dict(
            self.env["hotel.lost.found"]._read_group(
                [("previous_guest_id", "in", self.ids)],
                groupby=["previous_guest_id"],
                aggregates=["__count"],
            )
        )
        for partner in self:
            partner.property_count = properties.get(partner, 0)
            partner.safe_deposit_count = deposits.get(partner, 0)
            partner.lost_found_claim_count = claims.get(
                partner, 0
            ) + previous.get(partner, 0)

    def action_open_properties(self):
        self.ensure_one()
        return {
            "name": _("Guest Assets"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.guest.property",
            "view_mode": "list,form",
            "views": [[False, "list"], [False, "form"]],
            "domain": [("guest_id", "=", self.id)],
            "context": {"default_guest_id": self.id},
        }

    def action_open_safe_deposits(self):
        self.ensure_one()
        return {
            "name": _("Safe Deposits"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.safe.deposit",
            "view_mode": "list,form",
            "views": [[False, "list"], [False, "form"]],
            "domain": [("guest_id", "=", self.id)],
            "context": {"default_guest_id": self.id},
        }

    def action_open_lost_found(self):
        self.ensure_one()
        return {
            "name": _("Lost & Found"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.lost.found",
            "view_mode": "list,form,kanban",
            "views": [[False, "list"], [False, "form"], [False, "kanban"]],
            "domain": [
                "|",
                ("claimed_by_id", "=", self.id),
                ("previous_guest_id", "=", self.id),
            ],
        }

    @api.model
    def action_open_walkin_wizard(self):
        """Open the front-desk Book Guest wizard (no selection required)."""
        return {
            "name": _("New Book Guest"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.walkin.wizard",
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
        }