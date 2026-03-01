# Copyright 2025 Kencove
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)
"""Tests for Amazon shop sync operations: bulk catalog, stock push, pricing, crons."""

from unittest import mock

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CommonConnectorAmazonSpapi


@tagged("post_install", "-at_install")
class TestSyncCatalogBulk(CommonConnectorAmazonSpapi):
    """Tests for sync_catalog_bulk() via Reports API."""

    @mock.patch("requests.get")
    @mock.patch("time.sleep", return_value=None)
    @mock.patch(
        "odoo.addons.connector_amazon.models.backend.AmazonBackend._call_sp_api"
    )
    def test_sync_catalog_bulk_happy_path(
        self, mock_call_api, mock_sleep, mock_requests_get
    ):
        """Test full sync_catalog_bulk flow: create_report -> poll -> download -> parse."""
        tsv_content = self._create_sample_listings_tsv()

        # Mock API calls: create_report, get_report (DONE), get_report_document
        mock_call_api.side_effect = [
            {"reportId": "RPT-001"},
            {"processingStatus": "DONE", "reportDocumentId": "DOC-001"},
            {"url": "https://s3.example.com/report.tsv"},
        ]

        # Mock TSV download
        mock_response = mock.Mock()
        mock_response.content = tsv_content.encode("utf-8")
        mock_response.raise_for_status = mock.Mock()
        mock_requests_get.return_value = mock_response

        result = self.shop.sync_catalog_bulk()

        # Verify all 3 API calls were made
        self.assertEqual(mock_call_api.call_count, 3)
        # Default TSV has TEST-SKU-001 which matches self.product
        self.assertEqual(result["created"], 1)
        self.assertTrue(self.shop.last_catalog_sync)

    @mock.patch("requests.get")
    @mock.patch("time.sleep", return_value=None)
    @mock.patch(
        "odoo.addons.connector_amazon.models.backend.AmazonBackend._call_sp_api"
    )
    def test_sync_catalog_bulk_report_polls_in_progress(
        self, mock_call_api, mock_sleep, mock_requests_get
    ):
        """Test sync_catalog_bulk retries when report is IN_PROGRESS."""
        tsv = self._create_sample_listings_tsv()
        mock_call_api.side_effect = [
            {"reportId": "RPT-002"},
            {"processingStatus": "IN_PROGRESS"},
            {"processingStatus": "IN_PROGRESS"},
            {"processingStatus": "DONE", "reportDocumentId": "DOC-002"},
            {"url": "https://s3.example.com/report.tsv"},
        ]

        mock_resp = mock.Mock()
        mock_resp.content = tsv.encode("utf-8")
        mock_resp.raise_for_status = mock.Mock()
        mock_requests_get.return_value = mock_resp

        self.shop.sync_catalog_bulk()

        # create_report + 3x get_report + get_report_document = 5
        self.assertEqual(mock_call_api.call_count, 5)

    @mock.patch("time.sleep", return_value=None)
    @mock.patch(
        "odoo.addons.connector_amazon.models.backend.AmazonBackend._call_sp_api"
    )
    def test_sync_catalog_bulk_report_cancelled_raises(self, mock_call_api, mock_sleep):
        """Test sync_catalog_bulk raises UserError on CANCELLED report."""
        mock_call_api.side_effect = [
            {"reportId": "RPT-003"},
            {"processingStatus": "CANCELLED"},
        ]

        with self.assertRaises(UserError) as cm:
            self.shop.sync_catalog_bulk()

        self.assertIn("CANCELLED", str(cm.exception))

    @mock.patch("time.sleep", return_value=None)
    @mock.patch(
        "odoo.addons.connector_amazon.models.backend.AmazonBackend._call_sp_api"
    )
    def test_sync_catalog_bulk_report_fatal_raises(self, mock_call_api, mock_sleep):
        """Test sync_catalog_bulk raises UserError on FATAL report."""
        mock_call_api.side_effect = [
            {"reportId": "RPT-004"},
            {"processingStatus": "FATAL"},
        ]

        with self.assertRaises(UserError) as cm:
            self.shop.sync_catalog_bulk()

        self.assertIn("FATAL", str(cm.exception))

    @mock.patch(
        "odoo.addons.connector_amazon.models.backend.AmazonBackend._call_sp_api"
    )
    def test_sync_catalog_bulk_no_report_id_raises(self, mock_call_api):
        """Test sync_catalog_bulk raises when no reportId returned."""
        mock_call_api.return_value = {}

        with self.assertRaises(UserError) as cm:
            self.shop.sync_catalog_bulk()

        self.assertIn("no reportId", str(cm.exception))

    @mock.patch("time.sleep", return_value=None)
    @mock.patch(
        "odoo.addons.connector_amazon.models.backend.AmazonBackend._call_sp_api"
    )
    def test_sync_catalog_bulk_timeout_raises(self, mock_call_api, mock_sleep):
        """Test sync_catalog_bulk raises after polling times out."""
        mock_call_api.side_effect = [
            {"reportId": "RPT-005"},
        ] + [{"processingStatus": "IN_PROGRESS"}] * 60

        with self.assertRaises(UserError) as cm:
            self.shop.sync_catalog_bulk()

        self.assertIn("timed out", str(cm.exception))

    @mock.patch("requests.get")
    @mock.patch("time.sleep", return_value=None)
    @mock.patch(
        "odoo.addons.connector_amazon.models.backend.AmazonBackend._call_sp_api"
    )
    def test_sync_catalog_bulk_gzip_report(
        self, mock_call_api, mock_sleep, mock_requests_get
    ):
        """Test sync_catalog_bulk handles GZIP compressed reports."""
        import gzip

        tsv = self._create_sample_listings_tsv()

        mock_call_api.side_effect = [
            {"reportId": "RPT-GZ"},
            {"processingStatus": "DONE", "reportDocumentId": "DOC-GZ"},
            {
                "url": "https://s3.example.com/report.tsv.gz",
                "compressionAlgorithm": "GZIP",
            },
        ]

        mock_resp = mock.Mock()
        mock_resp.content = gzip.compress(tsv.encode("utf-8"))
        mock_resp.raise_for_status = mock.Mock()
        mock_requests_get.return_value = mock_resp

        result = self.shop.sync_catalog_bulk()

        self.assertEqual(result["created"], 1)


