from odoo.addons.component.core import Component

try:
    # Prefer the official python-amazon-sp-api library when available
    from sp_api.api import CatalogItems, Feeds, ListingsItems, Orders, ProductPricing
except Exception:  # ImportError or any env issue
    Orders = ProductPricing = Feeds = CatalogItems = ListingsItems = None


class AmazonBaseAdapter(Component):
    _name = "amazon.adapter"
    _inherit = "base.backend.adapter"
    _usage = "backend.adapter"
    _backend_model_name = "amazon.backend"

    def _call_api(self, method, endpoint, params=None, json_data=None):
        """Call SP-API through the backend with authentication (fallback path)."""
        backend = self.backend_record
        return backend._call_sp_api(
            method, endpoint, params=params, json_data=json_data
        )

    def _creds(self):
        """Helper to retrieve sp_api credentials from backend."""
        return self.backend_record._get_sp_api_credentials()


class AmazonOrdersAdapter(AmazonBaseAdapter):
    _name = "amazon.orders.adapter"
    _usage = "orders.adapter"

    def list_orders(
        self,
        marketplace_id,
        created_after=None,
        updated_after=None,
        order_statuses=None,
        next_token=None,
    ):
        """Fetch orders from Amazon Orders API with pagination support.

        Tries `sp_api.api.Orders` when available; falls back to raw HTTP.
        """
        if Orders:
            client = Orders(credentials=self._creds())
            if next_token:
                resp = client.get_orders_by_next_token(NextToken=next_token)
            else:
                resp = client.get_orders(
                    MarketplaceIds=[marketplace_id],
                    CreatedAfter=created_after,
                    LastUpdatedAfter=updated_after,
                    OrderStatuses=order_statuses,
                )
            return resp.payload if hasattr(resp, "payload") else resp

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

    def get_order_items(self, amazon_order_id, next_token=None):
        """Fetch order items for a specific order with pagination."""
        if Orders:
            client = Orders(credentials=self._creds())
            if next_token:
                resp = client.get_order_items(amazon_order_id, NextToken=next_token)
            else:
                resp = client.get_order_items(amazon_order_id)
            return resp.payload if hasattr(resp, "payload") else resp

        params = {"NextToken": next_token} if next_token else None
        endpoint = f"/orders/v0/orders/{amazon_order_id}/orderitems"
        return self._call_api("GET", endpoint, params=params)

    def get_order(self, amazon_order_id):
        """Fetch single order details."""
        if Orders:
            client = Orders(credentials=self._creds())
            resp = client.get_order(amazon_order_id)
            return resp.payload if hasattr(resp, "payload") else resp

        endpoint = f"/orders/v0/orders/{amazon_order_id}"
        return self._call_api("GET", endpoint)


class AmazonPricingAdapter(AmazonBaseAdapter):
    _name = "amazon.pricing.adapter"
    _usage = "pricing.adapter"

    def get_competitive_pricing(self, marketplace_id, asins=None, skus=None):
        """Get competitive pricing for products.

        Tries `sp_api.api.ProductPricing` when available; falls back to raw HTTP.
        """
        if ProductPricing:
            client = ProductPricing(credentials=self._creds())
            if asins:
                if len(asins) > 20:
                    raise ValueError(
                        "Amazon enforces a maximum of 20 ASINs per request"
                    )
                resp = client.get_competitive_pricing(
                    MarketplaceId=marketplace_id, Asins=asins
                )
            elif skus:
                if len(skus) > 20:
                    raise ValueError("Amazon enforces a maximum of 20 SKUs per request")
                resp = client.get_competitive_pricing(
                    MarketplaceId=marketplace_id, Skus=skus
                )
            else:
                return []
            return resp.payload if hasattr(resp, "payload") else resp

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
            "GET", "/products/pricing/v0/competitivePrice", params=params
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
        """Get pricing information for products."""
        if ProductPricing:
            client = ProductPricing(credentials=self._creds())
            kwargs = {"MarketplaceId": marketplace_id, "ItemType": item_type}
            if asins:
                kwargs["Asins"] = asins[:20]
            if skus:
                kwargs["Skus"] = skus[:20]
            resp = client.get_pricing(**kwargs)
            return resp.payload if hasattr(resp, "payload") else resp

        params = {"MarketplaceId": marketplace_id, "ItemType": item_type}
        if asins:
            params["Asins"] = ",".join(asins[:20])
        if skus:
            params["Skus"] = ",".join(skus[:20])
        return self._call_api("GET", "/products/pricing/v0/price", params=params)

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
    _name = "amazon.inventory.adapter"
    _usage = "inventory.adapter"

    def create_inventory_feed(self, feed_content, marketplace_ids):
        """Submit inventory/stock feed through Feeds API.

        If `sp_api` is available, use its Feeds client; otherwise fallback.
        """
        if Feeds:
            client = Feeds(credentials=self._creds())
            # 1) Create feed document
            doc = client.create_feed_document(contentType="text/xml; charset=UTF-8")
            doc_payload = getattr(doc, "payload", doc)
            feed_document_id = doc_payload.get("feedDocumentId")

            # 2) Upload content to the provided S3 URL
            upload_url = doc_payload.get("url") or doc_payload.get("uploadUrl")
            if upload_url:
                import requests

                # Amazon requires gzip for many feeds; existing code sends XML.
                # Keep as text upload for now; callers may pre-compress if needed.
                requests.put(
                    upload_url,
                    data=feed_content.encode("utf-8"),
                    headers={"Content-Type": "text/xml; charset=UTF-8"},
                    timeout=60,
                )

            # 3) Create feed submission
            created = client.create_feed(
                feedType="POST_INVENTORY_AVAILABILITY_DATA",
                marketplaceIds=marketplace_ids,
                inputFeedDocumentId=feed_document_id,
            )
            return created.payload if hasattr(created, "payload") else created

        # Fallback path via generic feed adapter (raw HTTP)
        feed_adapter = self.component(usage="feed.adapter")
        doc_response = feed_adapter.create_feed_document()
        feed_document_id = doc_response.get("feedDocumentId")
        return feed_adapter.create_feed(
            "POST_INVENTORY_AVAILABILITY_DATA", feed_document_id, marketplace_ids
        )


