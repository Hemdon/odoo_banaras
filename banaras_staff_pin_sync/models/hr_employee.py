from odoo import api, models

BANARAS_ROOT_COMPANY = 4  # Banaras Paan (parent of all branch companies)


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    def _banaras_branch_company_ids(self):
        """Banaras group = parent company 4 + all its branch children.
        New branches are picked up automatically."""
        root = self.env["res.company"].sudo().browse(BANARAS_ROOT_COMPANY)
        if not root.exists():
            return []
        return (root | root.child_ids).ids

    def _banaras_sync_pin(self):
        """Propagate this employee's PIN to the same person's records in every
        other Banaras branch company. 'Same person' is matched by name."""
        if self.env.context.get("banaras_skip_pin_sync"):
            return
        branch_ids = self._banaras_branch_company_ids()
        if not branch_ids:
            return
        Emp = self.env["hr.employee"].sudo().with_context(banaras_skip_pin_sync=True)
        for emp in self:
            name = (emp.name or "").strip()
            if not name or emp.company_id.id not in branch_ids:
                continue
            peers = Emp.search([
                ("name", "=", name),
                ("company_id", "in", branch_ids),
                ("id", "!=", emp.id),
            ])
            stale = peers.filtered(lambda e: e.pin != emp.pin)
            if stale:
                stale.write({"pin": emp.pin})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._banaras_sync_pin()
        return records

    def write(self, vals):
        result = super().write(vals)
        if "pin" in vals or "name" in vals:
            self._banaras_sync_pin()
        return result
