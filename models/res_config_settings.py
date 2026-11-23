from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # Housekeeping
    hotel_require_inspection = fields.Boolean(
        string="Require Cleaning Inspection",
        related="company_id.hotel_require_inspection",
        readonly=False,
        help="When enabled a cleaned room stays out of the sellable pool until "
        "a supervisor inspects it.",
    )
    hotel_auto_housekeeping_on_checkout = fields.Boolean(
        string="Housekeeping Task on Check-out",
        related="company_id.hotel_auto_housekeeping_on_checkout",
        readonly=False,
        help="Create a cleaning task automatically when a guest checks out.",
    )
    hotel_housekeeping_department_id = fields.Many2one(
        comodel_name="hr.department",
        string="Housekeeping Team",
        related="company_id.hotel_housekeeping_department_id",
        readonly=False,
        help="Team acting as the housekeeping pool. When it has a single "
        "member, cleaning tasks are assigned to that employee automatically.",
    )
    hotel_turnover_policy = fields.Selection(
        related="company_id.hotel_turnover_policy",
        readonly=False,
        string="Default Room Turnover Policy",
        help="How a room is prepared for the next guest after check-out.",
    )

    # Accounting & Invoicing
    hotel_sales_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Hotel Sales Journal",
        related="company_id.hotel_sales_journal_id",
        readonly=False,
        domain="[('type', '=', 'sale')]",
        help="Journal used to create customer invoices for guest folios. Empty "
        "means the default sales journal of the company.",
    )
    hotel_checkout_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Check-out Payment Journal",
        related="company_id.hotel_checkout_journal_id",
        readonly=False,
        domain="[('type', 'in', ('bank', 'cash', 'credit'))]",
        help="Journal used to settle the guest balance at check-out. Empty "
        "means the first bank, cash or credit card journal of the company.",
    )
    hotel_deposit_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Deposit Payment Journal",
        related="company_id.hotel_deposit_journal_id",
        readonly=False,
        domain="[('type', 'in', ('bank', 'cash', 'credit'))]",
        help="Journal used to collect advance deposits at booking or check-in. "
        "Empty falls back to the check-out payment journal.",
    )
    hotel_room_charge_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Room Charge Journal",
        related="company_id.hotel_room_charge_journal_id",
        readonly=False,
        domain="[('type', 'in', ('bank', 'cash', 'credit'))]",
        help="Bank/cash journal used by the 'Charge to Room' POS payment method.",
    )
    hotel_income_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Room Revenue Account",
        related="company_id.hotel_income_account_id",
        readonly=False,
        domain="[('account_type', 'in', ('income', 'income_other'))]",
        help="Default income account for room accommodation revenue when not "
        "set on the room type or product.",
    )
    hotel_receivable_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Hotel Receivable Account",
        related="company_id.hotel_receivable_account_id",
        readonly=False,
        domain="[('account_type', '=', 'asset_receivable')]",
        help="Default customer receivable account for hotel guests.",
    )
    hotel_room_charge_clearing_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Room Charge Clearing Account",
        related="company_id.hotel_room_charge_clearing_account_id",
        readonly=False,
        domain="[('account_type', '=', 'asset_current')]",
        help="Clearing account used to bridge Point of Sale and room service "
        "charges to the guest folio.",
    )
    hotel_default_product_id = fields.Many2one(
        comodel_name="product.product",
        string="Default Room Revenue Product",
        related="company_id.hotel_default_product_id",
        readonly=False,
        domain="[('type', '=', 'service')]",
        help="Default service product invoiced for room stays if the room type "
        "has no specific product assigned.",
    )
    hotel_default_tax_ids = fields.Many2many(
        comodel_name="account.tax",
        related="company_id.hotel_default_tax_ids",
        readonly=False,
        domain="[('type_tax_use', '=', 'sale')]",
        help="Default customer taxes applied to room charges if not configured "
        "on the room type or product.",
    )

    # Room Service / Point of Sale
    hotel_pos_room_service_config_id = fields.Many2one(
        comodel_name="pos.config",
        string="Room Service Point of Sale",
        related="company_id.hotel_pos_room_service_config_id",
        readonly=False,
        help="Point of Sale receiving the food orders taken from the Room "
        "Service screen. Empty means the Main Restaurant Point of Sale.",
    )
    hotel_room_charge_payment_method_id = fields.Many2one(
        comodel_name="pos.payment.method",
        string="Room Charge Payment Method",
        related="company_id.hotel_room_charge_payment_method_id",
        readonly=False,
        help="POS payment method used to charge restaurant/room service orders to the guest folio.",
    )
    hotel_room_service_product_id = fields.Many2one(
        comodel_name="product.product",
        string="Room Service Folio Product",
        related="company_id.hotel_room_service_product_id",
        readonly=False,
        domain="[('type', '=', 'service')]",
        help="Service product carrying room service food charges on the guest folio invoice.",
    )

    # Inventory / Stock Locations
    hotel_room_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Hotel Rooms Location",
        related="company_id.hotel_room_location_id",
        readonly=False,
        domain="[('usage', '=', 'internal')]",
        help="Inventory location holding the supplies and minibar stock kept "
        "in the guest rooms.",
    )
    hotel_consumption_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Room Consumption Location",
        related="company_id.hotel_consumption_location_id",
        readonly=False,
        domain="[('usage', 'in', ('customer', 'inventory'))]",
        help="Destination of posted room consumption. The standard stock "
        "valuation relieves the inventory from this location.",
    )
    hotel_kitchen_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Hotel Kitchen Location",
        related="company_id.hotel_kitchen_location_id",
        readonly=False,
        domain="[('usage', '=', 'internal')]",
        help="Kitchen or F&B store location holding ingredients and prepared items.",
    )
    hotel_storeroom_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Hotel Storeroom Location",
        related="company_id.hotel_storeroom_location_id",
        readonly=False,
        domain="[('usage', '=', 'internal')]",
        help="Main internal storeroom location from which guest rooms are replenished.",
    )
    hotel_housekeeping_cart_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Housekeeping Cart Location",
        related="company_id.hotel_housekeeping_cart_location_id",
        readonly=False,
        domain="[('usage', '=', 'internal')]",
        help="Internal location representing the housekeeping cart or staff buffer stock from which guest rooms are refilled.",
    )
    hotel_internal_picking_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="Room Supplies Operation Type",
        related="company_id.hotel_internal_picking_type_id",
        readonly=False,
        domain="[('code', '=', 'internal')]",
        help="Internal transfer operation type used to move supplies out of rooms or replenish them.",
    )

    # Reservation Defaults
    hotel_default_checkin_time = fields.Float(
        string="Default Check-in Time",
        related="company_id.hotel_default_checkin_time",
        readonly=False,
        help="Default check-in hour of day (e.g. 14.0 for 14:00).",
    )
    hotel_default_checkout_time = fields.Float(
        string="Default Check-out Time",
        related="company_id.hotel_default_checkout_time",
        readonly=False,
        help="Default check-out hour of day (e.g. 11.0 for 11:00).",
    )
    hotel_default_booking_duration = fields.Integer(
        string="Default Booking Duration (Nights)",
        related="company_id.hotel_default_booking_duration",
        readonly=False,
        help="Default stay duration in nights for new reservations.",
    )
    hotel_reservation_confirmation_policy = fields.Selection(
        related="company_id.hotel_reservation_confirmation_policy",
        readonly=False,
        string="Reservation Confirmation Policy",
        help="Policy for confirming newly created reservations.",
    )
    hotel_cancellation_policy = fields.Selection(
        related="company_id.hotel_cancellation_policy",
        readonly=False,
        string="Cancellation Policy",
        help="Default hotel cancellation terms.",
    )
    hotel_default_reservation_state = fields.Selection(
        related="company_id.hotel_default_reservation_state",
        readonly=False,
        string="Default Reservation Status",
        help="Initial state for new reservations when created.",
    )
    hotel_breakfast_price = fields.Float(
        string="Breakfast Price / Guest / Night",
        related="company_id.hotel_breakfast_price",
        readonly=False,
        help="Default breakfast charge per eligible guest per night.",
    )

    # Room Consumption Defaults
    hotel_consumable_standard_qty = fields.Float(
        string="Default Standard Quantity",
        related="company_id.hotel_consumable_standard_qty",
        readonly=False,
        help="Fallback par level quantity for room consumables.",
    )
    hotel_consumable_allowance_qty = fields.Float(
        string="Default Allowance Quantity",
        related="company_id.hotel_consumable_allowance_qty",
        readonly=False,
        help="Fallback complimentary allowance quantity.",
    )
    hotel_consumable_allowance_scope = fields.Selection(
        related="company_id.hotel_consumable_allowance_scope",
        readonly=False,
        string="Default Allowance Scope",
        help="Fallback allowance scope when not configured on room or product.",
    )
    hotel_consumable_allowance_price = fields.Float(
        string="Default Excess Consumption Price",
        related="company_id.hotel_consumable_allowance_price",
        readonly=False,
        help="Fallback chargeable price unit for excess consumption.",
    )
    hotel_consumable_replenishment_policy = fields.Selection(
        related="company_id.hotel_consumable_replenishment_policy",
        readonly=False,
        string="Default Replenishment Policy",
        help="Fallback replenishment policy for consumables.",
    )

    # Approvals
    hotel_require_rate_approval = fields.Boolean(
        string="Require Room Rate Approval",
        related="company_id.hotel_require_rate_approval",
        readonly=False,
        help="Block direct changes of a room type rate: every change must be "
        "requested through a Room Rate Change document.",
    )
    hotel_require_discount_approval = fields.Boolean(
        string="Require Discount Approval",
        related="company_id.hotel_require_discount_approval",
        readonly=False,
        help="Block discounts above the free threshold on a stay unless an "
        "approved discount request covers them.",
    )
    hotel_discount_free_pct = fields.Float(
        string="Free Discount Threshold (%)",
        related="company_id.hotel_discount_free_pct",
        readonly=False,
        digits="Discount",
        help="Discount a front-desk user may grant without any approval "
        "(0-5%). Anything above it needs an approved discount request.",
    )
    hotel_discount_manager_pct = fields.Float(
        string="Hotel Manager Threshold (%)",
        related="company_id.hotel_discount_manager_pct",
        readonly=False,
        digits="Discount",
        help="Discount a hotel manager may approve on his own (up to 15%). "
        "Above it the general manager must approve.",
    )

    # Constraints / Validations
    @api.constrains("hotel_sales_journal_id")
    def _check_hotel_sales_journal(self):
        for record in self:
            if record.hotel_sales_journal_id:
                if record.hotel_sales_journal_id.type != "sale":
                    raise ValidationError(_("Hotel Sales Journal must be of type 'sale'."))
                if record.company_id and record.hotel_sales_journal_id.company_id and record.hotel_sales_journal_id.company_id != record.company_id:
                    raise ValidationError(_("Hotel Sales Journal must belong to company %s.", record.company_id.name))

    @api.constrains("hotel_checkout_journal_id")
    def _check_hotel_checkout_journal(self):
        for record in self:
            if record.hotel_checkout_journal_id:
                if record.hotel_checkout_journal_id.type not in ("bank", "cash", "credit"):
                    raise ValidationError(_("Check-out Payment Journal must be Bank or Cash."))
                if record.company_id and record.hotel_checkout_journal_id.company_id and record.hotel_checkout_journal_id.company_id != record.company_id:
                    raise ValidationError(_("Check-out Payment Journal must belong to company %s.", record.company_id.name))

    @api.constrains("hotel_deposit_journal_id")
    def _check_hotel_deposit_journal(self):
        for record in self:
            if record.hotel_deposit_journal_id:
                if record.hotel_deposit_journal_id.type not in ("bank", "cash", "credit"):
                    raise ValidationError(_("Deposit Payment Journal must be Bank or Cash."))
                if record.company_id and record.hotel_deposit_journal_id.company_id and record.hotel_deposit_journal_id.company_id != record.company_id:
                    raise ValidationError(_("Deposit Payment Journal must belong to company %s.", record.company_id.name))

    @api.constrains("hotel_room_charge_journal_id")
    def _check_hotel_room_charge_journal(self):
        for record in self:
            if record.hotel_room_charge_journal_id:
                if record.hotel_room_charge_journal_id.type not in ("bank", "cash", "credit"):
                    raise ValidationError(_("Room Charge Journal must be Bank or Cash."))
                if record.company_id and record.hotel_room_charge_journal_id.company_id and record.hotel_room_charge_journal_id.company_id != record.company_id:
                    raise ValidationError(_("Room Charge Journal must belong to company %s.", record.company_id.name))

    @api.constrains("hotel_income_account_id")
    def _check_hotel_income_account(self):
        for record in self:
            if record.hotel_income_account_id:
                if record.hotel_income_account_id.account_type not in ("income", "income_other"):
                    raise ValidationError(_("Room Revenue Account must have account type 'income' or 'income_other'."))
                if record.company_id and record.hotel_income_account_id.company_ids and record.company_id not in record.hotel_income_account_id.company_ids:
                    raise ValidationError(_("Room Revenue Account must belong to company %s.", record.company_id.name))

    @api.constrains("hotel_receivable_account_id")
    def _check_hotel_receivable_account(self):
        for record in self:
            if record.hotel_receivable_account_id:
                if record.hotel_receivable_account_id.account_type != "asset_receivable":
                    raise ValidationError(_("Hotel Receivable Account must have account type 'asset_receivable'."))
                if record.company_id and record.hotel_receivable_account_id.company_ids and record.company_id not in record.hotel_receivable_account_id.company_ids:
                    raise ValidationError(_("Hotel Receivable Account must belong to company %s.", record.company_id.name))

    @api.constrains("hotel_room_charge_clearing_account_id")
    def _check_hotel_room_charge_clearing_account(self):
        for record in self:
            if record.hotel_room_charge_clearing_account_id:
                if record.hotel_room_charge_clearing_account_id.account_type != "asset_current":
                    raise ValidationError(_("Room Charge Clearing Account must have account type 'asset_current'."))
                if record.company_id and record.hotel_room_charge_clearing_account_id.company_ids and record.company_id not in record.hotel_room_charge_clearing_account_id.company_ids:
                    raise ValidationError(_("Room Charge Clearing Account must belong to company %s.", record.company_id.name))

    @api.constrains("hotel_default_checkin_time", "hotel_default_checkout_time", "hotel_default_booking_duration")
    def _check_reservation_times(self):
        for record in self:
            if not (0.0 <= record.hotel_default_checkin_time < 24.0):
                raise ValidationError(_("Default check-in time must be between 00:00 and 23:59 (0.0 to 23.99)."))
            if not (0.0 <= record.hotel_default_checkout_time < 24.0):
                raise ValidationError(_("Default check-out time must be between 00:00 and 23:59 (0.0 to 23.99)."))
            if record.hotel_default_booking_duration < 1:
                raise ValidationError(_("Default booking duration must be at least 1 night."))

    @api.constrains("hotel_room_location_id", "hotel_kitchen_location_id", "hotel_storeroom_location_id", "hotel_housekeeping_cart_location_id")
    def _check_internal_locations(self):
        for record in self:
            for field_name in ("hotel_room_location_id", "hotel_kitchen_location_id", "hotel_storeroom_location_id", "hotel_housekeeping_cart_location_id"):
                loc = record[field_name]
                if loc:
                    if loc.usage != "internal":
                        raise ValidationError(_("Location %s must be an internal location.", loc.display_name))
                    if record.company_id and loc.company_id and loc.company_id != record.company_id:
                        raise ValidationError(_("Location %s must belong to company %s.", loc.display_name, record.company_id.name))

    @api.constrains("hotel_consumption_location_id")
    def _check_consumption_location(self):
        for record in self:
            loc = record.hotel_consumption_location_id
            if loc:
                if loc.usage not in ("customer", "inventory"):
                    raise ValidationError(_("Room Consumption Location %s must have usage 'customer' or 'inventory'.", loc.display_name))
                if record.company_id and loc.company_id and loc.company_id != record.company_id:
                    raise ValidationError(_("Location %s must belong to company %s.", loc.display_name, record.company_id.name))

    @api.constrains("hotel_internal_picking_type_id")
    def _check_picking_type(self):
        for record in self:
            picking_type = record.hotel_internal_picking_type_id
            if picking_type:
                if picking_type.code != "internal":
                    raise ValidationError(_("Room Supplies Operation Type must have code 'internal'."))
                if record.company_id and picking_type.warehouse_id and picking_type.warehouse_id.company_id != record.company_id:
                    raise ValidationError(_("Operation Type must belong to company %s.", record.company_id.name))

    def get_values(self):
        res = super().get_values()
        company = self.company_id or self.env.company
        ICP = self.env["ir.config_parameter"].sudo()

        # Migrate legacy ir.config_parameter if company field is not yet set
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
        for field_name, (param_key, model_name) in m2o_mapping.items():
            if not company[field_name]:
                val = ICP.get_param(param_key)
                if val:
                    try:
                        rec = self.env[model_name].browse(int(val)).exists()
                        if rec:
                            res[field_name] = rec.id
                    except (ValueError, TypeError):
                        pass

        if not company.hotel_default_tax_ids:
            tax_ids_str = ICP.get_param("hotel.default_tax_ids", default="")
            tax_ids = [
                int(i)
                for i in (tax_ids_str or "").split(",")
                if i.strip().isdigit()
            ]
            if tax_ids:
                taxes = self.env["account.tax"].browse(tax_ids).exists()
                if taxes:
                    res["hotel_default_tax_ids"] = [Command.set(taxes.ids)]

        return res

    def set_values(self):
        super().set_values()
        ICP = self.env["ir.config_parameter"].sudo()

        for record in self:
            company = record.company_id or self.env.company
            journal = company.hotel_room_charge_journal_id
            method = company.hotel_room_charge_payment_method_id
            clearing = company.hotel_room_charge_clearing_account_id
            product = company.hotel_room_service_product_id
            pos_config = company.hotel_pos_room_service_config_id

            # Sync payment method and product with chosen clearing account and journal
            if method and journal and method.journal_id != journal:
                method.write({"journal_id": journal.id})
            if method and clearing and method.outstanding_account_id != clearing:
                method.write({"outstanding_account_id": clearing.id})
            if product and clearing:
                product.with_company(company).property_account_income_id = clearing.id
            if pos_config and method and method not in pos_config.payment_method_ids:
                pos_config.write({"payment_method_ids": [Command.link(method.id)]})

            # Mirror to ir.config_parameter for single-company legacy compatibility
            if company == self.env.ref("base.main_company", raise_if_not_found=False) or company == self.env.company:
                m2o_params = {
                    "hotel.sales_journal_id": company.hotel_sales_journal_id.id,
                    "hotel.checkout_journal_id": company.hotel_checkout_journal_id.id,
                    "hotel.deposit_journal_id": company.hotel_deposit_journal_id.id,
                    "hotel.room_charge_journal_id": company.hotel_room_charge_journal_id.id,
                    "hotel.income_account_id": company.hotel_income_account_id.id,
                    "hotel.receivable_account_id": company.hotel_receivable_account_id.id,
                    "hotel.room_charge_clearing_account_id": company.hotel_room_charge_clearing_account_id.id,
                    "hotel.default_product_id": company.hotel_default_product_id.id,
                    "hotel.pos_room_service_config_id": company.hotel_pos_room_service_config_id.id,
                    "hotel.room_charge_payment_method_id": company.hotel_room_charge_payment_method_id.id,
                    "hotel.room_service_product_id": company.hotel_room_service_product_id.id,
                    "hotel.room_location_id": company.hotel_room_location_id.id,
                    "hotel.consumption_location_id": company.hotel_consumption_location_id.id,
                    "hotel.kitchen_location_id": company.hotel_kitchen_location_id.id,
                    "hotel.storeroom_location_id": company.hotel_storeroom_location_id.id,
                    "hotel.housekeeping_cart_location_id": company.hotel_housekeeping_cart_location_id.id,
                    "hotel.internal_picking_type_id": company.hotel_internal_picking_type_id.id,
                    "hotel.housekeeping_department_id": company.hotel_housekeeping_department_id.id,
                }
                for param_key, param_val in m2o_params.items():
                    ICP.set_param(param_key, str(param_val) if param_val else "")

                ICP.set_param(
                    "hotel.default_tax_ids",
                    ",".join(str(i) for i in company.hotel_default_tax_ids.ids),
                )
                ICP.set_param("hotel.turnover_policy", company.hotel_turnover_policy or "")
                ICP.set_param("hotel.require_inspection", str(company.hotel_require_inspection))
                ICP.set_param("hotel.auto_housekeeping_on_checkout", str(company.hotel_auto_housekeeping_on_checkout))
