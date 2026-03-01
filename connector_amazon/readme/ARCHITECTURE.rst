Module Structure
----------------

::

    connector_amazon/
    ├── models/                    # Core data models
    │   ├── backend.py            # Amazon backend configuration and auth
    │   ├── marketplace.py         # Marketplace definitions
    │   ├── shop.py               # Shop-level sync configuration
    │   ├── product_binding.py    # Product to ASIN/SKU mapping
    │   ├── competitive_price.py  # Competitive pricing storage
    │   ├── order.py              # Order binding and line items
    │   ├── feed.py               # Feed tracking for stock/price push
    │   ├── notification_log.py   # SNS notification logging
    │   └── res_partner.py        # Partner extensions
    ├── components/                # Connector components
    │   ├── binder.py             # Key binding management
    │   ├── backend_adapter.py    # API request adapters
    │   └── mapper.py             # Data transformation mappers
    ├── controllers/
    │   └── webhook.py            # SNS webhook endpoint
    ├── security/
    │   └── ir.model.access.csv   # Access control
    ├── views/                     # UI forms and lists
    ├── data/
    │   └── ir_cron.xml           # Scheduled jobs
    ├── tests/                     # Comprehensive test suite
    │   ├── common.py             # Shared test fixtures
    │   ├── test_backend.py       # Backend auth and config tests
    │   ├── test_shop.py          # Shop sync tests
    │   ├── test_shop_sync.py     # Bulk catalog and cron tests
    │   ├── test_order.py         # Order import tests
    │   └── ...                   # Additional test modules
    └── README.rst                # Module overview
