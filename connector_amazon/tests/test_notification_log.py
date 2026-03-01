# Copyright 2025 Kencove
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)
"""Tests for amz.notification.log: process, dispatch, retry, payload parsing."""

import json
from unittest import mock

from odoo.tests import tagged

from .common import CommonConnectorAmazonSpapi


@tagged("post_install", "-at_install")
class TestProcessNotification(CommonConnectorAmazonSpapi):
    """Tests for process_notification() dispatch and state transitions."""

    def _create_notification(self, notif_type, payload=None, **kw):
        """Helper to create a notification log record."""
        vals = {
            "backend_id": self.backend.id,
            "notification_type": notif_type,
            "message_id": kw.pop("message_id", "MSG-TEST-001"),
            "state": kw.pop("state", "received"),
            "payload": json.dumps(payload) if payload else "",
        }
        vals.update(kw)
        return self.env["amz.notification.log"].create(vals)

    def test_order_change_finds_existing_order(self):
        """Test ORDER_CHANGE links to existing order binding."""
        order = self._create_amazon_order(external_id="ORDER-NOTIF-001")
        # Mock _sync_order_from_api so it doesn't hit the network
        with mock.patch.object(type(order), "_sync_order_from_api"):
            notif = self._create_notification(
                "ORDER_CHANGE",
                payload={"AmazonOrderId": "ORDER-NOTIF-001"},
            )
            notif.process_notification()

        self.assertEqual(notif.state, "processed")
        self.assertEqual(notif.order_id, order)

    def test_order_change_nested_structure(self):
        """Test ORDER_CHANGE handles nested OrderChangeNotification key."""
        order = self._create_amazon_order(external_id="ORDER-NESTED-001")
        with mock.patch.object(type(order), "_sync_order_from_api"):
            notif = self._create_notification(
                "ORDER_CHANGE",
                payload={
                    "OrderChangeNotification": {
                        "AmazonOrderId": "ORDER-NESTED-001",
                    }
                },
            )
            notif.process_notification()

        self.assertEqual(notif.state, "processed")
        self.assertEqual(notif.order_id, order)

    def test_order_change_missing_order_id_still_processed(self):
        """Test ORDER_CHANGE with no AmazonOrderId completes without error."""
        notif = self._create_notification(
            "ORDER_CHANGE",
            payload={"SomeOtherField": "value"},
        )
        notif.process_notification()

        self.assertEqual(notif.state, "processed")

    def test_listings_change_updates_existing_binding(self):
        """Test LISTINGS_ITEM_STATUS_CHANGE updates existing binding ASIN."""
        binding = self._create_product_binding(
            seller_sku="NOTIF-SKU-001", asin="B08OLD"
        )
        notif = self._create_notification(
            "LISTINGS_ITEM_STATUS_CHANGE",
            payload={
                "SellerSKU": "NOTIF-SKU-001",
                "Asin": "B08NEW",
                "Status": "Active",
            },
        )
        notif.process_notification()

        self.assertEqual(notif.state, "processed")
        self.assertEqual(notif.product_binding_id, binding)
        binding.invalidate_recordset()
        self.assertEqual(binding.asin, "B08NEW")

    def test_listings_change_creates_binding_for_known_product(self):
        """Test LISTINGS_ITEM_STATUS_CHANGE creates binding when product exists."""
        product = self.env["product.product"].create(
            {
                "name": "Notif Product",
                "default_code": "NOTIF-NEW-SKU",
                "type": "product",
            }
        )
        notif = self._create_notification(
            "LISTINGS_ITEM_STATUS_CHANGE",
            payload={
                "SellerSKU": "NOTIF-NEW-SKU",
                "Asin": "B08BRAND",
                "Status": "Active",
            },
        )
        notif.process_notification()

        self.assertEqual(notif.state, "processed")
        self.assertTrue(notif.product_binding_id)
        self.assertEqual(notif.product_binding_id.odoo_id, product)
        self.assertEqual(notif.product_binding_id.asin, "B08BRAND")

    def test_listings_change_missing_sku_still_processed(self):
        """Test LISTINGS_ITEM_STATUS_CHANGE without SellerSKU completes."""
        notif = self._create_notification(
            "LISTINGS_ITEM_STATUS_CHANGE",
            payload={"Asin": "B08NOSKU"},
        )
        notif.process_notification()

        self.assertEqual(notif.state, "processed")

    def test_feed_finished_updates_feed_done(self):
        """Test FEED_PROCESSING_FINISHED updates feed to done state."""
        feed = self.env["amz.feed"].create(
            {
                "backend_id": self.backend.id,
                "marketplace_id": self.marketplace.id,
                "feed_type": "POST_INVENTORY_AVAILABILITY_DATA",
                "state": "in_progress",
                "external_feed_id": "FEED-NOTIF-001",
                "payload_json": "<test/>",
            }
        )
        notif = self._create_notification(
            "FEED_PROCESSING_FINISHED",
            payload={
                "feedId": "FEED-NOTIF-001",
                "processingStatus": "DONE",
            },
        )
        notif.process_notification()

        self.assertEqual(notif.state, "processed")
        self.assertEqual(notif.feed_id, feed)
        feed.invalidate_recordset()
        self.assertEqual(feed.state, "done")

    def test_feed_finished_fatal_sets_error(self):
        """Test FEED_PROCESSING_FINISHED with FATAL sets feed to error."""
        feed = self.env["amz.feed"].create(
            {
                "backend_id": self.backend.id,
                "marketplace_id": self.marketplace.id,
                "feed_type": "POST_INVENTORY_AVAILABILITY_DATA",
                "state": "in_progress",
                "external_feed_id": "FEED-NOTIF-002",
                "payload_json": "<test/>",
            }
        )
        notif = self._create_notification(
            "FEED_PROCESSING_FINISHED",
            payload={
                "feedId": "FEED-NOTIF-002",
                "processingStatus": "FATAL",
            },
        )
        notif.process_notification()

        feed.invalidate_recordset()
        self.assertEqual(feed.state, "error")

    def test_feed_finished_missing_feed_id_still_processed(self):
        """Test FEED_PROCESSING_FINISHED without feedId completes."""
        notif = self._create_notification(
            "FEED_PROCESSING_FINISHED",
            payload={"processingStatus": "DONE"},
        )
        notif.process_notification()

        self.assertEqual(notif.state, "processed")

    def test_report_finished_processed(self):
        """Test REPORT_PROCESSING_FINISHED is handled without error."""
        notif = self._create_notification(
            "REPORT_PROCESSING_FINISHED",
            payload={
                "reportId": "RPT-001",
                "processingStatus": "DONE",
            },
        )
        notif.process_notification()

        self.assertEqual(notif.state, "processed")

    def test_unknown_type_ignored(self):
        """Test unknown notification type is set to ignored state."""
        notif = self._create_notification(
            "other",
            payload={"data": "value"},
        )
        notif.process_notification()

        self.assertEqual(notif.state, "ignored")
        self.assertIn("No handler for type", notif.error_message)

    def test_skips_already_processed(self):
        """Test process_notification skips if already processed."""
        notif = self._create_notification(
            "ORDER_CHANGE",
            state="processed",
            payload={"AmazonOrderId": "SKIP-ME"},
        )
        notif.process_notification()

        # Should remain processed, not re-process
        self.assertEqual(notif.state, "processed")

    def test_error_state_allows_reprocessing(self):
        """Test process_notification allows reprocessing from error state."""
        notif = self._create_notification(
            "REPORT_PROCESSING_FINISHED",
            state="error",
            payload={"reportId": "RPT-002", "processingStatus": "DONE"},
        )
        notif.process_notification()

        self.assertEqual(notif.state, "processed")

    def test_handler_exception_sets_error_state(self):
        """Test handler exception transitions to error state and increments retry."""
        notif = self._create_notification(
            "ORDER_CHANGE",
            payload={"AmazonOrderId": "ERROR-TEST"},
        )
        # Mock handler to raise
        with mock.patch.object(
            type(notif), "_handle_order_change", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(RuntimeError):
                notif.process_notification()

        self.assertEqual(notif.state, "error")
        self.assertIn("boom", notif.error_message)
        self.assertEqual(notif.retry_count, 1)

    def test_quantity_change_processed(self):
        """Test LISTINGS_ITEM_MFN_QUANTITY_CHANGE is processed without error."""
        notif = self._create_notification(
            "LISTINGS_ITEM_MFN_QUANTITY_CHANGE",
            payload={"SellerSKU": "QTY-SKU-001", "Quantity": 42},
        )
        notif.process_notification()

        self.assertEqual(notif.state, "processed")

    def test_fba_inventory_change_processed(self):
        """Test FBA_INVENTORY_AVAILABILITY_CHANGES is processed without error."""
        notif = self._create_notification(
            "FBA_INVENTORY_AVAILABILITY_CHANGES",
            payload={"FNSKU": "X00123", "ASIN": "B08FBA001"},
        )
        notif.process_notification()

        self.assertEqual(notif.state, "processed")

    def test_pricing_health_processed(self):
        """Test PRICING_HEALTH notification is processed without error."""
        notif = self._create_notification(
            "PRICING_HEALTH",
            payload={
                "ASIN": "B08PRICE",
                "SellerSKU": "PRICE-SKU",
                "IssueType": "Suppressed",
            },
        )
        notif.process_notification()

        self.assertEqual(notif.state, "processed")

    def test_listings_change_camelcase_keys(self):
        """Test LISTINGS_ITEM_STATUS_CHANGE handles lowercase camelCase keys."""
        self._create_product_binding(seller_sku="CAMEL-SKU", asin="B08OLD")
        notif = self._create_notification(
            "LISTINGS_ITEM_STATUS_CHANGE",
            payload={
                "sellerSku": "CAMEL-SKU",
                "asin": "B08CAMEL",
                "status": "Active",
            },
        )
        notif.process_notification()

        self.assertEqual(notif.state, "processed")
        self.assertTrue(notif.product_binding_id)

    def test_feed_finished_cancelled_sets_error(self):
        """Test FEED_PROCESSING_FINISHED with CANCELLED sets feed to error."""
        feed = self.env["amz.feed"].create(
            {
                "backend_id": self.backend.id,
                "marketplace_id": self.marketplace.id,
                "feed_type": "POST_INVENTORY_AVAILABILITY_DATA",
                "state": "in_progress",
                "external_feed_id": "FEED-CANCEL-001",
                "payload_json": "<test/>",
            }
        )
        notif = self._create_notification(
            "FEED_PROCESSING_FINISHED",
            payload={
                "feedId": "FEED-CANCEL-001",
                "processingStatus": "CANCELLED",
            },
        )
        notif.process_notification()

        feed.invalidate_recordset()
        self.assertEqual(feed.state, "error")


@tagged("post_install", "-at_install")
class TestSyncOrderFromApi(CommonConnectorAmazonSpapi):
    """Tests for _sync_order_from_api() method."""

    @mock.patch(
        "odoo.addons.connector_amazon.models.backend." "AmazonBackend._call_sp_api"
    )
    def test_sync_order_from_api_updates_status(self, mock_call_api):
        """Test _sync_order_from_api fetches and updates order data."""
        order = self._create_amazon_order(external_id="SYNC-API-001", status="Pending")
        mock_call_api.return_value = {
            "payload": {
                "AmazonOrderId": "SYNC-API-001",
                "OrderStatus": "Shipped",
                "PurchaseDate": "2025-06-01T10:00:00Z",
                "LastUpdateDate": "2025-06-02T10:00:00Z",
                "FulfillmentChannel": "MFN",
                "ShipServiceLevel": "Standard",
            }
        }

        order._sync_order_from_api()

        order.invalidate_recordset()
        self.assertEqual(order.status, "Shipped")
        self.assertTrue(order.last_sync)

    @mock.patch(
        "odoo.addons.connector_amazon.models.backend." "AmazonBackend._call_sp_api"
    )
    def test_sync_order_from_api_empty_payload(self, mock_call_api):
        """Test _sync_order_from_api handles empty payload gracefully."""
        order = self._create_amazon_order(external_id="SYNC-API-002", status="Pending")
        mock_call_api.return_value = {"payload": None}

        order._sync_order_from_api()

        # Status should remain unchanged
        self.assertEqual(order.status, "Pending")

    @mock.patch(
        "odoo.addons.connector_amazon.models.backend." "AmazonBackend._call_sp_api"
    )
    def test_sync_order_from_api_handles_api_error(self, mock_call_api):
        """Test _sync_order_from_api handles API errors without raising."""
        order = self._create_amazon_order(external_id="SYNC-API-003", status="Pending")
        mock_call_api.side_effect = Exception("Network timeout")

        # Should not raise — errors are logged
        order._sync_order_from_api()

        self.assertEqual(order.status, "Pending")

    def test_sync_order_from_api_no_external_id(self):
        """Test _sync_order_from_api returns early with no external_id."""
        order = self._create_amazon_order(external_id="SYNC-NOOP")
        order.write({"external_id": False})

        # Should return without error
        order._sync_order_from_api()


@tagged("post_install", "-at_install")
class TestActionRetry(CommonConnectorAmazonSpapi):
    """Tests for action_retry() method."""

    def test_retry_requeues_error_notification(self):
        """Test action_retry resets state and queues job."""
        notif = self.env["amz.notification.log"].create(
            {
                "backend_id": self.backend.id,
                "notification_type": "ORDER_CHANGE",
                "message_id": "RETRY-001",
                "state": "error",
                "payload": json.dumps({"AmazonOrderId": "RETRY-ORDER"}),
                "retry_count": 2,
            }
        )

        with mock.patch.object(type(notif), "with_delay") as mock_delay:
            mock_delay.return_value = mock.Mock()
            result = notif.action_retry()

        self.assertEqual(notif.state, "received")
        self.assertEqual(result["params"]["type"], "success")

    def test_retry_requeues_ignored_notification(self):
        """Test action_retry works on ignored notifications too."""
        notif = self.env["amz.notification.log"].create(
            {
                "backend_id": self.backend.id,
                "notification_type": "other",
                "message_id": "RETRY-002",
                "state": "ignored",
            }
        )

        with mock.patch.object(type(notif), "with_delay") as mock_delay:
            mock_delay.return_value = mock.Mock()
            result = notif.action_retry()

        self.assertEqual(notif.state, "received")
        self.assertEqual(result["params"]["type"], "success")

    def test_retry_noop_on_received_state(self):
        """Test action_retry does nothing if already in received state."""
        notif = self.env["amz.notification.log"].create(
            {
                "backend_id": self.backend.id,
                "notification_type": "ORDER_CHANGE",
                "message_id": "RETRY-003",
                "state": "received",
            }
        )

        with mock.patch.object(type(notif), "with_delay") as mock_delay:
            mock_delay.return_value = mock.Mock()
            notif.action_retry()

        # with_delay should NOT have been called since state is received
        mock_delay.assert_not_called()


@tagged("post_install", "-at_install")
class TestPayloadParsing(CommonConnectorAmazonSpapi):
    """Tests for _get_payload_dict() JSON parsing."""

    def test_valid_json_payload(self):
        """Test _get_payload_dict parses valid JSON."""
        notif = self.env["amz.notification.log"].create(
            {
                "backend_id": self.backend.id,
                "notification_type": "ORDER_CHANGE",
                "message_id": "PARSE-001",
                "payload": json.dumps({"key": "value", "nested": {"a": 1}}),
            }
        )

        result = notif._get_payload_dict()

        self.assertEqual(result["key"], "value")
        self.assertEqual(result["nested"]["a"], 1)

    def test_invalid_json_returns_empty_dict(self):
        """Test _get_payload_dict returns {} for invalid JSON."""
        notif = self.env["amz.notification.log"].create(
            {
                "backend_id": self.backend.id,
                "notification_type": "ORDER_CHANGE",
                "message_id": "PARSE-002",
                "payload": "not valid json {{{",
            }
        )

        result = notif._get_payload_dict()

        self.assertEqual(result, {})

    def test_empty_payload_returns_empty_dict(self):
        """Test _get_payload_dict returns {} for empty/falsy payload."""
        notif = self.env["amz.notification.log"].create(
            {
                "backend_id": self.backend.id,
                "notification_type": "ORDER_CHANGE",
                "message_id": "PARSE-003",
                "payload": "",
            }
        )

        result = notif._get_payload_dict()

        self.assertEqual(result, {})


@tagged("post_install", "-at_install")
class TestDisplayName(CommonConnectorAmazonSpapi):
    """Tests for _compute_display_name."""

    def test_display_name_with_type_and_message_id(self):
        """Test display name includes type and truncated message ID."""
        notif = self.env["amz.notification.log"].create(
            {
                "backend_id": self.backend.id,
                "notification_type": "ORDER_CHANGE",
                "message_id": "ABCDEFGHIJKLMNOP",
            }
        )

        self.assertIn("ORDER_CHANGE", notif.display_name)
        self.assertIn("ABCDEFGH", notif.display_name)

    def test_display_name_without_message_id(self):
        """Test display name falls back to notification type."""
        notif = self.env["amz.notification.log"].create(
            {
                "backend_id": self.backend.id,
                "notification_type": "FEED_PROCESSING_FINISHED",
            }
        )

        self.assertEqual(notif.display_name, "FEED_PROCESSING_FINISHED")
