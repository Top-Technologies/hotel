from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# States in which the hotel physically holds the item.
HELD_STATES = ("received", "stored", "ready_return")
# States that end the lifecycle of the record.
CLOSED_STATES = ("returned", "cancelled")


class HotelGuestProperty(models.Model):
    """Items brought to the hotel by a guest (laptops, jewellery, documents...)."""

    _name = "hotel.guest.property"
    _description = "Guest Property"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "received_date desc, id desc"

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
        required=True,
        ondelete="restrict",
        tracking=True,
        index=True,
    )
    reservation_id = fields.Many2one(
        comodel_name="hotel.reservation",
        string="Reservation",
        ondelete="set null",
        tracking=True,
        index=True,
        help="Stay during which the item was handed to the hotel.",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        related="reservation_id.company_id",
        store=True,
        index=True,
    )
    room_id = fields.Many2one(
        comodel_name="hotel.room",
        string="Room",
        ondelete="set null",
        tracking=True,
        index=True,
    )
    category_id = fields.Many2one(
        comodel_name="hotel.property.category",
        string="Category",
        required=True,
        ondelete="restrict",
        tracking=True,
        index=True,
    )
    description = fields.Char(required=True, tracking=True)
    serial_number = fields.Char(string="Serial / Identification No.")
    quantity = fields.Float(default=1.0)
    condition = fields.Selection(
        selection=[
            ("new", "New"),
            ("good", "Good"),
            ("fair", "Fair"),
            ("damaged", "Damaged"),
            ("broken", "Broken"),
        ],
        string="Condition",
        default="good",
        required=True,
        tracking=True,
    )
    ownership = fields.Selection(
        selection=[("guest", "Guest"), ("hotel", "Hotel")],
        string="Ownership",
        default="guest",
        required=True,
        tracking=True,
    )
    current_location_id = fields.Many2one(
        comodel_name="hotel.storage.location",
        string="Current Storage Location",
        ondelete="restrict",
        tracking=True,
        index=True,
    )
    state = fields.Selection(
        selection=[
            ("guest_possession", "With Guest"),
            ("deposit_requested", "Deposit Requested"),
            ("received", "Received"),
            ("stored", "In Safe"),
            ("ready_return", "Ready for Return"),
            ("returned", "Returned to Guest"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="guest_possession",
        required=True,
        tracking=True,
        index=True,
    )
    received_date = fields.Datetime(tracking=True)
    received_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Received By",
        default=lambda self: self.env.user,
        tracking=True,
    )
    expected_return_date = fields.Date(
        tracking=True,
        help="Date on which the guest expects the item back.",
    )
    is_return_due_today = fields.Boolean(
        string="Return Due Today",
        compute="_compute_return_flags",
        search="_search_return_due_today",
    )
    is_return_overdue = fields.Boolean(
        string="Return Overdue",
        compute="_compute_return_flags",
        search="_search_return_overdue",
    )
    returned_date = fields.Datetime(tracking=True)
    returned_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Returned By",
        tracking=True,
    )
    returned_to = fields.Char(
        string="Returned To",
        tracking=True,
        help="Name of the person who received the item back.",
    )
    notes = fields.Text()
    custody_ids = fields.One2many(
        comodel_name="hotel.property.custody",
        inverse_name="property_id",
        string="Custody Records",
        copy=False,
    )
    custody_count = fields.Integer(compute="_compute_custody_count")
    deposit_ids = fields.One2many(
        comodel_name="hotel.safe.deposit",
        inverse_name="property_id",
        string="Safe Deposits",
        copy=False,
    )
    deposit_count = fields.Integer(compute="_compute_deposit_count")
    color_index = fields.Integer(compute="_compute_color_index")

    _sql_constraints = [
        (
            "name_unique",
            "unique(name)",
            "Guest property references must be unique.",
        ),
        (
            "quantity_positive",
            "check (quantity > 0)",
            "Property quantity must be strictly positive.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name") in (False, None, "New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "hotel.guest.property"
                )
            if not vals.get("guest_id"):
                raise ValidationError(
                    _("A guest property must always be linked to a guest.")
                )
            if not vals.get("description"):
                raise ValidationError(
                    _("Describe the item handed over by the guest.")
                )
        return super().create(vals_list)

    def _compute_custody_count(self):
        counts = dict(
            self.env["hotel.property.custody"]._read_group(
                [("property_id", "in", self.ids)],
                groupby=["property_id"],
                aggregates=["__count"],
            )
        )
        for prop in self:
            prop.custody_count = counts.get(prop, 0)

    def _compute_deposit_count(self):
        counts = dict(
            self.env["hotel.safe.deposit"]._read_group(
                [("property_id", "in", self.ids)],
                groupby=["property_id"],
                aggregates=["__count"],
            )
        )
        for prop in self:
            prop.deposit_count = counts.get(prop, 0)

    @api.depends("state")
    def _compute_color_index(self):
        colors = {
            "guest_possession": 0,
            "deposit_requested": 4,
            "received": 2,
            "stored": 5,
            "ready_return": 1,
            "returned": 3,
            "cancelled": 9,
        }
        for prop in self:
            prop.color_index = colors.get(prop.state, 0)

    @api.depends("expected_return_date", "state")
    def _compute_return_flags(self):
        today = fields.Date.context_today(self)
        held = ("received", "stored", "ready_return")
        for prop in self:
            due = bool(
                prop.expected_return_date
                and prop.state in held
            )
            prop.is_return_due_today = due and prop.expected_return_date == today
            prop.is_return_overdue = due and prop.expected_return_date < today

    def _search_return_due_today(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise NotImplementedError()
        today = fields.Date.context_today(self)
        domain = [
            ("state", "in", ["received", "stored", "ready_return"]),
            ("expected_return_date", "=", today),
        ]
        if (operator == "=" and value) or (operator == "!=" and not value):
            return domain
        return ["!"] + domain

    def _search_return_overdue(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise NotImplementedError()
        today = fields.Date.context_today(self)
        domain = [
            ("state", "in", ["received", "stored", "ready_return"]),
            ("expected_return_date", "<", today),
        ]
        if (operator == "=" and value) or (operator == "!=" and not value):
            return domain
        return ["!"] + domain

    @api.model
    def _cron_expected_return_reminders(self):
        """Create activities for returns due today or already overdue."""
        today = fields.Date.context_today(self)
        act_xmlid = (
            "hotel.mail_activity_type_property_return"
            if self.env.ref(
                "hotel.mail_activity_type_property_return",
                raise_if_not_found=False,
            )
            else "mail.mail_activity_data_todo"
        )
        props = self.search(
            [
                ("state", "in", ["received", "stored", "ready_return"]),
                ("expected_return_date", "!=", False),
                ("expected_return_date", "<=", today),
            ],
        )
        Activity = self.env["mail.activity"]
        for prop in props:
            existing = Activity.search(
                [
                    ("res_model", "=", prop._name),
                    ("res_id", "=", prop.id),
                    ("summary", "ilike", prop.display_name),
                    ("date_deadline", "<=", today),
                ],
                limit=1,
            )
            if existing:
                continue
            summary = (
                _("Overdue return: %s") % prop.display_name
                if prop.expected_return_date < today
                else _("Return due today: %s") % prop.display_name
            )
            prop.activity_schedule(
                act_xmlid,
                summary=summary,
                note=_(
                    "Guest %(guest)s expects %(item)s back on %(date)s "
                    "(room %(room)s).",
                    guest=prop.guest_id.display_name,
                    item=prop.description or prop.name,
                    date=prop.expected_return_date,
                    room=prop.room_id.number or "-",
                ),
                date_deadline=prop.expected_return_date or today,
                user_id=prop.received_by_id.id or self.env.user.id,
            )
        return True

    @api.onchange("reservation_id")
    def _onchange_reservation_id(self):
        for prop in self:
            if prop.reservation_id:
                prop.guest_id = prop.reservation_id.guest_id
                prop.room_id = prop.reservation_id.room_id

    @api.constrains("guest_id", "reservation_id", "state")
    def _check_stay_data(self):
        for prop in self:
            if not prop.guest_id:
                raise ValidationError(
                    _("Guest property %s requires a guest.") % (prop.name or _("new"))
                )
            reservation = prop.reservation_id
            if reservation:
                if reservation.guest_id != prop.guest_id:
                    raise ValidationError(
                        _(
                            "Guest property %s: the guest does not match the "
                            "guest of reservation %s."
                        )
                        % (prop.name, reservation.name)
                    )
                if reservation.state in ("draft", "cancelled", "no_show"):
                    raise ValidationError(
                        _(
                            "Guest property %s: reservation %s is not an "
                            "active stay."
                        )
                        % (prop.name, reservation.name)
                    )
                if prop.room_id and prop.room_id != reservation.room_id:
                    raise ValidationError(
                        _(
                            "Guest property %s: the room does not match the "
                            "room of reservation %s."
                        )
                        % (prop.name, reservation.name)
                    )

    @api.constrains("received_date", "returned_date")
    def _check_return_after_receipt(self):
        for prop in self:
            if prop.received_date and prop.returned_date:
                if prop.returned_date < prop.received_date:
                    raise ValidationError(
                        _("Guest property %s cannot be returned before it was received.")
                        % prop.name
                    )

    @api.constrains("state", "received_date", "current_location_id")
    def _check_state_data(self):
        for prop in self:
            if prop.state in HELD_STATES and not prop.received_date:
                raise ValidationError(
                    _(
                        "Guest property %s: the reception date is required as "
                        "soon as the hotel holds the item."
                    )
                    % prop.name
                )
            if prop.state in ("stored", "ready_return") and not prop.current_location_id:
                raise ValidationError(
                    _(
                        "Guest property %s: a storage location is required to "
                        "store the item."
                    )
                    % prop.name
                )

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def _log_custody(self, action, **values):
        """Record a completed custody entry for this property."""
        self.ensure_one()
        return self.env["hotel.property.custody"].create(
            {
                "property_id": self.id,
                "action": action,
                "user_id": self.env.user.id,
                "custody_date": fields.Datetime.now(),
                "condition": self.condition,
                "state": "completed",
                **values,
            }
        )

    def action_request_deposit(self):
        for prop in self:
            if prop.state != "guest_possession":
                raise ValidationError(
                    _("Only items still with the guest can be marked as deposit requested.")
                )
        self.write({"state": "deposit_requested"})
        for prop in self:
            prop.message_post(
                body=_("Deposit requested for %s.", prop.description)
            )
            prop._log_custody("deposit", notes=_("Deposit requested from the guest."))
        return True

    def action_receive(self):
        for prop in self:
            if prop.state not in ("guest_possession", "deposit_requested"):
                raise ValidationError(
                    _("Only items with the guest or with a deposit request can be received.")
                )
            if not prop.current_location_id:
                raise ValidationError(
                    _("Set the storage location before receiving %s.") % prop.name
                )
        now = fields.Datetime.now()
        self.write(
            {
                "state": "received",
                "received_date": now,
                "received_by_id": self.env.user.id,
            }
        )
        for prop in self:
            prop.message_post(
                body=_(
                    "%s received from the guest and stored in %s.",
                    prop.description,
                    prop.current_location_id.display_name,
                )
            )
            prop._log_custody(
                "receive",
                to_location_id=prop.current_location_id.id,
                to_user_id=prop.received_by_id.id,
            )
        return True

    def action_store(self):
        for prop in self:
            if prop.state != "received":
                raise ValidationError(
                    _("Only received items can be stored in the safe.")
                )
            if not prop.current_location_id:
                raise ValidationError(
                    _("A storage location is required to store %s.") % prop.name
                )
        self.write({"state": "stored"})
        for prop in self:
            prop.message_post(
                body=_("Stored in %s.", prop.current_location_id.display_name)
            )
            prop._log_custody(
                "store",
                to_location_id=prop.current_location_id.id,
                to_user_id=self.env.user.id,
            )
        return True

    def action_ready_return(self):
        for prop in self:
            if prop.state != "stored":
                raise ValidationError(
                    _("Only items stored in the safe can be marked ready for return.")
                )
        self.write({"state": "ready_return"})
        for prop in self:
            prop.message_post(body=_("Marked ready to be returned to the guest."))
        return True

    def action_return(self):
        for prop in self:
            if prop.state not in ("stored", "ready_return"):
                raise ValidationError(
                    _("Only items held by the hotel can be returned to the guest.")
                )
            if not prop.returned_to:
                raise ValidationError(
                    _(
                        "Record who receives %s back before confirming the return."
                    )
                    % prop.name
                )
        now = fields.Datetime.now()
        self.write(
            {
                "state": "returned",
                "returned_date": now,
                "returned_by_id": self.env.user.id,
                "current_location_id": False,
            }
        )
        for prop in self:
            prop.message_post(
                body=_("Returned to %s.", prop.returned_to)
            )
            prop._log_custody(
                "return",
                from_location_id=prop._last_location_id(),
                to_user_id=self.env.user.id,
                notes=_("Handed back to %s.") % prop.returned_to,
            )
        return True

    def action_cancel(self):
        for prop in self:
            if prop.state in CLOSED_STATES:
                raise ValidationError(
                    _("Property %s is already closed.") % prop.name
                )
        self.write({"state": "cancelled"})
        for prop in self:
            prop.message_post(body=_("Property record cancelled."))
        return True

    def _last_location_id(self):
        self.ensure_one()
        custody = self.custody_ids.sorted(lambda c: (c.custody_date, c.id))[-1:]
        return custody.to_location_id.id if custody else False

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def action_open_custody(self):
        self.ensure_one()
        return {
            "name": _("Custody Records"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.property.custody",
            "view_mode": "list,form",
            "domain": [("property_id", "=", self.id)],
            "context": {"default_property_id": self.id},
        }

    def action_open_deposits(self):
        self.ensure_one()
        return {
            "name": _("Safe Deposits"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.safe.deposit",
            "view_mode": "list,form",
            "domain": [("property_id", "=", self.id)],
            "context": {"default_property_id": self.id},
        }

    def action_print_property_card(self):
        self.ensure_one()
        return self.env.ref(
            "hotel.action_report_guest_property"
        ).report_action(self)