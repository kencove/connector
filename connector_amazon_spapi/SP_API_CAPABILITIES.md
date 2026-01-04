# Amazon SP-API Capabilities Matrix

This document outlines what SP-API operations are available, implemented, and tested in this connector module.

## Implementation Status Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Implemented and tested |
| 🔧 | Implemented, needs testing |
| 📋 | Adapter exists, not wired to UI |
| ❌ | Not implemented |
| 🔲 | Available in SP-API, not in module |

---

## Current Implementation Status

### Sellers API
| Endpoint | Status | Notes |
|----------|--------|-------|
| `GET /sellers/v1/marketplaceParticipations` | ✅ | Used by `action_fetch_marketplaces()` |

### Orders API (`/orders/v0/`)
| Endpoint | Status | Notes |
|----------|--------|-------|
| `GET /orders` | ✅ | `sync_orders()` with pagination |
| `GET /orders/{orderId}` | 🔧 | Adapter exists |
| `GET /orders/{orderId}/orderItems` | ✅ | Line item sync |
| `GET /orders/{orderId}/buyerInfo` | 🔲 | PII - requires approval |
| `GET /orders/{orderId}/address` | 🔲 | PII - requires approval |
| `POST /orders/{orderId}/shipmentConfirmation` | 🔧 | `push_shipment()` |

### Product Pricing API (`/products/pricing/v0/`)
| Endpoint | Status | Notes |
|----------|--------|-------|
| `GET /competitivePrice` | ✅ | `sync_competitive_prices()` |
| `GET /price` | 📋 | Adapter exists, not used |
| `GET /listings/{sku}/offers` | 🔲 | Buy Box details |
| `GET /items/{asin}/offers` | 🔲 | Buy Box details |
| Batch endpoints | 🔲 | Higher throughput |

### Catalog Items API (`/catalog/2022-04-01/`)
| Endpoint | Status | Notes |
|----------|--------|-------|
| `GET /items` (search) | 📋 | Adapter exists |
| `GET /items/{asin}` | 📋 | Adapter exists |

### Listings Items API (`/listings/2021-08-01/`)
| Endpoint | Status | Notes |
|----------|--------|-------|
| `GET /items/{sellerId}/{sku}` | 🔧 | `sync_catalog()` - single SKU only |
| `PUT /items/{sellerId}/{sku}` | 📋 | Adapter exists |
| `PATCH /items/{sellerId}/{sku}` | 📋 | Adapter exists |
| `DELETE /items/{sellerId}/{sku}` | 📋 | Adapter exists |

### Feeds API (`/feeds/2021-06-30/`)
| Endpoint | Status | Notes |
|----------|--------|-------|
| `POST /documents` | 🔧 | Feed document creation |
| `POST /feeds` | 🔧 | Feed submission |
| `GET /feeds/{feedId}` | 🔧 | Status check |
| `GET /documents/{docId}` | 📋 | Adapter exists |
| `DELETE /feeds/{feedId}` | 📋 | Adapter exists |

### Feed Types Supported
| Feed Type | Status | Notes |
|-----------|--------|-------|
| `POST_INVENTORY_AVAILABILITY_DATA` | 🔧 | Stock push |
| `POST_PRODUCT_PRICING_DATA` | 📋 | Price push |
| `POST_ORDER_FULFILLMENT_DATA` | 🔧 | Shipment tracking |
| `POST_PRODUCT_DATA` | ❌ | Product creation |
| `POST_ORDER_ACKNOWLEDGEMENT_DATA` | ❌ | Order acknowledgement |

---

## Reports API (`/reports/2021-06-30/`) - INITIAL SYNC

### Implementation Status: ✅ IMPLEMENTED

| Endpoint | Status | Notes |
|----------|--------|-------|
| `POST /reports` | ✅ | Request report generation |
| `GET /reports/{reportId}` | ✅ | Check report status |
| `GET /documents/{documentId}` | ✅ | Get download URL |
| `DELETE /reports/{reportId}` | ✅ | Cancel report |
| `GET /reports` | ✅ | List reports with filters |

### Supported Report Types
| Report Type | Purpose | Status |
|-------------|---------|--------|
| `GET_MERCHANT_LISTINGS_ALL_DATA` | **All active listings with SKU/ASIN** | ✅ Used by bulk sync |
| `GET_MERCHANT_LISTINGS_DATA` | Active listings summary | 📋 Adapter ready |
| `GET_FLAT_FILE_OPEN_LISTINGS_DATA` | Open listings | 📋 Adapter ready |
| `GET_AFN_INVENTORY_DATA` | FBA inventory levels | 📋 Adapter ready |
| `GET_FBA_MYI_ALL_INVENTORY_DATA` | Complete FBA inventory | 📋 Adapter ready |
| `GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE` | Historical orders | 📋 Adapter ready |
| `GET_FLAT_FILE_RETURNS_DATA_BY_RETURN_DATE` | Returns data | 📋 Adapter ready |

