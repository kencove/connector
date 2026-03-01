# Copyright 2025 Kencove
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)
"""Tests for amz.marketplace: batch creation, currency resolution, carrier mapping."""

from odoo.tests import tagged

from .common import CommonConnectorAmazonSpapi


@tagged("post_install", "-at_install")
class TestMarketplaceCreate(CommonConnectorAmazonSpapi):
    """Tests for marketplace create() and batch creation."""

    def test_create_sets_default_code_from_country_code(self):
        """Test create() auto-sets code from country_code when code is missing."""
        mp = self.env["amz.marketplace"].create(
            {
                "name": "Amazon.de",
                "marketplace_id": "A1PA6795UKMFR9",
                "backend_id": self.backend.id,
                "currency_id": self.env.company.currency_id.id,
                "country_code": "DE",
            }
        )

        self.assertEqual(mp.code, "DE")

    def test_create_sets_code_from_name_fallback(self):
        """Test create() derives code from name when no country_code."""
        mp = self.env["amz.marketplace"].create(
            {
                "name": "Amazon Mexico",
                "marketplace_id": "A1AM78C64UM0Y8",
                "backend_id": self.backend.id,
                "currency_id": self.env.company.currency_id.id,
            }
        )

        # Should use first 2 chars of name uppercase
        self.assertEqual(mp.code, "AM")

    def test_batch_creation(self):
        """Test multiple marketplaces can be created in a single batch."""
        vals_list = [
            {
                "name": "Amazon.ca",
                "marketplace_id": "A2EUQ1WTGCTBG2",
                "backend_id": self.backend.id,
                "currency_id": self.env.company.currency_id.id,
                "country_code": "CA",
            },
            {
                "name": "Amazon.com.mx",
                "marketplace_id": "A1AM78C64UM0Y8",
                "backend_id": self.backend.id,
                "currency_id": self.env.company.currency_id.id,
                "country_code": "MX",
            },
        ]

        marketplaces = self.env["amz.marketplace"].create(vals_list)

        self.assertEqual(len(marketplaces), 2)
        self.assertEqual(marketplaces[0].code, "CA")
        self.assertEqual(marketplaces[1].code, "MX")


@tagged("post_install", "-at_install")
class TestResolveCurrency(CommonConnectorAmazonSpapi):
    """Tests for _resolve_currency() heuristics."""

    def test_resolve_currency_backend_company(self):
        """Test currency resolves from backend company first."""
        currency = self.env["amz.marketplace"]._resolve_currency(
            {"code": "XX"},
            self.env["res.currency"],
            self.backend,
        )

        self.assertEqual(currency, self.backend.company_id.currency_id)

    def test_resolve_currency_uk_marketplace(self):
        """Test UK marketplace resolves to GBP."""
        gbp = self.env["res.currency"].search([("name", "=", "GBP")], limit=1)
        if not gbp:
            self.skipTest("GBP currency not available")

        # Pass backend=None to bypass backend company currency check
        currency = self.env["amz.marketplace"]._resolve_currency(
            {"code": "UK", "name": "Amazon.co.uk"},
            self.env["res.currency"],
            None,
        )

        self.assertEqual(currency, gbp)

    def test_resolve_currency_jp_marketplace(self):
        """Test Japanese marketplace resolves to JPY."""
        jpy = self.env["res.currency"].search([("name", "=", "JPY")], limit=1)
        if not jpy:
            self.skipTest("JPY currency not available")

        # Pass backend=None to bypass backend company currency check
        currency = self.env["amz.marketplace"]._resolve_currency(
            {"code": "JP", "name": "Amazon.co.jp"},
            self.env["res.currency"],
            None,
        )

        self.assertEqual(currency, jpy)

    def test_resolve_currency_company_fallback(self):
        """Test resolves to company currency when no heuristic matches."""
        currency = self.env["amz.marketplace"]._resolve_currency(
            {"code": "ZZ", "name": "Unknown"},
            self.env["res.currency"],
            None,  # no backend
        )

        self.assertEqual(currency, self.env.company.currency_id)

    def test_create_auto_resolves_currency(self):
        """Test create() auto-resolves currency when not provided."""
        mp = self.env["amz.marketplace"].create(
            {
                "name": "Amazon.com",
                "marketplace_id": "ATVPDKIKX0DER_AUTO",
                "backend_id": self.backend.id,
                "country_code": "US",
                "code": "US",
            }
        )

        self.assertTrue(mp.currency_id)


