import logging
from urllib.parse import urlencode

import requests

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmazonProductBinding(models.Model):
    _name = "amz.product.binding"
    _description = "Amazon Product Binding"
    _inherit = "external.binding"
    _inherits = {"product.product": "odoo_id"}

    odoo_id = fields.Many2one(
        comodel_name="product.product",
        string="Odoo Product",
        required=True,
        ondelete="cascade",
    )
    backend_id = fields.Many2one(
        comodel_name="amz.backend",
        required=True,
        ondelete="restrict",
    )
    marketplace_id = fields.Many2one(
        comodel_name="amz.marketplace", ondelete="restrict"
    )
    external_id = fields.Char(string="External ID")
    seller_sku = fields.Char(string="Seller SKU", required=True)
    asin = fields.Char(string="ASIN")
    fulfillment_channel = fields.Selection(
        selection=[("FBM", "Fulfilled by Merchant"), ("AFN", "Fulfilled by Amazon")],
        default="FBM",
    )
    lead_time_days = fields.Integer(string="Lead Time (days)", default=0)
    handling_time_days = fields.Integer(string="Handling Time (days)", default=0)
    stock_buffer = fields.Integer(
        string="Safety Stock Buffer",
        default=0,
        help="Units to hold back when syncing stock.",
    )
    sync_price = fields.Boolean(default=True)
    sync_stock = fields.Boolean(default=True)
    last_price_sync = fields.Datetime()
    last_stock_sync = fields.Datetime()

    competitive_price_ids = fields.One2many(
        comodel_name="amz.competitive.price",
        inverse_name="product_binding_id",
        string="Competitive Prices",
    )
    competitive_price_count = fields.Integer(
        string="# Competitive Prices",
        compute="_compute_competitive_price_count",
    )

    _sql_constraints = [
        (
            "amz_product_unique",
            "unique(backend_id, seller_sku)",
            "A binding with this seller SKU already exists for the backend.",
        ),
    ]

    def _compute_competitive_price_count(self):
        """Count active competitive prices for this binding"""
        for record in self:
            record.competitive_price_count = len(
                record.competitive_price_ids.filtered("active")
            )

    def action_fetch_competitive_prices(self):
        """Fetch competitive pricing from Amazon SP-API"""
        self.ensure_one()

        if not self.asin:
            raise UserError(_("This product has no ASIN assigned."))

        if not self.marketplace_id:
            raise UserError(_("No marketplace assigned to this product."))

        # Use pricing adapter to fetch competitive prices via work_on context
        with self.backend_id.work_on("amz.product.binding") as work:
            adapter = work.component(usage="pricing.adapter")
            result = adapter.get_competitive_pricing(
                marketplace_id=self.marketplace_id.marketplace_id,
                asins=[self.asin],
            )

        # Normalize response — may be a list or dict with payload key
        if isinstance(result, dict):
            result = result.get("payload") or result.get("results") or []
        if not result or not isinstance(result, list):
            raise UserError(_("No competitive pricing data returned from Amazon API."))

        # Use mapper to transform API response via work_on context
        with self.backend_id.work_on("amz.product.binding") as work:
            mapper = work.component(
                usage="import.mapper", model_name="amz.product.binding"
            )

        competitive_price_vals_list = []
        for pricing_data in result:
            vals = mapper.map_competitive_price(pricing_data, self)
            if vals:
                competitive_price_vals_list.append(vals)

        if not competitive_price_vals_list:
            raise UserError(
                _(
                    "No competitive pricing data found for ASIN %(asin)s "
                    "in marketplace %(marketplace)s"
                )
                % {
                    "asin": self.asin,
                    "marketplace": self.marketplace_id.name,
                }
            )

        # Create competitive price records
        self.env["amz.competitive.price"].create(competitive_price_vals_list)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Success"),
                "message": _("%d competitive price(s) fetched successfully")
                % len(competitive_price_vals_list),
                "type": "success",
            },
        }

    def action_view_competitive_prices(self):
        """Open competitive prices for this binding"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Competitive Prices for %s") % self.display_name,
            "res_model": "amz.competitive.price",
            "view_mode": "tree,form",
            "domain": [("product_binding_id", "=", self.id)],
            "context": {
                "default_product_binding_id": self.id,
                "default_asin": self.asin,
                "default_marketplace_id": self.marketplace_id.id,
            },
        }

    def _build_enrichment_url(self, template):
        """Format a URL template with product and backend context."""
        backend = self.backend_id
        base = (backend.enrichment_base_url or "").rstrip("/")
        return template.format(
            base_url=base,
            asin=self.asin or "",
            sku=self.seller_sku or "",
            marketplace=self.marketplace_id.code if self.marketplace_id else "",
            brand=backend.enrichment_brand_id or "",
            product_id="{product_id}",  # deferred — filled after API call
        )

    def action_view_enrichment(self):
        """Open product in the configured listing enrichment service.

        Uses the backend's enrichment_lookup_template to call the
        provider API, then opens the dashboard URL in a new tab.
        Falls back to a search-based URL if the API call fails.
        """
        self.ensure_one()
        backend = self.backend_id

        if backend.enrichment_provider in (False, "none"):
            raise UserError(
                _(
                    "No listing enrichment provider configured. "
                    "Go to Amazon SP-API \u2192 Backends \u2192 %(backend)s "
                    "and select an enrichment provider."
                )
                % {"backend": backend.name}
            )

        if not backend.enrichment_base_url:
            raise UserError(_("Enrichment API URL is not configured."))

        base_url = backend.enrichment_base_url.rstrip("/")

        # Try API lookup if we have a template and API key
        if backend.enrichment_lookup_template and backend.enrichment_api_key:
            lookup_url = self._build_enrichment_url(backend.enrichment_lookup_template)
            headers = {}
            params = {}
            key_header = backend.enrichment_api_key_header or "X-API-Key"
            if backend.enrichment_key_in_query:
                params[key_header] = backend.enrichment_api_key
            else:
                headers[key_header] = backend.enrichment_api_key

            try:
                resp = requests.get(
                    lookup_url, headers=headers, params=params, timeout=10
                )
                if resp.status_code == 200:
                    data = resp.json()
                    # Try dashboard_url from response
                    dashboard_url = data.get("dashboard_url") or data.get("url")
                    if dashboard_url:
                        return {
                            "type": "ir.actions.act_url",
                            "url": dashboard_url,
                            "target": "new",
                        }
                    # Try dashboard template with product_id
                    pid = data.get("id") or data.get("product_id")
                    if pid and backend.enrichment_dashboard_template:
                        url = backend.enrichment_dashboard_template.format(
                            base_url=base_url,
                            product_id=pid,
                            asin=self.asin or "",
                            sku=self.seller_sku or "",
                            marketplace=(
                                self.marketplace_id.code if self.marketplace_id else ""
                            ),
                            brand=backend.enrichment_brand_id or "",
                        )
                        return {
                            "type": "ir.actions.act_url",
                            "url": url,
                            "target": "new",
                        }
                elif resp.status_code == 404:
                    identifier = self.asin or self.seller_sku
                    raise UserError(
                        _("Product '%(id)s' not found in %(provider)s.")
                        % {
                            "id": identifier,
                            "provider": backend.enrichment_provider,
                        }
                    )
                else:
                    _logger.warning(
                        "Enrichment lookup failed: %s %s",
                        resp.status_code,
                        resp.text[:200],
                    )
            except requests.RequestException as exc:
                _logger.warning("Enrichment API call failed: %s", exc)

        # Fallback: open base URL with search query
        search_params = urlencode({"search": self.asin or self.seller_sku})
        return {
            "type": "ir.actions.act_url",
            "url": f"{base_url}/products?{search_params}",
            "target": "new",
        }
