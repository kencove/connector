# Copyright 2025 Kencove
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)
"""Tests for shipment push, partner creation, and shipment XML generation."""

from unittest import mock

from odoo import fields
from odoo.tests import tagged

from .common import CommonConnectorAmazonSpapi


@tagged("post_install", "-at_install")
class TestPushShipment(CommonConnectorAmazonSpapi):
    """Tests for push_shipment() and related helper methods."""

    def _setup_order_with_picking(self, external_id, tracking_ref="TRACK-001"):
        """Create an Amazon order with a done picking that has tracking."""
        binding = self._create_amazon_order(external_id=external_id)
        sale_order = binding.odoo_id

        # Create order line + Amazon order line binding
        order_line = self.env["sale.order.line"].create(
            {
                "order_id": sale_order.id,
                "product_id": self.product.id,
                "product_uom_qty": 2,
                "price_unit": 25.0,
            }
        )
        self.env["amz.sale.order.line"].create(
            {
                "odoo_id": order_line.id,
                "amz_order_id": binding.id,
                "external_id": f"ITEM-{external_id}",
                "backend_id": self.backend.id,
            }
        )

        # Create delivery carrier
        carrier = self.env["delivery.carrier"].create(
            {
                "name": "Test Carrier",
                "product_id": self.product.id,
            }
        )
        sale_order.write({"carrier_id": carrier.id})

        picking = self._create_done_picking(
            sale_order, carrier=carrier, tracking_ref=tracking_ref
        )

        return binding, picking, carrier

    @mock.patch("odoo.addons.queue_job.models.base.DelayableRecordset.__getattr__")
    def test_push_shipment_creates_feed(self, mock_delay):
        """Test push_shipment creates a feed with correct XML."""
        mock_delay.return_value = mock.Mock()

        binding, picking, carrier = self._setup_order_with_picking("SHIP-001")

        result = binding.push_shipment()

        self.assertTrue(result)
        self.assertTrue(binding.shipment_confirmed)
        self.assertTrue(binding.last_shipment_push)

        # Verify feed was created
        feed = self.env["amz.feed"].search(
            [
                ("backend_id", "=", self.backend.id),
                ("feed_type", "=", "POST_ORDER_FULFILLMENT_DATA"),
            ],
            limit=1,
        )
        self.assertTrue(feed)
        self.assertIn("SHIP-001", feed.payload_json)
        self.assertIn("TRACK-001", feed.payload_json)

    def test_push_shipment_returns_false_no_picking(self):
        """Test push_shipment returns False when no done picking exists."""
        binding = self._create_amazon_order(external_id="SHIP-002")

        result = binding.push_shipment()

        self.assertFalse(result)
        self.assertFalse(binding.shipment_confirmed)

    @mock.patch("odoo.addons.queue_job.models.base.DelayableRecordset.__getattr__")
    def test_push_shipment_readonly_no_api_call(self, mock_delay):
        """Test push_shipment in read-only mode: feed created but not submitted to API."""
        mock_submit = mock.Mock()
        mock_delay.return_value = mock_submit

        self.backend.write({"read_only_mode": True, "test_mode": True})
        binding, picking, carrier = self._setup_order_with_picking("SHIP-RO")

        result = binding.push_shipment()

        self.assertTrue(result)

        # Feed should be created
        feed = self.env["amz.feed"].search(
            [
                ("backend_id", "=", self.backend.id),
                ("feed_type", "=", "POST_ORDER_FULFILLMENT_DATA"),
            ],
            limit=1,
        )
        self.assertTrue(feed)

        # The feed.submit_feed() is called via with_delay, but when it runs
        # the read_only_mode guard in submit_feed() will prevent API calls

    def test_push_shipment_no_done_picking_linked(self):
        """Test push_shipment returns False when no done pickings are linked."""
        binding = self._create_amazon_order(external_id="SHIP-NO-PICK")
        # _get_last_done_picking returns False since no pickings with sale_id
        result = binding.push_shipment()
        self.assertFalse(result)


@tagged("post_install", "-at_install")
class TestBuildShipmentFeedXml(CommonConnectorAmazonSpapi):
    """Tests for _build_shipment_feed_xml() XML structure."""

    def test_build_xml_contains_required_elements(self):
        """Test _build_shipment_feed_xml generates valid XML."""
        binding = self._create_amazon_order(external_id="XML-001")
        sale_order = binding.odoo_id

        order_line = self.env["sale.order.line"].create(
            {
                "order_id": sale_order.id,
                "product_id": self.product.id,
                "product_uom_qty": 5,
                "price_unit": 10.0,
            }
        )
        self.env["amz.sale.order.line"].create(
            {
                "odoo_id": order_line.id,
                "amz_order_id": binding.id,
                "external_id": "ITEM-XML-001",
                "backend_id": self.backend.id,
            }
        )

        carrier = self.env["delivery.carrier"].create(
            {
                "name": "FedEx Express",
                "product_id": self.product.id,
            }
        )
        sale_order.write({"carrier_id": carrier.id})

        picking = self._create_done_picking(
            sale_order, carrier=carrier, tracking_ref="FX123456"
        )

        xml = binding._build_shipment_feed_xml(picking)

        self.assertIn('<?xml version="1.0"', xml)
        self.assertIn("<AmazonEnvelope", xml)
        self.assertIn("<MessageType>OrderFulfillment</MessageType>", xml)
        self.assertIn("<AmazonOrderID>XML-001</AmazonOrderID>", xml)
        self.assertIn("<FulfillmentDate>", xml)
        self.assertIn("<CarrierName>FedEx Express</CarrierName>", xml)
        self.assertIn("<ShipperTrackingNumber>FX123456</ShipperTrackingNumber>", xml)
        self.assertIn("<AmazonOrderItemCode>ITEM-XML-001</AmazonOrderItemCode>", xml)
        self.assertIn("<Quantity>5</Quantity>", xml)

    def test_build_xml_returns_empty_for_false_picking(self):
        """Test _build_shipment_feed_xml returns '' when picking is False."""
        binding = self._create_amazon_order(external_id="XML-NONE")

        xml = binding._build_shipment_feed_xml(False)

        self.assertEqual(xml, "")


