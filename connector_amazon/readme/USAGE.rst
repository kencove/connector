Configure an Amazon backend, marketplaces, and at least one shop, then:

1. Authorize SP-API credentials (LWA + IAM role).
2. Run order import/catalog sync jobs (or enable scheduled crons).
3. Use read-only mode for validation in sandbox/live dry runs.
4. Enable the webhook endpoint for near real-time SNS updates.

See CONFIGURATION and ARCHITECTURE docs for detailed setup steps.
