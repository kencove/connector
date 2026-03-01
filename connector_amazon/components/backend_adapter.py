from odoo.addons.component.core import Component


class AmazonBaseAdapter(Component):
    _name = "amz.adapter"
    _inherit = "base.backend.adapter"
    _usage = "backend.adapter"
    _backend_model_name = "amz.backend"

    def _call_api(self, method, endpoint, params=None, json_data=None):
        """Call SP-API through the backend with authentication"""
        backend = self.backend_record
        return backend._call_sp_api(
            method, endpoint, params=params, json_data=json_data
        )


class AmazonOrdersAdapter(AmazonBaseAdapter):
    _name = "amz.orders.adapter"
    _usage = "orders.adapter"

    def list_orders(
        self,
        marketplace_id,
        created_after=None,
        updated_after=None,
        order_statuses=None,
        next_token=None,
    ):
        """Fetch orders from Amazon Orders API with pagination support

        Args:
            marketplace_id: Amazon marketplace ID
            created_after: ISO 8601 datetime for CreatedAfter filter
            updated_after: ISO 8601 datetime for LastUpdatedAfter filter
            order_statuses: List of order statuses to filter
            next_token: Pagination token for subsequent requests

        Returns:
            dict: API response with Orders list and NextToken
        """
        params = {"MarketplaceIds": marketplace_id}

        if next_token:
            params["NextToken"] = next_token
        else:
            if created_after:
                params["CreatedAfter"] = created_after
            if updated_after:
                params["LastUpdatedAfter"] = updated_after
            if order_statuses:
                params["OrderStatuses"] = ",".join(order_statuses)

        return self._call_api("GET", "/orders/v0/orders", params=params)

    def get_order_items(self, amz_order_id, next_token=None):
        """Fetch order items for a specific order with pagination

        Args:
            amz_order_id: Amazon order ID
            next_token: Pagination token for subsequent requests

        Returns:
            dict: API response with OrderItems list and NextToken
        """
        params = {"NextToken": next_token} if next_token else None
        endpoint = f"/orders/v0/orders/{amz_order_id}/orderItems"
        return self._call_api("GET", endpoint, params=params)

    def get_order(self, amz_order_id):
        """Fetch single order details

        Args:
            amz_order_id: Amazon order ID

        Returns:
            dict: Order details
        """
        endpoint = f"/orders/v0/orders/{amz_order_id}"
        return self._call_api("GET", endpoint)


class AmazonPricingAdapter(AmazonBaseAdapter):
    _name = "amz.pricing.adapter"
    _usage = "pricing.adapter"

    def get_competitive_pricing(self, marketplace_id, asins=None, skus=None):
        """Get competitive pricing for products

        Args:
            marketplace_id: Amazon marketplace ID
            asins: List of ASINs (max 20)
            skus: List of SKUs (max 20)

        Returns:
            dict: Pricing information
        """
        params = {"MarketplaceId": marketplace_id}

        if asins:
            if len(asins) > 20:
                raise ValueError("Amazon enforces a maximum of 20 ASINs per request")
            params["Asins"] = ",".join(asins)
        elif skus:
            if len(skus) > 20:
                raise ValueError("Amazon enforces a maximum of 20 SKUs per request")
            params["Skus"] = ",".join(skus)

        return self._call_api(
            "GET", "/products/pricing/2022-05-01/competitivePrice", params=params
        )

    def get_competitive_pricing_bulk(
        self,
        marketplace_id,
        asins=None,
        skus=None,
        chunk_size=20,
    ):
        """Fetch competitive pricing in chunks and merge results.

        Amazon enforces a maximum number of identifiers per request
        (commonly 20). This helper partitions the input list into
        chunks of up to ``chunk_size`` and aggregates all responses
        into a single list.

        Args:
            marketplace_id: Amazon marketplace ID
            asins: List of ASINs to query
            skus: List of SKUs to query
            chunk_size: Max IDs per request (defaults to 20)

        Returns:
            list: Aggregated competitive pricing payload across chunks
        """
        ids = list(asins or skus or [])
        if not ids:
            return []

        # Respect API hard limit of 20 when chunking
        chunk_size = min(int(chunk_size or 20), 20)

        aggregated = []
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            # Call underlying single-request method
            if asins is not None:
                resp = self.get_competitive_pricing(
                    marketplace_id=marketplace_id, asins=chunk
                )
            else:
                resp = self.get_competitive_pricing(
                    marketplace_id=marketplace_id, skus=chunk
                )

            # Adapter returns a list of pricing entries when successful
            if isinstance(resp, list):
                aggregated.extend(resp)
            elif isinstance(resp, dict):
                # Some backends may encapsulate results in a payload
                payload = resp.get("payload") or resp.get("results")
                if isinstance(payload, list):
                    aggregated.extend(payload)

        return aggregated

    def get_pricing(self, marketplace_id, item_type, asins=None, skus=None):
        """Get pricing information for products

        Args:
            marketplace_id: Amazon marketplace ID
            item_type: 'Asin' or 'Sku'
            asins: List of ASINs (max 20)
            skus: List of SKUs (max 20)

        Returns:
            dict: Pricing information
        """
        params = {"MarketplaceId": marketplace_id, "ItemType": item_type}

        if asins:
            params["Asins"] = ",".join(asins[:20])
        if skus:
            params["Skus"] = ",".join(skus[:20])

        return self._call_api(
            "GET", "/products/pricing/2022-05-01/price", params=params
        )

    def create_price_feed(self, feed_content):
        """Submit price feed through Feeds API

        Args:
            feed_content: XML feed content as string

        Returns:
            dict: Feed creation response with feedId
        """
        # Price feeds are submitted through the generic feed adapter
        # This is a wrapper for consistency
        feed_adapter = self.component(usage="feed.adapter")
        return feed_adapter.create_feed("POST_PRODUCT_PRICING_DATA", feed_content)