class AmazonFeedAdapter(AmazonBaseAdapter):
    _name = "amazon.feed.adapter"
    _usage = "feed.adapter"

    def create_feed_document(self, content_type="text/xml; charset=UTF-8"):
        """Create feed document and get upload URL."""
        if Feeds:
            client = Feeds(credentials=self._creds())
            resp = client.create_feed_document(contentType=content_type)
            return resp.payload if hasattr(resp, "payload") else resp
        payload = {"contentType": content_type}
        return self._call_api("POST", "/feeds/2021-06-30/documents", json_data=payload)

    def create_feed(
        self, feed_type, feed_document_id, marketplace_ids, feed_options=None
    ):
        """Create feed submission."""
        if Feeds:
            client = Feeds(credentials=self._creds())
            kwargs = {
                "feedType": feed_type,
                "marketplaceIds": marketplace_ids,
                "inputFeedDocumentId": feed_document_id,
            }
            if feed_options:
                kwargs["feedOptions"] = feed_options
            resp = client.create_feed(**kwargs)
            return resp.payload if hasattr(resp, "payload") else resp

        payload = {
            "feedType": feed_type,
            "marketplaceIds": marketplace_ids,
            "inputFeedDocumentId": feed_document_id,
        }
        if feed_options:
            payload["feedOptions"] = feed_options
        return self._call_api("POST", "/feeds/2021-06-30/feeds", json_data=payload)

    def get_feed(self, feed_id):
        """Get feed processing status."""
        if Feeds:
            client = Feeds(credentials=self._creds())
            resp = client.get_feed(feed_id)
            return resp.payload if hasattr(resp, "payload") else resp
        endpoint = f"/feeds/2021-06-30/feeds/{feed_id}"
        return self._call_api("GET", endpoint)

    def get_feed_document(self, feed_document_id):
        """Get feed processing result document."""
        if Feeds:
            client = Feeds(credentials=self._creds())
            resp = client.get_feed_document(feed_document_id)
            return resp.payload if hasattr(resp, "payload") else resp
        endpoint = f"/feeds/2021-06-30/documents/{feed_document_id}"
        return self._call_api("GET", endpoint)

    def cancel_feed(self, feed_id):
        """Cancel a feed submission."""
        if Feeds:
            client = Feeds(credentials=self._creds())
            resp = client.cancel_feed(feed_id)
            return resp.payload if hasattr(resp, "payload") else resp
        endpoint = f"/feeds/2021-06-30/feeds/{feed_id}"
        return self._call_api("DELETE", endpoint)


class AmazonCatalogAdapter(AmazonBaseAdapter):
    _name = "amazon.catalog.adapter"
    _usage = "catalog.adapter"

    def search_catalog_items(
        self,
        marketplace_ids=None,
        keywords=None,
        identifiers=None,
        identifier_type=None,
        marketplace_id=None,
    ):
        """Search catalog items."""
        ids_list = marketplace_ids or ([marketplace_id] if marketplace_id else [])
        if CatalogItems:
            client = CatalogItems(credentials=self._creds())
            resp = client.search_catalog_items(
                marketplaceIds=ids_list,
                keywords=keywords,
                identifiers=identifiers,
                identifiersType=identifier_type,
            )
            return resp.payload if hasattr(resp, "payload") else resp

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
        """Get detailed catalog item information."""
        ids_list = marketplace_ids or ([marketplace_id] if marketplace_id else [])
        if CatalogItems:
            client = CatalogItems(credentials=self._creds())
            resp = client.get_catalog_item(
                asin,
                marketplaceIds=ids_list,
                includedData=included_data,
            )
            return resp.payload if hasattr(resp, "payload") else resp

        params = {"marketplaceIds": ",".join(ids_list)}
        if included_data:
            params["includedData"] = ",".join(included_data)
        endpoint = f"/catalog/2022-04-01/items/{asin}"
        return self._call_api("GET", endpoint, params=params)


class AmazonListingsAdapter(AmazonBaseAdapter):
    _name = "amazon.listings.adapter"
    _usage = "listings.adapter"

    def get_listings_item(self, seller_sku, marketplace_ids, included_data=None):
        """Get seller's listing for a SKU."""
        if ListingsItems:
            client = ListingsItems(credentials=self._creds())
            resp = client.get_listings_item(
                self.backend_record.seller_id,
                seller_sku,
                marketplaceIds=marketplace_ids,
                includedData=included_data,
            )
            return resp.payload if hasattr(resp, "payload") else resp

        params = {"marketplaceIds": ",".join(marketplace_ids)}
        if included_data:
            params["includedData"] = ",".join(included_data)
        endpoint = (
            f"/listings/2021-08-01/items/{self.backend_record.seller_id}/{seller_sku}"
        )
        return self._call_api("GET", endpoint, params=params)

    def put_listings_item(self, seller_sku, marketplace_ids, product_type, attributes):
        """Create or fully update a listing."""
        if ListingsItems:
            client = ListingsItems(credentials=self._creds())
            resp = client.put_listings_item(
                self.backend_record.seller_id,
                seller_sku,
                marketplaceIds=marketplace_ids,
                productType=product_type,
                attributes=attributes,
                requirements="LISTING",
            )
            return resp.payload if hasattr(resp, "payload") else resp

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
