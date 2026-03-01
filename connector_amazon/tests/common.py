# Copyright 2025 Kencove
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from datetime import datetime, timedelta

from odoo.addons.component.tests.common import TransactionComponentCase


class CommonConnectorAmazonSpapi(TransactionComponentCase):
    """Base class for Amazon connector tests"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))

    def setUp(self):
        super().setUp()
        self.backend = self._create_backend()
        self.marketplace = self._create_marketplace()
        self.shop = self._create_shop()
        # Create a simple product used by most sample Amazon items
        self.product = self.env["product.product"].create(
            {
                "name": "Test Product",
                "default_code": "TEST-SKU-001",
                "type": "product",
                "list_price": 99.99,
            }
        )
        # Create partner for order tests
        self.partner = self.env["res.partner"].create(
            {
                "name": "Test Customer",
                "email": "test@example.com",
            }
        )

    def _create_backend(self, **kwargs):
        """Create a test backend record"""
        values = {
            "name": "Test Amazon Backend",
            "code": "test_amazon",
            "version": "spapi",
            "seller_id": "AKIAIOSFODNN7EXAMPLE",
            "region": "na",
            "lwa_client_id": "amzn1.application-oa2-client.test",
            "lwa_client_secret": "test-client-secret",
            "lwa_refresh_token": "Atzr|test-refresh-token",
            "company_id": self.env.company.id,
        }
        values.update(kwargs)
        return self.env["amz.backend"].create(values)

    def _create_marketplace(self, **kwargs):
        """Create a test marketplace record"""
        # Get the default currency
        default_currency = self.env.company.currency_id

        values = {
            "name": "Amazon.com",
            "code": "US",
            "marketplace_id": "ATVPDKIKX0DER",
            "backend_id": self.backend.id,
            "currency_id": default_currency.id,
            "timezone": "America/New_York",
            "country_code": "US",
        }
        values.update(kwargs)
        return self.env["amz.marketplace"].create(values)

    def _create_shop(self, **kwargs):
        """Create a test shop record"""
        values = {
            "name": "Test Amazon Shop",
            "backend_id": self.backend.id,
            "marketplace_id": self.marketplace.id,
            "company_id": self.env.company.id,
            "import_orders": True,
            "sync_stock": True,
            "sync_price": True,
        }
        values.update(kwargs)
        return self.env["amz.shop"].create(values)

    def _create_sample_amazon_order(self):
        """Create a sample Amazon order data structure"""
        return {
            "AmazonOrderId": "111-1111111-1111111",
            "PurchaseDate": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "LastUpdateDate": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "OrderStatus": "Pending",
            "FulfillmentChannel": "MFN",
            "BuyerEmail": "test@example.com",
            "BuyerName": "Test Buyer",
            "BuyerPhoneNumber": "+1-555-0100",
            "ShipServiceLevel": "Standard",
            "IsBusinessOrder": False,
            "NumberOfItemsShipped": 1,
            "NumberOfItemsUnshipped": 0,
            "PaymentExecutionDetail": {"PaymentMethod": "Other"},
            "PaymentMethod": "Other",
            "OrderType": "StandardOrder",
            "EarliestShipDate": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "LatestShipDate": (datetime.now() + timedelta(days=5)).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "IsISPU": False,
            "MarketplaceId": "ATVPDKIKX0DER",
            "ShippingAddress": {
                "AddressType": "Residential",
                "City": "Los Angeles",
                "County": "Los Angeles County",
                "District": "California",
                "Name": "Test Buyer",
                "Phone": "+1-555-0100",
                "PostalCode": "90210",
                "StateOrRegion": "CA",
                "Street1": "123 Test St",
                "CountryCode": "US",
            },
        }

    def _create_sample_amazon_order_item(self):
        """Create a sample Amazon order item data structure"""
        return {
            "OrderItemId": "TEST-ORDER-ITEM-001",
            "SellerSKU": "TEST-SKU-001",
            "ASIN": "TEST-ASIN-001",
            "Title": "Test Product",
            "QuantityOrdered": 1,
            "QuantityShipped": 0,
            "ItemPrice": {"Amount": "99.99", "CurrencyCode": "USD"},
            "ShippingPrice": {"Amount": "0.00", "CurrencyCode": "USD"},
            "ItemTax": {"Amount": "0.00", "CurrencyCode": "USD"},
            "ShippingTax": {"Amount": "0.00", "CurrencyCode": "USD"},
            "PromotionDiscount": {"Amount": "0.00", "CurrencyCode": "USD"},
            "SerialNumberRequired": False,
            "IsGift": False,
            "ConditionNote": "",
            "ConditionId": "New",
            "ConditionSubtypeId": "New",
            "DeemedReservePrice": {"Amount": "0.00", "CurrencyCode": "USD"},
            "IsFulfillable": True,
        }

    def _create_amazon_order(self, **kwargs):
        """Create an amz.sale.order with required partner and sale.order"""
        # Create partner if not provided
        if "partner_id" not in kwargs:
            partner = self.env["res.partner"].create(
                {"name": "Test Buyer", "email": "test@example.com"}
            )
        else:
            partner = self.env["res.partner"].browse(kwargs.pop("partner_id"))

        # Create sale.order if odoo_id not provided
        if "odoo_id" not in kwargs:
            order_name = kwargs.get("name", "TEST-SALE-ORDER")
            sale_order = self.env["sale.order"].create(
                {
                    "partner_id": partner.id,
                    "name": order_name,
                }
            )
            kwargs["odoo_id"] = sale_order.id

        # Set default values if not provided
        defaults = {
            "shop_id": self.shop.id,
            "backend_id": self.backend.id,
            "external_id": "TEST-AMAZON-ORDER-001",
            "purchase_date": datetime.now(),
            "status": "Pending",
        }
        defaults.update(kwargs)

        return self.env["amz.sale.order"].create(defaults)

    def _create_product_binding(self, **kwargs):
        """Create an amz.product.binding"""
        defaults = {
            "backend_id": self.backend.id,
            "marketplace_id": self.marketplace.id,
            "odoo_id": self.product.id,
            "seller_sku": "TEST-SKU-001",
            "asin": "B08TEST123",
            "sync_stock": False,
            "sync_price": False,
        }
        defaults.update(kwargs)
        return self.env["amz.product.binding"].create(defaults)

    def _create_test_carrier(self, **kwargs):
        """Create a test delivery carrier, handling environment-specific fields"""
        carrier_model = self.env["delivery.carrier"]

        # First try to find an existing carrier to reuse
        existing = carrier_model.search([], limit=1)
        if existing:
            return existing

        # Check if stamps_service_type field exists in the model
        has_stamps_field = "stamps_service_type" in carrier_model._fields

        vals = {
            "name": "Test Carrier",
            "product_id": self.product.id,
        }
        vals.update(kwargs)

        if has_stamps_field:
            vals["stamps_service_type"] = "US-FC"
            return carrier_model.create(vals)

        # If stamps field not in model but DB might have constraint,
        # use SQL to handle the insert with default value
        try:
            return carrier_model.create(vals)
        except Exception:
            # Database has stamps_service_type NOT NULL but model doesn't have field
            # Use raw SQL to insert with a default value
            self.env.cr.execute(
                """
                INSERT INTO delivery_carrier
                (name, product_id, delivery_type,
                stamps_service_type,
                create_uid, write_uid, create_date, write_date)
                VALUES (%s, %s, 'fixed', 'US-FC', %s, %s, NOW(), NOW())
                RETURNING id
            """,
                ("Test Carrier", self.product.id, self.env.uid, self.env.uid),
            )
            carrier_id = self.env.cr.fetchone()[0]
            return carrier_model.browse(carrier_id)

    def _set_qty_in_stock_location(self, product, quantity):
        """Set available stock quantity for a product in the default stock location."""
        location = self.env.ref("stock.stock_location_stock")
        quants = self.env["stock.quant"]._gather(product, location, strict=True)
        quantity -= sum(quants.mapped("quantity"))
        self.env["stock.quant"]._update_available_quantity(product, location, quantity)

    def _create_done_picking(self, sale_order, carrier=None, tracking_ref=None):
        """Create a done stock.picking linked to a sale order.

        Args:
            sale_order: sale.order record
            carrier: Optional delivery.carrier record
            tracking_ref: Optional tracking reference string

        Returns:
            stock.picking record in 'done' state
        """
        warehouse = self.shop.warehouse_id or self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        picking_type = (
            warehouse.out_type_id
            if warehouse
            else self.env.ref("stock.picking_type_out")
        )
        vals = {
            "picking_type_id": picking_type.id,
            "location_id": picking_type.default_location_src_id.id
            or self.env.ref("stock.stock_location_stock").id,
            "location_dest_id": picking_type.default_location_dest_id.id
            or self.env.ref("stock.stock_location_customers").id,
            "origin": sale_order.name,
            "state": "done",
        }
        if carrier:
            vals["carrier_id"] = carrier.id
        if tracking_ref:
            vals["carrier_tracking_ref"] = tracking_ref
        return self.env["stock.picking"].create(vals)

    def _create_sample_listings_tsv(self, rows=None):
        """Create sample TSV content matching GET_MERCHANT_LISTINGS_ALL_DATA report.

        Args:
            rows: Optional list of dicts to override default row data.
                  Each dict can have: seller-sku, asin1, item-name, price,
                  quantity, fulfillment-channel, status.

        Returns:
            str: TSV content with header and data rows
        """
        headers = [
            "seller-sku",
            "asin1",
            "item-name",
            "price",
            "quantity",
            "fulfillment-channel",
            "status",
        ]
        default_rows = [
            {
                "seller-sku": "TEST-SKU-001",
                "asin1": "B08TEST123",
                "item-name": "Test Product",
                "price": "99.99",
                "quantity": "10",
                "fulfillment-channel": "DEFAULT",
                "status": "Active",
            },
        ]

        data_rows = rows or default_rows
        lines = ["\t".join(headers)]
        for row in data_rows:
            line = "\t".join(row.get(h, "") for h in headers)
            lines.append(line)

        return "\n".join(lines)

    def _create_sample_pricing_data(self, asin=None):
        """Create sample competitive pricing data from Amazon API"""
        return {
            "ASIN": asin or "B08TEST123",
            "status": "Success",
            "Product": {
                "CompetitivePricing": {
                    "CompetitivePrices": [
                        {
                            "CompetitivePriceId": "1",
                            "Price": {
                                "LandedPrice": {"CurrencyCode": "USD", "Amount": 99.99},
                                "ListingPrice": {
                                    "CurrencyCode": "USD",
                                    "Amount": 89.99,
                                },
                                "Shipping": {"CurrencyCode": "USD", "Amount": 10.00},
                            },
                            "condition": "New",
                            "subcondition": "New",
                            "belongsToRequester": True,
                        }
                    ],
                    "NumberOfOfferListings": [
                        {"condition": "New", "Count": 5},
                    ],
                },
            },
        }
