# ruff:file-ignore[unsorted-imports]
# Import order is significant: Odoo requires base models to be registered
# before the models that inherit from them.
from . import hotel_config
from . import hotel_deposit_ledger
from . import hotel_deposit_ledger_schedule
from . import product_template
from . import hotel_room_consumable
from . import hotel_room_type
from . import hotel_room
from . import hotel_reservation
from . import hotel_breakfast_consumption
from . import hotel_account_move
from . import hotel_account_payment
from . import hotel_complaint
from . import hotel_credit_approval
from . import hotel_dashboard
from . import hotel_demo_loader
from . import hotel_discount_approval
from . import hotel_guest_property
from . import hotel_guest_survey
from . import hotel_housekeeping
from . import hotel_lost_found
from . import hotel_maintenance
from . import hotel_property_config
from . import hotel_property_custody
from . import hotel_property_integration
from . import hotel_rate_approval
from . import hotel_room_consumption
from . import hotel_room_inspection
from . import hotel_room_service
from . import hotel_safe_deposit
from . import hotel_supply_requisition
from . import res_company
from . import res_config_settings
from . import res_partner