@tagged("post_install", "-at_install")
class TestProcessListingsReport(CommonConnectorAmazonSpapi):
    """Tests for _process_listings_report() TSV parsing."""

    def test_process_listings_report_creates_bindings(self):
        """Test TSV report parsing creates product bindings for matched products."""
        result = self.shop._process_listings_report(self._create_sample_listings_tsv())

        # self.product has default_code=TEST-SKU-001 matching TSV
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["skipped"], 0)

    def test_process_listings_report_updates_existing_binding(self):
        """Test _process_listings_report updates existing binding ASIN."""
        self._create_product_binding(seller_sku="TEST-SKU-001", asin="B08OLD")

        tsv = self._create_sample_listings_tsv(
            [{"seller-sku": "TEST-SKU-001", "asin1": "B08NEW", "status": "Active"}]
        )

        result = self.shop._process_listings_report(tsv)

        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["created"], 0)

        binding = self.env["amz.product.binding"].search(
            [("backend_id", "=", self.backend.id), ("seller_sku", "=", "TEST-SKU-001")]
        )
        self.assertEqual(binding.asin, "B08NEW")

    def test_process_listings_report_skips_empty_sku(self):
        """Test _process_listings_report skips rows without seller-sku."""
        tsv = self._create_sample_listings_tsv(
            [{"seller-sku": "", "asin1": "B08NOSKU", "status": "Active"}]
        )

        result = self.shop._process_listings_report(tsv)

        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["created"], 0)

    def test_process_listings_report_skips_unmatched_product(self):
        """Test _process_listings_report skips SKUs with no Odoo product."""
        tsv = self._create_sample_listings_tsv(
            [{"seller-sku": "UNKNOWN-SKU", "asin1": "B08UNKNOWN"}]
        )

        result = self.shop._process_listings_report(tsv)

        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["created"], 0)

    def test_process_listings_report_multiple_rows(self):
        """Test _process_listings_report handles multiple rows correctly."""
        self.env["product.product"].create(
            {"name": "Extra Product", "default_code": "EXTRA-SKU", "type": "product"}
        )

        tsv = self._create_sample_listings_tsv(
            [
                {"seller-sku": "TEST-SKU-001", "asin1": "B08A"},
                {"seller-sku": "EXTRA-SKU", "asin1": "B08B"},
                {"seller-sku": "MISSING-SKU", "asin1": "B08C"},
                {"seller-sku": "", "asin1": "B08D"},
            ]
        )

        result = self.shop._process_listings_report(tsv)

        self.assertEqual(result["created"], 2)  # TEST-SKU-001 + EXTRA-SKU
        self.assertEqual(result["skipped"], 2)  # MISSING-SKU + empty