class AmazonInventoryAdapter(AmazonBaseAdapter):
    _name = "amz.inventory.adapter"
    _usage = "inventory.adapter"

    def create_inventory_feed(self, feed_content, marketplace_ids):
        """Submit inventory/stock feed through Feeds API

        Args:
            feed_content: XML feed content as string
            marketplace_ids: List of marketplace IDs

        Returns:
            dict: Feed creation response with feedId
        """
        import requests

        feed_adapter = self.component(usage="feed.adapter")

        # Step 1: Create feed document to get presigned upload URL
        doc_response = feed_adapter.create_feed_document()
        feed_document_id = doc_response.get("feedDocumentId")
        upload_url = doc_response.get("url")

        # Step 2: Upload feed content to the presigned S3 URL
        if upload_url and feed_content:
            requests.put(
                upload_url,
                data=feed_content.encode("utf-8"),
                headers={"Content-Type": "text/xml; charset=UTF-8"},
                timeout=60,
            )

        # Step 3: Create feed submission referencing the uploaded document
        return feed_adapter.create_feed(
            "POST_INVENTORY_AVAILABILITY_DATA", feed_document_id, marketplace_ids
        )


class AmazonFeedAdapter(AmazonBaseAdapter):
    _name = "amz.feed.adapter"
    _usage = "feed.adapter"

    def create_feed_document(self, content_type="text/xml; charset=UTF-8"):
        """Create feed document and get upload URL

        Args:
            content_type: Content type for the feed

        Returns:
            dict: Response with feedDocumentId and uploadUrl
        """
        payload = {"contentType": content_type}
        return self._call_api("POST", "/feeds/2021-06-30/documents", json_data=payload)

    def create_feed(
        self, feed_type, feed_document_id, marketplace_ids, feed_options=None
    ):
        """Create feed submission

        Args:
            feed_type: Amazon feed type (e.g., 'POST_PRODUCT_DATA')
            feed_document_id: Document ID from create_feed_document
            marketplace_ids: List of marketplace IDs
            feed_options: Optional dict of feed-specific options

        Returns:
            dict: Response with feedId
        """
        payload = {
            "feedType": feed_type,
            "marketplaceIds": marketplace_ids,
            "inputFeedDocumentId": feed_document_id,
        }

        if feed_options:
            payload["feedOptions"] = feed_options

        return self._call_api("POST", "/feeds/2021-06-30/feeds", json_data=payload)

    def get_feed(self, feed_id):
        """Get feed processing status

        Args:
            feed_id: Amazon feed ID

        Returns:
            dict: Feed status and details
        """
        endpoint = f"/feeds/2021-06-30/feeds/{feed_id}"
        return self._call_api("GET", endpoint)

    def get_feed_document(self, feed_document_id):
        """Get feed processing result document

        Args:
            feed_document_id: Result document ID from feed status

        Returns:
            dict: Response with downloadUrl for results
        """
        endpoint = f"/feeds/2021-06-30/documents/{feed_document_id}"
        return self._call_api("GET", endpoint)

    def cancel_feed(self, feed_id):
        """Cancel a feed submission

        Args:
            feed_id: Amazon feed ID

        Returns:
            dict: Cancellation response
        """
        endpoint = f"/feeds/2021-06-30/feeds/{feed_id}"
        return self._call_api("DELETE", endpoint)


