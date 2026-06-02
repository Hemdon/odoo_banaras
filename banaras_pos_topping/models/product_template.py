from odoo import models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        if "description_sale" not in fields_list:
            fields_list = list(fields_list) + ["description_sale"]
        return fields_list
