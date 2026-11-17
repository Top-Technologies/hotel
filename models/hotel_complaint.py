from datetime import datetime, time

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HotelComplaint(models.Model):
    _name = "hotel.complaint"
    _description = "Guest Complaint"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "reported_date desc, id desc"

    name = fields.Char(
        string="Reference",
        required=True,
        default="New",
        readonly=True,
        copy=False,
        index=True,
    )
    guest_id = fields.Many2one(
        comodel_name="res.partner",
        string="Guest",
        ondelete="set null",
        index=True,
    )
    reservation_id = fields.Many2one(
        comodel_name="hotel.reservation",
        string="Reservation",
        ondelete="set null",
        index=True,
    )
    room_id = fields.Many2one(
        comodel_name="hotel.room",
        string="Room",
        ondelete="set null",
        index=True,
    )
    floor = fields.Integer(
        string="Floor", related="room_id.floor", store=True, index=True
    )
    category = fields.Selection(
        selection=[
            ("cleanliness", "Cleanliness"),
            ("noise", "Noise"),
            ("staff", "Staff"),
            ("food", "Food"),
            ("billing", "Billing"),
            ("maintenance", "Maintenance"),
            ("other", "Other"),
        ],
        string="Category",
        required=True,
        default="cleanliness",
        index=True,
    )
    priority = fields.Selection(
        selection=[
            ("low", "Low"),
            ("medium", "Medium"),
            ("high", "High"),
            ("critical", "Critical"),
        ],
        string="Priority",
        default="medium",
        required=True,
        index=True,
    )
    description = fields.Text(string="Complaint", required=True)
    action_taken = fields.Text(string="Action Taken")
    employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Responsible",
        tracking=True,
        index=True,
    )
    state = fields.Selection(
        selection=[
            ("new", "New"),
            ("in_progress", "In Progress"),
            ("resolved", "Resolved"),
            ("closed", "Closed"),
        ],
        string="Status",
        default="new",
        required=True,
        index=True,
        tracking=True,
    )
    reported_date = fields.Date(
        string="Reported On",
        default=lambda self: fields.Date.context_today(self),
        required=True,
        index=True,
    )
    reported_month = fields.Char(
        string="Month", compute="_compute_reported_month", store=True
    )
    resolved_date = fields.Datetime(string="Resolved On", readonly=True, copy=False)
    resolution_hours = fields.Float(
        string="Resolution (h)",
        compute="_compute_resolution_hours",
        store=True,
        help="Time between the report and the resolution.",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
        index=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name") in (False, None, "New"):
                company_id = vals.get("company_id") or self.env.company.id
                vals["name"] = self.env["ir.sequence"].with_company(company_id).sudo().next_by_code(
                    "hotel.complaint"
                ) or _("New")
        return super().create(vals_list)

    @api.depends("reported_date")
    def _compute_reported_month(self):
        for complaint in self:
            complaint.reported_month = (
                complaint.reported_date.strftime("%Y-%m")
                if complaint.reported_date
                else False
            )

    @api.depends("reported_date", "resolved_date")
    def _compute_resolution_hours(self):
        for complaint in self:
            if complaint.reported_date and complaint.resolved_date:
                start = datetime.combine(complaint.reported_date, time.min)
                complaint.resolution_hours = max(
                    0.0,
                    (complaint.resolved_date - start).total_seconds() / 3600.0,
                )
            else:
                complaint.resolution_hours = 0.0

    @api.onchange("reservation_id")
    def _onchange_reservation_id(self):
        for complaint in self:
            if complaint.reservation_id:
                complaint.guest_id = complaint.reservation_id.guest_id
                complaint.room_id = complaint.reservation_id.room_id

    def action_start(self):
        for complaint in self:
            if complaint.state != "new":
                raise ValidationError(
                    _("Only new complaints can be put in progress.")
                )
        self.write({"state": "in_progress"})
        return True

    def action_resolve(self):
        for complaint in self:
            if complaint.state not in ("new", "in_progress"):
                raise ValidationError(
                    _("Only new or in-progress complaints can be resolved.")
                )
            if not complaint.action_taken:
                raise ValidationError(
                    _("Record the action taken before resolving complaint %s.")
                    % complaint.name
                )
        self.write({"state": "resolved", "resolved_date": fields.Datetime.now()})
        return True

    def action_close(self):
        for complaint in self:
            if complaint.state != "resolved":
                raise ValidationError(
                    _("Only resolved complaints can be closed.")
                )
        self.write({"state": "closed"})
        return True

    def action_reopen(self):
        for complaint in self:
            if complaint.state not in ("resolved", "closed"):
                raise ValidationError(
                    _("Only resolved or closed complaints can be reopened.")
                )
        self.write({"state": "in_progress", "resolved_date": False})
        return True
