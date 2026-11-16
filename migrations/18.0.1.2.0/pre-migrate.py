# -*- coding: utf-8 -*-
"""Purge leftover dina_hotel report model / xmlids from the rebrand."""


def migrate(cr, version):
    # Orphan report model left after dina_hotel → hotel rename.
    cr.execute(
        """
        DELETE FROM ir_model_fields
         WHERE model = 'report.dina_hotel.report_deposit_ledger'
        """
    )
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE model = 'ir.model'
           AND res_id IN (
                SELECT id FROM ir_model
                 WHERE model = 'report.dina_hotel.report_deposit_ledger'
           )
        """
    )
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE model = 'report.dina_hotel.report_deposit_ledger'
            OR name ILIKE '%dina_hotel%report_deposit%'
            OR (module = 'dina_hotel')
        """
    )
    cr.execute(
        """
        DELETE FROM ir_model
         WHERE model = 'report.dina_hotel.report_deposit_ledger'
        """
    )
    # Drop the old module row if it still hangs around uninstalled/to remove.
    cr.execute(
        """
        DELETE FROM ir_module_module
         WHERE name = 'dina_hotel'
           AND state IN ('uninstalled', 'to remove', 'uninstallable')
        """
    )
