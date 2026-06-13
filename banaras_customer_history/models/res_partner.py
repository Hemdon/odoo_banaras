from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    x_goodtill_customer_id = fields.Char("Good Till Customer ID", index=True, copy=False)
    x_goodtill_customer_group = fields.Char("Good Till Customer Group", copy=False)
    x_goodtill_created_at = fields.Datetime("Good Till Created At", copy=False)
    x_goodtill_updated_at = fields.Datetime("Good Till Updated At", copy=False)
    x_goodtill_loyalty_points_snapshot = fields.Float("Good Till Loyalty Points Snapshot", copy=False)

    x_goodtill_history_order_count = fields.Integer("Good Till History Order Count", copy=False)
    x_goodtill_history_total_spend = fields.Monetary(
        "Good Till History Total Spend",
        currency_field="currency_id",
        copy=False,
    )
    x_goodtill_history_total_quantity = fields.Float("Good Till History Total Quantity", copy=False)
    x_goodtill_first_order_date = fields.Date("Good Till First Order Date", copy=False)
    x_goodtill_last_order_date = fields.Date("Good Till Last Order Date", copy=False)
    x_goodtill_history_outlets = fields.Char("Good Till History Outlets", copy=False)
    x_goodtill_last_history_sync_at = fields.Datetime("Good Till Last History Sync At", copy=False)
    x_goodtill_history_source = fields.Char("Good Till History Source", copy=False)
    x_goodtill_history_sale_ids = fields.Text("Good Till History Sale IDs", copy=False)
    x_banaras_loyalty_card_ids = fields.One2many(
        "loyalty.card",
        "partner_id",
        string="Loyalty Cards",
    )
    x_banaras_pos_loyalty_points = fields.Float(
        "POS Loyalty Points",
        compute="_compute_banaras_pos_loyalty_points",
    )
    x_banaras_pos_order_count = fields.Integer(
        "POS Total Orders",
        compute="_compute_banaras_pos_order_history",
    )
    x_banaras_pos_last_order_date = fields.Datetime(
        "POS Last Order Date",
        compute="_compute_banaras_pos_order_history",
    )

    @api.depends("x_banaras_loyalty_card_ids.points", "x_banaras_loyalty_card_ids.active")
    def _compute_banaras_pos_loyalty_points(self):
        balances = {partner_id: 0.0 for partner_id in self.ids}
        cards = self.env["loyalty.card"].sudo().search(
            [
                ("partner_id", "in", self.ids),
                ("program_id", "in", [23, 24]),
                ("active", "=", True),
            ]
        )
        for card in cards:
            partner_id = card.partner_id.id
            balances[partner_id] = max(balances[partner_id], card.points or 0.0)
        for partner in self:
            partner.x_banaras_pos_loyalty_points = balances.get(partner.id, 0.0)

    @api.depends("x_goodtill_history_order_count", "x_goodtill_last_order_date")
    def _compute_banaras_pos_order_history(self):
        odoo_history = {}
        if self.ids:
            self.env.cr.execute(
                """
                    SELECT partner_id, COUNT(*), MAX(date_order)
                      FROM pos_order
                     WHERE partner_id = ANY(%s)
                       AND state NOT IN ('draft', 'cancel')
                     GROUP BY partner_id
                """,
                [self.ids],
            )
            odoo_history = {
                partner_id: (order_count, last_order_date)
                for partner_id, order_count, last_order_date in self.env.cr.fetchall()
            }

        for partner in self:
            odoo_count, odoo_last_order = odoo_history.get(partner.id, (0, False))
            goodtill_last_order = (
                fields.Datetime.to_datetime(partner.x_goodtill_last_order_date)
                if partner.x_goodtill_last_order_date
                else False
            )
            dates = [date for date in (goodtill_last_order, odoo_last_order) if date]
            partner.x_banaras_pos_order_count = (
                partner.x_goodtill_history_order_count + odoo_count
            )
            partner.x_banaras_pos_last_order_date = max(dates) if dates else False

    @api.model
    def _load_pos_data_fields(self, config):
        fields_to_load = super()._load_pos_data_fields(config)
        for field_name in (
            "x_banaras_pos_loyalty_points",
            "x_banaras_pos_order_count",
            "x_banaras_pos_last_order_date",
        ):
            if field_name not in fields_to_load:
                fields_to_load.append(field_name)
        return fields_to_load
