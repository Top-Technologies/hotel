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