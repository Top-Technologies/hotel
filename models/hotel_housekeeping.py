from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HotelHousekeepingTask(models.Model):
    _name = "hotel.housekeeping.task"
    _description = "Hotel Housekeeping Task"
    _inherit = ["mail.thread", "mail.activity.mixin", "hotel.config"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Reference",
        required=True,
        default="New",
        readonly=True,
        copy=False,
        index=True,
    )
    room_id = fields.Many2one(
        comodel_name="hotel.room",
        string="Room",
        required=True,
        ondelete="cascade",
        tracking=True,
        index=True,
    )
    floor = fields.Integer(
        string="Floor", related="room_id.floor", store=True, index=True,
    )
    room_type_id = fields.Many2one(
        comodel_name="hotel.room.type",
        string="Room Type",
        related="room_id.room_type_id",
        store=True,
    )
    reservation_id = fields.Many2one(
        comodel_name="hotel.reservation",
        string="Reservation",
        ondelete="set null",
        index=True,
        help="Stay that requested the cleaning (set at check-out).",
    )
    employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Assigned To",
        tracking=True,
        index=True,
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        related="employee_id.user_id",
        string="Assigned User",
        store=False,
    )
    date = fields.Date(
        string="Date",
        default=fields.Date.context_today,
        required=True,
        index=True,
    )
    state = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("inspected", "Inspected"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="pending",
        required=True,
        index=True,
        tracking=True,
    )
    started_at = fields.Datetime(string="Started On", readonly=True, copy=False)
    ended_at = fields.Datetime(string="Ended On", readonly=True, copy=False)
    duration_minutes = fields.Float(
        string="Duration (min)",
        compute="_compute_duration",
        store=True,
        help="Cleaning time, used to report the average cleaning duration per "
        "employee.",
    )
    notes = fields.Text(string="Notes")
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
        index=True,
    )

    _sql_constraints = [
        (
            "duration_positive",
            "check (duration_minutes >= 0)",
            "Cleaning duration cannot be negative.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name") in (False, None, "New"):
                company_id = vals.get("company_id") or self.env.company.id
                vals["name"] = self.env["ir.sequence"].with_company(company_id).sudo().next_by_code(
                    "hotel.housekeeping.task",
                ) or _("New")
        tasks = super().create(vals_list)
        for task in tasks:
            room = task.room_id
            if room.status not in ("dirty", "cleaning", "out_of_service"):
                room._action_set_status(
                    "dirty", _("Cleaning requested (%s).") % task.name,
                )
        return tasks

    @api.depends("started_at", "ended_at")
    def _compute_duration(self):
        for task in self:
            if task.started_at and task.ended_at:
                task.duration_minutes = max(
                    0.0,
                    (task.ended_at - task.started_at).total_seconds() / 60.0,
                )
            else:
                task.duration_minutes = 0.0

    @api.model
    def _action_create_for_room(self, room, reservation=None, notes=None):
        """Create the cleaning task of a room and flag it as being cleaned."""
        return self.create(
            {
                "room_id": room.id,
                "reservation_id": reservation.id if reservation else False,
                "employee_id": self._hotel_housekeeping_employee().id,
                "date": fields.Date.context_today(self),
                "notes": notes,
            },
        )

    def action_start(self):
        for task in self:
            if task.state != "pending":
                raise ValidationError(
                    _("Only pending cleaning tasks can be started."),
                )
            if task.room_id.status == "out_of_service":
                raise ValidationError(
                    _("Room %s is out of service, it cannot be cleaned.")
                    % task.room_id.number,
                )
            task.write({"state": "in_progress", "started_at": fields.Datetime.now()})
            task.room_id._action_set_status("cleaning", _("Cleaning started."))
        return True

    def action_done(self):
        for task in self:
            if task.state not in ("pending", "in_progress"):
                raise ValidationError(
                    _("Only pending or running cleaning tasks can be completed."),
                )
            vals = {"state": "done", "ended_at": fields.Datetime.now()}
            if not task.started_at:
                vals["started_at"] = vals["ended_at"]
            task.write(vals)
            task.room_id._action_set_status(
                "clean",
                _("Cleaning completed, ready to sell.")
                if not self._hotel_require_inspection()
                else _("Cleaned, waiting for supervisor inspection."),
            )
        return True

    def action_inspect(self):
        if not (
            self.env.su
            or self.env.user.has_group("hotel.group_housekeeping_supervisor")
        ):
            raise UserError(
                _("Only a housekeeping supervisor can inspect a cleaned room."),
            )
        for task in self:
            if task.state != "done":
                raise ValidationError(
                    _("Only completed cleaning tasks can be inspected."),
                )
            task.write({"state": "inspected"})
            task.room_id._action_set_status(
                "inspected", _("Room inspected and ready to sell."),
            )
        return True

    def action_cancel(self):
        for task in self:
            if task.state in ("done", "inspected"):
                raise ValidationError(
                    _("Cleaning tasks that are already completed cannot be "
                      "cancelled."),
                )
            task.write({"state": "cancelled"})
        return True
