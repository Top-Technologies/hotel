from odoo import Command, _, api, models
from odoo.exceptions import UserError


class HotelConfig(models.AbstractModel):
    """Read access to hotel settings supporting multi-company and config parameters.

    Concrete helpers are defined here so that every hotel model resolves its
    configuration the same way.
    """

    _name = "hotel.config"
    _description = "Hotel Configuration Accessors"

    def _hotel_param(self, key, default=False, company=None):
        """Return the raw configuration value for ``key``."""
        company = company or self.env.company
        field_name = f"hotel_{key}"
        if hasattr(company, field_name):
            val = getattr(company, field_name)
            if val is not None and val is not False and val != "":
                return val
        value = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("hotel.%s" % key, default=None)
        )
        return default if value is None else value

    @api.model
    def _hotel_bool_param(self, key, default=False, company=None):
        value = self._hotel_param(key, default=default, company=company)
        if isinstance(value, bool):
            return value
        if value is None or value == "":
            return default
        return value not in ("False", "false", "0", "None")

    @api.model
    def _hotel_m2o_param(self, key, comodel_name, company=None):
        """Return the record set stored in a many2one configuration value."""
        company = company or self.env.company
        field_name = f"hotel_{key}"
        if hasattr(company, field_name):
            rec = getattr(company, field_name)
            if rec and rec.exists():
                if hasattr(rec, "company_id") and rec.company_id and rec.company_id != company:
                    pass
                elif hasattr(rec, "company_ids") and rec.company_ids and company not in rec.company_ids:
                    pass
                else:
                    return rec

        value = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("hotel.%s" % key, default=None)
        )
        if not value:
            return self.env[comodel_name].browse()
        try:
            rec_id = int(value)
        except (ValueError, TypeError):
            return self.env[comodel_name].browse()

        rec = self.env[comodel_name].browse(rec_id).exists()
        if not rec:
            return self.env[comodel_name].browse()
        if hasattr(rec, "company_id") and rec.company_id and rec.company_id != company:
            return self.env[comodel_name].browse()
        if hasattr(rec, "company_ids") and rec.company_ids and company not in rec.company_ids:
            return self.env[comodel_name].browse()
        return rec

    def _hotel_float_param(self, key, default, company=None):
        value = self._hotel_param(key, default=default, company=company)
        if isinstance(value, (int, float)):
            return float(value)
        if value in (False, "", None):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    # -------------------------------------------------------------------------
    # Housekeeping
    # -------------------------------------------------------------------------
    @api.model
    def _hotel_auto_housekeeping(self, company=None):
        """Whether a cleaning task is created automatically at check-out."""
        company = company or self.env.company
        if hasattr(company, "hotel_auto_housekeeping_on_checkout"):
            return company.hotel_auto_housekeeping_on_checkout
        return self._hotel_bool_param("auto_housekeeping_on_checkout", True, company=company)

    @api.model
    def _hotel_require_inspection(self, company=None):
        """Whether a cleaned room must be inspected before it is sellable."""
        company = company or self.env.company
        if hasattr(company, "hotel_require_inspection"):
            return company.hotel_require_inspection
        return self._hotel_bool_param("require_inspection", False, company=company)

    @api.model
    def _hotel_require_checkout_inspection(self, company=None):
        """Whether a room consumption inspection is required at check-out."""
        return self._hotel_bool_param("require_checkout_inspection", True, company=company)

    @api.model
    def _hotel_turnover_policy_default(self, company=None):
        """Hotel default policy for preparing a room for the next guest."""
        company = company or self.env.company
        policy = (
            getattr(company, "hotel_turnover_policy", None)
            or self._hotel_param("turnover_policy", company=company)
        )
        if policy not in ("replenish", "carry_forward"):
            return "replenish"
        return policy

    @api.model
    def _hotel_housekeeping_department(self, company=None):
        """The ``hr.department`` acting as the housekeeping pool."""
        return self._hotel_m2o_param(
            "housekeeping_department_id", "hr.department", company=company,
        )

    @api.model
    def _hotel_housekeeping_employee(self, company=None):
        """Employee auto-assigned to a cleaning task (single-employee pool)."""
        department = self._hotel_housekeeping_department(company=company)
        if not department:
            return self.env["hr.employee"].browse()
        employees = self.env["hr.employee"].search([("department_id", "=", department.id)])
        return employees if len(employees) == 1 else self.env["hr.employee"].browse()

    # -------------------------------------------------------------------------
    # Accounting & Invoicing
    # -------------------------------------------------------------------------
    @api.model
    def _hotel_sales_journal(self, company=None):
        """Journal used for customer invoices and guest folios."""
        company = company or self.env.company
        journal = self._hotel_m2o_param("sales_journal_id", "account.journal", company=company)
        if journal and journal.type == "sale":
            return journal
        journal = self.env["account.journal"].search(
            [
                ("type", "=", "sale"),
                *self.env["account.journal"]._check_company_domain(company),
            ],
            limit=1,
        )
        if journal:
            return journal
        # Fallback safe creation only if no sales journal exists in company
        base_code = "HSALE"
        code = base_code
        idx = 1
        while self.env["account.journal"].search_count([("code", "=", code), *self.env["account.journal"]._check_company_domain(company)]):
            code = f"HS{idx}"
            idx += 1
        journal = self.env["account.journal"].create(
            {
                "name": "Hotel Sales",
                "code": code,
                "type": "sale",
                "company_id": company.id,
            }
        )
        return journal

    @api.model
    def _hotel_payment_journal(self, company=None):
        """Journal used to settle balances at check-out."""
        company = company or self.env.company
        journal = self._hotel_m2o_param("checkout_journal_id", "account.journal", company=company)
        if journal and journal.type in ("bank", "cash", "credit"):
            return journal
        return self.env["account.journal"].search(
            [
                *self.env["account.journal"]._check_company_domain(company),
                ("type", "in", ("bank", "cash", "credit")),
            ],
            limit=1,
        )

    @api.model
    def _hotel_deposit_journal(self, company=None):
        """Journal used to collect advance deposits at booking or check-in."""
        company = company or self.env.company
        journal = self._hotel_m2o_param("deposit_journal_id", "account.journal", company=company)
        if journal and journal.type in ("bank", "cash", "credit"):
            return journal
        return self._hotel_payment_journal(company=company)

    @api.model
    def _hotel_room_charge_journal(self, company=None):
        """Bank/cash journal of the 'Charge to Room' payment method."""
        company = company or self.env.company
        journal = self._hotel_m2o_param("room_charge_journal_id", "account.journal", company=company)
        if journal and journal.type in ("bank", "cash", "credit"):
            return journal
        ref_journal = self.env.ref("hotel.room_charge_journal", raise_if_not_found=False)
        if ref_journal and ref_journal.exists() and (not ref_journal.company_id or ref_journal.company_id == company):
            return ref_journal
        # Check by code RCH in company
        journal = self.env["account.journal"].search(
            [("code", "=", "RCH"), *self.env["account.journal"]._check_company_domain(company)],
            limit=1,
        )
        if journal:
            return journal
        return self.env["account.journal"].browse()

    @api.model
    def _ensure_room_charge_journal(self, company=None):
        """Ensure room charge journal exists without duplicating existing code 'RCH'."""
        company = company or self.env.company
        journal = self._hotel_room_charge_journal(company=company)
        if not journal:
            journal = self.env["account.journal"].search(
                [("name", "=", "Room Charge"), *self.env["account.journal"]._check_company_domain(company)],
                limit=1,
            )
        if not journal:
            base_code = "RCH"
            code = base_code
            idx = 1
            while self.env["account.journal"].search_count([("code", "=", code), *self.env["account.journal"]._check_company_domain(company)]):
                code = f"RC{idx}"
                idx += 1
            journal = self.env["account.journal"].create(
                {
                    "name": "Room Charge",
                    "code": code,
                    "type": "bank",
                    "company_id": company.id,
                }
            )
        if not company.hotel_room_charge_journal_id:
            company.hotel_room_charge_journal_id = journal
        # Update XML ID if main company so legacy env.ref calls find it
        main_company = self.env.ref("base.main_company", raise_if_not_found=False)
        if not main_company or company == main_company:
            xmlid_rec = self.env.ref("hotel.room_charge_journal", raise_if_not_found=False)
            if not xmlid_rec or not xmlid_rec.exists():
                self.env["ir.model.data"].sudo()._update_xmlids(
                    [{"xml_id": "hotel.room_charge_journal", "record": journal, "noupdate": True}]
                )
        return journal

    @api.model
    def _hotel_room_charge_payment_method(self, company=None):
        """POS payment method used to charge orders to the guest folio."""
        company = company or self.env.company
        method = self._hotel_m2o_param("room_charge_payment_method_id", "pos.payment.method", company=company)
        if method:
            return method
        ref_method = self.env.ref("hotel.room_charge_payment_method", raise_if_not_found=False)
        if ref_method and ref_method.exists() and (not ref_method.company_id or ref_method.company_id == company):
            return ref_method
        method = self.env["pos.payment.method"].search(
            [("name", "=", "Charge to Room"), *self.env["pos.payment.method"]._check_company_domain(company)],
            limit=1,
        )
        if method:
            return method
        return self.env["pos.payment.method"].browse()

    @api.model
    def _ensure_room_charge_payment_method(self, company=None):
        """Ensure the 'Charge to Room' POS payment method exists."""
        company = company or self.env.company
        method = self._hotel_room_charge_payment_method(company=company)
        if not method:
            journal = self._ensure_room_charge_journal(company=company)
            clearing = self._create_room_charge_clearing_account(company=company)
            method = self.env["pos.payment.method"].create(
                {
                    "name": "Charge to Room",
                    "journal_id": journal.id,
                    "outstanding_account_id": clearing.id,
                    "split_transactions": False,
                    "is_cash_count": False,
                    "company_id": company.id,
                }
            )
        if not company.hotel_room_charge_payment_method_id:
            company.hotel_room_charge_payment_method_id = method
        main_company = self.env.ref("base.main_company", raise_if_not_found=False)
        if not main_company or company == main_company:
            xmlid_rec = self.env.ref("hotel.room_charge_payment_method", raise_if_not_found=False)
            if not xmlid_rec or not xmlid_rec.exists():
                self.env["ir.model.data"].sudo()._update_xmlids(
                    [{"xml_id": "hotel.room_charge_payment_method", "record": method, "noupdate": True}]
                )
        return method

    @api.model
    def _hotel_room_service_product(self, company=None):
        """Service product carrying room service food charges on the guest folio."""
        company = company or self.env.company
        product = self._hotel_m2o_param("room_service_product_id", "product.product", company=company)
        if product:
            return product
        tmpl = self.env.ref("hotel.room_service_pos_product", raise_if_not_found=False)
        if tmpl and tmpl.exists():
            return tmpl.product_variant_id
        product = self.env["product.product"].search(
            [("default_code", "=", "ROOMSRV"), ("company_id", "in", (False, company.id))],
            limit=1,
        )
        if product:
            return product
        return self.env["product.product"].browse()

    @api.model
    def _ensure_room_service_product(self, company=None):
        """Ensure the room service folio product exists."""
        company = company or self.env.company
        product = self._hotel_room_service_product(company=company)
        if not product:
            clearing = self._create_room_charge_clearing_account(company=company)
            tmpl = self.env["product.template"].create(
                {
                    "name": "Room Service",
                    "default_code": "ROOMSRV",
                    "type": "service",
                    "sale_ok": True,
                    "purchase_ok": False,
                    "list_price": 0.0,
                    "available_in_pos": False,
                    "taxes_id": [Command.clear()],
                    "supplier_taxes_id": [Command.clear()],
                    "property_account_income_id": clearing.id,
                    "company_id": False,
                }
            )
            product = tmpl.product_variant_id
        if not company.hotel_room_service_product_id:
            company.hotel_room_service_product_id = product
        main_company = self.env.ref("base.main_company", raise_if_not_found=False)
        if not main_company or company == main_company:
            xmlid_rec = self.env.ref("hotel.room_service_pos_product", raise_if_not_found=False)
            if not xmlid_rec or not xmlid_rec.exists():
                self.env["ir.model.data"].sudo()._update_xmlids(
                    [{"xml_id": "hotel.room_service_pos_product", "record": product.product_tmpl_id, "noupdate": True}]
                )
        return product

    @api.model
    def _create_room_charge_clearing_account(self, company=None):
        """Create or recover the account used to charge food to the guest folio."""
        company = company or self.env.company
        account = self._hotel_m2o_param(
            "room_charge_clearing_account_id", "account.account", company=company,
        )
        if account and account.account_type == "asset_current":
            return account

        xmlid = "hotel.room_charge_clearing_account"
        account = self.env.ref(xmlid, raise_if_not_found=False)
        if account and (not account.company_ids or company in account.company_ids):
            if account.account_type != "asset_current":
                account.account_type = "asset_current"
            return account

        Account = self.env["account.account"]
        account = Account.search(
            [
                ("code", "=", "RCHG"),
                ("company_ids", "in", company.id),
            ],
            limit=1,
        )
        if not account:
            vals = {
                "name": _("Room Charge Clearing"),
                "code": "RCHG",
                "account_type": "asset_current",
                "company_ids": [Command.set(company.ids)],
            }
            if "create_asset" in Account._fields:
                vals["create_asset"] = "no"
            account = Account.create(vals)

        if account.account_type != "asset_current":
            account.account_type = "asset_current"

        main_company = self.env.ref("base.main_company", raise_if_not_found=False)
        if not main_company or company == main_company:
            data = self.env["ir.model.data"].sudo().search(
                [
                    ("module", "=", "hotel"),
                    ("name", "=", "room_charge_clearing_account"),
                ],
                limit=1,
            )
            if data:
                data.write({"res_id": account.id})
            else:
                self.env["ir.model.data"].sudo().create(
                    {
                        "module": "hotel",
                        "name": "room_charge_clearing_account",
                        "model": "account.account",
                        "res_id": account.id,
                        "noupdate": True,
                    },
                )
        return account

    @api.model
    def _hotel_receivable_account(self, company=None):
        """Return the company receivable account, creating it once if missing."""
        company = company or self.env.company
        account = self._hotel_m2o_param("receivable_account_id", "account.account", company=company)
        if account and account.account_type == "asset_receivable":
            return account
        Account = self.env["account.account"]
        account = Account.search(
            [
                ("account_type", "=", "asset_receivable"),
                *Account._check_company_domain(company),
            ],
            limit=1,
        )
        if account:
            return account
        xmlid = "hotel.hotel_receivable_account"
        account = self.env.ref(xmlid, raise_if_not_found=False)
        if account and (not account.company_ids or company in account.company_ids):
            return account
        vals = {
            "name": _("Account Receivable"),
            "code": "121000",
            "account_type": "asset_receivable",
            "reconcile": True,
            "company_ids": [Command.set(company.ids)],
        }
        if "create_asset" in Account._fields:
            vals["create_asset"] = "no"
        account = Account.with_company(company).create(vals)
        main_company = self.env.ref("base.main_company", raise_if_not_found=False)
        if not main_company or company == main_company:
            self.env["ir.model.data"].sudo().create(
                {
                    "module": "hotel",
                    "name": "hotel_receivable_account",
                    "model": "account.account",
                    "res_id": account.id,
                    "noupdate": True,
                },
            )
        partner = company.partner_id.with_company(company)
        if not partner.property_account_receivable_id:
            partner.property_account_receivable_id = account
        return account

    @api.model
    def _hotel_income_account(self, company=None):
        """Return the company income account, creating it once if missing."""
        company = company or self.env.company
        account = self._hotel_m2o_param("income_account_id", "account.account", company=company)
        if account and account.account_type in ("income", "income_other"):
            return account
        Account = self.env["account.account"]
        account = Account.search(
            [
                ("account_type", "=", "income"),
                *Account._check_company_domain(company),
            ],
            limit=1,
        )
        if account:
            return account
        xmlid = "hotel.hotel_income_account"
        account = self.env.ref(xmlid, raise_if_not_found=False)
        if account and (not account.company_ids or company in account.company_ids):
            return account
        vals = {
            "name": _("Room Revenue"),
            "code": "400000",
            "account_type": "income",
            "company_ids": [Command.set(company.ids)],
        }
        if "create_asset" in Account._fields:
            vals["create_asset"] = "no"
        account = Account.with_company(company).create(vals)
        main_company = self.env.ref("base.main_company", raise_if_not_found=False)
        if not main_company or company == main_company:
            self.env["ir.model.data"].sudo().create(
                {
                    "module": "hotel",
                    "name": "hotel_income_account",
                    "model": "account.account",
                    "res_id": account.id,
                    "noupdate": True,
                },
            )
        return account

    @api.model
    def _hotel_default_product(self, company=None):
        """Default service product used for room revenue."""
        return self._hotel_m2o_param("default_product_id", "product.product", company=company)

    @api.model
    def _hotel_default_taxes(self, company=None):
        """Default taxes applied to room revenue charges."""
        company = company or self.env.company
        if hasattr(company, "hotel_default_tax_ids") and company.hotel_default_tax_ids:
            return company.hotel_default_tax_ids
        tax_ids_str = self._hotel_param("default_tax_ids", "", company=company)
        if not tax_ids_str:
            return self.env["account.tax"].browse()
        ids = [int(i) for i in str(tax_ids_str).split(",") if str(i).strip().isdigit()]
        return self.env["account.tax"].browse(ids).exists()

    # -------------------------------------------------------------------------
    # Room Service / POS
    # -------------------------------------------------------------------------
    @api.model
    def _hotel_pos_room_service_config(self, company=None):
        """Point of Sale receiving the room service orders."""
        company = company or self.env.company
        config = self._hotel_m2o_param("pos_room_service_config_id", "pos.config", company=company)
        if config:
            return config
        return self._ensure_hotel_room_service_pos(company=company)

    @api.model
    def _ensure_hotel_room_service_pos(self, company=None):
        """Create or recover dedicated Hotel Room Service POS config."""
        company = company or self.env.company
        PosConfig = self.env["pos.config"].sudo()
        method = self._ensure_room_charge_payment_method(company=company)
        config = self.env.ref("hotel.pos_config_room_service", raise_if_not_found=False)
        if config and config.company_id and config.company_id != company:
            config = PosConfig.browse()
        if not config:
            config = PosConfig.search(
                [("name", "=", "Hotel Room Service"), *PosConfig._check_company_domain(company)],
                limit=1,
            )
        if not config:
            self.env.cr.execute(
                """
                SELECT column_name FROM information_schema.columns
                 WHERE table_name = 'pos_config'
                   AND column_name LIKE 'self_ordering%%'
                   AND is_nullable = 'NO'
                   AND column_default IS NULL
                """
            )
            defaults = {
                "self_ordering_mode": "'nothing'",
                "self_ordering_service_mode": "'counter'",
                "self_ordering_pay_after": "'meal'",
            }
            for (column,) in self.env.cr.fetchall():
                default_sql = defaults.get(column)
                if default_sql:
                    self.env.cr.execute(
                        f"ALTER TABLE pos_config ALTER COLUMN {column} SET DEFAULT {default_sql}"
                    )
            vals = {"name": "Hotel Room Service", "company_id": company.id}
            if "module_pos_restaurant" in PosConfig._fields:
                vals["module_pos_restaurant"] = False
            if "self_ordering_mode" in PosConfig._fields:
                vals["self_ordering_mode"] = "nothing"
            if "self_ordering_service_mode" in PosConfig._fields:
                vals["self_ordering_service_mode"] = "counter"
            if method:
                vals["payment_method_ids"] = [Command.set(method.ids)]
            config = PosConfig.create(vals)
            main_company = self.env.ref("base.main_company", raise_if_not_found=False)
            if not main_company or company == main_company:
                self.env["ir.model.data"].sudo()._update_xmlids(
                    [
                        {
                            "xml_id": "hotel.pos_config_room_service",
                            "record": config,
                            "noupdate": True,
                        }
                    ],
                )
        elif method and method not in config.payment_method_ids:
            config.write({"payment_method_ids": [Command.link(method.id)]})

        if not company.hotel_pos_room_service_config_id:
            company.hotel_pos_room_service_config_id = config
        return config

    # -------------------------------------------------------------------------
    # Inventory & Stock Locations
    # -------------------------------------------------------------------------
    @api.model
    def _hotel_room_location(self, company=None):
        """Stock location holding supplies kept in the guest rooms."""
        company = company or self.env.company
        location = self._hotel_m2o_param("room_location_id", "stock.location", company=company)
        if location:
            return location
        ref_loc = self.env.ref("hotel.hotel_location_rooms", raise_if_not_found=False)
        if ref_loc and ref_loc.exists() and (not ref_loc.company_id or ref_loc.company_id == company):
            return ref_loc
        return (
            self.env["stock.location"].search(
                [("name", "=", "Hotel Rooms"), ("usage", "=", "internal"), *self.env["stock.location"]._check_company_domain(company)],
                limit=1,
            )
            or self.env["stock.location"].browse()
        )

    @api.model
    def _hotel_consumption_location(self, company=None):
        """Stock location of supplies consumed in the guest rooms."""
        company = company or self.env.company
        location = self._hotel_m2o_param("consumption_location_id", "stock.location", company=company)
        if location:
            return location
        ref_loc = self.env.ref("hotel.hotel_location_consumption", raise_if_not_found=False)
        if ref_loc and ref_loc.exists() and (not ref_loc.company_id or ref_loc.company_id == company):
            return ref_loc
        return (
            self.env["stock.location"].search(
                [("name", "=", "Hotel Room Consumption"), ("usage", "in", ("customer", "inventory")), *self.env["stock.location"]._check_company_domain(company)],
                limit=1,
            )
            or self.env["stock.location"].browse()
        )

    @api.model
    def _hotel_supplies_return_location(self, company=None):
        """Internal storage where unused room supplies are returned."""
        company = company or self.env.company
        location = self._hotel_m2o_param("supplies_return_location_id", "stock.location", company=company)
        if location:
            return location
        room_location = self._hotel_room_location(company=company)
        if room_location and room_location.location_id:
            return room_location.location_id
        return (
            self.env["stock.location"].search(
                [("usage", "=", "internal"), *self.env["stock.location"]._check_company_domain(company)],
                limit=1,
            )
            or self.env.ref("stock.stock_location_stock", raise_if_not_found=False)
            or self.env["stock.location"].browse()
        )

    @api.model
    def _hotel_kitchen_location(self, company=None):
        """Stock location of the hotel kitchen / F&B store."""
        company = company or self.env.company
        location = self._hotel_m2o_param("kitchen_location_id", "stock.location", company=company)
        if location:
            return location
        ref_loc = self.env.ref("hotel.hotel_location_kitchen", raise_if_not_found=False)
        if ref_loc and ref_loc.exists() and (not ref_loc.company_id or ref_loc.company_id == company):
            return ref_loc
        return (
            self.env["stock.location"].search(
                [("name", "=", "Hotel Kitchen"), ("usage", "=", "internal"), *self.env["stock.location"]._check_company_domain(company)],
                limit=1,
            )
            or self.env["stock.location"].browse()
        )

    @api.model
    def _hotel_storeroom_location(self, company=None):
        """Main internal storeroom location from which guest rooms are replenished."""
        company = company or self.env.company
        location = self._hotel_m2o_param("storeroom_location_id", "stock.location", company=company)
        if location:
            return location
        room_location = self._hotel_room_location(company=company)
        if room_location and room_location.location_id:
            return room_location.location_id
        return (
            self.env["stock.location"].search(
                [("usage", "=", "internal"), *self.env["stock.location"]._check_company_domain(company)],
                limit=1,
            )
            or self.env.ref("stock.stock_location_stock", raise_if_not_found=False)
            or self.env["stock.location"].browse()
        )

    @api.model
    def _hotel_housekeeping_cart_location(self, company=None):
        """Internal location holding buffer supplies on the housekeeping staff cart."""
        company = company or self.env.company
        location = self._hotel_m2o_param("housekeeping_cart_location_id", "stock.location", company=company)
        if location:
            return location
        cart_loc = self.env.ref("hotel.hotel_location_housekeeping_cart", raise_if_not_found=False)
        if cart_loc and cart_loc.exists() and (not cart_loc.company_id or cart_loc.company_id == company):
            return cart_loc
        return self._hotel_storeroom_location(company=company)

    @api.model
    def _hotel_internal_picking_type(self, company=None):
        """Internal transfer type used to move supplies out of the rooms."""
        company = company or self.env.company
        custom_type = self._hotel_m2o_param("internal_picking_type_id", "stock.picking.type", company=company)
        if custom_type:
            return custom_type
        hotel_type = self.env.ref("hotel.hotel_picking_type_internal", raise_if_not_found=False)
        if hotel_type and hotel_type.exists() and (not hotel_type.warehouse_id or hotel_type.warehouse_id.company_id == company):
            return hotel_type
        picking_type = self.env["stock.picking.type"].search(
            [
                ("code", "=", "internal"),
                ("warehouse_id.company_id", "=", company.id),
            ],
            limit=1,
        )
        if picking_type:
            return picking_type
        return self.env["stock.picking.type"].with_context(active_test=False).search([("code", "=", "internal")], limit=1)

    # -------------------------------------------------------------------------
    # Reservation Defaults
    # -------------------------------------------------------------------------
    @api.model
    def _hotel_default_checkin_time(self, company=None):
        return self._hotel_float_param("default_checkin_time", 14.0, company=company)

    @api.model
    def _hotel_default_checkout_time(self, company=None):
        return self._hotel_float_param("default_checkout_time", 11.0, company=company)

    @api.model
    def _hotel_default_booking_duration(self, company=None):
        company = company or self.env.company
        val = getattr(company, "hotel_default_booking_duration", None)
        if val:
            return int(val)
        val = self._hotel_param("default_booking_duration", company=company)
        try:
            return int(val) if val else 1
        except (ValueError, TypeError):
            return 1

    @api.model
    def _hotel_reservation_confirmation_policy(self, company=None):
        company = company or self.env.company
        policy = getattr(company, "hotel_reservation_confirmation_policy", None) or self._hotel_param("reservation_confirmation_policy", company=company)
        if policy not in ("manual", "deposit", "auto"):
            return "manual"
        return policy

    @api.model
    def _hotel_cancellation_policy(self, company=None):
        company = company or self.env.company
        policy = getattr(company, "hotel_cancellation_policy", None) or self._hotel_param("cancellation_policy", company=company)
        if policy not in ("free", "deposit_forfeit", "penalty"):
            return "free"
        return policy

    @api.model
    def _hotel_default_reservation_state(self, company=None):
        company = company or self.env.company
        state = getattr(company, "hotel_default_reservation_state", None) or self._hotel_param("default_reservation_state", company=company)
        if state not in ("draft", "confirmed"):
            return "draft"
        return state

    # -------------------------------------------------------------------------
    # Room Consumption Defaults
    # -------------------------------------------------------------------------
    @api.model
    def _hotel_consumable_standard_qty(self, company=None):
        return self._hotel_float_param("consumable_standard_qty", 0.0, company=company)

    @api.model
    def _hotel_consumable_allowance_qty(self, company=None):
        return self._hotel_float_param("consumable_allowance_qty", 0.0, company=company)

    @api.model
    def _hotel_consumable_allowance_scope(self, company=None):
        company = company or self.env.company
        scope = getattr(company, "hotel_consumable_allowance_scope", None) or self._hotel_param("consumable_allowance_scope", company=company)
        if scope not in ("stay", "day", "guest"):
            return "stay"
        return scope

    @api.model
    def _hotel_consumable_allowance_price(self, company=None):
        return self._hotel_float_param("consumable_allowance_price", 0.0, company=company)

    @api.model
    def _hotel_consumable_replenishment_policy(self, company=None):
        company = company or self.env.company
        policy = getattr(company, "hotel_consumable_replenishment_policy", None) or self._hotel_param("consumable_replenishment_policy", company=company)
        if policy not in ("replenish", "carry_forward"):
            return "replenish"
        return policy

    # -------------------------------------------------------------------------
    # Approvals & Discounts
    # -------------------------------------------------------------------------
    @api.model
    def _hotel_require_rate_approval(self, company=None):
        """Whether room rate changes must go through the approval workflow."""
        company = company or self.env.company
        if hasattr(company, "hotel_require_rate_approval"):
            return company.hotel_require_rate_approval
        return self._hotel_bool_param("require_rate_approval", True, company=company)

    @api.model
    def _hotel_require_discount_approval(self, company=None):
        """Whether a discount above the free threshold must be approved."""
        company = company or self.env.company
        if hasattr(company, "hotel_require_discount_approval"):
            return company.hotel_require_discount_approval
        return self._hotel_bool_param("require_discount_approval", True, company=company)

    @api.model
    def _hotel_discount_free_pct(self, company=None):
        """Discount a front-desk user may grant without approval (0-5%)."""
        return self._hotel_float_param("discount_free_pct", 5.0, company=company)

    @api.model
    def _hotel_discount_manager_pct(self, company=None):
        """Discount a hotel manager may grant (up to 15%)."""
        return self._hotel_float_param("discount_manager_pct", 15.0, company=company)

    @api.model
    def _discount_level(self, discount_pct, rule_level="none", company=None):
        """Authorization level required for ``discount_pct``."""
        if discount_pct <= self._hotel_discount_free_pct(company=company):
            level = "none"
        elif discount_pct <= self._hotel_discount_manager_pct(company=company):
            level = "manager"
        else:
            level = "general_manager"
        if rule_level == "general_manager":
            return "general_manager"
        if rule_level == "manager" and level == "none":
            return "manager"
        return level

    # -------------------------------------------------------------------------
    # Centralized Validation
    # -------------------------------------------------------------------------
    @api.model
    def validate_accounting_config(
        self,
        company=None,
        check_sales=True,
        check_checkout=False,
        check_deposit=False,
        check_room_charge=False,
    ):
        """Centralized validation for hotel accounting configuration."""
        company = company or self.env.company
        errors = []

        if check_sales:
            journal = self._hotel_sales_journal(company=company)
            if not journal:
                errors.append(_("Hotel Sales Journal is not configured for company '%s'.", company.name))
            elif journal.type != "sale":
                errors.append(_("Hotel Sales Journal '%s' must be of type 'Sale'.", journal.name))
            elif journal.company_id and journal.company_id != company:
                errors.append(_("Hotel Sales Journal '%s' belongs to company '%s', not '%s'.", journal.name, journal.company_id.name, company.name))

            income = self._hotel_income_account(company=company)
            if not income:
                errors.append(_("Room Revenue Account is not configured for company '%s'.", company.name))
            elif income.account_type not in ("income", "income_other"):
                errors.append(_("Room Revenue Account '%s' must have account type Income or Other Income.", income.code))
            elif income.company_ids and company not in income.company_ids:
                errors.append(_("Room Revenue Account '%s' is not accessible to company '%s'.", income.code, company.name))

            receivable = self._hotel_receivable_account(company=company)
            if not receivable:
                errors.append(_("Hotel Receivable Account is not configured for company '%s'.", company.name))
            elif receivable.account_type != "asset_receivable":
                errors.append(_("Hotel Receivable Account '%s' must have account type Receivable.", receivable.code))
            elif receivable.company_ids and company not in receivable.company_ids:
                errors.append(_("Hotel Receivable Account '%s' is not accessible to company '%s'.", receivable.code, company.name))

        if check_checkout:
            journal = self._hotel_payment_journal(company=company)
            if not journal:
                errors.append(_("Check-out Payment Journal is not configured for company '%s'.", company.name))
            elif journal.type not in ("bank", "cash", "credit"):
                errors.append(_("Check-out Payment Journal '%s' must be Bank or Cash.", journal.name))
            elif journal.company_id and journal.company_id != company:
                errors.append(_("Check-out Payment Journal '%s' belongs to company '%s', not '%s'.", journal.name, journal.company_id.name, company.name))

        if check_deposit:
            journal = self._hotel_deposit_journal(company=company)
            if not journal:
                errors.append(_("Deposit Payment Journal is not configured for company '%s'.", company.name))
            elif journal.type not in ("bank", "cash", "credit"):
                errors.append(_("Deposit Payment Journal '%s' must be Bank or Cash.", journal.name))
            elif journal.company_id and journal.company_id != company:
                errors.append(_("Deposit Payment Journal '%s' belongs to company '%s', not '%s'.", journal.name, journal.company_id.name, company.name))

        if check_room_charge:
            journal = self._hotel_room_charge_journal(company=company)
            if not journal:
                errors.append(_("Room Charge Journal is not configured for company '%s'.", company.name))
            elif journal.type not in ("bank", "cash", "credit"):
                errors.append(_("Room Charge Journal '%s' must be Bank or Cash.", journal.name))
            elif journal.company_id and journal.company_id != company:
                errors.append(_("Room Charge Journal '%s' belongs to company '%s', not '%s'.", journal.name, journal.company_id.name, company.name))

            clearing = self._create_room_charge_clearing_account(company=company)
            if not clearing:
                errors.append(_("Room Charge Clearing Account is not configured for company '%s'.", company.name))
            elif clearing.account_type != "asset_current":
                errors.append(_("Room Charge Clearing Account '%s' must have account type Current Assets.", clearing.code))
            elif clearing.company_ids and company not in clearing.company_ids:
                errors.append(_("Room Charge Clearing Account '%s' is not accessible to company '%s'.", clearing.code, company.name))

        if errors:
            raise UserError(_("Accounting Configuration Errors:\n• %s\n\nPlease check Hotel Settings.", "\n• ".join(errors)))
        return True

    @api.model
    def validate_pos_config(self, company=None):
        """Centralized validation for hotel Room Service POS configuration."""
        company = company or self.env.company
        errors = []

        pos_config = self._hotel_pos_room_service_config(company=company)
        if not pos_config:
            errors.append(_("Room Service Point of Sale configuration is missing for company '%s'.", company.name))
        elif pos_config.company_id and pos_config.company_id != company:
            errors.append(_("Room Service Point of Sale '%s' belongs to company '%s', not '%s'.", pos_config.name, pos_config.company_id.name, company.name))

        method = self._hotel_room_charge_payment_method(company=company)
        if not method:
            errors.append(_("Room Charge Payment Method is not configured for company '%s'.", company.name))
        elif pos_config and method not in pos_config.payment_method_ids:
            errors.append(_("Room Charge Payment Method '%s' is not assigned to Point of Sale '%s'.", method.name, pos_config.name))
        elif method.company_id and method.company_id != company:
            errors.append(_("Room Charge Payment Method '%s' belongs to company '%s', not '%s'.", method.name, method.company_id.name, company.name))

        journal = self._hotel_room_charge_journal(company=company) or (method and method.journal_id)
        if not journal:
            errors.append(_("Room Charge Journal is not configured for company '%s'.", company.name))
        elif journal.company_id and journal.company_id != company:
            errors.append(_("Room Charge Journal '%s' belongs to company '%s', not '%s'.", journal.name, journal.company_id.name, company.name))

        clearing = self._create_room_charge_clearing_account(company=company)
        if not clearing:
            errors.append(_("Room Charge Clearing Account is missing for company '%s'.", company.name))
        elif clearing.account_type != "asset_current":
            errors.append(_("Room Charge Clearing Account '%s' must have account type Current Assets.", clearing.code))

        product = self._hotel_room_service_product(company=company)
        if not product:
            errors.append(_("Room Service Folio Product is not configured for company '%s'.", company.name))
        elif product.type != "service":
            errors.append(_("Room Service Folio Product '%s' must be a service product.", product.display_name))

        if errors:
            raise UserError(_("Room Service POS Configuration Errors:\n• %s\n\nPlease check Hotel Settings.", "\n• ".join(errors)))
        return True

    @api.model
    def validate_inventory_config(
        self,
        company=None,
        check_supplies=True,
        check_consumption=False,
        check_kitchen=False,
    ):
        """Centralized validation for hotel inventory configuration."""
        company = company or self.env.company
        errors = []

        if check_supplies:
            room_loc = self._hotel_room_location(company=company)
            if not room_loc:
                errors.append(_("Hotel Rooms Location is not configured for company '%s'.", company.name))
            elif room_loc.usage != "internal":
                errors.append(_("Hotel Rooms Location '%s' must be an internal location.", room_loc.display_name))
            elif room_loc.company_id and room_loc.company_id != company:
                errors.append(_("Hotel Rooms Location '%s' belongs to company '%s', not '%s'.", room_loc.display_name, room_loc.company_id.name, company.name))

            cart_loc = self._hotel_housekeeping_cart_location(company=company)
            if not cart_loc:
                errors.append(_("Housekeeping Cart Location is not configured for company '%s'.", company.name))
            elif cart_loc.usage != "internal":
                errors.append(_("Housekeeping Cart Location '%s' must be an internal location.", cart_loc.display_name))
            elif cart_loc.company_id and cart_loc.company_id != company:
                errors.append(_("Housekeeping Cart Location '%s' belongs to company '%s', not '%s'.", cart_loc.display_name, cart_loc.company_id.name, company.name))

            picking_type = self._hotel_internal_picking_type(company=company)
            if not picking_type:
                errors.append(_("Room Supplies Operation Type is not configured for company '%s'.", company.name))
            elif picking_type.code != "internal":
                errors.append(_("Room Supplies Operation Type '%s' must be an internal transfer operation.", picking_type.name))
            elif picking_type.warehouse_id and picking_type.warehouse_id.company_id != company:
                errors.append(_("Room Supplies Operation Type '%s' belongs to company '%s', not '%s'.", picking_type.name, picking_type.warehouse_id.company_id.name, company.name))

        if check_consumption:
            cons_loc = self._hotel_consumption_location(company=company)
            if not cons_loc:
                errors.append(_("Room Consumption Location is not configured for company '%s'.", company.name))
            elif cons_loc.usage not in ("customer", "inventory"):
                errors.append(_("Room Consumption Location '%s' must be a customer or inventory loss location.", cons_loc.display_name))
            elif cons_loc.company_id and cons_loc.company_id != company:
                errors.append(_("Room Consumption Location '%s' belongs to company '%s', not '%s'.", cons_loc.display_name, cons_loc.company_id.name, company.name))

        if check_kitchen:
            kitchen_loc = self._hotel_kitchen_location(company=company)
            if not kitchen_loc:
                errors.append(_("Hotel Kitchen Location is not configured for company '%s'.", company.name))
            elif kitchen_loc.usage != "internal":
                errors.append(_("Hotel Kitchen Location '%s' must be an internal location.", kitchen_loc.display_name))

        if errors:
            raise UserError(_("Inventory Configuration Errors:\n• %s\n\nPlease check Hotel Settings.", "\n• ".join(errors)))
        return True

    @api.model
    def validate_housekeeping_config(self, company=None):
        """Centralized validation for hotel housekeeping configuration."""
        company = company or self.env.company
        errors = []
        dept = self._hotel_housekeeping_department(company=company)
        if dept and dept.company_id and dept.company_id != company:
            errors.append(_("Housekeeping Department '%s' belongs to company '%s', not '%s'.", dept.name, dept.company_id.name, company.name))
        policy = self._hotel_turnover_policy_default(company=company)
        if policy not in ("replenish", "carry_forward"):
            errors.append(_("Invalid room turnover policy '%s'. Must be replenish or carry_forward.", policy))
        if errors:
            raise UserError(_("Housekeeping Configuration Errors:\n• %s\n\nPlease check Hotel Settings.", "\n• ".join(errors)))
        return True

    @api.model
    def _hotel_stock_move_vals(
        self,
        product,
        qty,
        location,
        location_dest,
        description=None,
    ):
        """Odoo stock.move values for hotel internal transfers."""
        product.ensure_one()
        return {
            "description_picking_manual": description or product.display_name,
            "product_id": product.id,
            "product_uom_qty": qty,
            "product_uom": product.uom_id.id,
            "location_id": location.id,
            "location_dest_id": location_dest.id,
        }
