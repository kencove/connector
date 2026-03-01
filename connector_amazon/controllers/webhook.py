import base64
import json
import logging

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Cache for SNS signing certificates
_cert_cache = {}


class AmazonWebhookController(http.Controller):
    """Controller for receiving Amazon SP-API notifications via SNS.

    Amazon sends notifications to this webhook endpoint. The flow is:
    1. Amazon publishes to SNS topic
    2. SNS sends HTTP POST to this webhook
    3. We verify the SNS signature
    4. We process the notification (queue a background job)

    Security:
    - Token in URL authenticates the request to a specific backend
    - SNS message signature verification ensures message integrity
    - Only accepts messages from Amazon's SNS service
    """

    @http.route(
        "/amz/webhook/<string:token>",
        type="json",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def receive_notification(self, token, **kwargs):
        """Receive and process Amazon SNS notification.

        Args:
            token: Security token that identifies the backend

        Returns:
            dict: Response indicating success or failure
        """
        try:
            # Get the raw JSON body
            data = request.jsonrequest

            if not data:
                _logger.warning("Empty request body received")
                return {"status": "error", "message": "Empty request body"}

            # Find backend by webhook token
            backend = self._get_backend_by_token(token)
            if not backend:
                _logger.warning("Invalid webhook token: %s", token[:8] + "...")
                return {"status": "error", "message": "Invalid token"}

            # Verify SNS signature (skip in test mode)
            if not backend.test_mode:
                if not self._verify_sns_signature(data):
                    _logger.warning("SNS signature verification failed")
                    return {"status": "error", "message": "Invalid signature"}

            # Handle different SNS message types
            message_type = data.get("Type")

            if message_type == "SubscriptionConfirmation":
                return self._handle_subscription_confirmation(data, backend)

            elif message_type == "UnsubscribeConfirmation":
                return self._handle_unsubscribe_confirmation(data, backend)

            elif message_type == "Notification":
                return self._handle_notification(data, backend)

            else:
                _logger.warning("Unknown SNS message type: %s", message_type)
                return {"status": "error", "message": f"Unknown type: {message_type}"}

        except Exception as e:
            _logger.exception("Error processing webhook")
            return {"status": "error", "message": str(e)}

    def _get_backend_by_token(self, token):
        """Find backend by webhook token.

        Args:
            token: Webhook security token

        Returns:
            amz.backend record or None
        """
        if not token:
            return None

        return (
            request.env["amz.backend"]
            .sudo()
            .search([("webhook_token", "=", token), ("active", "=", True)], limit=1)
        )

    def _verify_sns_signature(self, message):
        """Verify Amazon SNS message signature.

        Amazon signs all SNS messages with their private key. We verify
        using their public certificate (fetched from SigningCertURL).

        Args:
            message: SNS message dict

        Returns:
            bool: True if signature is valid
        """
        try:
            # Get the signing certificate URL
            cert_url = message.get("SigningCertURL") or message.get("SigningCertUrl")
            if not cert_url:
                _logger.warning("No SigningCertURL in message")
                return False

            # Validate cert URL is from Amazon
            if not self._is_valid_cert_url(cert_url):
                _logger.warning("Invalid SigningCertURL: %s", cert_url)
                return False

            # Get the certificate (cached)
            cert = self._get_certificate(cert_url)
            if not cert:
                return False

            # Build the string to sign based on message type
            string_to_sign = self._build_string_to_sign(message)
            if not string_to_sign:
                return False

            # Decode the signature
            signature = base64.b64decode(message.get("Signature", ""))

            # Verify the signature
            public_key = cert.public_key()
            public_key.verify(
                signature,
                string_to_sign.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA1(),
            )

            return True

        except Exception as e:
            _logger.warning("SNS signature verification error: %s", str(e))
            return False

    def _is_valid_cert_url(self, url):
        """Validate that certificate URL is from Amazon SNS.

        Args:
            url: Certificate URL

        Returns:
            bool: True if URL is valid Amazon SNS cert URL
        """
        import urllib.parse

        parsed = urllib.parse.urlparse(url)

        # Must be HTTPS
        if parsed.scheme != "https":
            return False

        # Must be from Amazon SNS domain
        valid_domains = [
            "sns.us-east-1.amazonaws.com",
            "sns.us-west-2.amazonaws.com",
            "sns.eu-west-1.amazonaws.com",
            "sns.ap-northeast-1.amazonaws.com",
            "sns.ap-southeast-1.amazonaws.com",
            "sns.ap-southeast-2.amazonaws.com",
        ]

        # Allow any sns.*.amazonaws.com domain
        if parsed.hostname and parsed.hostname.endswith(".amazonaws.com"):
            if parsed.hostname.startswith("sns."):
                return True

        return parsed.hostname in valid_domains

    def _get_certificate(self, cert_url):
        """Fetch and cache SNS signing certificate.

        Args:
            cert_url: URL to fetch certificate from

        Returns:
            Certificate object or None
        """
        global _cert_cache

        # Check cache first
        if cert_url in _cert_cache:
            return _cert_cache[cert_url]

        try:
            response = requests.get(cert_url, timeout=10)
            response.raise_for_status()

            cert = x509.load_pem_x509_certificate(response.content)
            _cert_cache[cert_url] = cert

            return cert

        except Exception as e:
            _logger.warning("Failed to fetch SNS certificate: %s", str(e))
            return None

    def _build_string_to_sign(self, message):
        """Build the canonical string to sign for SNS signature verification.

        The string format depends on the message type.

        Args:
            message: SNS message dict

        Returns:
            str: Canonical string to sign
        """
        message_type = message.get("Type")

        if message_type == "Notification":
            fields = [
                "Message",
                "MessageId",
                "Subject",
                "Timestamp",
                "TopicArn",
                "Type",
            ]
        elif message_type in ("SubscriptionConfirmation", "UnsubscribeConfirmation"):
            fields = [
                "Message",
                "MessageId",
                "SubscribeURL",
                "Timestamp",
                "Token",
                "TopicArn",
                "Type",
            ]
        else:
            return None

        # Build string with field name and value pairs
        parts = []
        for field in fields:
            value = message.get(field)
            if value is not None:
                parts.append(f"{field}\n{value}\n")

        return "".join(parts)

    def _handle_subscription_confirmation(self, data, backend):
        """Handle SNS subscription confirmation.

        When you create a subscription, SNS sends a confirmation request.
        We automatically confirm by visiting the SubscribeURL.

        Args:
            data: SNS message dict
            backend: amz.backend record

        Returns:
            dict: Response
        """
        subscribe_url = data.get("SubscribeURL")
        topic_arn = data.get("TopicArn")

        _logger.info(
            "Received SNS subscription confirmation for backend %s, topic %s",
            backend.name,
            topic_arn,
        )

        if subscribe_url:
            try:
                # Confirm the subscription
                response = requests.get(subscribe_url, timeout=30)
                response.raise_for_status()

                _logger.info("Successfully confirmed SNS subscription")

                # Log the notification
                self._create_notification_log(
                    backend,
                    notification_type="SubscriptionConfirmation",
                    topic_arn=topic_arn,
                    message_id=data.get("MessageId"),
                    raw_message=json.dumps(data),
                    status="confirmed",
                )

                return {"status": "ok", "message": "Subscription confirmed"}

            except Exception as e:
                _logger.exception("Failed to confirm SNS subscription")

                self._create_notification_log(
                    backend,
                    notification_type="SubscriptionConfirmation",
                    topic_arn=topic_arn,
                    message_id=data.get("MessageId"),
                    raw_message=json.dumps(data),
                    status="error",
                    error_message=str(e),
                )

                return {"status": "error", "message": str(e)}

        return {"status": "error", "message": "No SubscribeURL provided"}

    def _handle_unsubscribe_confirmation(self, data, backend):
        """Handle SNS unsubscribe confirmation.

        Args:
            data: SNS message dict
            backend: amz.backend record

        Returns:
            dict: Response
        """
        topic_arn = data.get("TopicArn")

        _logger.info(
            "Received SNS unsubscribe confirmation for backend %s, topic %s",
            backend.name,
            topic_arn,
        )

        self._create_notification_log(
            backend,
            notification_type="UnsubscribeConfirmation",
            topic_arn=topic_arn,
            message_id=data.get("MessageId"),
            raw_message=json.dumps(data),
            status="confirmed",
        )

        return {"status": "ok", "message": "Unsubscribe confirmed"}

    def _handle_notification(self, data, backend):
        """Handle actual SP-API notification.

        Parse the notification and dispatch to appropriate handler.

        Args:
            data: SNS message dict
            backend: amz.backend record

        Returns:
            dict: Response
        """
        try:
            # Parse the inner message (SP-API notification payload)
            message_str = data.get("Message", "{}")
            if isinstance(message_str, str):
                payload = json.loads(message_str)
            else:
                payload = message_str

            notification_type = payload.get("notificationType")
            notification_payload = payload.get("payload", {})

            _logger.info(
                "Received SP-API notification: %s for backend %s",
                notification_type,
                backend.name,
            )

            # Create notification log
            log = self._create_notification_log(
                backend,
                notification_type=notification_type,
                topic_arn=data.get("TopicArn"),
                message_id=data.get("MessageId"),
                raw_message=json.dumps(data),
                payload=json.dumps(notification_payload),
                status="received",
            )

            # Queue background job to process the notification
            if log:
                log.with_delay().process_notification()

            return {
                "status": "ok",
                "message": f"Notification {notification_type} queued",
            }

        except json.JSONDecodeError as e:
            _logger.warning("Failed to parse notification message: %s", str(e))
            return {"status": "error", "message": "Invalid JSON in message"}

        except Exception as e:
            _logger.exception("Error handling notification")
            return {"status": "error", "message": str(e)}

    def _create_notification_log(
        self,
        backend,
        notification_type,
        topic_arn=None,
        message_id=None,
        raw_message=None,
        payload=None,
        status="received",
        error_message=None,
    ):
        """Create a notification log record.

        Args:
            backend: amz.backend record
            notification_type: Type of notification
            topic_arn: SNS topic ARN
            message_id: SNS message ID
            raw_message: Full raw message JSON
            payload: Parsed notification payload JSON
            status: Processing status
            error_message: Error message if failed

        Returns:
            amz.notification.log record
        """
        try:
            return (
                request.env["amz.notification.log"]
                .sudo()
                .create(
                    {
                        "backend_id": backend.id,
                        "notification_type": notification_type,
                        "topic_arn": topic_arn,
                        "message_id": message_id,
                        "raw_message": raw_message,
                        "payload": payload,
                        "state": status,
                        "error_message": error_message,
                    }
                )
            )
        except Exception as e:
            _logger.exception("Failed to create notification log: %s", str(e))
            return None
