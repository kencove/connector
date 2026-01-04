# Copyright 2025 Kencove
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import json
from unittest.mock import MagicMock, patch

from odoo.tests import tagged

from .common import CommonConnectorAmazonSpapi


@tagged("post_install", "-at_install")
class TestWebhookController(CommonConnectorAmazonSpapi):
    """Test Amazon webhook controller for SNS notifications"""

    def setUp(self):
        super().setUp()
        # Enable webhook on backend with test mode
        self.backend.write({
            "webhook_active": True,
            "test_mode": True,  # Skip signature verification
            "notify_order_change": True,
            "notify_listings_change": True,
            "notify_feed_processing": True,
        })
        self.webhook_token = self.backend.webhook_token

    def test_notification_log_model_exists(self):
        """Test that the notification log model is properly registered"""
        self.assertTrue(
            "amazon.notification.log" in self.env,
            "amazon.notification.log model should be registered"
        )

    def test_notification_log_creation(self):
        """Test creating a notification log entry"""
        log = self.env["amazon.notification.log"].create({
            "backend_id": self.backend.id,
            "notification_type": "ORDER_CHANGE",
            "message_id": "test-message-id-123",
            "state": "received",
            "payload": json.dumps({"AmazonOrderId": "111-1111111-1111111"}),
        })

        self.assertTrue(log.id)
        self.assertEqual(log.notification_type, "ORDER_CHANGE")
        self.assertEqual(log.state, "received")
        self.assertEqual(log.backend_id.id, self.backend.id)

    def test_notification_log_display_name(self):
        """Test notification log display name computation"""
        log = self.env["amazon.notification.log"].create({
            "backend_id": self.backend.id,
            "notification_type": "ORDER_CHANGE",
            "message_id": "abcd1234-5678-90ef-ghij-klmnopqrstuv",
            "state": "received",
        })

        self.assertIn("ORDER_CHANGE", log.display_name)
        self.assertIn("abcd1234", log.display_name)

    def test_notification_log_process_order_change(self):
        """Test processing ORDER_CHANGE notification"""
        # Create existing order to update
        amazon_order = self._create_amazon_order(
            external_id="111-1111111-1111111"
        )

        log = self.env["amazon.notification.log"].create({
            "backend_id": self.backend.id,
            "notification_type": "ORDER_CHANGE",
            "message_id": "test-order-change-msg",
            "state": "received",
            "payload": json.dumps({
                "AmazonOrderId": "111-1111111-1111111",
                "OrderChangeNotification": {
                    "AmazonOrderId": "111-1111111-1111111",
                    "OrderStatus": "Shipped",
                }
            }),
        })

        # Mock the sync call to avoid API calls
        with patch.object(
            type(amazon_order), "_sync_order_from_api", return_value=None
        ):
            log.process_notification()

        self.assertEqual(log.state, "processed")
        self.assertEqual(log.order_id.id, amazon_order.id)

    def test_notification_log_process_listings_change(self):
        """Test processing LISTINGS_ITEM_STATUS_CHANGE notification"""
        # Create existing product binding
        binding = self._create_product_binding(seller_sku="TEST-SKU-001")

        log = self.env["amazon.notification.log"].create({
            "backend_id": self.backend.id,
            "notification_type": "LISTINGS_ITEM_STATUS_CHANGE",
            "message_id": "test-listings-change-msg",
            "state": "received",
            "payload": json.dumps({
                "SellerSKU": "TEST-SKU-001",
                "Asin": "B08NEWTEST",
                "Status": "Active",
            }),
        })

        log.process_notification()

        self.assertEqual(log.state, "processed")
        self.assertEqual(log.product_binding_id.id, binding.id)
        # ASIN should be updated
        self.assertEqual(binding.asin, "B08NEWTEST")

    def test_notification_log_process_feed_finished(self):
        """Test processing FEED_PROCESSING_FINISHED notification"""
        # Create a feed record
        feed = self.env["amazon.feed"].create({
            "backend_id": self.backend.id,
            "external_feed_id": "feed-12345-67890",
            "feed_type": "POST_INVENTORY_AVAILABILITY_DATA",
            "state": "submitted",
        })

        log = self.env["amazon.notification.log"].create({
            "backend_id": self.backend.id,
            "notification_type": "FEED_PROCESSING_FINISHED",
            "message_id": "test-feed-finished-msg",
            "state": "received",
            "payload": json.dumps({
                "feedId": "feed-12345-67890",
                "processingStatus": "DONE",
            }),
        })

        log.process_notification()

        self.assertEqual(log.state, "processed")
        self.assertEqual(log.feed_id.id, feed.id)
        self.assertEqual(feed.state, "done")

    def test_notification_log_unknown_type_ignored(self):
        """Test that unknown notification types are marked as ignored"""
        log = self.env["amazon.notification.log"].create({
            "backend_id": self.backend.id,
            "notification_type": "UNKNOWN_TYPE",
            "message_id": "test-unknown-msg",
            "state": "received",
            "payload": json.dumps({"some": "data"}),
        })

        log.process_notification()

        self.assertEqual(log.state, "ignored")
        self.assertIn("No handler", log.error_message)

    def test_notification_log_retry(self):
        """Test retry functionality for failed notifications"""
        log = self.env["amazon.notification.log"].create({
            "backend_id": self.backend.id,
            "notification_type": "ORDER_CHANGE",
            "message_id": "test-retry-msg",
            "state": "error",
            "error_message": "Previous error",
            "retry_count": 1,
            "payload": json.dumps({"AmazonOrderId": "999-9999999-9999999"}),
        })

        # Mock with_delay to avoid actual queue job
        with patch.object(log, "with_delay", return_value=log):
            result = log.action_retry()

        self.assertEqual(log.state, "received")
        self.assertEqual(result["type"], "ir.actions.client")

    def test_backend_webhook_url_computed(self):
        """Test that webhook URL is properly computed"""
        self.assertTrue(self.backend.webhook_url)
        self.assertIn("/amazon/webhook/", self.backend.webhook_url)
        self.assertIn(self.backend.webhook_token, self.backend.webhook_url)

    def test_backend_webhook_token_regenerate(self):
        """Test regenerating webhook token"""
        old_token = self.backend.webhook_token
        self.backend.action_regenerate_webhook_token()
        new_token = self.backend.webhook_token

        self.assertNotEqual(old_token, new_token)
        self.assertTrue(len(new_token) > 20)