### Bulk Catalog Sync Flow
```
Shop → action_sync_catalog_bulk() → sync_catalog_bulk()
  1. POST /reports (GET_MERCHANT_LISTINGS_ALL_DATA)
  2. Poll GET /reports/{id} until DONE
  3. GET /documents/{id} → download URL
  4. Download TSV, decompress if GZIP
  5. Parse TSV → create/update amazon.product.binding
```

---

## NOT IMPLEMENTED - Future Enhancements

### FBA Inventory API (`/fba/inventory/v1/`)
| Endpoint | Purpose |
|----------|---------|
| `GET /summaries` | FBA inventory summaries |

---

## Notifications API - Implementation Scope

### Overview
The Amazon SP-API Notifications API enables real-time event-driven updates via Amazon SNS (Simple Notification Service). This eliminates polling and provides instant awareness of order changes, inventory updates, and listing modifications.

### Architecture Requirements

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│   Amazon SP-API     │────▶│    Amazon SNS       │────▶│   Odoo Webhook      │
│   Notifications     │     │    Topic            │     │   Endpoint          │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘
                                                                  │
                                                                  ▼
                                                        ┌─────────────────────┐
                                                        │  Queue Job /        │
                                                        │  Process Event      │
                                                        └─────────────────────┘
```

### Components Needed

#### 1. Webhook Controller (`controllers/webhook.py`)
```python
class AmazonNotificationController(http.Controller):

    @http.route(
        '/amazon/webhook/<string:token>',
        type='json',
        auth='public',
        methods=['POST'],
        csrf=False,
    )
    def receive_notification(self, token, **kwargs):
        """
        Receive SNS notifications from Amazon.

        Security:
        - Token in URL validates the request
        - SNS message signature verification
        - IP whitelist (optional)
        """
        # 1. Validate token against backend.webhook_token
        # 2. Handle SNS subscription confirmation
        # 3. Verify SNS message signature
        # 4. Parse notification type and dispatch
        # 5. Queue background job for processing
```

#### 2. Backend Fields (`models/backend.py`)
```python
# Webhook configuration
webhook_token = fields.Char(
    string="Webhook Security Token",
    default=lambda self: secrets.token_urlsafe(32),
    help="Secret token for webhook URL authentication",
)
webhook_url = fields.Char(
    string="Webhook URL",
    compute="_compute_webhook_url",
    help="URL to configure in Amazon SP-API notifications",
)
sns_subscription_arn = fields.Char(
    string="SNS Subscription ARN",
    readonly=True,
)

# Notification subscriptions
notify_order_change = fields.Boolean(
    string="Order Change Notifications",
    help="Receive real-time order status updates",
)
notify_listings_change = fields.Boolean(
    string="Listings Change Notifications",
    help="Receive updates when listings are modified",
)
notify_inventory_change = fields.Boolean(
    string="Inventory Change Notifications",
    help="Receive FBA inventory level changes",
)
```

#### 3. Notifications Adapter (`components/backend_adapter.py`)
```python
class AmazonNotificationsAdapter(AmazonBaseAdapter):
    _name = "amazon.notifications.adapter"
    _usage = "notifications.adapter"

    def get_subscription(self, notification_type):
        """GET /notifications/v1/subscriptions/{notificationType}"""

    def create_subscription(self, notification_type, destination_id):
        """POST /notifications/v1/subscriptions"""

    def delete_subscription(self, subscription_id):
        """DELETE /notifications/v1/subscriptions/{subscriptionId}"""

    def get_destinations(self):
        """GET /notifications/v1/destinations"""

    def create_destination(self, name, sqs_arn):
        """POST /notifications/v1/destinations"""

    def delete_destination(self, destination_id):
        """DELETE /notifications/v1/destinations/{destinationId}"""
```

#### 4. SNS Message Handler
```python
def _handle_sns_message(self, message):
    """Process incoming SNS message"""
    message_type = message.get('Type')

    if message_type == 'SubscriptionConfirmation':
        # Auto-confirm subscription by visiting SubscribeURL
        requests.get(message['SubscribeURL'])
        return

    if message_type == 'Notification':
        payload = json.loads(message['Message'])
        notification_type = payload.get('notificationType')

        handlers = {
            'ORDER_CHANGE': self._handle_order_change,
            'LISTINGS_ITEM_STATUS_CHANGE': self._handle_listing_change,
            'FBA_INVENTORY_AVAILABILITY_CHANGES': self._handle_inventory_change,
        }

        handler = handlers.get(notification_type)
        if handler:
            handler(payload)
