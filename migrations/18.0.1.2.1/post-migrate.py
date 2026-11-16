# -*- coding: utf-8 -*-
"""One-shot rich demo load for databases upgraded with demo enabled.

Fresh installs run the same loaders from demo/hotel_rich_demo.xml (mode=init).
Upgrades skip <function> tags under noupdate, so this migration fills the gap.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    hotel = env["ir.module.module"].search([("name", "=", "hotel")], limit=1)
    if not hotel or not hotel.demo:
        _logger.info("hotel post-migrate: skip rich demo (demo flag off)")
        return
    loader = env["hotel.demo.loader"]
    _logger.info("hotel post-migrate: loading rich demo via hotel.demo.loader")
    loader.load_full_demo()
    loader.load_dashboard_demo()
