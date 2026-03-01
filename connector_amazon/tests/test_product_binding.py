# Copyright 2025 Kencove
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)
"""Tests for amz.product.binding model — competitive pricing fetch and compute."""

from unittest import mock

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CommonConnectorAmazonSpapi


@tagged("post_install", "-at_install")
class TestProductBindingCompetitivePricing(CommonConnectorAmazonSpapi):
    """Tests for action_fetch_competitive_prices and related computed fields."""

    def setUp(self):
        super().setUp()
        self.binding = self._create_product_binding(
            seller_sku="PB-SKU-001",
            asin="B08PB001",
        )

    def test_compute_competitive_price_count_empty(self):
        """Test count is 0 with no competitive prices."""
        self.assertEqual(self.binding.competitive_price_count, 0)

    def test_compute_competitive_price_count_with_records(self):
        """Test count reflects active competitive prices."""
        self.env["amz.competitive.price"].create(
            {
                "product_binding_id": self.binding.id,
                "asin": "B08PB001",
                "marketplace_id": self.marketplace.id,
                "listing_price": 89.99,
                "currency_id": self.env.company.currency_id.id,
            }
        )

        self.binding.invalidate_recordset()
        self.assertEqual(self.binding.competitive_price_count, 1)

    def test_fetch_prices_no_asin_raises(self):
        """Test action_fetch_competitive_prices raises when no ASIN."""
        binding = self._create_product_binding(
            seller_sku="NO-ASIN",
            asin=False,
        )

        with self.assertRaises(UserError) as cm:
            binding.action_fetch_competitive_prices()

        self.assertIn("no ASIN", str(cm.exception))

    def test_fetch_prices_no_marketplace_raises(self):
        """Test action_fetch_competitive_prices raises when no marketplace."""
        binding = self._create_product_binding(
            seller_sku="NO-MKT",
            asin="B08NOMKT",
            marketplace_id=False,
        )

        with self.assertRaises(UserError) as cm:
            binding.action_fetch_competitive_prices()

        self.assertIn("No marketplace", str(cm.exception))

    @mock.patch(
        "odoo.addons.connector_amazon.components.backend_adapter."
        "AmazonPricingAdapter.get_competitive_pricing"
    )
    def test_fetch_prices_success(self, mock_get_pricing):
        """Test successful fetch creates competitive price records."""
        mock_get_pricing.return_value = [
            {
                "ASIN": "B08PB001",
                "Product": {
                    "CompetitivePricing": {
                        "CompetitivePrices": [
                            {
                                "CompetitivePriceId": "1",
                                "Price": {
                                    "LandedPrice": {
                                        "CurrencyCode": "USD",
                                        "Amount": "99.99",
                                    },
                                    "ListingPrice": {
                                        "CurrencyCode": "USD",
                                        "Amount": "89.99",
                                    },
                                    "Shipping": {
                                        "CurrencyCode": "USD",
                                        "Amount": "10.00",
                                    },
                                },
                                "condition": "New",
                                "offerType": "BuyBox",
                                "belongsToRequester": True,
                            }
                        ],
                        "NumberOfOfferListings": [
                            {"condition": "New", "Count": 5},
                        ],
                    }
                },
            }
        ]

        result = self.binding.action_fetch_competitive_prices()

        # Should create a competitive price record
        prices = self.env["amz.competitive.price"].search(
            [("product_binding_id", "=", self.binding.id)]
        )
        self.assertEqual(len(prices), 1)
        self.assertEqual(prices.listing_price, 89.99)

        # Should return success notification
        self.assertEqual(result["params"]["type"], "success")

    @mock.patch(
        "odoo.addons.connector_amazon.components.backend_adapter."
        "AmazonPricingAdapter.get_competitive_pricing"
    )
    def test_fetch_prices_empty_response_raises(self, mock_get_pricing):
        """Test raises when API returns empty results."""
        mock_get_pricing.return_value = []

        with self.assertRaises(UserError) as cm:
            self.binding.action_fetch_competitive_prices()

        self.assertIn("No competitive pricing data returned", str(cm.exception))

    @mock.patch(
        "odoo.addons.connector_amazon.components.backend_adapter."
        "AmazonPricingAdapter.get_competitive_pricing"
    )
    def test_fetch_prices_no_competitive_data_raises(self, mock_get_pricing):
        """Test raises when API returns data but mapper produces no results."""
        mock_get_pricing.return_value = [
            {
                "ASIN": "B08PB001",
                "Product": {
                    "CompetitivePricing": {"CompetitivePrices": []},
                },
            }
        ]

        with self.assertRaises(UserError) as cm:
            self.binding.action_fetch_competitive_prices()

        self.assertIn("No competitive pricing data found", str(cm.exception))

    def test_action_view_competitive_prices(self):
        """Test action_view_competitive_prices returns correct action."""
        result = self.binding.action_view_competitive_prices()

        self.assertEqual(result["type"], "ir.actions.act_window")
        self.assertEqual(result["res_model"], "amz.competitive.price")
        self.assertIn(
            ("product_binding_id", "=", self.binding.id),
            result["domain"],
        )

    def test_sql_constraint_unique_sku_per_backend(self):
        """Test SQL constraint prevents duplicate SKU per backend."""
        from psycopg2 import IntegrityError

        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self._create_product_binding(
                    seller_sku="PB-SKU-001",  # same as setUp
                    asin="B08DUPE",
                )
