from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    # Accounting & Invoicing
    hotel_sales_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Hotel Sales Journal",
        domain="[('type', '=', 'sale')]",
        check_company=True,
        help="Journal used to create customer invoices for guest folios.",
    )
    hotel_checkout_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Check-out Payment Journal",
        domain="[('type', 'in', ('bank', 'cash', 'credit'))]",
        check_company=True,
        help="Journal used to settle the guest balance at check-out.",
    )
    hotel_deposit_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Deposit Payment Journal",
        domain="[('type', 'in', ('bank', 'cash', 'credit'))]",
        check_company=True,
        help="Journal used to collect advance deposits at booking or check-in.",
    )
    hotel_room_charge_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Room Charge Journal",
        domain="[('type', 'in', ('bank', 'cash', 'credit'))]",
        check_company=True,
        help="Bank/cash journal used by the 'Charge to Room' POS payment method.",
    )
    hotel_income_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Room Revenue Account",
        domain="[('account_type', 'in', ('income', 'income_other'))]",
        check_company=True,
        help="Default income account for room accommodation revenue when not set on the room type or product.",
    )
    hotel_receivable_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Hotel Receivable Account",
        domain="[('account_type', '=', 'asset_receivable')]",
        check_company=True,
        help="Default customer receivable account for hotel guests.",
    )
    hotel_room_charge_clearing_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Room Charge Clearing Account",
        domain="[('account_type', '=', 'asset_current')]",
        check_company=True,
        help="Clearing account used to bridge Point of Sale and room service charges to the guest folio.",
    )
    hotel_default_product_id = fields.Many2one(
        comodel_name="product.product",
        string="Default Room Revenue Product",
        domain="[('type', '=', 'service')]",
        check_company=True,
        help="Default service product invoiced for room stays if the room type has no specific product assigned.",
    )
    hotel_default_tax_ids = fields.Many2many(
        comodel_name="account.tax",
        relation="hotel_company_default_tax_rel",
        column1="company_id",
        column2="tax_id",
        string="Default Room Taxes",
        domain="[('type_tax_use', '=', 'sale')]",
        check_company=True,
        help="Default customer taxes applied to room charges if not configured on the room type or product.",
    )

    # Room Service / Point of Sale
    hotel_pos_room_service_config_id = fields.Many2one(
        comodel_name="pos.config",
        string="Room Service Point of Sale",
        check_company=True,
        help="Point of Sale receiving food orders taken from the Room Service screen.",
    )
    hotel_room_charge_payment_method_id = fields.Many2one(
        comodel_name="pos.payment.method",
        string="Room Charge Payment Method",
        check_company=True,
        help="POS payment method used to charge restaurant/room service orders to the guest folio.",
    )
    hotel_room_service_product_id = fields.Many2one(
        comodel_name="product.product",
        string="Room Service Folio Product",
        domain="[('type', '=', 'service')]",
        check_company=True,
        help="Service product carrying room service food charges on the guest folio invoice.",
    )

    # Inventory / Stock Locations
    hotel_room_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Hotel Rooms Location",
        domain="[('usage', '=', 'internal')]",
        check_company=True,
        help="Inventory location holding supplies and minibar stock kept in the guest rooms.",
    )
    hotel_consumption_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Room Consumption Location",
        domain="[('usage', 'in', ('customer', 'inventory'))]",
        check_company=True,
        help="Destination of posted room consumption.",
    )
    hotel_kitchen_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Hotel Kitchen Location",
        domain="[('usage', '=', 'internal')]",
        check_company=True,
        help="Kitchen or F&B store location holding ingredients and prepared items.",
    )
    hotel_storeroom_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Hotel Storeroom Location",
        domain="[('usage', '=', 'internal')]",
        check_company=True,
        help="Main internal storeroom location from which guest rooms are replenished.",
    )
    hotel_housekeeping_cart_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Housekeeping Cart Location",
        domain="[('usage', '=', 'internal')]",
        check_company=True,
        help="Internal location representing the housekeeping cart or staff buffer stock.",
    )
    hotel_internal_picking_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="Room Supplies Operation Type",
        domain="[('code', '=', 'internal')]",
        check_company=True,
        help="Internal transfer operation type used to move supplies out of rooms or replenish them.",
    )

    # Housekeeping
    hotel_auto_housekeeping_on_checkout = fields.Boolean(
        string="Housekeeping Task on Check-out",
        default=True,
        help="Create a cleaning task automatically when a guest checks out.",
    )
    hotel_require_inspection = fields.Boolean(
        string="Require Cleaning Inspection",
        default=False,
        help="When enabled, a cleaned room stays out of the sellable pool until a supervisor inspects it.",
    )
    hotel_housekeeping_department_id = fields.Many2one(
        comodel_name="hr.department",
        string="Housekeeping Team",
        check_company=True,
        help="Team acting as the housekeeping pool.",
    )
    hotel_turnover_policy = fields.Selection(
        selection=[
            ("replenish", "Replenish to Standard Quantity"),
            ("carry_forward", "Carry Forward Verified Remaining Stock"),
        ],
        string="Default Room Turnover Policy",
        default="replenish",
        help="How a room is prepared for the next guest after check-out.",
    )

    # Reservation Defaults
    hotel_default_checkin_time = fields.Float(
        string="Default Check-in Time",
        default=14.0,
        help="Default check-in hour of day (e.g. 14.0 for 14:00).",
    )
    hotel_default_checkout_time = fields.Float(
        string="Default Check-out Time",
        default=11.0,
        help="Default check-out hour of day (e.g. 11.0 for 11:00).",
    )
    hotel_default_booking_duration = fields.Integer(
        string="Default Booking Duration (Nights)",
        default=1,
        help="Default stay duration in nights for new reservations.",
    )
    hotel_reservation_confirmation_policy = fields.Selection(
        selection=[
            ("manual", "Manual Confirmation"),
            ("deposit", "Confirm on Deposit Payment"),
            ("auto", "Automatic Confirmation"),
        ],
        string="Reservation Confirmation Policy",
        default="manual",
        help="Policy for confirming newly created reservations.",
    )
    hotel_cancellation_policy = fields.Selection(
        selection=[
            ("free", "Free Cancellation"),
            ("deposit_forfeit", "Forfeit Deposit"),
            ("penalty", "Cancellation Penalty"),
        ],
        string="Cancellation Policy",
        default="free",
        help="Default hotel cancellation terms.",
    )
    hotel_default_reservation_state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
        ],
        string="Default Reservation Status",
        default="draft",
        help="Initial state for new reservations when created.",
    )

    # Room Consumption Defaults
    hotel_consumable_standard_qty = fields.Float(
        string="Default Standard Quantity",
        default=0.0,
        digits="Product Unit",
        help="Fallback par level quantity for room consumables.",
    )
    hotel_consumable_allowance_qty = fields.Float(
        string="Default Allowance Quantity",
        default=0.0,
        digits="Product Unit",
        help="Fallback complimentary allowance quantity.",
    )
    hotel_consumable_allowance_scope = fields.Selection(
        selection=[
            ("stay", "Per Stay"),
            ("day", "Per Day"),
            ("guest", "Per Guest"),
        ],
        string="Default Allowance Scope",
        default="stay",
        help="Fallback allowance scope when not configured on room or product.",
    )
    hotel_consumable_allowance_price = fields.Float(
        string="Default Excess Consumption Price",
        default=0.0,
        help="Fallback chargeable price unit for excess consumption.",
    )
    hotel_consumable_replenishment_policy = fields.Selection(
        selection=[
            ("replenish", "Replenish to Standard Quantity"),
            ("carry_forward", "Carry Forward Verified Remaining Stock"),
        ],
        string="Default Replenishment Policy",
        default="replenish",
        help="Fallback replenishment policy for consumables.",
    )

    # Approvals
    hotel_require_rate_approval = fields.Boolean(
        string="Require Room Rate Approval",
        default=True,
    )
    hotel_require_discount_approval = fields.Boolean(
        string="Require Discount Approval",
        default=True,
    )
    hotel_discount_free_pct = fields.Float(
        string="Free Discount Threshold (%)",
        default=5.0,
        digits="Discount",
    )
    hotel_discount_manager_pct = fields.Float(
        string="Hotel Manager Threshold (%)",
        default=15.0,
        digits="Discount",
    )
