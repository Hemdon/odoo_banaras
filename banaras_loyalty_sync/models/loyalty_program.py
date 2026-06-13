from odoo import fields, models


class LoyaltyProgram(models.Model):
    _inherit = "loyalty.program"

    x_banaras_branch_loyalty = fields.Boolean(
        string="Banaras Branch Loyalty",
        help=(
            "Tick for each branch's points program. Programs flagged here are kept "
            "in sync with each other (a customer's balance is mirrored across all of "
            "them) and new customers are auto-enrolled into every flagged program. "
            "Add a new branch later by simply ticking this box on its loyalty program."
        ),
        default=False,
        copy=False,
    )
