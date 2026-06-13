from . import models


def post_init_flag_branch_programs(env):
    """Flag the existing Banaras points programs as branch loyalty programs.

    Runs on install/upgrade so the new sync + auto-enrollment works immediately
    for the current Rayners (#23) and Hatch End (#24) programs without hardcoding
    ids. Any future branch only needs the checkbox ticked on its program.
    """
    programs = env["loyalty.program"].sudo().search(
        [
            ("program_type", "=", "loyalty"),
            ("name", "ilike", "Banaras Paan Loyalty"),
        ]
    )
    to_flag = programs.filtered(lambda p: not p.x_banaras_branch_loyalty)
    if to_flag:
        to_flag.write({"x_banaras_branch_loyalty": True})
