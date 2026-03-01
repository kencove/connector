# Copyright 2025 Kencove
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from unittest.mock import patch

from .common import CommonConnectorAmazonSpapi


class TestEECoexistence(CommonConnectorAmazonSpapi):
    """Tests for coexistence with the Odoo Enterprise sale_amazon module."""

    def test_sale_amazon_installed_false_by_default(self):
        """sale_amazon_installed is False when the EE module is not installed."""
        self.assertFalse(self.backend.sale_amazon_installed)

    def test_sale_amazon_installed_true_when_present(self):
        """sale_amazon_installed is True when ir.module.module shows installed."""
        IrModule = self.env["ir.module.module"].sudo()
        # Create a fake module record to simulate sale_amazon being installed
        IrModule.create(
            {
                "name": "sale_amazon",
                "state": "installed",
            }
        )
        # Recompute
        self.backend.invalidate_recordset(["sale_amazon_installed"])
        self.assertTrue(self.backend.sale_amazon_installed)

    def test_disable_ee_order_sync_toggles_cron(self):
        """Setting disable_ee_order_sync triggers _toggle_ee_order_cron."""
        with patch.object(type(self.backend), "_toggle_ee_order_cron") as mock_toggle:
            self.backend.write({"disable_ee_order_sync": True})
            mock_toggle.assert_called_once_with(disable=True)

    def test_toggle_ee_order_cron_no_model(self):
        """_toggle_ee_order_cron is a no-op when amazon.account model absent."""
        # Should not raise when amazon.account doesn't exist
        self.backend._toggle_ee_order_cron(disable=True)

    def test_order_skip_ee_duplicate(self):
        """Orders already imported by sale_amazon are skipped."""
        # Simulate sale_amazon_installed = True
        IrModule = self.env["ir.module.module"].sudo()
        IrModule.create({"name": "sale_amazon", "state": "installed"})
        self.backend.invalidate_recordset(["sale_amazon_installed"])

        amazon_order_data = self._create_sample_amazon_order()

        # Only run this test if sale.order has amazon_order_ref field
        # (i.e., sale_amazon is actually installed in the test DB)
        if "amazon_order_ref" not in self.env["sale.order"]._fields:
            # Can't fully test without the EE field — just verify the
            # code path doesn't raise when the field is missing
            binding = (
                self.env["amz.sale.order"]
                .with_context(amz_skip_line_sync=True)
                ._create_or_update_from_amazon(self.shop, amazon_order_data)
            )
            self.assertTrue(binding)
            return

        # If amazon_order_ref exists, create a pre-existing EE order
        ee_order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "amazon_order_ref": amazon_order_data["AmazonOrderId"],
            }
        )
        self.assertTrue(ee_order)

        # Now import should skip this order
        binding = (
            self.env["amz.sale.order"]
            .with_context(
                amz_skip_line_sync=True,
            )
            ._create_or_update_from_amazon(self.shop, amazon_order_data)
        )
        self.assertFalse(binding)