@tagged("post_install", "-at_install")
class TestPushStockDetails(CommonConnectorAmazonSpapi):
    """Additional tests for push_stock and _build_inventory_feed_xml."""

    def test_push_stock_no_bindings_returns_early(self):
        """Test push_stock returns early when no bindings have sync_stock=True."""
        self.shop.sync_stock = True

        feed_count_before = self.env["amz.feed"].search_count(
            [("backend_id", "=", self.backend.id)]
        )
        self.shop.push_stock()
        feed_count_after = self.env["amz.feed"].search_count(
            [("backend_id", "=", self.backend.id)]
        )
        self.assertEqual(feed_count_before, feed_count_after)

    def test_build_inventory_feed_xml_multiple_products(self):
        """Test XML contains all products with correct message IDs."""
        bindings_list = []
        for i in range(3):
            prod = self.env["product.product"].create(
                {"name": f"Prod {i}", "default_code": f"MP-{i}", "type": "product"}
            )
            b = self._create_product_binding(seller_sku=f"MP-{i}", odoo_id=prod.id)
            self._set_qty_in_stock_location(prod, 10.0 * (i + 1))
            bindings_list.append(b)

        bindings = bindings_list[0] | bindings_list[1] | bindings_list[2]
        xml = self.shop._build_inventory_feed_xml(bindings)

        for i in range(3):
            self.assertIn(f"<SKU>MP-{i}</SKU>", xml)
            self.assertIn(f"<MessageID>{i + 1}</MessageID>", xml)

    def test_build_inventory_feed_xml_zero_stock(self):
        """Test XML sends 0 when product has no stock."""
        prod = self.env["product.product"].create(
            {"name": "Zero", "default_code": "ZERO-SKU", "type": "product"}
        )
        binding = self._create_product_binding(seller_sku="ZERO-SKU", odoo_id=prod.id)
        # Default qty is 0

        xml = self.shop._build_inventory_feed_xml(binding)

        self.assertIn("<Available>0</Available>", xml)

    def test_push_stock_read_only_no_feed(self):
        """Test push_stock in read-only mode: no feed created, timestamp updated."""
        self.shop.sync_stock = True
        self.backend.write({"read_only_mode": True, "test_mode": True})

        binding = self._create_product_binding(seller_sku="RO-SKU", sync_stock=True)
        self._set_qty_in_stock_location(binding.odoo_id, 25.0)

        feed_count_before = self.env["amz.feed"].search_count(
            [("backend_id", "=", self.backend.id)]
        )

        self.shop.push_stock()

        feed_count_after = self.env["amz.feed"].search_count(
            [("backend_id", "=", self.backend.id)]
        )
        self.assertEqual(feed_count_before, feed_count_after)
        self.assertTrue(self.shop.last_stock_sync)


@tagged("post_install", "-at_install")
class TestCronMethods(CommonConnectorAmazonSpapi):
    """Tests for cron job methods on amz.shop."""

    def test_cron_sync_orders_processes_hourly_shops(self):
        """Test cron_sync_orders finds hourly shops with import_orders."""
        self.shop.write(
            {
                "import_orders": True,
                "order_sync_interval": "hourly",
                "active": True,
            }
        )

        with mock.patch.object(type(self.shop), "action_sync_orders") as mock_sync:
            self.env["amz.shop"].cron_sync_orders()
            mock_sync.assert_called()

    def test_cron_sync_competitive_prices_processes_shops(self):
        """Test cron_sync_competitive_prices queues jobs for active shops."""
        self.shop.write({"sync_price": True, "active": True})

        with mock.patch.object(type(self.shop), "with_delay") as mock_delay:
            mock_delay.return_value = mock.Mock()
            self.env["amz.shop"].cron_sync_competitive_prices()

    def test_cron_sync_catalog_bulk_daily_shops(self):
        """Test cron_sync_catalog_bulk queues for daily-configured shops."""
        self.shop.write({"active": True, "catalog_sync_interval": "daily"})

        with mock.patch.object(type(self.shop), "with_delay") as mock_delay:
            mock_delay.return_value = mock.Mock()
            self.env["amz.shop"].cron_sync_catalog_bulk()

    def test_cron_push_stock_skips_disabled(self):
        """Test cron_push_stock skips shops with sync_stock=False."""
        self.shop.write({"sync_stock": False, "active": True})

        with mock.patch.object(type(self.shop), "action_push_stock") as mock_push:
            self.env["amz.shop"].cron_push_stock()
            mock_push.assert_not_called()

    def test_cron_push_shipments_skips_no_tracking(self):
        """Test cron_push_shipments skips orders without carrier tracking."""
        order = self._create_amazon_order(external_id="CRON-SHIP-001")
        order.write({"shipment_confirmed": False})

        # Create done picking without tracking ref
        self._create_done_picking(order.odoo_id)

        self.shop.cron_push_shipments()

        self.assertFalse(order.shipment_confirmed)