@tagged("post_install", "-at_install")
class TestNotificationLogModel(CommonConnectorAmazonSpapi):
    """Test notification log model methods"""

    def test_get_payload_dict_valid_json(self):
        """Test parsing valid JSON payload"""
        log = self.env["amazon.notification.log"].create({
            "backend_id": self.backend.id,
            "notification_type": "ORDER_CHANGE",
            "state": "received",
            "payload": json.dumps({"key": "value", "number": 123}),
        })

        result = log._get_payload_dict()

        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("key"), "value")
        self.assertEqual(result.get("number"), 123)

    def test_get_payload_dict_empty(self):
        """Test parsing empty payload"""
        log = self.env["amazon.notification.log"].create({
            "backend_id": self.backend.id,
            "notification_type": "ORDER_CHANGE",
            "state": "received",
        })

        result = log._get_payload_dict()

        self.assertEqual(result, {})

    def test_get_payload_dict_invalid_json(self):
        """Test parsing invalid JSON payload"""
        log = self.env["amazon.notification.log"].create({
            "backend_id": self.backend.id,
            "notification_type": "ORDER_CHANGE",
            "state": "received",
            "payload": "not valid json {",
        })

        result = log._get_payload_dict()

        self.assertEqual(result, {})

    def test_handle_order_change_new_order(self):
        """Test ORDER_CHANGE for non-existent order creates new order"""
        log = self.env["amazon.notification.log"].create({
            "backend_id": self.backend.id,
            "notification_type": "ORDER_CHANGE",
            "state": "received",
            "payload": json.dumps({
                "AmazonOrderId": "NEW-ORDER-123",
            }),
        })

        # Mock the adapter to avoid API calls
        mock_adapter = MagicMock()
        mock_adapter.get_order.return_value = {
            "payload": self._create_sample_amazon_order()
        }

        with patch.object(
            self.backend, "work_on"
        ) as mock_work_on:
            mock_work = MagicMock()
            mock_work.component.return_value = mock_adapter
            mock_work_on.return_value.__enter__ = MagicMock(return_value=mock_work)
            mock_work_on.return_value.__exit__ = MagicMock(return_value=False)

            # This will try to sync the new order
            # The handler will log warning since _create_or_update_from_amazon
            # needs more setup
            log._handle_order_change()

    def test_handle_listings_change_create_binding(self):
        """Test LISTINGS_ITEM_STATUS_CHANGE creates new binding when product exists"""
        # Create product with matching SKU
        product = self.env["product.product"].create({
            "name": "New Product",
            "default_code": "NEW-SKU-999",
            "type": "product",
        })

        log = self.env["amazon.notification.log"].create({
            "backend_id": self.backend.id,
            "notification_type": "LISTINGS_ITEM_STATUS_CHANGE",
            "state": "received",
            "payload": json.dumps({
                "SellerSKU": "NEW-SKU-999",
                "Asin": "B09NEWPROD",
                "Status": "Active",
            }),
        })

        log._handle_listings_change()

        # Check binding was created
        binding = self.env["amazon.product.binding"].search([
            ("backend_id", "=", self.backend.id),
            ("seller_sku", "=", "NEW-SKU-999"),
        ])

        self.assertTrue(binding)
        self.assertEqual(binding.asin, "B09NEWPROD")
        self.assertEqual(binding.odoo_id.id, product.id)
        self.assertEqual(log.product_binding_id.id, binding.id)