class AmazonCatalogAdapter(AmazonBaseAdapter):
    _name = "amz.catalog.adapter"
    _usage = "catalog.adapter"

    def search_catalog_items(
        self,
        marketplace_ids=None,
        keywords=None,
        identifiers=None,
        identifier_type=None,
        marketplace_id=None,
    ):
        """Search catalog items

        Args:
            marketplace_ids: List of marketplace IDs
            marketplace_id: Single marketplace ID (alternative to list)
            keywords: Search keywords
            identifiers: List of product identifiers (ASIN, UPC, etc.)
            identifier_type: Type of identifier ('ASIN', 'UPC', 'EAN', etc.)

        Returns:
            dict: Catalog items matching search
        """
        ids_list = marketplace_ids or ([marketplace_id] if marketplace_id else [])
        params = {"marketplaceIds": ",".join(ids_list)}

        if keywords:
            params["keywords"] = keywords
        if identifiers:
            params["identifiers"] = ",".join(identifiers)
        if identifier_type:
            params["identifiersType"] = identifier_type

        return self._call_api("GET", "/catalog/2022-04-01/items", params=params)

    def get_catalog_item(
        self, asin, marketplace_ids=None, included_data=None, marketplace_id=None
    ):
        """Get detailed catalog item information

        Args:
            asin: Product ASIN
            marketplace_ids: List of marketplace IDs
            marketplace_id: Single marketplace ID (alternative to list)
            included_data: List of data types to include
                ('attributes', 'identifiers', 'images', 'productTypes', etc.)

        Returns:
            dict: Detailed catalog item data
        """
        ids_list = marketplace_ids or ([marketplace_id] if marketplace_id else [])
        params = {"marketplaceIds": ",".join(ids_list)}

        if included_data:
            params["includedData"] = ",".join(included_data)

        endpoint = f"/catalog/2022-04-01/items/{asin}"
        return self._call_api("GET", endpoint, params=params)


class AmazonReportsAdapter(AmazonBaseAdapter):
    """Adapter for Amazon Reports API.

    The Reports API allows requesting bulk data exports for inventory,
    orders, returns, and more. This is essential for initial sync of
    binding tables.

    Ref: https://developer-docs.amazon.com/sp-api/docs/reports-api-v2021-06-30-reference
    """

    _name = "amz.reports.adapter"
    _usage = "reports.adapter"

    # Common report types for seller data
    REPORT_TYPES = {
        "listings_all": "GET_MERCHANT_LISTINGS_ALL_DATA",
        "listings_active": "GET_MERCHANT_LISTINGS_DATA",
        "listings_open": "GET_FLAT_FILE_OPEN_LISTINGS_DATA",
        "fba_inventory": "GET_AFN_INVENTORY_DATA",
        "fba_inventory_all": "GET_FBA_MYI_ALL_INVENTORY_DATA",
        "orders_all": "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE",
        "returns": "GET_FLAT_FILE_RETURNS_DATA_BY_RETURN_DATE",
    }

    def create_report(
        self,
        report_type,
        marketplace_ids,
        data_start_time=None,
        data_end_time=None,
        report_options=None,
    ):
        """Request generation of a report.

        Args:
            report_type: Amazon report type (e.g., GET_MERCHANT_LISTINGS_ALL_DATA)
            marketplace_ids: List of marketplace IDs
            data_start_time: Optional ISO 8601 start time for date-ranged reports
            data_end_time: Optional ISO 8601 end time for date-ranged reports
            report_options: Optional dict of report-specific options

        Returns:
            dict: Response with reportId
        """
        payload = {
            "reportType": report_type,
            "marketplaceIds": marketplace_ids,
        }

        if data_start_time:
            payload["dataStartTime"] = data_start_time
        if data_end_time:
            payload["dataEndTime"] = data_end_time
        if report_options:
            payload["reportOptions"] = report_options

        return self._call_api("POST", "/reports/2021-06-30/reports", json_data=payload)

    def get_report(self, report_id):
        """Get report status and details.

        Args:
            report_id: Amazon report ID

        Returns:
            dict: Report details including processingStatus and reportDocumentId
        """
        endpoint = f"/reports/2021-06-30/reports/{report_id}"
        return self._call_api("GET", endpoint)

    def get_report_document(self, report_document_id):
        """Get report document download URL.

        Args:
            report_document_id: Document ID from completed report

        Returns:
            dict: Response with url for download (may be compressed)
        """
        endpoint = f"/reports/2021-06-30/documents/{report_document_id}"
        return self._call_api("GET", endpoint)

    def cancel_report(self, report_id):
        """Cancel a report request.

        Args:
            report_id: Amazon report ID

        Returns:
            dict: Cancellation response
        """
        endpoint = f"/reports/2021-06-30/reports/{report_id}"
        return self._call_api("DELETE", endpoint)

    def get_reports(
        self,
        report_types=None,
        processing_statuses=None,
        marketplace_ids=None,
        page_size=10,
        next_token=None,
    ):
        """List reports with optional filters.

        Args:
            report_types: List of report types to filter
            processing_statuses: List of statuses (IN_QUEUE, IN_PROGRESS, DONE, etc.)
            marketplace_ids: List of marketplace IDs
            page_size: Number of results per page (max 100)
            next_token: Pagination token

        Returns:
            dict: List of reports with pagination
        """
        params = {"pageSize": min(page_size, 100)}

        if report_types:
            params["reportTypes"] = ",".join(report_types)
        if processing_statuses:
            params["processingStatuses"] = ",".join(processing_statuses)
        if marketplace_ids:
            params["marketplaceIds"] = ",".join(marketplace_ids)
        if next_token:
            params["nextToken"] = next_token

        return self._call_api("GET", "/reports/2021-06-30/reports", params=params)