```

### Available Notification Types

| Type | Description | Use Case |
|------|-------------|----------|
| `ORDER_CHANGE` | Order created, updated, or cancelled | Real-time order sync |
| `LISTINGS_ITEM_STATUS_CHANGE` | Listing status changes | Sync new listings |
| `LISTINGS_ITEM_MFN_QUANTITY_CHANGE` | MFN quantity changes | Stock reconciliation |
| `FBA_INVENTORY_AVAILABILITY_CHANGES` | FBA inventory changes | FBA stock sync |
| `FEED_PROCESSING_FINISHED` | Feed completed | Feed status tracking |
| `REPORT_PROCESSING_FINISHED` | Report ready | Auto-download reports |

### Security Considerations

1. **Webhook Token**: Random token in URL prevents unauthorized access
2. **SNS Signature Verification**: Verify `x-amz-sns-signature` header
3. **IP Whitelisting**: Optional - restrict to Amazon IP ranges
4. **HTTPS Only**: Webhook must be served over TLS
5. **Rate Limiting**: Implement request throttling
6. **Idempotency**: Handle duplicate notifications gracefully

### Implementation Steps

1. **Phase 1: Webhook Infrastructure**
   - Add webhook controller with token auth
   - Add SNS signature verification
   - Add backend configuration fields
   - Test with SNS subscription confirmation

2. **Phase 2: Notifications Adapter**
   - Implement Notifications API adapter
   - Add destination creation (SQS or EventBridge)
   - Add subscription management

3. **Phase 3: Event Handlers**
   - ORDER_CHANGE → trigger order sync
   - LISTINGS_ITEM_STATUS_CHANGE → create bindings
   - Implement queue job for each handler

4. **Phase 4: UI & Management**
   - Backend form for subscription management
   - Notification log/history view
   - Health monitoring dashboard

### AWS Requirements

- **SQS Queue** or **EventBridge**: Amazon requires a destination
- **IAM Policy**: SP-API needs permission to publish to your destination
- **Public Endpoint**: Odoo must be accessible from internet (for HTTP destination)

### Alternative: SQS Polling (Simpler)

If webhook is complex, use SQS polling instead:
```
Amazon SP-API → SQS Queue → Odoo Cron polls SQS → Process
```

This avoids webhook complexity but adds ~1-5 min latency.

---

## Initial Sync Strategy for Binding Tables

### ✅ IMPLEMENTED: Bulk Catalog Sync via Reports API

Use the **"Bulk Catalog Sync (Reports)"** button on the Shop form to:
1. Request `GET_MERCHANT_LISTINGS_ALL_DATA` report
2. Automatically poll until complete (up to 10 min)
3. Download and parse the TSV report
4. Create/update `amazon.product.binding` records

**Report contains:**
- seller-sku → `amazon.product.binding.seller_sku`
- asin1 → `amazon.product.binding.asin`
- item-name (logged for reference)
- price, quantity, fulfillment-channel (available for future use)

**Matching Logic:**
- If binding exists (by SKU+backend): Update ASIN if changed
- If no binding but Odoo product exists (by `default_code`): Create binding
- If no Odoo product: Log warning, skip (manual product creation needed)

### Ongoing Sync for New Listings
After initial bulk sync, new listings can be captured by:
1. **Scheduled re-sync**: Run bulk sync weekly/monthly
2. **Manual trigger**: Click "Bulk Catalog Sync" when new products added
3. **Future**: Notifications API subscription (not yet implemented)

---

## Test Coverage Status

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_backend.py` | 17 | Auth, tokens, connection |
| `test_shop.py` | 14 | Order sync, stock push |
| `test_order.py` | 16 | Order import, lines |
| `test_adapters.py` | ~17 | API adapters (incl. Reports API) |
| `test_mapper.py` | ~8 | Data transformation |
| `test_feed.py` | ~12 | Feed lifecycle |
| `test_competitive_price.py` | ~10 | Price fetch |

### Sandbox Testing Status
| Feature | Mock Tests | Sandbox Ready |
|---------|------------|---------------|
| Connection Test | ✅ | ✅ (with `test_mode`) |
| Fetch Marketplaces | ✅ | ✅ |
| Order Sync | ✅ | ✅ |
| Order Line Sync | ✅ | ✅ |
| Competitive Pricing | ✅ | ✅ |
| Stock Push (Feed) | ✅ | 🔧 (needs live test) |
| Shipment Push | 🔧 | 🔧 |
| Catalog Sync | 🔧 | 🔧 (single SKU only) |

---

## Recommendations for Future Development

### ✅ COMPLETED: Reports API for Initial Sync
- `AmazonReportsAdapter` implemented in `components/backend_adapter.py`
- `sync_catalog_bulk()` implemented in `models/shop.py`
- UI button "Bulk Catalog Sync (Reports)" added to Shop form

### Priority 1: Scheduled Bulk Sync Cron
Add a cron job option to periodically refresh bindings:
```python
def cron_sync_catalog_bulk(self):
    """Weekly/monthly full catalog refresh via Reports API"""
```

### Priority 2: Real-time Notifications
Subscribe to SP-API notifications for:
- `ORDER_CHANGE` - New/updated orders
- `PRICING_HEALTH` - Price alerts
- `ITEM_INVENTORY_EVENT_CHANGE` - Stock changes

---

## SP-API Rate Limits Reference

| API | Rate | Burst |
|-----|------|-------|
| Orders getOrders | 0.0167/s | 20 |
| Orders getOrderItems | 0.5/s | 30 |
| Pricing getCompetitivePrice | 0.5/s | 1 |
| Feeds createFeed | 0.0083/s | 15 |
| Reports createReport | 0.0167/s | 15 |
| Catalog searchItems | 2/s | 2 |
