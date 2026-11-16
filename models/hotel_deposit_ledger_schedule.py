from odoo import _, api, fields, models


class HotelDepositLedgerSchedule(models.Model):
    _name = "hotel.deposit.ledger.schedule"
    _description = "Scheduled Deposit Ledger"
    _inherit = ["mail.thread"]

    name = fields.Char(required=True)
    frequency = fields.Selection(
        [("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly")],
        default="weekly", required=True,
    )
    weekday = fields.Selection(
        [("0", "Monday"), ("1", "Tuesday"), ("2", "Wednesday"), ("3", "Thursday"),
         ("4", "Friday"), ("5", "Saturday"), ("6", "Sunday")],
        default="0",
    )
    recipient_ids = fields.Many2many("res.partner", string="Recipients")
    format = fields.Selection(
        [("pdf", "PDF"), ("xlsx", "Excel"), ("both", "Both")],
        default="pdf", required=True,
    )
    options_json = fields.Text(default="{}")
    last_sent = fields.Datetime(readonly=True, copy=False)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, required=True, index=True
    )

    def _is_due(self, now):
        self.ensure_one()
        if not self.last_sent:
            return True
        delta = now - self.last_sent
        if self.frequency == "daily":
            return delta.days >= 1
        if self.frequency == "weekly":
            return delta.days >= 7 and str(now.weekday()) == self.weekday
        if self.frequency == "monthly":
            return (now.year, now.month) != (
                self.last_sent.year, self.last_sent.month
            )
        return False

    @api.model
    def _cron_send_due(self):
        now = fields.Datetime.now()
        for schedule in self.search([("active", "=", True)]):
            if schedule._is_due(now):
                schedule.action_send()

    def action_send(self):
        import json

        self.ensure_one()
        options = {}
        try:
            options = json.loads(self.options_json or "{}")
        except Exception:
            options = {}
        data = self.env["hotel.deposit.ledger"].get_report_data(options)
        attachments = []
        if self.format in ("pdf", "both"):
            content, _ = self.env["ir.actions.report"]._render_qweb_pdf(
                "hotel.report_deposit_ledger", [],
                data={"options": options},
            )
            att = self.env["ir.attachment"].create(
                {
                    "name": "Deposit_Ledger.pdf",
                    "type": "binary",
                    "datas": __import__("base64").b64encode(content).decode("ascii"),
                    "res_model": self._name,
                    "res_id": self.id,
                    "mimetype": "application/pdf",
                }
            )
            attachments.append(att.id)
        if self.format in ("xlsx", "both"):
            try:
                import io
                import json
                import xlsxwriter
                import base64

                data_rep = self.env["hotel.deposit.ledger"].get_report_data(options)
                buf = io.BytesIO()
                wb = xlsxwriter.Workbook(buf, {"in_memory": True})
                ws = wb.add_worksheet("Deposit Ledger")
                bold = wb.add_format({"bold": True})
                money = wb.add_format({"num_format": "#,##0.00"})
                date_fmt = wb.add_format({"num_format": "yyyy-mm-dd"})
                ws.write(0, 0, data_rep["company"], bold)
                headers = [
                    "Guest", "Booking", "Arrival", "Nights", "Stay value",
                    "Deposit held", "Still to pay", "Paid by",
                ]
                for col, h in enumerate(headers):
                    ws.write(2, col, h, bold)
                row = 3
                for group in data_rep["groups"]:
                    ws.write(row, 0, "%s (%d)" % (group["label"], group["count"]), bold)
                    ws.write(row, 4, group["stay_value"], money)
                    ws.write(row, 5, group["deposit_held"], money)
                    ws.write(row, 6, group["still_to_pay"], money)
                    row += 1
                    for r in group["rows"]:
                        ws.write(row, 0, r["guest"])
                        ws.write(row, 1, r["booking"])
                        arrival = r["arrival"]
                        if hasattr(arrival, "isoformat"):
                            ws.write(row, 2, arrival.isoformat(), date_fmt)
                        else:
                            ws.write(row, 2, arrival)
                        ws.write(row, 3, r["nights"])
                        ws.write(row, 4, r["stay_value"], money)
                        ws.write(row, 5, r["deposit_held"], money)
                        ws.write(row, 6, r["still_to_pay"], money)
                        ws.write(row, 7, r["paid_by"])
                        row += 1
                ws.write(row, 0, "Total", bold)
                ws.write(row, 4, data_rep["totals"]["stay_value"], money)
                ws.write(row, 5, data_rep["totals"]["deposit_held"], money)
                ws.write(row, 6, data_rep["totals"]["still_to_pay"], money)
                ws.set_column(0, 0, 28)
                ws.set_column(1, 7, 16)
                wb.close()
                att_xls = self.env["ir.attachment"].create(
                    {
                        "name": "Deposit_Ledger.xlsx",
                        "type": "binary",
                        "datas": base64.b64encode(buf.getvalue()).decode("ascii"),
                        "res_model": self._name,
                        "res_id": self.id,
                        "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    }
                )
                attachments.append(att_xls.id)
            except Exception:
                pass
        template = self.env.ref(
            "hotel.mail_template_deposit_ledger", raise_if_not_found=False
        )
        mail = None
        if template:
            mail = template.send_mail(self.id, force_send=True, email_values={"attachment_ids": [(6, 0, attachments)]} if attachments else None)
        self.last_sent = fields.Datetime.now()
        return mail