class AmazonNotificationsAdapter(AmazonBaseAdapter):
    """Adapter for Amazon SP-API Notifications API.

    Manages notification subscriptions and destinations for real-time
    event updates via Amazon SNS.

    Ref: https://developer-docs.amazon.com/sp-api/docs/notifications-api-v1-reference
    """

    _name = "amz.notifications.adapter"
    _usage = "notifications.adapter"

    # Available notification types
    NOTIFICATION_TYPES = {
        "order_change": "ORDER_CHANGE",
        "listings_change": "LISTINGS_ITEM_STATUS_CHANGE",
        "mfn_quantity": "LISTINGS_ITEM_MFN_QUANTITY_CHANGE",
        "fba_inventory": "FBA_INVENTORY_AVAILABILITY_CHANGES",
        "feed_finished": "FEED_PROCESSING_FINISHED",
        "report_finished": "REPORT_PROCESSING_FINISHED",
        "pricing_health": "PRICING_HEALTH",
        "product_type": "PRODUCT_TYPE_DEFINITIONS_CHANGE",
    }

    def get_subscription(self, notification_type):
        """Get subscription for a notification type.

        Args:
            notification_type: Amazon notification type (e.g., ORDER_CHANGE)

        Returns:
            dict: Subscription details or empty if not subscribed
        """
        endpoint = f"/notifications/v1/subscriptions/{notification_type}"
        return self._call_api("GET", endpoint)

    def create_subscription(
        self, notification_type, destination_id, payload_version=None
    ):
        """Create a subscription to a notification type.

        Args:
            notification_type: Amazon notification type
            destination_id: Destination ID from create_destination
            payload_version: Optional payload version (e.g., "1.0")

        Returns:
            dict: Subscription details with subscriptionId
        """
        endpoint = "/notifications/v1/subscriptions"
        payload = {
            "notificationType": notification_type,
            "destinationId": destination_id,
        }

        if payload_version:
            payload["payloadVersion"] = payload_version

        return self._call_api("POST", endpoint, json_data=payload)

    def delete_subscription(self, notification_type, subscription_id):
        """Delete a subscription.

        Args:
            notification_type: Amazon notification type
            subscription_id: Subscription ID to delete

        Returns:
            dict: Empty response on success
        """
        endpoint = (
            f"/notifications/v1/subscriptions/{notification_type}/{subscription_id}"
        )
        return self._call_api("DELETE", endpoint)

    def get_destinations(self):
        """Get all notification destinations.

        Returns:
            dict: List of destinations
        """
        return self._call_api("GET", "/notifications/v1/destinations")

    def get_destination(self, destination_id):
        """Get a specific destination.

        Args:
            destination_id: Destination ID

        Returns:
            dict: Destination details
        """
        endpoint = f"/notifications/v1/destinations/{destination_id}"
        return self._call_api("GET", endpoint)

    def create_destination(self, name, arn, resource_type="SQS"):
        """Create a notification destination.

        For HTTP/HTTPS webhooks, use EventBridge instead of SQS.
        Amazon SP-API doesn't support direct HTTP endpoints; you need
        either SQS or EventBridge as intermediary.

        Args:
            name: Destination name
            arn: ARN of SQS queue or EventBridge event bus
            resource_type: "SQS" or "EVENT_BRIDGE"

        Returns:
            dict: Destination with destinationId
        """
        endpoint = "/notifications/v1/destinations"

        if resource_type == "SQS":
            payload = {
                "name": name,
                "resourceSpecification": {"sqs": {"arn": arn}},
            }
        elif resource_type == "EVENT_BRIDGE":
            payload = {
                "name": name,
                "resourceSpecification": {
                    "eventBridge": {
                        "accountId": arn.split(":")[4],  # Extract account ID from ARN
                        "region": arn.split(":")[3],  # Extract region from ARN
                    }
                },
            }
        else:
            raise ValueError(f"Unsupported resource type: {resource_type}")

        return self._call_api("POST", endpoint, json_data=payload)

    def delete_destination(self, destination_id):
        """Delete a notification destination.

        Args:
            destination_id: Destination ID to delete

        Returns:
            dict: Empty response on success
        """
        endpoint = f"/notifications/v1/destinations/{destination_id}"
        return self._call_api("DELETE", endpoint)


