from odoo import api, models


class LoyaltyCard(models.Model):
    _inherit = "loyalty.card"

    @api.model
    def _banaras_branch_program_ids(self):
        """Return ids of all loyalty (points) programs flagged as Banaras branches.

        Replaces the old hardcoded {23: 24} pair so the sync/enrollment scales to
        any number of branches: tick ``x_banaras_branch_loyalty`` on a program and
        it joins the set automatically.
        """
        programs = self.env["loyalty.program"].sudo().search(
            [
                ("x_banaras_branch_loyalty", "=", True),
                ("program_type", "=", "loyalty"),
            ]
        )
        return programs.ids

    def _banaras_sync_and_enroll(self):
        if self.env.context.get("banaras_skip_loyalty_sync"):
            return

        branch_ids = self._banaras_branch_program_ids()
        if len(branch_ids) < 1:
            return

        Card = self.env["loyalty.card"].sudo().with_context(
            banaras_skip_loyalty_sync=True,
            loyalty_no_mail=True,
            action_no_send_mail=True,
        )
        History = self.env["loyalty.history"].sudo()

        # Partners touched by this batch that have a branch card in scope.
        partners = self.filtered(
            lambda card: card.partner_id and card.program_id.id in branch_ids
        ).mapped("partner_id")

        for partner in partners:
            # The card just created/written for this partner is authoritative.
            trigger = self.filtered(
                lambda card: card.partner_id == partner
                and card.program_id.id in branch_ids
            )[:1]
            if not trigger:
                continue
            points = trigger.points

            existing = Card.search(
                [
                    ("partner_id", "=", partner.id),
                    ("program_id", "in", branch_ids),
                    ("program_type", "=", "loyalty"),
                ]
            )
            have_program_ids = existing.mapped("program_id").ids

            # 1) Auto-enroll: create a card in every flagged branch the partner is
            #    missing (covers "both cards on customer create" and future branches).
            for program_id in branch_ids:
                if program_id not in have_program_ids:
                    Card.create(
                        {
                            "partner_id": partner.id,
                            "program_id": program_id,
                            "points": points,
                        }
                    )

            # 2) N-way sync: align every other branch card to the trigger balance.
            for card in existing:
                if card.id == trigger.id or card.points == points:
                    continue
                difference = points - card.points
                card.write({"points": points})
                History.create(
                    {
                        "card_id": card.id,
                        "description": "Synced from paired Banaras branch loyalty card",
                        "issued": difference if difference > 0 else 0,
                        "used": -difference if difference < 0 else 0,
                    }
                )

    @api.model_create_multi
    def create(self, vals_list):
        cards = super().create(vals_list)
        cards._banaras_sync_and_enroll()
        return cards

    def write(self, vals):
        result = super().write(vals)
        if "points" in vals:
            self._banaras_sync_and_enroll()
        return result
