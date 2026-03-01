import logging
import secrets
from datetime import datetime, timedelta

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmazonBackend(models.Model):
    _name = "amz.backend"
    _inherit = "connector.backend"
    _description = "Amazon Backend"

    @api.model
    def _select_versions(self):
        return [("spapi", "Selling Partner API")]

    name = fields.Char(required=True)
    code = fields.Char(help="Short code to identify this backend.")
    version = fields.Selection(
        selection=_select_versions, required=True, default="spapi"
    )
    seller_id = fields.Char(required=True, string="Seller ID")
    region = fields.Selection(
        selection=[("na", "North America"), ("eu", "Europe"), ("fe", "Far East")],
        required=True,
        default="na",
    )
    lwa_client_id = fields.Char(string="LWA Client ID", required=True)
    lwa_client_secret = fields.Char()
    lwa_refresh_token = fields.Char()
    aws_role_arn = fields.Char()
    aws_external_id = fields.Char(string="AWS External ID")
    endpoint = fields.Char(string="SP-API Endpoint")
    test_mode = fields.Boolean(
        string="Sandbox Mode",
        default=False,
        help=(
            "When enabled, API calls include the x-amzn-api-sandbox header "
            "which triggers Amazon's static sandbox responses. Use this "
            "to test API integration without affecting live data. "
            "Requires valid SP-API credentials."
        ),
    )
    read_only_mode = fields.Boolean(
        string="Read-Only Mode (Testing)",
        default=False,
        help=(
            "When enabled, all write operations to Amazon (stock updates, "
            "shipment tracking, etc.) will be logged instead of actually "
            "submitted. Use this for testing and verification without "
            "affecting your Amazon account."
        ),
    )
    enable_price_sync = fields.Boolean(default=True)
    enable_stock_sync = fields.Boolean(default=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    warehouse_id = fields.Many2one(
        comodel_name="stock.warehouse", string="Default Warehouse"
    )
    marketplace_ids = fields.One2many(
        comodel_name="amz.marketplace",
        inverse_name="backend_id",
        string="Marketplaces",
    )
    shop_ids = fields.One2many(
        comodel_name="amz.shop",
        inverse_name="backend_id",
        string="Shops",
    )
    note = fields.Text(string="Notes")

    # Access Token (temporary, refreshed automatically)
    access_token = fields.Char(readonly=True)
    token_expires_at = fields.Datetime(readonly=True)

    # Webhook Configuration for SP-API Notifications
    webhook_token = fields.Char(
        string="Webhook Security Token",
        default=lambda self: secrets.token_urlsafe(32),
        help="Secret token used in webhook URL for authentication. Auto-generated.",
        copy=False,
    )
    webhook_url = fields.Char(
        string="Webhook URL",
        compute="_compute_webhook_url",
        help="URL to configure in Amazon SP-API notifications destination.",
    )
    webhook_active = fields.Boolean(
        default=False,
        help="Enable webhook endpoint to receive real-time notifications.",
    )

    # Notification Subscriptions
    notify_order_change = fields.Boolean(
        string="Order Change Notifications",
        help="Receive real-time notifications when orders are created or updated.",
    )
    notify_listings_change = fields.Boolean(
        string="Listings Change Notifications",
        help="Receive notifications when product listings are modified.",
    )
    notify_feed_processing = fields.Boolean(
        string="Feed Processing Notifications",
        help="Receive notifications when feed processing completes.",
    )
    notify_report_processing = fields.Boolean(
        string="Report Processing Notifications",
        help="Receive notifications when report generation completes.",
    )

    # SNS Subscription tracking
    sns_destination_id = fields.Char(
        string="SNS Destination ID",
        readonly=True,
        help="Amazon SP-API destination ID for this webhook.",
    )
    notification_log_ids = fields.One2many(
        comodel_name="amz.notification.log",
        inverse_name="backend_id",
        string="Notification Logs",
    )
    notification_log_count = fields.Integer(
        string="Notification Count",
        compute="_compute_notification_log_count",
    )
    active = fields.Boolean(default=True)

    # Enterprise Edition coexistence (sale_amazon)
    sale_amazon_installed = fields.Boolean(
        string="sale_amazon Installed",
        compute="_compute_sale_amazon_installed",
        help="Whether the Odoo Enterprise sale_amazon module is installed.",
    )
    disable_ee_order_sync = fields.Boolean(
        string="Disable EE Order Sync",
        default=False,
        help=(
            "When enabled, deactivates the sale_amazon cron jobs so that "
            "this connector handles all Amazon order synchronization. "
            "Enable this to prevent duplicate order imports."
        ),
    )

    # Amazon Hub Integration
    hub_base_url = fields.Char(
        string="Amazon Hub URL",
        help=(
            "Base URL for the Amazon Hub listing analysis dashboard "
            "(e.g., https://amazon-hub.kencove.com). Used to link products "
            "to their AI analysis page."
        ),
    )
    hub_api_key = fields.Char(
        string="Amazon Hub API Key",
        help="API key for authenticated calls to the Amazon Hub REST API.",
        copy=False,
    )
    hub_brand_slug = fields.Char(
        help=(
            "Brand slug used in the Amazon Hub (e.g., kencove, titan, powerfields). "
            "Must match the slug in the Hub's brands table."
        ),
    )

    @api.depends("webhook_token")
    def _compute_webhook_url(self):
        """Compute the full webhook URL for this backend."""
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        for record in self:
            if record.webhook_token:
                record.webhook_url = f"{base_url}/amz/webhook/{record.webhook_token}"
            else:
                record.webhook_url = False

    def _compute_notification_log_count(self):
        """Compute count of notification logs."""
        for record in self:
            record.notification_log_count = len(record.notification_log_ids)

    def action_view_notification_logs(self):
        """Open notification logs for this backend."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Notification Logs",
            "res_model": "amz.notification.log",
            "view_mode": "tree,form",
            "domain": [("backend_id", "=", self.id)],
            "context": {"default_backend_id": self.id},
        }

    def action_regenerate_webhook_token(self):
        """Generate a new webhook token."""
        self.ensure_one()
        self.webhook_token = secrets.token_urlsafe(32)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Token Regenerated",
                "message": (
                    "A new webhook token has been generated. "
                    "Update your Amazon notification destination."
                ),
                "type": "warning",
                "sticky": False,
            },
        }

    def _compute_sale_amazon_installed(self):
        """Check if the Odoo Enterprise sale_amazon module is installed."""
        IrModule = self.env["ir.module.module"].sudo()
        installed = IrModule.search(
            [("name", "=", "sale_amazon"), ("state", "=", "installed")],
            limit=1,
        )
        for record in self:
            record.sale_amazon_installed = bool(installed)

    def write(self, vals):
        """Override write to toggle EE cron when disable_ee_order_sync changes."""
        res = super().write(vals)
        if "disable_ee_order_sync" in vals:
            self._toggle_ee_order_cron(disable=vals["disable_ee_order_sync"])
        return res

    def _toggle_ee_order_cron(self, disable=True):
        """Activate or deactivate the sale_amazon order sync cron jobs.

        The EE ``sale_amazon`` module registers cron jobs on the
        ``amazon.account`` model.  When ``disable_ee_order_sync`` is
        True we deactivate those crons so only this connector imports
        orders.  Setting it False reactivates them.
        """
        IrCron = self.env["ir.cron"].sudo()
        IrModel = self.env["ir.model"].sudo()
        model = IrModel.search([("model", "=", "amazon.account")], limit=1)
        if not model:
            return
        crons = IrCron.search([("model_id", "=", model.id)])
        if crons:
            crons.write({"active": not disable})
            _logger.info(
                "sale_amazon crons %s: %s",
                "deactivated" if disable else "reactivated",
                crons.mapped("name"),
            )

    @api.model
    def _get_lwa_token_url(self):
        return "https://api.amazon.com/auth/o2/token"

    def _get_sp_api_endpoint(self):
        """Get SP-API endpoint based on region"""
        self.ensure_one()
        endpoints = {
            "na": "https://sellingpartnerapi-na.amazon.com",
            "eu": "https://sellingpartnerapi-eu.amazon.com",
            "fe": "https://sellingpartnerapi-fe.amazon.com",
        }
        return self.endpoint or endpoints.get(self.region)

    def _refresh_access_token(self):
        """Refresh LWA access token using refresh token"""
        self.ensure_one()
        url = self._get_lwa_token_url()
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self.lwa_refresh_token,
            "client_id": self.lwa_client_id,
            "client_secret": self.lwa_client_secret,
        }

        try:
            response = requests.post(url, data=payload, timeout=30)
            response.raise_for_status()
            data = response.json()

            self.write(
                {
                    "access_token": data["access_token"],
                    "token_expires_at": datetime.now()
                    + timedelta(seconds=data["expires_in"] - 60),
                }
            )

            return data["access_token"]
        except Exception as e:
            raise UserError(f"Failed to refresh LWA access token: {str(e)}") from e

    def _get_access_token(self):
        """Get valid access token, refreshing if necessary"""
        self.ensure_one()
        if (
            not self.access_token
            or not self.token_expires_at
            or self.token_expires_at <= datetime.now()
        ):
            self._refresh_access_token()

        return self.access_token

    def _call_sp_api(self, method, endpoint, params=None, json_data=None):
        """Make authenticated SP-API call.

        When test_mode is enabled, adds the x-amzn-api-sandbox header to
        trigger Amazon's static sandbox responses instead of live data.
        """
        self.ensure_one()
        access_token = self._get_access_token()
        url = f"{self._get_sp_api_endpoint()}{endpoint}"

        headers = {
            "x-amz-access-token": access_token,
            "Content-Type": "application/json",
        }

        if self.test_mode:
            # Enable Amazon SP-API static sandbox mode
            # Returns predefined test responses instead of live data
            headers["x-amzn-api-sandbox"] = "true"
            _logger.info(
                "[AmazonBackend] Sandbox mode active for %s %s", method, endpoint
            )

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_data,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            raise UserError(
                f"SP-API HTTP Error: {e.response.status_code} - {e.response.text}"
            ) from e
        except Exception as e:
            raise UserError(f"SP-API Call Failed: {str(e)}") from e

    def action_test_connection(self):
        """Test SP-API connection by fetching marketplace participations"""
        self.ensure_one()

        try:
            result = self._call_sp_api(
                "GET",
                "/sellers/v1/marketplaceParticipations",
            )
            if result.get("payload"):
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "Connection Successful",
                        "message": (
                            f"Connected to Amazon SP-API. "
                            f"Found {len(result['payload'])} marketplace(s)."
                        ),
                        "type": "success",
                        "sticky": False,
                    },
                }
        except Exception as e:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Connection Failed",
                    "message": str(e),
                    "type": "danger",
                    "sticky": True,
                },
            }

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Connection Failed",
                "message": "No marketplaces returned by SP-API.",
                "type": "warning",
                "sticky": False,
            },
        }

    def action_fetch_marketplaces(self):
        """Fetch marketplaces from SP-API and upsert records.

        Uses ``/sellers/v1/marketplaceParticipations`` to discover the
        marketplaces this seller participates in, then creates or updates
        ``amz.marketplace`` entries linked to this backend.
        """
        self.ensure_one()

        result = self._call_sp_api("GET", "/sellers/v1/marketplaceParticipations")
        payload = result.get("payload") or []

        if not payload:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "No Marketplaces",
                    "message": "No marketplace participations returned by SP-API.",
                    "type": "warning",
                    "sticky": False,
                },
            }

        Marketplace = self.env["amz.marketplace"]
        Currency = self.env["res.currency"]

        created = 0
        updated = 0

        for item in payload:
            marketplace = item.get("marketplace", {})
            marketplace_id = marketplace.get("id")
            if not marketplace_id:
                continue

            country_code = (marketplace.get("countryCode") or "").upper()
            currency_code = marketplace.get("defaultCurrencyCode")
            name = marketplace.get("name") or marketplace_id

            currency = False
            if currency_code:
                currency = Currency.search([("name", "=", currency_code)], limit=1)

            vals = {
                "name": name,
                "code": country_code,
                "marketplace_id": marketplace_id,
                "backend_id": self.id,
                "country_code": country_code,
                "region": self.region,
            }
            if currency:
                vals["currency_id"] = currency.id

            # Prefer the already-linked marketplaces to avoid missing the
            # record when the database search ignores an unflushed cache.
            existing = self.marketplace_ids.filtered(
                lambda m: m.marketplace_id == marketplace_id
            )
            if not existing:
                existing = Marketplace.search(
                    [
                        ("backend_id", "=", self.id),
                        ("marketplace_id", "=", marketplace_id),
                    ],
                    limit=1,
                )

            if existing:
                existing.write(vals)
                updated += 1
            else:
                Marketplace.create(vals)
                created += 1

        if created or updated:
            # Log the update/create event to the Odoo server log
            _logger.info(
                "[AmazonBackend] Created %d, updated %d marketplace(s) for backend ID %s",
                created,
                updated,
                self.id,
            )
            # Notify success and reload form to display fetched marketplaces
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Marketplaces Synced",
                    "message": f"Created {created}, updated {updated} marketplace(s).",
                    "type": "success",
                    "sticky": False,
                    "next": {
                        "type": "ir.actions.client",
                        "tag": "reload",
                    },
                },
            }
        else:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Marketplaces Synced",
                    "message": "No marketplaces created or updated.",
                    "type": "info",
                    "sticky": False,
                },
            }