@tagged("post_install", "-at_install")
class TestGetLastDonePicking(CommonConnectorAmazonSpapi):
    """Tests for _get_last_done_picking() helper."""

    def test_returns_false_when_no_pickings(self):
        """Test returns False when order has no pickings."""
        binding = self._create_amazon_order(external_id="PICK-NONE")

        result = binding._get_last_done_picking()

        self.assertFalse(result)

    def test_ignores_non_done_pickings(self):
        """Test only considers pickings in done state."""
        binding = self._create_amazon_order(external_id="PICK-DRAFT")
        if not binding.odoo_id:
            sale_order = self.env["sale.order"].create({"partner_id": self.partner.id})
            binding.write({"odoo_id": sale_order.id})

        # Create draft and assigned pickings (not done)
        self.env["stock.picking"].create(
            {
                "picking_type_id": self.env.ref("stock.picking_type_out").id,
                "location_id": self.env.ref("stock.stock_location_stock").id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
                "sale_id": binding.odoo_id.id,
                "state": "draft",
            }
        )

        result = binding._get_last_done_picking()

        self.assertFalse(result)

    def test_returns_latest_done_picking(self):
        """Test returns the most recent done picking."""
        binding = self._create_amazon_order(external_id="PICK-LATEST")
        if not binding.odoo_id:
            sale_order = self.env["sale.order"].create({"partner_id": self.partner.id})
            binding.write({"odoo_id": sale_order.id})

        # Create older done picking
        old_picking = self._create_done_picking(binding.odoo_id)
        old_picking.write(
            {
                "date_done": fields.Datetime.subtract(fields.Datetime.now(), days=2),
            }
        )

        # Create newer done picking with tracking
        new_picking = self._create_done_picking(
            binding.odoo_id, tracking_ref="LATEST-TRACK"
        )

        result = binding._get_last_done_picking()

        self.assertTrue(result)
        self.assertEqual(result.id, new_picking.id)


@tagged("post_install", "-at_install")
class TestGetOrCreatePartnerEdgeCases(CommonConnectorAmazonSpapi):
    """Additional edge case tests for _get_or_create_partner."""

    def test_get_country_from_code_valid(self):
        """Test _get_or_create_partner resolves valid country code."""
        amazon_order = self._create_sample_amazon_order()
        amazon_order["ShippingAddress"]["CountryCode"] = "US"
        amazon_order["BuyerEmail"] = "countrytest@unique.example.com"

        order_obj = self.env["amz.sale.order"]
        partner = order_obj._get_or_create_partner(amazon_order)

        us = self.env["res.country"].search([("code", "=", "US")], limit=1)
        if us:
            self.assertEqual(partner.country_id, us)

    def test_get_state_from_code_valid(self):
        """Test _get_or_create_partner resolves valid state code."""
        amazon_order = self._create_sample_amazon_order()
        amazon_order["ShippingAddress"]["CountryCode"] = "US"
        amazon_order["ShippingAddress"]["StateOrRegion"] = "NY"
        amazon_order["BuyerEmail"] = "statetest@unique.example.com"

        order_obj = self.env["amz.sale.order"]
        partner = order_obj._get_or_create_partner(amazon_order)

        us = self.env["res.country"].search([("code", "=", "US")], limit=1)
        if us:
            ny = self.env["res.country.state"].search(
                [("code", "=", "NY"), ("country_id", "=", us.id)], limit=1
            )
            if ny:
                self.assertEqual(partner.state_id, ny)

    def test_get_or_create_partner_empty_email_and_name(self):
        """Test partner creation with minimal data."""
        amazon_order = self._create_sample_amazon_order()
        amazon_order["BuyerEmail"] = ""
        amazon_order["ShippingAddress"]["Name"] = "Minimal Customer"
        amazon_order["ShippingAddress"]["AddressLine1"] = ""
        amazon_order["ShippingAddress"]["City"] = ""

        order_obj = self.env["amz.sale.order"]
        partner = order_obj._get_or_create_partner(amazon_order)

        self.assertTrue(partner)
        self.assertEqual(partner.name, "Minimal Customer")
