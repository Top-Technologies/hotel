from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

STATUS_TRANSITIONS = {
    "available": ("reserved", "occupied", "dirty", "clean", "inspected", "out_of_service"),
    "reserved": ("occupied", "available", "dirty", "out_of_service"),
    "occupied": ("dirty", "out_of_service"),
    "dirty": ("cleaning", "clean", "out_of_service"),
    "cleaning": ("dirty", "clean", "out_of_service"),
    "clean": ("inspected", "dirty", "reserved", "occupied", "out_of_service"),
    "inspected": ("reserved", "occupied", "dirty", "out_of_service"),
    "out_of_service": ("dirty", "available", "clean", "occupied"),
}

READY_STATUSES = ("clean", "inspected")

SELLABLE_STATUSES = ("available", "reserved", "clean", "inspected")


class HotelRoom(models.Model):
    _name = "hotel.room"
    _description = "Hotel Room"
    _inherit = ["mail.thread", "hotel.config"]
    _order = "sequence, number, id"

    name = fields.Char(
        string="Room Name",
        compute="_compute_name",
        store=True,
        readonly=False,
        precompute=True,
        required=True,
        copy=False,
    )
    number = fields.Char(string="Room Number", required=True, copy=False)
    sequence = fields.Integer(string="Sequence", default=10)
    active = fields.Boolean(string="Active", default=True)
    floor = fields.Integer(string="Floor", default=1)
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
    capacity = fields.Integer(
        string="Capacity",
        compute="_compute_capacity",
        store=True,
        readonly=False,
        precompute=True,
        help="Defaults to the capacity of the room type.",
    )
    amenity_ids = fields.Many2many(
        comodel_name="hotel.amenity",
        string="Amenities",
        help="Copied from the room type when the room has none of its own.",
    )
    status = fields.Selection(
        selection=[
            ("available", "Available"),
            ("reserved", "Reserved"),
            ("occupied", "Occupied"),
            ("dirty", "Dirty"),
            ("cleaning", "Cleaning"),
            ("clean", "Clean"),
            ("inspected", "Inspected"),
            ("out_of_service", "Out of Service"),
        ],
        string="Status",
        default="available",
        required=True,
        index=True,
        tracking=True,
    )
    reservation_ids = fields.One2many(
        comodel_name="hotel.reservation",
        inverse_name="room_id",
        string="Reservations",
    )
    status_changed_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Status Changed By",
        readonly=True,
        copy=False,
    )
    status_changed_at = fields.Datetime(
        string="Status Changed On",
        readonly=True,
        copy=False,
    )
    base_price = fields.Monetary(
        string="Standard Rate",
        related="room_type_id.base_price",
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="room_type_id.currency_id",
        readonly=True,
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        related="room_type_id.product_id",
        store=True,
        readonly=True,
    )
    is_sellable = fields.Boolean(
        string="Ready to Sell",
        compute="_compute_is_sellable",
        help="Clean (or inspected) rooms are the only ones reception may assign.",
    )
    stay_count = fields.Integer(string="Stays", compute="_compute_stay_count")
    cleaning_count = fields.Integer(string="Cleanings", compute="_compute_cleaning_count")
    maintenance_count = fields.Integer(
        string="Maintenance Requests", compute="_compute_maintenance_count",
    )
    room_consumption_ids = fields.One2many(
        comodel_name="hotel.room.consumption",
        inverse_name="room_id",
        string="Room Consumptions",
    )
    room_consumption_count = fields.Integer(
        string="Consumption Records",
        compute="_compute_room_consumption_count",
    )
    note = fields.Text(string="Notes")

    _sql_constraints = [
        (
            "number_unique",
            "unique(number, company_id)",
            "Room numbers must be unique per company.",
        ),
        (
            "capacity_positive",
            "check (capacity >= 0)",
            "Room capacity cannot be negative.",
        ),
    ]

    @api.depends("number", "room_type_id.name")
    def _compute_name(self):
        for room in self:
            if not room.name:
                room.name = " - ".join(
                    part for part in (room.number, room.room_type_id.name) if part
                )

    @api.depends("room_type_id.capacity")
    def _compute_capacity(self):
        for room in self:
            if not room.capacity:
                room.capacity = room.room_type_id.capacity

    @api.onchange("room_type_id")
    def _onchange_room_type_id(self):
        for room in self:
            if not room.capacity:
                room.capacity = room.room_type_id.capacity
            if room.room_type_id.amenity_ids and not room.amenity_ids:
                room.amenity_ids = room.room_type_id.amenity_ids

    @api.depends("status")
    def _compute_is_sellable(self):
        sellable = (
            ("inspected",) if self._hotel_require_inspection() else SELLABLE_STATUSES
        )
        for room in self:
            room.is_sellable = room.status in sellable

    def _compute_stay_count(self):
        reservation_model = self.env["hotel.reservation"]
        for room in self:
            room.stay_count = reservation_model.search_count(
                [("room_id", "=", room.id), ("state", "not in", ("draft", "cancelled", "no_show"))],
            )

    def _compute_cleaning_count(self):
        housekeeping_model = self.env["hotel.housekeeping.task"]
        for room in self:
            room.cleaning_count = housekeeping_model.search_count(
                [("room_id", "=", room.id)],
            )

    def _compute_maintenance_count(self):
        for room in self:
            room.maintenance_count = self.env["maintenance.request"].search_count(
                [("room_id", "=", room.id)],
            )

    def _effective_consumables(self):
        """Configured consumables of the room, room overrides first."""
        self.ensure_one()
        return self.env["hotel.room.consumable"]._for_room(self)

    def _hotel_turnover_policy(self):
        """Effective turnover policy: room type override or hotel default."""
        self.ensure_one()
        return (
            self.room_type_id.turnover_policy
            or self._hotel_turnover_policy_default()
        )

    def write(self, vals):
        if "status" in vals and not self.env.context.get("hotel_status_transition"):
            raise UserError(
                _(
                    "The room status is driven by the hotel flow (check-in, "
                    "check-out, housekeeping, maintenance) and cannot be edited "
                    "directly. Use the buttons on the room or the reservation.",
                ),
            )
        return super().write(vals)

    def _action_set_status(self, status, reason=None, force=False):
        """Move rooms to ``status``, enforcing the room status flow.

        Pass ``force=True`` for stay lifecycle sync (check-in / check-out /
        cancel) when the room is stuck on an unexpected housekeeping status
        and must still follow the reservation.
        """
        for room in self:
            if room.status == status:
                continue
            allowed = STATUS_TRANSITIONS.get(room.status, ())
            if status not in allowed and not force:
                raise ValidationError(
                    _("Room %s cannot move from %s to %s.")
                    % (room.number, room.status, status),
                )
            previous = room.status
            forced = force and status not in allowed
            room.with_context(hotel_status_transition=True).write(
                {
                    "status": status,
                    "status_changed_by_id": self.env.user.id,
                    "status_changed_at": fields.Datetime.now(),
                },
            )
            body = reason
            if forced:
                body = _(
                    "%(reason)s (status synchronized from %(previous)s to %(to)s).",
                    reason=reason or _("Room status updated."),
                    previous=previous,
                    to=status,
                )
            if body:
                room.message_post(body=body)
        return True

    def _sync_status_for_stay(self, status, reason=None):
        """Set room status for a reservation lifecycle event (always succeeds)."""
        return self._action_set_status(status, reason=reason, force=True)

    def action_open_reservations(self):
        self.ensure_one()
        return {
            "name": _("Reservations"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.reservation",
            "view_mode": "list,form",
            "views": [[False, "list"], [False, "form"]],
            "domain": [("room_id", "=", self.id)],
            "context": {"default_room_id": self.id, "default_room_type_id": self.room_type_id.id},
        }

    def action_request_cleaning(self):
        """Raise a cleaning request for the room (front desk / housekeeping).

        Creating the task only flags the room as dirty; the room becomes
        clean when housekeeping completes the task, never on creation.
        """
        self.ensure_one()
        task = self.env["hotel.housekeeping.task"].create(
            {
                "room_id": self.id,
                "employee_id": False,
                "date": fields.Date.context_today(self),
                "notes": _("Cleaning requested from the room."),
            },
        )
        return {
            "name": _("Cleaning Task"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.housekeeping.task",
            "res_id": task.id,
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "current",
        }

    def action_open_maintenance(self):
        self.ensure_one()
        return {
            "name": _("Maintenance Requests"),
            "type": "ir.actions.act_window",
            "res_model": "maintenance.request",
            "view_mode": "list,kanban,form",
            "domain": [("room_id", "=", self.id)],
            "context": {
                "default_room_id": self.id,
                "search_default_todo": 1,
                "default_maintenance_type": "corrective",
            },
        }

    def action_request_maintenance(self):
        self.ensure_one()
        return {
            "name": _("New Maintenance Request"),
            "type": "ir.actions.act_window",
            "res_model": "maintenance.request",
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "current",
            "context": {
                "default_room_id": self.id,
                "default_name": _("Maintenance: Room %s") % self.number,
                "default_maintenance_type": "corrective",
            },
        }

    def action_open_housekeeping(self):
        self.ensure_one()
        return {
            "name": _("Housekeeping Tasks"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.housekeeping.task",
            "view_mode": "list,kanban,form",
            "domain": [("room_id", "=", self.id)],
            "context": {
                "default_room_id": self.id,
            },
        }

    def _compute_room_consumption_count(self):
        for room in self:
            room.room_consumption_count = len(room.room_consumption_ids)

    def action_open_room_consumptions(self):
        self.ensure_one()
        return {
            "name": _("Room Consumption - %s", self.name),
            "type": "ir.actions.act_window",
            "res_model": "hotel.room.consumption",
            "view_mode": "list,form,pivot",
            "domain": [("room_id", "=", self.id)],
            "context": {"default_room_id": self.id},
        }

    def action_set_out_of_service(self):
        for room in self:
            room._action_set_status(
                "out_of_service",
                _("Room taken out of service by %s.") % self.env.user.name,
            )
        return True

    def action_return_to_service(self):
        for room in self:
            if room.status != "out_of_service":
                raise UserError(_("Only out-of-service rooms can be returned to service."))
            open_requests = self.env["maintenance.request"].search_count([
                ("room_id", "=", room.id),
                ("stage_id.done", "=", False),
                ("archive", "=", False),
            ])
            if open_requests > 0:
                raise UserError(
                    _("Cannot return room %s to service: %d open maintenance request(s) exist.")
                    % (room.number, open_requests),
                )
            active_reservation = self.env["hotel.reservation"].search([
                ("room_id", "=", room.id),
                ("state", "=", "checked_in"),
            ], limit=1)
            if active_reservation:
                room._action_set_status(
                    "occupied",
                    _("Returned to service by %s (guest in-house).") % self.env.user.name,
                )
            else:
                room._action_set_status(
                    "dirty",
                    _("Returned to service by %s, awaiting cleaning.") % self.env.user.name,
                )
                self.env["hotel.housekeeping.task"]._action_create_for_room(
                    room, notes=_("Cleaning required after returning to service."),
                )
        return True


