# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is an Odoo 16 connector module for Amazon Seller Central SP-API integration. It handles order import, stock synchronization, competitive pricing, and shipment tracking using the OCA (Odoo Community Association) connector framework patterns.

## Development Commands

### Running Tests

```bash
# Full test suite (47+ tests)
invoke test --cur-file odoo/custom/src/connector/connector_amazon_spapi/__manifest__.py

# Specific test file
invoke test --cur-file odoo/custom/src/connector/connector_amazon_spapi/tests/test_backend.py

# With debugpy for VS Code debugging
invoke test --cur-file odoo/custom/src/connector/connector_amazon_spapi/__manifest__.py --debugpy
```

### Doodba Environment

```bash
cd /Users/dkendall/projects/odoo/ecom-odoo
invoke start   # Start Docker containers
invoke stop    # Stop containers
```

## Architecture

### OCA Connector Pattern

The module follows the OCA connector framework with three main component types:

1. **Adapters** (`components/backend_adapter.py`) - Encapsulate SP-API HTTP communication
   - `AmazonOrdersAdapter` - Orders API endpoints
   - `AmazonPricingAdapter` - Pricing API endpoints

2. **Mappers** (`components/mapper.py`) - Transform Amazon API responses to Odoo models
   - `AmazonOrderImportMapper` - Maps orders to `sale.order`
   - `AmazonOrderLineImportMapper` - Maps order items to `sale.order.line`
   - `AmazonProductPriceImportMapper` - Maps pricing data

3. **Binder** (`components/binder.py`) - Maps external IDs (Amazon order IDs) to Odoo record IDs

### Data Binding Pattern

Models use `external.binding` to link Odoo records with Amazon entities:

```
amazon.backend (1 per integration)
└── amazon.marketplace (fetched from SP-API)
    └── amazon.shop (marketplace + backend combination, sync operations)

amazon.sale.order (external.binding → sale.order)
amazon.product.binding (external.binding → product.product)
amazon.competitive.price (pricing history)
amazon.feed (bulk operations via Feeds API)
```

### Key Models

| Model | File | Purpose |
|-------|------|---------|
| `amazon.backend` | models/backend.py | Central auth config, LWA token management |
| `amazon.shop` | models/shop.py | Sync operations (orders, stock, prices) |
| `amazon.sale.order` | models/order.py | Order import, shipment tracking |
| `amazon.product.binding` | models/product_binding.py | Product-Amazon ASIN/SKU mappings |
| `amazon.feed` | models/feed.py | Feeds API for bulk operations |

### Async Operations

All sync operations use `queue_job` for async processing:
- `shop.action_sync_orders()` → queues `sync_orders()`
- `shop.action_push_stock()` → queues `push_stock()`
- Cron jobs in `data/ir_cron.xml` for scheduled syncs

### Read-Only Mode

Backend has a `read_only_mode` flag that logs operations instead of calling Amazon APIs - useful for testing without affecting the Amazon account.

## Testing

All tests mock external API calls (no real Amazon requests). Test fixtures are in `tests/common.py` with `CommonConnectorAmazonSpapi` base class.

Key test files:
- `test_backend.py` - Auth, token refresh, connectivity
- `test_shop.py` - Order sync, catalog sync
- `test_order.py` - Order creation, line item mapping
- `test_adapters.py` - API call handling
- `test_mapper.py` - Data transformation

## Dependencies

- `connector` (OCA connector framework)
- `queue_job` (async job processing)
- `sale_management`, `stock`, `product`, `delivery` (Odoo core)
- `requests` (HTTP client)