@tagged("post_install", "-at_install")
class TestDeliveryCarrierMapping(CommonConnectorAmazonSpapi):
    """Tests for get_delivery_carrier_for_amazon_shipping()."""

    def _setup_carriers(self):
        """Create carriers for all shipping levels."""
        self.carrier_standard = self.env["delivery.carrier"].create(
            {
                "name": "Standard",
                "product_id": self.product.id,
            }
        )
        self.carrier_expedited = self.env["delivery.carrier"].create(
            {
                "name": "Expedited",
                "product_id": self.product.id,
            }
        )
        self.carrier_priority = self.env["delivery.carrier"].create(
            {
                "name": "Priority",
                "product_id": self.product.id,
            }
        )
        self.carrier_scheduled = self.env["delivery.carrier"].create(
            {
                "name": "Scheduled",
                "product_id": self.product.id,
            }
        )
        self.carrier_default = self.env["delivery.carrier"].create(
            {
                "name": "Default",
                "product_id": self.product.id,
            }
        )
        self.marketplace.write(
            {
                "delivery_standard_id": self.carrier_standard.id,
                "delivery_expedited_id": self.carrier_expedited.id,
                "delivery_priority_id": self.carrier_priority.id,
                "delivery_scheduled_id": self.carrier_scheduled.id,
                "delivery_default_id": self.carrier_default.id,
            }
        )

    def test_standard_shipping(self):
        """Test Standard maps to delivery_standard_id."""
        self._setup_carriers()
        carrier = self.marketplace.get_delivery_carrier_for_amazon_shipping("Standard")
        self.assertEqual(carrier, self.carrier_standard)

    def test_expedited_shipping(self):
        """Test Expedited maps to delivery_expedited_id."""
        self._setup_carriers()
        carrier = self.marketplace.get_delivery_carrier_for_amazon_shipping("Expedited")
        self.assertEqual(carrier, self.carrier_expedited)

    def test_priority_shipping(self):
        """Test Priority maps to delivery_priority_id."""
        self._setup_carriers()
        carrier = self.marketplace.get_delivery_carrier_for_amazon_shipping("Priority")
        self.assertEqual(carrier, self.carrier_priority)

    def test_nextday_maps_to_priority(self):
        """Test NextDay maps to delivery_priority_id."""
        self._setup_carriers()
        carrier = self.marketplace.get_delivery_carrier_for_amazon_shipping("NextDay")
        self.assertEqual(carrier, self.carrier_priority)

    def test_secondday_maps_to_expedited(self):
        """Test SecondDay maps to delivery_expedited_id."""
        self._setup_carriers()
        carrier = self.marketplace.get_delivery_carrier_for_amazon_shipping("SecondDay")
        self.assertEqual(carrier, self.carrier_expedited)

    def test_scheduled_shipping(self):
        """Test Scheduled maps to delivery_scheduled_id."""
        self._setup_carriers()
        carrier = self.marketplace.get_delivery_carrier_for_amazon_shipping("Scheduled")
        self.assertEqual(carrier, self.carrier_scheduled)

    def test_unknown_falls_back_to_default(self):
        """Test unknown shipping level falls back to delivery_default_id."""
        self._setup_carriers()
        carrier = self.marketplace.get_delivery_carrier_for_amazon_shipping("SameDay")
        self.assertEqual(carrier, self.carrier_default)

    def test_missing_specific_carrier_falls_back(self):
        """Test falls back to default when specific mapping is empty."""
        self.marketplace.write(
            {
                "delivery_standard_id": False,
                "delivery_default_id": self.env["delivery.carrier"]
                .create(
                    {
                        "name": "Fallback",
                        "product_id": self.product.id,
                    }
                )
                .id,
            }
        )

        carrier = self.marketplace.get_delivery_carrier_for_amazon_shipping("Standard")
        self.assertEqual(carrier.name, "Fallback")

    def test_no_carriers_configured(self):
        """Test returns empty recordset when no carriers configured."""
        self.marketplace.write(
            {
                "delivery_standard_id": False,
                "delivery_expedited_id": False,
                "delivery_priority_id": False,
                "delivery_scheduled_id": False,
                "delivery_default_id": False,
            }
        )

        carrier = self.marketplace.get_delivery_carrier_for_amazon_shipping("Standard")
        self.assertFalse(carrier)
