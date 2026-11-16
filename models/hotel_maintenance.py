from odoo import _, api, fields, models


class MaintenanceRequest(models.Model):
    _inherit = "maintenance.request"

    room_id = fields.Many2one(
        comodel_name="hotel.room",
        string="Room",
        ondelete="set null",
        index=True,
        help="Guest room concerned by this request. An open request takes the "
        "room out of service; a repaired request sets it back to dirty.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        requests = super().create(vals_list)
        requests._hotel_room_maintenance_update()
        return requests

    def write(self, vals):
        old_rooms = self.mapped("room_id") if "room_id" in vals else self.env["hotel.room"]
        result = super().write(vals)
        if any(f in vals for f in ("stage_id", "room_id", "archive")):
            all_rooms = old_rooms | self.mapped("room_id")
            self._hotel_room_maintenance_update(rooms=all_rooms)
        return result

    def unlink(self):
        rooms = self.mapped("room_id")
        result = super().unlink()
        if rooms:
            self.env["maintenance.request"]._hotel_room_maintenance_update(rooms=rooms)
        return result

    @api.model
    def _hotel_room_maintenance_update(self, rooms=None):
        """Keep hotel room status in sync with maintenance requests.

        - If a room has ANY open (not done, not archived) request:
          The room is taken out of service.
        - If all requests for a room are resolved (done or archived):
          If the room was out of service:
            - If an active checked-in reservation exists: room returns to occupied.
            - Otherwise: room returns to dirty and a post-repair cleaning task is created.
        """
        if rooms is None:
            rooms = self.mapped("room_id")
        if not rooms:
            return

        housekeeping = self.env["hotel.housekeeping.task"]
        for room in rooms.filtered(lambda r: r.exists()):
            open_requests = self.search([
                ("room_id", "=", room.id),
                ("stage_id.done", "=", False),
                ("archive", "=", False),
            ])
            if open_requests:
                if room.status != "out_of_service":
                    req_names = ", ".join(open_requests.mapped("name"))
                    room.sudo()._action_set_status(
                        "out_of_service",
                        _("Out of service: maintenance request (%s).") % req_names,
                    )
            else:
                if room.status == "out_of_service":
                    active_reservation = self.env["hotel.reservation"].search([
                        ("room_id", "=", room.id),
                        ("state", "=", "checked_in"),
                    ], limit=1)
                    if active_reservation:
                        room.sudo()._action_set_status(
                            "occupied",
                            _("Repaired: room occupied by %s (%s).")
                            % (active_reservation.guest_id.name, active_reservation.name),
                        )
                    else:
                        room.sudo()._action_set_status(
                            "dirty",
                            _("Repaired, awaiting post-repair cleaning."),
                        )
                        housekeeping.sudo()._action_create_for_room(
                            room, notes=_("Post-repair cleaning after maintenance."),
                        )

    def _hotel_room_maintenance_started(self):
        """Compatibility wrapper: synchronize room status for open requests."""
        self._hotel_room_maintenance_update()

    def _hotel_room_maintenance_stage_changed(self):
        """Compatibility wrapper: synchronize room status when stage changes."""
        self._hotel_room_maintenance_update()

    def action_open_room(self):
        self.ensure_one()
        return {
            "name": _("Room"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.room",
            "view_mode": "form",
            "res_id": self.room_id.id,
        }

