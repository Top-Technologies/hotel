from datetime import datetime, time, timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestStaffAndBreakfast(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.hotel_breakfast_price = 400.0

        cls.partner = cls.env["res.partner"].create({"name": "Paying Guest"})
        cls.employee = cls.env["hr.employee"].create({
            "name": "Staff Member Jane",
            "work_phone": "+123456789",
        })

        cls.room_type = cls.env["hotel.room.type"].create({
            "name": "Deluxe Room",
            "capacity": 3,
            "base_price": 2000.0,
            "company_id": cls.company.id,
        })
        cls.room = cls.env["hotel.room"].create({
            "name": "Room 101",
            "number": "101",
            "room_type_id": cls.room_type.id,
            "status": "clean",
            "company_id": cls.company.id,
        })

        today = fields.Date.context_today(cls.env.user)
        cls.checkin = datetime.combine(today + timedelta(days=1), time(14, 0))
        cls.checkout = datetime.combine(today + timedelta(days=4), time(11, 0))

    def test_01_staff_reservation_cost_capture_and_no_invoice(self):
        """Staff reservation captures internal cost, follows lifecycle, and never generates guest invoice."""
        res = self.env["hotel.reservation"].create({
            "reservation_type": "staff",
            "staff_id": self.employee.id,
            "room_type_id": self.room_type.id,
            "room_id": self.room.id,
            "checkin": self.checkin,
            "checkout": self.checkout,
            "adults": 1,
        })

        self.assertEqual(res.reservation_type, "staff")
        self.assertEqual(res.staff_id, self.employee)
        self.assertTrue(res.guest_id)
        self.assertEqual(res.nights, 3)
        self.assertEqual(res.base_rate, 2000.0)
        self.assertEqual(res.rate, 2000.0)
        # Internal cost captured: 3 nights * 2000 = 6000
        self.assertEqual(res.internal_cost, 6000.0)
        # Guest amount receivable is 0
        self.assertEqual(res.total, 0.0)
        self.assertEqual(res.balance_due, 0.0)

        # Confirm and check-in
        res.action_confirm()
        self.assertEqual(res.state, "confirmed")
        res.write({
            "state": "checked_in",
            "actual_checkin": self.checkin,
        })

        # Staff reservation must block folio invoice generation
        with self.assertRaises(UserError):
            res._action_create_folio_invoice()

        with self.assertRaises(UserError):
            res.action_open_guest_folio()

        # Checkout wizard
        wizard_vals = self.env["hotel.checkout.wizard"].with_context(
            default_reservation_id=res.id
        ).default_get(["reservation_id", "create_invoice", "settle_balance"])
        self.assertFalse(wizard_vals.get("create_invoice"))
        self.assertFalse(wizard_vals.get("settle_balance"))

        wizard = self.env["hotel.checkout.wizard"].create({
            "reservation_id": res.id,
            "checkout_at": self.checkout,
            "create_invoice": False,
        })
        wizard._compute_charges()
        # Charges to guest must be 0 for room
        self.assertEqual(wizard.charges_total, 0.0)
        self.assertEqual(wizard.balance_due, 0.0)

        wizard.action_confirm_checkout()
        self.assertEqual(res.state, "checked_out")
        self.assertEqual(len(res.invoice_ids), 0)
        # Cost remains available after checkout
        self.assertEqual(res.internal_cost, 6000.0)

    def test_02_guest_reservation_with_breakfast_pricing_and_consumption(self):
        """Guest reservation with breakfast calculates pricing and tracks daily consumption per guest."""
        res = self.env["hotel.reservation"].create({
            "reservation_type": "guest",
            "guest_id": self.partner.id,
            "room_type_id": self.room_type.id,
            "room_id": self.room.id,
            "checkin": self.checkin,
            "checkout": self.checkout,
            "adults": 2,
            "children": 0,
            "breakfast_option": "with",
        })

        self.assertEqual(res.nights, 3)
        self.assertEqual(res.base_rate, 2000.0)
        self.assertEqual(res.breakfast_price, 400.0)
        # 2 guests * 400 = 800 per night
        self.assertEqual(res.breakfast_amount_per_night, 800.0)
        # 800 * 3 nights = 2400 total breakfast
        self.assertEqual(res.breakfast_total, 2400.0)
        # Breakfast inclusive rate: 2000 + 800 = 2800
        self.assertEqual(res.rate, 2800.0)
        # Total room amount: 3 * 2800 = 8400
        self.assertEqual(res.room_total, 8400.0)
        self.assertEqual(res.total, 8400.0)
        self.assertEqual(res.balance_due, 8400.0)

        # Before confirm, no consumption records
        self.assertEqual(len(res.breakfast_consumption_ids), 0)

        # Confirm reservation -> generates tracking records: 3 nights * 2 guests = 6 records
        res.action_confirm()
        self.assertEqual(len(res.breakfast_consumption_ids), 6)
        self.assertEqual(res.breakfast_count, 6)
        self.assertEqual(res.breakfast_used_count, 0)

        # Verify entitlement and initial state
        for rec in res.breakfast_consumption_ids:
            self.assertTrue(rec.is_entitled)
            self.assertEqual(rec.state, "not_used")

        # Staff marks 1 breakfast as used
        first_rec = res.breakfast_consumption_ids.sorted("date")[0]
        first_rec.action_mark_used()
        self.assertEqual(first_rec.state, "used")
        self.assertEqual(first_rec.user_id, self.env.user)
        self.assertTrue(first_rec.recorded_at)
        self.assertEqual(res.breakfast_used_count, 1)

        # Re-confirming or saving does not duplicate records or reset consumed status
        res._sync_breakfast_consumption_records()
        self.assertEqual(len(res.breakfast_consumption_ids), 6)
        self.assertEqual(first_rec.state, "used")

        # Checkout wizard calculates breakfast-inclusive amount exactly once
        res.write({
            "state": "checked_in",
            "actual_checkin": self.checkin,
        })
        wizard = self.env["hotel.checkout.wizard"].create({
            "reservation_id": res.id,
            "checkout_at": self.checkout,
            "create_invoice": False,
        })
        wizard._compute_charges()
        self.assertEqual(wizard.room_charge, 8400.0)
        self.assertEqual(wizard.charges_total, 8400.0)

    def test_03_without_breakfast_reservation_remains_unchanged(self):
        """Without breakfast bookings retain original calculation and create no entitlements."""
        res = self.env["hotel.reservation"].create({
            "reservation_type": "guest",
            "guest_id": self.partner.id,
            "room_type_id": self.room_type.id,
            "room_id": self.room.id,
            "checkin": self.checkin,
            "checkout": self.checkout,
            "adults": 2,
            "breakfast_option": "without",
        })

        self.assertEqual(res.base_rate, 2000.0)
        self.assertEqual(res.breakfast_total, 0.0)
        self.assertEqual(res.rate, 2000.0)
        self.assertEqual(res.total, 6000.0)

        res.action_confirm()
        self.assertEqual(len(res.breakfast_consumption_ids), 0)
