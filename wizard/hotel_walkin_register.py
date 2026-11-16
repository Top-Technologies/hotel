from odoo import _, fields, models
from odoo.exceptions import ValidationError


class HotelWalkinRegisterWizard(models.TransientModel):
    """Date range picker used to print the Book Register report."""

    _name = "hotel.walkin.register.wizard"
    _description = "Book Register Report"

    date_from = fields.Datetime(
        string="From",
        required=True,
        default=lambda self: fields.Datetime.to_string(
            fields.Datetime.now().replace(day=1, hour=0, minute=0, second=0)
        ),
    )
    date_to = fields.Datetime(
        string="To",
        required=True,
        default=lambda self: fields.Datetime.now(),
    )

    def action_print(self):
        self.ensure_one()
        if not self.date_to or not self.date_from:
            raise ValidationError(_("Choose a date range to print."))
        if self.date_to < self.date_from:
            raise ValidationError(
                _("The 'To' date must be later than the 'From' date.")
            )
        reservations = self.env["hotel.reservation"].search(
            [
                ("source", "=", "walkin"),
                ("checkin", ">=", self.date_from),
                ("checkin", "<=", self.date_to),
            ],
            order="checkin, id",
        )
        if not reservations:
            raise ValidationError(
                _("No walk-in reservations were registered in the selected period.")
            )
        return self.env.ref(
            "hotel.action_report_walkin_register"
        ).report_action(reservations)