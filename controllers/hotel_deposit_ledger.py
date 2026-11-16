import io
import json

import xlsxwriter

from odoo import http
from odoo.http import request


class HotelDepositLedgerController(http.Controller):
    @http.route("/hotel/deposit_ledger/xlsx", type="http", auth="user")
    def deposit_ledger_xlsx(self, options="{}", **kw):
        data = request.env["hotel.deposit.ledger"].get_report_data(
            json.loads(options) if isinstance(options, str) else options
        )
        buf = io.BytesIO()
        wb = xlsxwriter.Workbook(buf, {"in_memory": True})
        ws = wb.add_worksheet("Deposit Ledger")
        bold = wb.add_format({"bold": True})
        money = wb.add_format({"num_format": "#,##0.00"})
        date_fmt = wb.add_format({"num_format": "yyyy-mm-dd"})

        ws.write(0, 0, data["company"], bold)
        headers = [
            "Guest", "Booking", "Status", "Arrival", "Nights", "Stay value",
            "Deposit held", "Still to pay", "Paid by",
        ]
        for col, h in enumerate(headers):
            ws.write(2, col, h, bold)
        row = 3
        for group in data["groups"]:
            ws.write(row, 0, "%s (%d)" % (group["label"], group["count"]), bold)
            ws.write(row, 5, group["stay_value"], money)
            ws.write(row, 6, group["deposit_held"], money)
            ws.write(row, 7, group["still_to_pay"], money)
            row += 1
            for r in group["rows"]:
                ws.write(row, 0, r["guest"])
                ws.write(row, 1, r["booking"])
                ws.write(row, 2, r["status"])
                arrival = r["arrival"]
                if hasattr(arrival, "isoformat"):
                    ws.write(row, 3, arrival.isoformat(), date_fmt)
                else:
                    ws.write(row, 3, arrival)
                ws.write(row, 4, r["nights"])
                ws.write(row, 5, r["stay_value"], money)
                ws.write(row, 6, r["deposit_held"], money)
                ws.write(row, 7, r["still_to_pay"], money)
                ws.write(row, 8, r["paid_by"])
                row += 1
        ws.write(row, 0, "Total", bold)
        ws.write(row, 5, data["totals"]["stay_value"], money)
        ws.write(row, 6, data["totals"]["deposit_held"], money)
        ws.write(row, 7, data["totals"]["still_to_pay"], money)
        ws.set_column(0, 0, 28)
        ws.set_column(1, 8, 16)
        wb.close()
        return request.make_response(
            buf.getvalue(),
            headers=[
                (
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
                ("Content-Disposition", "attachment; filename=deposit_ledger.xlsx"),
            ],
        )
