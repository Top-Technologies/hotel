# -*- coding: utf-8 -*-
"""Bridge so demo XML can invoke the rich Python demo loaders."""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class HotelDemoLoader(models.AbstractModel):
    _name = "hotel.demo.loader"
    _description = "Hotel Demo Loader"

    @api.model
    def load_full_demo(self):
        """Load operational demo (folio, HK, POS, approvals, property, …)."""
        from odoo.addons.hotel.demo import full_demo

        try:
            full_demo.load(self.env, allow_commit=False)
        except Exception:
            # Demo must never block module install/update.
            _logger.exception("hotel.demo.loader.load_full_demo failed")
        return True

    @api.model
    def load_dashboard_demo(self):
        """Load dashboard KPI extras (departures, status mix, books, property)."""
        from odoo.addons.hotel.demo import dashboard_demo

        try:
            dashboard_demo.load(self.env, allow_commit=False)
        except Exception:
            _logger.exception("hotel.demo.loader.load_dashboard_demo failed")
        return True
