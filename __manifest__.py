{
    "name": "Hotel & Restaurant",
    "version": "18.0.1.4.0",
    "category": "Hotel Management",
    "summary": "Hotel & Restaurant Management: rooms, reservations, front desk, housekeeping and guest billing",
    "description": """
Hotel & Restaurant Management System
======================================

Comprehensive hotel management system for Hotels & Restaurants operations.
Compatible with Odoo 18 Community (no Enterprise dependencies).

- Room types, rooms with a button-driven room status flow and a room record with
  smart buttons (stays, cleanings, maintenance requests).
- Reservations with double-booking prevention, availability views (Room Board /
  Kanban / calendar), guest registration on check-in and billing on check-out.
- Guest invoices (folio) built from the room revenue product and the room analytic
  account, with deposit deduction and payment registration.
- Housekeeping tasks created on check-out, with a Kanban board for housekeepers and
  an optional supervisor inspection step.
- Room maintenance integrated with the Maintenance app: an open request takes the
  room out of service, a repaired request sets it back to dirty.
- Guest complaints with pivot/graph analysis per category, floor and month.
- Room service: food orders taken for an in-house guest are sent to the
  Point of Sale (kitchen display, stock, restaurant history) and charged to
  the guest folio through a clearing account, paid at check-out.
    """,
    "author": "TOPTechnologies",
    "website": "https://www.toptech.et/",
    "license": "OPL-1",
    "depends": [
        "base",
        "mail",
        "contacts",
        "account",
        "hr",
        "maintenance",
        "stock",
        "survey",
        "point_of_sale",
        "pos_restaurant",
    ],
    "data": [
        "security/hotel_security.xml",
        "security/ir.model.access.csv",
        "security/hotel_rules.xml",
        "data/ir_sequence_data.xml",
        "data/hotel_amenity_data.xml",
        "data/hotel_consumable_products_data.xml",
        "data/hotel_stock_data.xml",
        "data/hotel_pos_data.xml",
        "data/hotel_deposit_ledger_data.xml",
        "data/hotel_discount_rule_data.xml",
        "data/hotel_property_cron_data.xml",
        "report/hotel_deposit_ledger_report.xml",
        "views/hotel_deposit_ledger_views.xml",
        "wizard/hotel_checkin_views.xml",
        "wizard/hotel_checkout_views.xml",
        "wizard/hotel_walkin_views.xml",
        "views/hotel_room_type_views.xml",
        "views/hotel_room_views.xml",
        "views/hotel_reservation_views.xml",
        "views/hotel_housekeeping_views.xml",
        "views/hotel_room_consumption_views.xml",
        "views/hotel_supply_requisition_views.xml",
        "views/product_template_views.xml",
        "views/hotel_approvals_views.xml",
        "views/hotel_complaint_views.xml",
        "views/account_move_views.xml",
        "views/hotel_property_config_views.xml",
        "views/hotel_guest_property_views.xml",
        "views/hotel_safe_deposit_views.xml",
        "views/hotel_lost_found_views.xml",
        "report/hotel_room_service_report.xml",
        "report/hotel_report.xml",
        "views/res_config_settings_views.xml",
        "views/hotel_dashboard_views.xml",
        "views/hotel_guest_views.xml",
        "views/hotel_guest_survey_views.xml",
        "views/hotel_room_service_views.xml",
        "views/hotel_menus.xml",
    ],
    "demo": [
        "demo/hotel_demo_data.xml",
        "demo/hotel_consumption_demo.xml",
        "demo/hotel_rich_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "hotel/static/src/css/hotel_dashboard.css",
            "hotel/static/src/css/hotel_availability.css",
            "hotel/static/src/js/hotel_dashboard.js",
            "hotel/static/src/js/hotel_availability.js",
            "hotel/static/src/js/hotel_deposit_ledger.js",
            "hotel/static/src/scss/hotel_housekeeping.scss",
            "hotel/static/src/scss/hotel_deposit_ledger.scss",
            "hotel/static/src/scss/hotel_reservation.scss",
            "hotel/static/src/xml/hotel_dashboard.xml",
            "hotel/static/src/xml/hotel_availability.xml",
            "hotel/static/src/xml/hotel_deposit_ledger.xml",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
    "post_init_hook": "post_init_hook",
}
