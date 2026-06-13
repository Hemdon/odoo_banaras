"""Flag existing Banaras points programs as branch loyalty programs.

post_init_hook only runs on first install, not on upgrade, so this migration
ensures the flag is set when upgrading an already-installed module to 2.0.0.
"""


def migrate(cr, version):
    cr.execute(
        """
        update loyalty_program
           set x_banaras_branch_loyalty = true
         where program_type = 'loyalty'
           and coalesce(name->>'en_GB', name->>'en_US', '') ilike '%Banaras Paan Loyalty%'
           and coalesce(x_banaras_branch_loyalty, false) = false
        """
    )
