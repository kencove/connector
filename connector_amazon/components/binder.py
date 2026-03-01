from odoo.addons.component.core import Component


class AmazonBinder(Component):
    _name = "amz.binder"
    _inherit = "base.binder"
    _usage = "binder"
    _backend_model_name = "amz.backend"

    # TODO: extend with helper methods for multi-marketplace keys if needed
