from odoo import fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    hotel_reservation_id = fields.Many2one(
        comodel_name="hotel.reservation",
        string="Reservation",
        copy=False,
        ondelete="set null",
        index=True,
        help="Guest stay this payment is an advance or settlement for.",
    )

    hotel_deposit_channel = fields.Selection(
        selection=[("desk", "Desk"), ("online", "Online")],
        string="Deposit Channel",
        default="desk",
        copy=False,
        help="Where the advance was taken. Shown as 'Paid by' on the Deposit Ledger.",
    )
