from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    hotel_reservation_id = fields.Many2one(
        comodel_name="hotel.reservation",
        string="Reservation",
        copy=False,
        ondelete="set null",
        index=True,
        help="Guest folio this document was generated from.",
    )
