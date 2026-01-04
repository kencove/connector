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

### Notifications API (`/notifications/v1/`)
| Endpoint | Purpose |
|----------|---------|
| Subscribe to events | Real-time order/inventory updates |

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
