from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SurveyUserInput(models.Model):
    """A guest survey response linked to the stay it rates.

    The survey itself (questions, answers, QR codes, scoring) stays in the
    standard Odoo Survey application; only the link to the hotel stay is a
    hotel concern.
    """

    _inherit = "survey.user_input"

    guest_id = fields.Many2one(
        comodel_name="res.partner",
        string="Guest",
        index=True,
        tracking=True,
        help="Guest the answers belong to.",
    )
    reservation_id = fields.Many2one(
        comodel_name="hotel.reservation",
        string="Reservation",
        index=True,
        tracking=True,
        help="Stay the answers refer to.",
    )
    room_id = fields.Many2one(
        comodel_name="hotel.room",
        related="reservation_id.room_id",
        store=True,
        index=True,
        string="Room",
    )
    checkin_date = fields.Datetime(
        related="reservation_id.actual_checkin",
        store=True,
        string="Check-in Date",
    )
    checkout_date = fields.Datetime(
        related="reservation_id.actual_checkout",
        store=True,
        string="Check-out Date",
    )
    service_type = fields.Selection(
        selection=[
            ("stay", "Overall Stay"),
            ("front_desk", "Front Desk"),
            ("room", "Room & Housekeeping"),
            ("restaurant", "Restaurant & Bar"),
            ("maintenance", "Maintenance"),
            ("other", "Other"),
        ],
        string="Service Type",
        index=True,
        tracking=True,
        help="Hotel service the guest is rating.",
    )
    rating = fields.Float(
        string="Rating",
        digits=(16, 1),
        tracking=True,
        help="Overall rating of the stay, from 0 (worst) to 5 (best).",
    )
    comments = fields.Text(string="Comments", tracking=True)

    _sql_constraints = [
        (
            "rating_within_five",
            "CHECK (rating >= 0 AND rating <= 5)",
            "A guest rating must be between 0 and 5.",
        ),
    ]

    @api.constrains("rating")
    def _check_rating(self):
        for user_input in self:
            if not 0.0 <= user_input.rating <= 5.0:
                raise ValidationError(
                    _("A guest rating must be between 0 and 5.")
                )

    # ------------------------------------------------------------------
    # linking a response to the stay
    # ------------------------------------------------------------------
    @api.model
    def _hotel_stay_of(self, partner):
        """The stay a response from ``partner`` belongs to.

        Only a stay that has already started is considered so that a response
        is never attached to a booking that has not happened yet.
        """
        if not partner:
            return self.env["hotel.reservation"]
        partner_id = partner.id if hasattr(partner, "id") else partner
        return self.env["hotel.reservation"].search(
            [
                ("guest_id", "=", partner_id),
                ("state", "in", ("checked_in", "checked_out")),
            ],
            order="actual_checkout desc, checkout desc",
            limit=1,
        )

    @api.model
    def _hotel_prepare_vals(self, vals):
        """Complete the hotel link of a response being created."""
        if vals.get("reservation_id"):
            reservation = self.env["hotel.reservation"].browse(
                vals["reservation_id"]
            )
            if reservation.exists() and not vals.get("guest_id"):
                vals["guest_id"] = reservation.guest_id.id
            return vals
        partner = vals.get("partner_id")
        if not partner:
            return vals
        reservation = self._hotel_stay_of(partner)
        if reservation:
            vals["reservation_id"] = reservation.id
            vals.setdefault("guest_id", reservation.guest_id.id)
        else:
            vals.setdefault("guest_id", partner)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._hotel_prepare_vals(vals)
        records = super().create(vals_list)
        records.mapped("reservation_id")._invalidate_stay_feedback()
        return records

    def write(self, vals):
        previous = (
            self.mapped("reservation_id")
            if "reservation_id" in vals or "partner_id" in vals
            else self.env["hotel.reservation"]
        )
        result = super().write(vals)
        if "reservation_id" in vals or "partner_id" in vals:
            for user_input in self:
                if user_input.reservation_id and not user_input.guest_id:
                    user_input.guest_id = user_input.reservation_id.guest_id
                elif user_input.partner_id and not user_input.reservation_id:
                    reservation = self._hotel_stay_of(user_input.partner_id)
                    if reservation:
                        user_input.reservation_id = reservation
        (previous | self.mapped("reservation_id"))._invalidate_stay_feedback()
        return result

    def unlink(self):
        reservations = self.mapped("reservation_id")
        result = super().unlink()
        reservations._invalidate_stay_feedback()
        return result

    @api.onchange("reservation_id")
    def _onchange_reservation_id(self):
        for user_input in self:
            if user_input.reservation_id:
                user_input.guest_id = user_input.reservation_id.guest_id

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        for user_input in self:
            if user_input.partner_id and not user_input.guest_id:
                user_input.guest_id = user_input.partner_id

    def action_open_stay(self):
        self.ensure_one()
        if not self.reservation_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Reservation"),
            "res_model": "hotel.reservation",
            "view_mode": "form",
            "res_id": self.reservation_id.id,
            "target": "current",
        }
