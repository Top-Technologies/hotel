from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

CLAIM_STATES = ("claim_requested", "verified")


class HotelLostFound(models.Model):
    """Items found on the premises or handed in by guests."""

    _name = "hotel.lost.found"
    _description = "Lost & Found Item"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "found_date desc, id desc"

    name = fields.Char(
        string="Reference",
        required=True,
        default="New",
        readonly=True,
        copy=False,
        index=True,
    )
    category_id = fields.Many2one(
        comodel_name="hotel.property.category",
        string="Item Type",
        required=True,
        ondelete="restrict",
        tracking=True,
        index=True,
    )
    description = fields.Char(required=True, tracking=True)
    serial_number = fields.Char()
    quantity = fields.Float(default=1.0)
    found_date = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    found_location = fields.Char(
        string="Where Found", help="Free description of the place where it was found."
    )
    found_room_id = fields.Many2one(
        comodel_name="hotel.room",
        string="Room (if known)",
        ondelete="set null",
        index=True,
    )
    storage_location_id = fields.Many2one(
        comodel_name="hotel.storage.location",
        string="Storage Location",
        ondelete="restrict",
        tracking=True,
        index=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
        index=True,
        required=True,
    )
    found_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Recorded By",
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
    )
    previous_guest_id = fields.Many2one(
        comodel_name="res.partner",
        string="Previous Guest (if known)",
        ondelete="set null",
        index=True,
    )
    previous_reservation_id = fields.Many2one(
        comodel_name="hotel.reservation",
        string="Previous Reservation",
        ondelete="set null",
        index=True,
    )
    claimed_by_id = fields.Many2one(
        comodel_name="res.partner",
        string="Claimed By",
        ondelete="restrict",
        tracking=True,
        index=True,
    )
    claim_reference = fields.Char(
        string="Claim Evidence",
        help="Passport number, booking reference or other ID details used to match the claimant.",
    )
    claim_id_document = fields.Binary(
        string="Claim ID Document",
        attachment=True,
        help="Scanned ID or booking confirmation presented by the claimant.",
    )
    claim_id_document_filename = fields.Char(string="Claim ID Filename")
    claim_verification_notes = fields.Text(
        string="Verification Notes",
        help="What was checked (ID vs reservation, description match, distinguishing marks…).",
    )
    claim_date = fields.Datetime(tracking=True)
    verified = fields.Boolean(copy=False)
    verified_by_id = fields.Many2one(comodel_name="res.users", string="Verified By")
    verified_date = fields.Datetime()
    returned_to = fields.Char(string="Returned To")
    returned_by_id = fields.Many2one(comodel_name="res.users", string="Returned By")
    returned_date = fields.Datetime()
    disposal_method = fields.Selection(
        selection=[
            ("return_to_owner", "Return to Owner"),
            ("donate", "Donate"),
            ("recycle", "Recycle"),
            ("destroy", "Destroy"),
            ("sell", "Sell"),
        ],
        string="Disposal Method",
    )
    disposal_date = fields.Datetime()
    transfer_to = fields.Char(string="Transferred To")
    state = fields.Selection(
        selection=[
            ("found", "Found"),
            ("stored", "Stored"),
            ("claim_requested", "Claim Requested"),
            ("verified", "Claim Verified"),
            ("returned", "Returned to Claimant"),
            ("transferred", "Transferred"),
            ("disposed", "Disposed"),
            ("unclaimed", "Unclaimed"),
        ],
        string="Status",
        default="found",
        required=True,
        tracking=True,
        index=True,
    )
    notes = fields.Text()
    days_in_storage = fields.Integer(compute="_compute_days_in_storage")
    color_index = fields.Integer(compute="_compute_color_index")

    _sql_constraints = [
        (
            "name_unique",
            "unique(name)",
            "Lost & found references must be unique.",
        ),
        (
            "quantity_positive",
            "check (quantity > 0)",
            "Lost & found quantity must be strictly positive.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name") in (False, None, "New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("hotel.lost.found")
        return super().create(vals_list)

    def _compute_days_in_storage(self):
        today = fields.Date.context_today(self)
        for item in self:
            reference = item.found_date
            item.days_in_storage = (
                (today - reference.date()).days if reference else 0
            )

    @api.depends("state")
    def _compute_color_index(self):
        colors = {
            "found": 0,
            "stored": 4,
            "claim_requested": 2,
            "verified": 5,
            "returned": 3,
            "transferred": 6,
            "disposed": 9,
            "unclaimed": 1,
        }
        for item in self:
            item.color_index = colors.get(item.state, 0)

    @api.onchange("previous_reservation_id")
    def _onchange_previous_reservation_id(self):
        for item in self:
            if item.previous_reservation_id:
                item.previous_guest_id = item.previous_reservation_id.guest_id
                if not item.found_room_id:
                    item.found_room_id = item.previous_reservation_id.room_id

    @api.constrains("state", "storage_location_id")
    def _check_storage_location(self):
        for item in self:
            if item.state in (
                "stored",
                "claim_requested",
                "verified",
                "returned",
                "transferred",
            ) and not item.storage_location_id:
                raise ValidationError(
                    _(
                        "Lost & found item %s: set the storage location before "
                        "storing it."
                    )
                    % item.name
                )

    @api.constrains("state", "claimed_by_id", "claim_date")
    def _check_claim_data(self):
        for item in self:
            if item.state in CLAIM_STATES and not item.claimed_by_id:
                raise ValidationError(
                    _(
                        "Lost & found item %s: record who claims the item before "
                        "requesting the claim."
                    )
                    % item.name
                )

    @api.constrains("state", "returned_to")
    def _check_return_data(self):
        for item in self:
            if item.state == "returned" and not item.returned_to:
                raise ValidationError(
                    _(
                        "Lost & found item %s: record who received the item back."
                    )
                    % item.name
                )

    @api.constrains("state", "disposal_method")
    def _check_disposal_data(self):
        for item in self:
            if item.state == "disposed" and not item.disposal_method:
                raise ValidationError(
                    _(
                        "Lost & found item %s: record the disposal method."
                    )
                    % item.name
                )

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_store(self):
        for item in self:
            if item.state != "found":
                raise ValidationError(
                    _("Only items in the 'Found' state can be stored.")
                )
            if not item.storage_location_id:
                raise ValidationError(
                    _("Set the storage location before storing %s.") % item.name
                )
        self.write({"state": "stored"})
        for item in self:
            item.message_post(
                body=_("Stored in %s.", item.storage_location_id.display_name)
            )
        return True

    def action_request_claim(self):
        for item in self:
            if item.state not in ("stored", "unclaimed"):
                raise ValidationError(
                    _("Only stored items can be claimed.")
                )
            if not item.claimed_by_id:
                raise ValidationError(
                    _("Record who claims item %s.") % item.name
                )
        self.write({"state": "claim_requested", "claim_date": fields.Datetime.now()})
        for item in self:
            item.message_post(
                body=_("Claim requested by %s.", item.claimed_by_id.display_name)
            )
        return True

    def action_verify_claim(self):
        for item in self:
            if item.state != "claim_requested":
                raise ValidationError(
                    _("Only items with a requested claim can be verified.")
                )
            if not item.claim_reference:
                raise ValidationError(
                    _(
                        "Record the evidence used to verify the claim of item %s "
                        "(passport / booking reference)."
                    )
                    % item.name
                )
            if not item.claim_verification_notes:
                raise ValidationError(
                    _(
                        "Add verification notes for %s before approving the claim "
                        "(what was checked against the item and the claimant)."
                    )
                    % item.name
                )
        self.write(
            {
                "state": "verified",
                "verified": True,
                "verified_by_id": self.env.user.id,
                "verified_date": fields.Datetime.now(),
            }
        )
        for item in self:
            item.message_post(
                body=_(
                    "Claim verified by %(user)s.\nEvidence: %(evidence)s\nNotes: %(notes)s",
                    user=self.env.user.display_name,
                    evidence=item.claim_reference,
                    notes=item.claim_verification_notes,
                )
            )
        return True

    def action_reject_claim(self):
        for item in self:
            if item.state != "claim_requested":
                raise ValidationError(
                    _("Only items with a requested claim can be rejected.")
                )
        self.write(
            {"state": "unclaimed", "claim_date": False, "claimed_by_id": False}
        )
        for item in self:
            item.message_post(body=_("Claim rejected; item is unclaimed again."))
        return True

    def action_return(self):
        for item in self:
            if item.state != "verified":
                raise ValidationError(
                    _("Only verified claims can be returned to the claimant.")
                )
        for item in self:
            if not item.returned_to:
                raise ValidationError(
                    _("Record who receives item %s back.") % item.name
                )
        for item in self:
            item.write(
                {
                    "state": "returned",
                    "returned_by_id": self.env.user.id,
                    "returned_date": fields.Datetime.now(),
                }
            )
            item.message_post(body=_("Returned to %s.", item.returned_to))
        return True

    def action_mark_unclaimed(self):
        for item in self:
            if item.state not in ("found", "stored", "claim_requested"):
                raise ValidationError(
                    _("Only open items can be marked as unclaimed.")
                )
        self.write({"state": "unclaimed"})
        return True

    def action_transfer(self):
        for item in self:
            if item.state not in ("stored", "unclaimed"):
                raise ValidationError(
                    _("Only stored or unclaimed items can be transferred.")
                )
            if not item.transfer_to:
                raise ValidationError(
                    _("Record the new keeper of item %s.") % item.name
                )
        self.write({"state": "transferred"})
        for item in self:
            item.message_post(body=_("Transferred to %s.", item.transfer_to))
        return True

    def action_dispose(self):
        for item in self:
            if item.state not in ("stored", "unclaimed"):
                raise ValidationError(
                    _("Only stored or unclaimed items can be disposed.")
                )
            if not item.disposal_method:
                raise ValidationError(
                    _("Record the disposal method for item %s.") % item.name
                )
        self.write(
            {"state": "disposed", "disposal_date": fields.Datetime.now()}
        )
        for item in self:
            item.message_post(
                body=_("Disposed (%s).", item.disposal_method)
            )
        return True

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def action_open_lost_found_report(self):
        return self.env.ref("hotel.action_report_lost_found").report_action(
            self, data={"disposition_date": fields.Date.context_today(self)}
        )
