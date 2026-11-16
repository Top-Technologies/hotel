from . import models
from . import wizard
from . import controllers


def post_init_hook(env):
    """Ensure accounts and records used for folio invoicing exist after install."""
    env["hotel.config"]._create_room_charge_clearing_account()
    env["hotel.config"]._hotel_receivable_account()
    env["hotel.config"]._hotel_income_account()
    env["hotel.config"]._hotel_sales_journal()
    env["hotel.config"]._ensure_room_charge_journal()
    env["hotel.config"]._ensure_room_charge_payment_method()
    env["hotel.config"]._ensure_room_service_product()
    env["hotel.config"]._ensure_hotel_room_service_pos()
