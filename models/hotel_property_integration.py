from odoo import _, api, fields, models


class HotelReservationProperty(models.Model):
    """Guest assets and safe deposits attached to a stay."""

    _inherit = "hotel.reservation"

    property_count = fields.Integer(
        string="Guest Assets", compute="_compute_property_counts"
    )
    safe_deposit_count = fields.Integer(
        string="Safe Deposits", compute="_compute_property_counts"
    )

    def _compute_property_counts(self):
        properties = dict(
            self.env["hotel.guest.property"]._read_group(
                [("reservation_id", "in", self.ids)],
                groupby=["reservation_id"],
                aggregates=["__count"],
            )
        )
        deposits = dict(
            self.env["hotel.safe.deposit"]._read_group(
                [("reservation_id", "in", self.ids)],
                groupby=["reservation_id"],
                aggregates=["__count"],
            )
        )
        for reservation in self:
            reservation.property_count = properties.get(reservation, 0)
            reservation.safe_deposit_count = deposits.get(reservation, 0)

    def action_open_properties(self):
        self.ensure_one()
        return {
            "name": _("Guest Assets"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.guest.property",
            "view_mode": "list,form",
            "domain": [("reservation_id", "=", self.id)],
            "context": {"default_reservation_id": self.id},
        }

    def action_open_safe_deposits(self):
        self.ensure_one()
        return {
            "name": _("Safe Deposits"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.safe.deposit",
            "view_mode": "list,form",
            "domain": [("reservation_id", "=", self.id)],
            "context": {"default_reservation_id": self.id},
        }

    def action_open_lost_found(self):
        return {
            "name": _("Lost & Found"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.lost.found",
            "view_mode": "list,form,kanban",
            "domain": [("previous_reservation_id", "=", self.id)],
        }

    def write(self, vals):
        res = super().write(vals)
        if vals.get("state") == "checked_out":
            self._return_stored_guest_assets()
        return res

    def _return_stored_guest_assets(self):
        """Automatically return any guest properties held in custody/safe upon checkout."""
        held_states = ("received", "stored", "ready_return", "deposit_requested")
        for reservation in self:
            properties = self.env["hotel.guest.property"].search([
                ("reservation_id", "=", reservation.id),
                ("state", "in", held_states),
            ])
            if not properties and reservation.guest_id:
                properties = self.env["hotel.guest.property"].search([
                    ("guest_id", "=", reservation.guest_id.id),
                    ("room_id", "=", reservation.room_id.id),
                    ("state", "in", held_states),
                ])
            if not properties:
                continue

            now = fields.Datetime.now()
            recipient_name = (
                reservation.guest_id.name
                or (reservation.staff_id.name if reservation.staff_id else _("Guest"))
            )

            for prop in properties:
                # 1. Release open safe deposits linked to this property
                open_deposits = prop.deposit_ids.filtered(lambda d: d.state in ("received", "stored"))
                if open_deposits:
                    open_deposits.write({
                        "state": "released",
                        "released_by_id": self.env.user.id,
                        "released_date": now,
                    })
                    for dep in open_deposits:
                        dep.message_post(
                            body=_(
                                "Safe deposit automatically released upon check-out of %(reservation)s.",
                                reservation=reservation.name,
                            )
                        )

                # 2. Return the property to the guest
                last_loc = prop.current_location_id.id or prop._last_location_id()
                ret_name = prop.returned_to or recipient_name
                prop.write({
                    "state": "returned",
                    "returned_date": now,
                    "returned_by_id": self.env.user.id,
                    "returned_to": ret_name,
                    "current_location_id": False,
                })
                prop.message_post(
                    body=_(
                        "Guest asset automatically returned to %(recipient)s upon check-out of %(reservation)s.",
                        recipient=ret_name,
                        reservation=reservation.name,
                    )
                )
                prop._log_custody(
                    "return",
                    from_location_id=last_loc,
                    to_user_id=self.env.user.id,
                    notes=_(
                        "Automatically returned upon check-out of %(reservation)s to %(recipient)s.",
                        reservation=reservation.name,
                        recipient=ret_name,
                    ),
                )
                reservation.message_post(
                    body=_(
                        "Stored guest asset <b>%(name)s</b> (%(desc)s) automatically returned to %(recipient)s upon check-out.",
                        name=prop.name,
                        desc=prop.description,
                        recipient=ret_name,
                    )
                )



class HotelRoomProperty(models.Model):
    """Guest assets currently linked to a room."""

    _inherit = "hotel.room"

    property_count = fields.Integer(
        string="Guest Assets", compute="_compute_property_counts"
    )
    safe_deposit_count = fields.Integer(
        string="Safe Deposits", compute="_compute_property_counts"
    )
    lost_found_count = fields.Integer(
        string="Lost & Found Items", compute="_compute_property_counts"
    )

    def _compute_property_counts(self):
        properties = dict(
            self.env["hotel.guest.property"]._read_group(
                [("room_id", "in", self.ids)],
                groupby=["room_id"],
                aggregates=["__count"],
            )
        )
        deposits = dict(
            self.env["hotel.safe.deposit"]._read_group(
                [("room_id", "in", self.ids)],
                groupby=["room_id"],
                aggregates=["__count"],
            )
        )
        lost = dict(
            self.env["hotel.lost.found"]._read_group(
                [("found_room_id", "in", self.ids)],
                groupby=["found_room_id"],
                aggregates=["__count"],
            )
        )
        for room in self:
            room.property_count = properties.get(room, 0)
            room.safe_deposit_count = deposits.get(room, 0)
            room.lost_found_count = lost.get(room, 0)

    def action_open_properties(self):
        self.ensure_one()
        return {
            "name": _("Guest Assets"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.guest.property",
            "view_mode": "list,form",
            "domain": [("room_id", "=", self.id)],
            "context": {"default_room_id": self.id},
        }

    def action_open_safe_deposits(self):
        self.ensure_one()
        return {
            "name": _("Safe Deposits"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.safe.deposit",
            "view_mode": "list,form",
            "domain": [("room_id", "=", self.id)],
            "context": {"default_room_id": self.id},
        }

    def action_open_lost_found(self):
        self.ensure_one()
        return {
            "name": _("Lost & Found"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.lost.found",
            "view_mode": "list,form,kanban",
            "domain": [("found_room_id", "=", self.id)],
            "context": {"default_found_room_id": self.id},
        }