class AmazonListingsAdapter(AmazonBaseAdapter):
    _name = "amz.listings.adapter"
    _usage = "listings.adapter"

    def get_listings_item(self, seller_sku, marketplace_ids, included_data=None):
        """Get seller's listing for a SKU

        Args:
            seller_sku: Seller SKU
            marketplace_ids: List of marketplace IDs
            included_data: List of data sections ('summaries', 'attributes', etc.)

        Returns:
            dict: Listing details
        """
        params = {"marketplaceIds": ",".join(marketplace_ids)}

        if included_data:
            params["includedData"] = ",".join(included_data)

        endpoint = (
            "/listings/2021-08-01/items/"
            f"{self.backend_record.seller_id}/{seller_sku}"
        )
        return self._call_api("GET", endpoint, params=params)

    def put_listings_item(self, seller_sku, marketplace_ids, product_type, attributes):
        """Create or fully update a listing

        Args:
            seller_sku: Seller SKU
            marketplace_ids: List of marketplace IDs
            product_type: Amazon product type
            attributes: Dict of listing attributes

        Returns:
            dict: Update response with status
        """
        endpoint = (
            f"/listings/2021-08-01/items/{self.backend_record.seller_id}/{seller_sku}"
        )
        payload = {
            "productType": product_type,
            "requirements": "LISTING",
            "attributes": attributes,
        }
        params = {"marketplaceIds": ",".join(marketplace_ids)}

        return self._call_api("PUT", endpoint, params=params, json_data=payload)

    def patch_listings_item(self, seller_sku, marketplace_ids, patches):
        """Partially update a listing

        Args:
            seller_sku: Seller SKU
            marketplace_ids: List of marketplace IDs
            patches: List of JSON Patch operations

        Returns:
            dict: Update response with status
        """
        endpoint = (
            f"/listings/2021-08-01/items/{self.backend_record.seller_id}/{seller_sku}"
        )
        payload = {"productType": "PRODUCT", "patches": patches}
        params = {"marketplaceIds": ",".join(marketplace_ids)}

        return self._call_api("PATCH", endpoint, params=params, json_data=payload)

    def delete_listings_item(self, seller_sku, marketplace_ids):
        """Delete a listing

        Args:
            seller_sku: Seller SKU
            marketplace_ids: List of marketplace IDs

        Returns:
            dict: Deletion response
        """
        endpoint = (
            f"/listings/2021-08-01/items/{self.backend_record.seller_id}/{seller_sku}"
        )
        params = {"marketplaceIds": ",".join(marketplace_ids)}

        return self._call_api("DELETE", endpoint, params=params)
