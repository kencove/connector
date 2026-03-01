import json
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AmazonNotificationLog(models.Model):
    """Log of Amazon SP-API notifications received via webhook.

    Each notification is logged here and processed asynchronously
    via queue_job. This provides:
    - Audit trail of all notifications
    - Retry capability for failed processing
    - Debugging information
    """

    _name = "amz.notification.log"
    _description = "Amazon Notification Log"
    _order = "create_date desc"
    _rec_name = "display_name"

    backend_id = fields.Many2one(
        comodel_name="amz.backend",
        required=True,
        ondelete="cascade",
        index=True,
    )
    notification_type = fields.Selection(
        selection=[
            ("SubscriptionConfirmation", "Subscription Confirmation"),
            ("UnsubscribeConfirmation", "Unsubscribe Confirmation"),
            ("ORDER_CHANGE", "Order Change"),
            ("LISTINGS_ITEM_STATUS_CHANGE", "Listings Item Status Change"),
            ("LISTINGS_ITEM_MFN_QUANTITY_CHANGE", "MFN Quantity Change"),
            ("FBA_INVENTORY_AVAILABILITY_CHANGES", "FBA Inventory Change"),
            ("FEED_PROCESSING_FINISHED", "Feed Processing Finished"),
            ("REPORT_PROCESSING_FINISHED", "Report Processing Finished"),
            ("PRICING_HEALTH", "Pricing Health"),
            ("PRODUCT_TYPE_DEFINITIONS_CHANGE", "Product Type Change"),
            ("other", "Other"),
        ],
        index=True,
    )
    display_name = fields.Char(compute="_compute_display_name", store=True)
    topic_arn = fields.Char(string="SNS Topic ARN")
    message_id = fields.Char(string="SNS Message ID", index=True)
    raw_message = fields.Text(
        help="Full SNS message as received",
    )
    payload = fields.Text(
        string="Notification Payload",
        help="Parsed SP-API notification payload",
    )
    state = fields.Selection(
        selection=[
            ("received", "Received"),
            ("processing", "Processing"),
            ("processed", "Processed"),
            ("confirmed", "Confirmed"),
            ("error", "Error"),
            ("ignored", "Ignored"),
        ],
        default="received",
        index=True,
    )
    error_message = fields.Text()
    retry_count = fields.Integer(default=0)
    processed_date = fields.Datetime()

    # Linked records created/updated by this notification
    order_id = fields.Many2one(
        comodel_name="amz.sale.order",
        string="Related Order",
    )
    product_binding_id = fields.Many2one(
        comodel_name="amz.product.binding",
        string="Related Product Binding",
    )
    feed_id = fields.Many2one(
        comodel_name="amz.feed",
        string="Related Feed",
    )

    @api.depends("notification_type", "message_id")
    def _compute_display_name(self):
        for record in self:
            if record.notification_type and record.message_id:
                record.display_name = (
                    f"{record.notification_type} ({record.message_id[:8]}...)"
                )
            elif record.notification_type:
                record.display_name = record.notification_type
            else:
                record.display_name = f"Notification #{record.id}"

    def process_notification(self):
        """Process the notification based on its type.

        This method is called as a queue job to process notifications
        asynchronously after they are received.
        """
        self.ensure_one()

        if self.state not in ("received", "error"):
            _logger.info("Skipping notification %s in state %s", self.id, self.state)
            return

        self.write({"state": "processing"})

        try:
            # Dispatch to appropriate handler
            handlers = {
                "ORDER_CHANGE": self._handle_order_change,
                "LISTINGS_ITEM_STATUS_CHANGE": self._handle_listings_change,
                "LISTINGS_ITEM_MFN_QUANTITY_CHANGE": self._handle_quantity_change,
                "FBA_INVENTORY_AVAILABILITY_CHANGES": self._handle_fba_inventory_change,
                "FEED_PROCESSING_FINISHED": self._handle_feed_finished,
                "REPORT_PROCESSING_FINISHED": self._handle_report_finished,
                "PRICING_HEALTH": self._handle_pricing_health,
            }

            handler = handlers.get(self.notification_type)

            if handler:
                handler()
                self.write(
                    {
                        "state": "processed",
                        "processed_date": fields.Datetime.now(),
                    }
                )
            else:
                _logger.info(
                    "No handler for notification type: %s", self.notification_type
                )
                self.write(
                    {
                        "state": "ignored",
                        "error_message": f"No handler for type: {self.notification_type}",
                    }
                )

        except Exception as e:
            _logger.exception("Error processing notification %s", self.id)
            self.write(
                {
                    "state": "error",
                    "error_message": str(e),
                    "retry_count": self.retry_count + 1,
                }
            )
            raise

    def _get_payload_dict(self):
        """Parse payload JSON to dict."""
        if self.payload:
            try:
                return json.loads(self.payload)
            except json.JSONDecodeError:
                return {}
        return {}

    def _handle_order_change(self):
        """Handle ORDER_CHANGE notification.

        Triggers order sync for the affected order.
        """
        payload = self._get_payload_dict()

        amz_order_id = payload.get("AmazonOrderId")
        if not amz_order_id:
            # Try nested structure
            order_change = payload.get("OrderChangeNotification", {})
            amz_order_id = order_change.get("AmazonOrderId")

        if not amz_order_id:
            _logger.warning("ORDER_CHANGE missing AmazonOrderId: %s", payload)
            return

        _logger.info("Processing ORDER_CHANGE for order %s", amz_order_id)

        # Find or sync the order
        order_binding = self.env["amz.sale.order"].search(
            [
                ("backend_id", "=", self.backend_id.id),
                ("external_id", "=", amz_order_id),
            ],
            limit=1,
        )

        if order_binding:
            # Update existing order - fetch latest details
            order_binding._sync_order_from_api()
            self.order_id = order_binding
        else:
            # New order - trigger shop sync for this specific order
            # Find any shop for this backend and sync
            shop = self.backend_id.shop_ids[:1]
            if shop:
                with self.backend_id.work_on("amz.sale.order") as work:
                    adapter = work.component(usage="orders.adapter")
                    result = adapter.get_order(amz_order_id)

                if result and result.get("payload"):
                    order_data = result["payload"]
                    new_order = self.env[
                        "amz.sale.order"
                    ]._create_or_update_from_amazon(shop, order_data)
                    self.order_id = new_order

    def _handle_listings_change(self):
        """Handle LISTINGS_ITEM_STATUS_CHANGE notification.

        Updates or creates product bindings when listings change.
        """
        payload = self._get_payload_dict()

        seller_sku = payload.get("SellerSKU") or payload.get("sellerSku")
        asin = payload.get("Asin") or payload.get("asin")
        status = payload.get("Status") or payload.get("status")

        if not seller_sku:
            _logger.warning(
                "LISTINGS_ITEM_STATUS_CHANGE missing SellerSKU: %s", payload
            )
            return

        _logger.info(
            "Processing LISTINGS_ITEM_STATUS_CHANGE for SKU %s, status %s",
            seller_sku,
            status,
        )

        # Find existing binding
        binding = self.env["amz.product.binding"].search(
            [
                ("backend_id", "=", self.backend_id.id),
                ("seller_sku", "=", seller_sku),
            ],
            limit=1,
        )

        if binding:
            # Update ASIN if provided
            if asin and asin != binding.asin:
                binding.asin = asin
            self.product_binding_id = binding
        else:
            # Try to create binding if product exists in Odoo
            product = self.env["product.product"].search(
                [("default_code", "=", seller_sku)], limit=1
            )

            if product:
                # Get first marketplace for this backend
                marketplace = self.backend_id.marketplace_ids[:1]
                if marketplace:
                    new_binding = self.env["amz.product.binding"].create(
                        {
                            "backend_id": self.backend_id.id,
                            "marketplace_id": marketplace.id,
                            "odoo_id": product.id,
                            "seller_sku": seller_sku,
                            "asin": asin,
                            "sync_stock": True,
                            "sync_price": True,
                        }
                    )
                    self.product_binding_id = new_binding
                    _logger.info("Created new binding for SKU %s", seller_sku)
            else:
                _logger.warning(
                    "No Odoo product found for SKU %s, skipping binding creation",
                    seller_sku,
                )

    def _handle_quantity_change(self):
        """Handle LISTINGS_ITEM_MFN_QUANTITY_CHANGE notification.

        Could be used to reconcile stock levels.
        """
        payload = self._get_payload_dict()
        seller_sku = payload.get("SellerSKU") or payload.get("sellerSku")

        _logger.info(
            "Received MFN quantity change for SKU %s (reconciliation not implemented)",
            seller_sku,
        )
        # Future: Could trigger stock reconciliation

    def _handle_fba_inventory_change(self):
        """Handle FBA_INVENTORY_AVAILABILITY_CHANGES notification.

        Could be used to sync FBA inventory levels.
        """
        payload = self._get_payload_dict()

        _logger.info(
            "Received FBA inventory change (sync not implemented): %s",
            payload,
        )
        # Future: Could trigger FBA inventory sync

    def _handle_feed_finished(self):
        """Handle FEED_PROCESSING_FINISHED notification.

        Updates the feed record with processing results.
        """
        payload = self._get_payload_dict()

        feed_id = payload.get("feedId")
        processing_status = payload.get("processingStatus")

        if not feed_id:
            _logger.warning("FEED_PROCESSING_FINISHED missing feedId: %s", payload)
            return

        _logger.info(
            "Processing FEED_PROCESSING_FINISHED for feed %s, status %s",
            feed_id,
            processing_status,
        )

        # Find the feed record
        feed = self.env["amz.feed"].search(
            [
                ("backend_id", "=", self.backend_id.id),
                ("external_feed_id", "=", feed_id),
            ],
            limit=1,
        )

        if feed:
            # Update feed status
            state_mapping = {
                "DONE": "done",
                "CANCELLED": "error",
                "FATAL": "error",
            }
            new_state = state_mapping.get(processing_status, "error")

            feed.write(
                {
                    "state": new_state,
                    "last_state_message": f"Notification: {processing_status}",
                    "last_status_update": fields.Datetime.now(),
                }
            )
            self.feed_id = feed
        else:
            _logger.warning("Feed %s not found for notification", feed_id)

    def _handle_report_finished(self):
        """Handle REPORT_PROCESSING_FINISHED notification.

        Could be used to auto-download completed reports.
        """
        payload = self._get_payload_dict()

        report_id = payload.get("reportId")
        processing_status = payload.get("processingStatus")

        _logger.info(
            "Received REPORT_PROCESSING_FINISHED for report %s, status %s",
            report_id,
            processing_status,
        )
        # Future: Could trigger auto-download of report

    def _handle_pricing_health(self):
        """Handle PRICING_HEALTH notification.

        Alerts about pricing issues (suppressed offers, etc.)
        """
        payload = self._get_payload_dict()

        _logger.info("Received PRICING_HEALTH notification: %s", payload)
        # Future: Could create alerts or trigger price updates

    def action_retry(self):
        """Manually retry processing a failed notification."""
        self.ensure_one()
        if self.state in ("error", "ignored"):
            self.write({"state": "received"})
            self.with_delay().process_notification()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Retry Queued",
                "message": "Notification processing has been queued for retry.",
                "type": "success",
                "sticky": False,
            },
        }

    def action_view_raw_message(self):
        """Open a popup to view the full raw message."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Raw Message",
            "res_model": "amz.notification.log",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": {
                "form_view_ref": "connector_amazon.view_notification_log_raw_form"
            },
        }
