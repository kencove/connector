# Copyright 2025 Kencove
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)
"""Tests for action_manage_subscriptions on amz.backend."""

from unittest import mock

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CommonConnectorAmazonSpapi


@tagged("post_install", "-at_install")
class TestManageSubscriptions(CommonConnectorAmazonSpapi):
    """Tests for action_manage_subscriptions()."""

    def _mock_work_context(self):
        """Return a mock work_on context manager with adapter."""
        mock_adapter = mock.Mock()
        mock_work = mock.Mock()
        mock_work.component.return_value = mock_adapter

        cm = mock.MagicMock()
        cm.__enter__ = mock.Mock(return_value=mock_work)
        cm.__exit__ = mock.Mock(return_value=False)

        return cm, mock_adapter

    def test_readonly_mode_returns_warning(self):
        """Test action_manage_subscriptions returns warning in read-only mode."""
        self.backend.write(
            {
                "read_only_mode": True,
                "webhook_active": True,
            }
        )

        result = self.backend.action_manage_subscriptions()

        self.assertEqual(result["params"]["type"], "warning")
        self.assertIn("read-only", result["params"]["message"].lower())

    def test_webhook_inactive_raises(self):
        """Test action_manage_subscriptions raises if webhook not active."""
        self.backend.write(
            {
                "read_only_mode": False,
                "webhook_active": False,
            }
        )

        with self.assertRaises(UserError) as cm:
            self.backend.action_manage_subscriptions()

        self.assertIn("webhook", str(cm.exception).lower())

    def test_creates_destination_when_missing(self):
        """Test creates SNS destination if sns_destination_id is empty."""
        self.backend.write(
            {
                "read_only_mode": False,
                "webhook_active": True,
                "sns_destination_id": False,
                "notify_order_change": True,
            }
        )

        cm, mock_adapter = self._mock_work_context()
        mock_adapter.create_destination.return_value = {
            "payload": {"destinationId": "DEST-001"}
        }
        mock_adapter.create_subscription.return_value = {
            "payload": {"subscriptionId": "SUB-001"}
        }

        with mock.patch.object(type(self.backend), "work_on", return_value=cm):
            self.backend.action_manage_subscriptions()

        mock_adapter.create_destination.assert_called_once()
        self.assertEqual(self.backend.sns_destination_id, "DEST-001")

    def test_skips_destination_when_exists(self):
        """Test skips destination creation if already set."""
        self.backend.write(
            {
                "read_only_mode": False,
                "webhook_active": True,
                "sns_destination_id": "EXISTING-DEST",
                "notify_order_change": True,
            }
        )

        cm, mock_adapter = self._mock_work_context()
        mock_adapter.create_subscription.return_value = {
            "payload": {"subscriptionId": "SUB-002"}
        }

        with mock.patch.object(type(self.backend), "work_on", return_value=cm):
            self.backend.action_manage_subscriptions()

        mock_adapter.create_destination.assert_not_called()

    def test_creates_subscription_for_enabled_type(self):
        """Test creates subscription when notify flag is True and no sub ID."""
        self.backend.write(
            {
                "read_only_mode": False,
                "webhook_active": True,
                "sns_destination_id": "DEST-001",
                "notify_order_change": True,
                "sns_subscription_order_id": False,
                "notify_listings_change": False,
                "notify_feed_processing": False,
                "notify_report_processing": False,
            }
        )

        cm, mock_adapter = self._mock_work_context()
        mock_adapter.create_subscription.return_value = {
            "payload": {"subscriptionId": "SUB-ORDER-001"}
        }

        with mock.patch.object(type(self.backend), "work_on", return_value=cm):
            result = self.backend.action_manage_subscriptions()

        mock_adapter.create_subscription.assert_called_once_with(
            notification_type="ORDER_CHANGE",
            destination_id="DEST-001",
        )
        self.assertEqual(self.backend.sns_subscription_order_id, "SUB-ORDER-001")
        self.assertEqual(result["params"]["type"], "success")

    def test_deletes_subscription_for_disabled_type(self):
        """Test deletes subscription when notify flag is False and sub ID exists."""
        self.backend.write(
            {
                "read_only_mode": False,
                "webhook_active": True,
                "sns_destination_id": "DEST-001",
                "notify_order_change": False,
                "sns_subscription_order_id": "SUB-TO-DELETE",
                "notify_listings_change": False,
                "sns_subscription_listings_id": False,
                "notify_feed_processing": False,
                "sns_subscription_feed_id": False,
                "notify_report_processing": False,
                "sns_subscription_report_id": False,
            }
        )

        cm, mock_adapter = self._mock_work_context()

        with mock.patch.object(type(self.backend), "work_on", return_value=cm):
            result = self.backend.action_manage_subscriptions()

        mock_adapter.delete_subscription.assert_called_once_with(
            notification_type="ORDER_CHANGE",
            subscription_id="SUB-TO-DELETE",
        )
        self.assertFalse(self.backend.sns_subscription_order_id)
        self.assertEqual(result["params"]["type"], "success")

    def test_multiple_subscriptions_created_and_deleted(self):
        """Test multiple subscriptions created/deleted in single call."""
        self.backend.write(
            {
                "read_only_mode": False,
                "webhook_active": True,
                "sns_destination_id": "DEST-001",
                # Enable order and feed, disable listings (has existing sub)
                "notify_order_change": True,
                "sns_subscription_order_id": False,
                "notify_listings_change": False,
                "sns_subscription_listings_id": "SUB-LIST-OLD",
                "notify_feed_processing": True,
                "sns_subscription_feed_id": False,
                "notify_report_processing": False,
                "sns_subscription_report_id": False,
            }
        )

        cm, mock_adapter = self._mock_work_context()
        mock_adapter.create_subscription.side_effect = [
            {"payload": {"subscriptionId": "SUB-ORDER-NEW"}},
            {"payload": {"subscriptionId": "SUB-FEED-NEW"}},
        ]

        with mock.patch.object(type(self.backend), "work_on", return_value=cm):
            result = self.backend.action_manage_subscriptions()

        # 2 created, 1 deleted
        self.assertEqual(mock_adapter.create_subscription.call_count, 2)
        self.assertEqual(mock_adapter.delete_subscription.call_count, 1)
        self.assertEqual(self.backend.sns_subscription_order_id, "SUB-ORDER-NEW")
        self.assertEqual(self.backend.sns_subscription_feed_id, "SUB-FEED-NEW")
        self.assertFalse(self.backend.sns_subscription_listings_id)
        self.assertEqual(result["params"]["type"], "success")

    def test_destination_creation_failure_raises(self):
        """Test raises UserError when destination creation returns no ID."""
        self.backend.write(
            {
                "read_only_mode": False,
                "webhook_active": True,
                "sns_destination_id": False,
                "notify_order_change": True,
            }
        )

        cm, mock_adapter = self._mock_work_context()
        mock_adapter.create_destination.return_value = {"payload": {}}

        with mock.patch.object(type(self.backend), "work_on", return_value=cm):
            with self.assertRaises(UserError) as err:
                self.backend.action_manage_subscriptions()

        self.assertIn("destination", str(err.exception).lower())
