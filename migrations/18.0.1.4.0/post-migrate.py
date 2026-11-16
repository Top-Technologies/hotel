# -*- coding: utf-8 -*-
"""Migrate ir.config_parameter hotel settings to res.company fields and ensure compatibility."""

import logging
from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # Drop old single-column unique constraints; Odoo recreates them as multi-column
    _logger.info("Dropping old single-column unique constraints for hotel models...")
    for table, constraint in [
        ("hotel_room_type", "hotel_room_type_code_unique"),
        ("hotel_room", "hotel_room_number_unique"),
        ("hotel_lost_found", "hotel_lost_found_name_unique"),
        ("hotel_guest_property", "hotel_guest_property_name_unique"),
        ("hotel_safe_deposit", "hotel_safe_deposit_name_unique"),
        ("hotel_property_custody", "hotel_property_custody_name_unique"),
    ]:
        cr.execute(f"ALTER TABLE IF EXISTS {table} DROP CONSTRAINT IF EXISTS {constraint} CASCADE")
        cr.execute(f"DROP INDEX IF EXISTS {constraint}")

    ICP = env["ir.config_parameter"].sudo()
    companies = env["res.company"].search([])
    main_company = env.ref("base.main_company", raise_if_not_found=False) or companies[:1]

    m2o_mapping = {
        "hotel_sales_journal_id": ("hotel.sales_journal_id", "account.journal"),
        "hotel_checkout_journal_id": ("hotel.checkout_journal_id", "account.journal"),
        "hotel_deposit_journal_id": ("hotel.deposit_journal_id", "account.journal"),
        "hotel_room_charge_journal_id": ("hotel.room_charge_journal_id", "account.journal"),
        "hotel_income_account_id": ("hotel.income_account_id", "account.account"),
        "hotel_receivable_account_id": ("hotel.receivable_account_id", "account.account"),
        "hotel_room_charge_clearing_account_id": ("hotel.room_charge_clearing_account_id", "account.account"),
        "hotel_default_product_id": ("hotel.default_product_id", "product.product"),
        "hotel_pos_room_service_config_id": ("hotel.pos_room_service_config_id", "pos.config"),
        "hotel_room_charge_payment_method_id": ("hotel.room_charge_payment_method_id", "pos.payment.method"),
        "hotel_room_service_product_id": ("hotel.room_service_product_id", "product.product"),
        "hotel_room_location_id": ("hotel.room_location_id", "stock.location"),
        "hotel_consumption_location_id": ("hotel.consumption_location_id", "stock.location"),
        "hotel_kitchen_location_id": ("hotel.kitchen_location_id", "stock.location"),
        "hotel_storeroom_location_id": ("hotel.storeroom_location_id", "stock.location"),
        "hotel_housekeeping_cart_location_id": ("hotel.housekeeping_cart_location_id", "stock.location"),
        "hotel_internal_picking_type_id": ("hotel.internal_picking_type_id", "stock.picking.type"),
        "hotel_housekeeping_department_id": ("hotel.housekeeping_department_id", "hr.department"),
    }

    if main_company:
        vals = {}
        for field_name, (param_key, model_name) in m2o_mapping.items():
            param_val = ICP.get_param(param_key)
            if param_val:
                try:
                    rec_id = int(param_val)
                    if env[model_name].browse(rec_id).exists():
                        vals[field_name] = rec_id
                except (ValueError, TypeError):
                    pass

        turnover = ICP.get_param("hotel.turnover_policy")
        if turnover in ("replenish", "carry_forward"):
            vals["hotel_turnover_policy"] = turnover

        req_insp = ICP.get_param("hotel.require_inspection")
        if req_insp is not None:
            vals["hotel_require_inspection"] = req_insp in ("True", "true", "1")

        auto_hk = ICP.get_param("hotel.auto_housekeeping_on_checkout")
        if auto_hk is not None:
            vals["hotel_auto_housekeeping_on_checkout"] = auto_hk not in ("False", "false", "0")

        tax_ids_str = ICP.get_param("hotel.default_tax_ids")
        if tax_ids_str:
            tax_ids = [int(i) for i in tax_ids_str.split(",") if i.strip().isdigit()]
            valid_taxes = env["account.tax"].browse(tax_ids).exists()
            if valid_taxes:
                vals["hotel_default_tax_ids"] = [(6, 0, valid_taxes.ids)]

        if vals:
            main_company.write(vals)

    # Ensure POS and room charge records exist and are registered with xmlids
    for comp in companies:
        env["hotel.config"]._create_room_charge_clearing_account(company=comp)
        env["hotel.config"]._hotel_receivable_account(company=comp)
        env["hotel.config"]._ensure_room_charge_journal(company=comp)
        env["hotel.config"]._ensure_room_charge_payment_method(company=comp)
        env["hotel.config"]._ensure_room_service_product(company=comp)
        env["hotel.config"]._ensure_hotel_room_service_pos(company=comp)

    _logger.info("hotel migration to 18.0.1.4.0 completed successfully.")
