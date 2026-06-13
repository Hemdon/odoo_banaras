from odoo import api, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _banaras_enroll_branch_loyalty(self):
        """Give each eligible new customer a card in every Banaras branch program.

        Skips companies and internal staff (users / employees). Bulk migration
        passes ``banaras_skip_loyalty_sync`` in the context to opt out.
        """
        if self.env.context.get("banaras_skip_loyalty_sync"):
            return

        programs = self.env["loyalty.program"].sudo().search(
            [
                ("x_banaras_branch_loyalty", "=", True),
                ("program_type", "=", "loyalty"),
            ]
        )
        if not programs:
            return

        candidates = self.filtered(lambda p: not p.is_company and not p.user_ids)
        if not candidates:
            return

        # Exclude anyone who is an employee work contact (POS cashiers / staff).
        employee_partner_ids = set(
            self.env["hr.employee"]
            .sudo()
            .search([("work_contact_id", "in", candidates.ids)])
            .mapped("work_contact_id")
            .ids
        )

        Card = self.env["loyalty.card"].sudo().with_context(
            banaras_skip_loyalty_sync=True,
            loyalty_no_mail=True,
            action_no_send_mail=True,
        )

        for partner in candidates:
            if partner.id in employee_partner_ids:
                continue
            existing = Card.search(
                [
                    ("partner_id", "=", partner.id),
                    ("program_id", "in", programs.ids),
                ]
            )
            have_program_ids = set(existing.mapped("program_id").ids)
            missing = [pid for pid in programs.ids if pid not in have_program_ids]
            for program_id in missing:
                Card.create(
                    {
                        "partner_id": partner.id,
                        "program_id": program_id,
                        "points": 0.0,
                    }
                )

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners._banaras_enroll_branch_loyalty()
        return partners
