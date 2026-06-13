import csv
import html
import io
import json

from odoo import http
from odoo.http import request


PAID_STATES = ("paid", "done", "invoiced")
DEFAULT_CONFIG_IDS = (9, 13)
POS_NAMES = {9: "Rayners Lane", 13: "Hatch End"}


def _date_filters(params, alias="po"):
    where = [f"{alias}.state in %s", f"{alias}.config_id in %s"]
    values = [PAID_STATES, tuple(_config_ids(params))]
    date_from = params.get("date_from")
    date_to = params.get("date_to")
    if date_from:
        where.append(f"{alias}.date_order >= %s::date")
        values.append(date_from)
    if date_to:
        where.append(f"{alias}.date_order < (%s::date + interval '1 day')")
        values.append(date_to)
    return " and ".join(where), values


def _config_ids(params):
    raw = params.get("config_ids")
    if not raw:
        return list(DEFAULT_CONFIG_IDS)
    ids = []
    for item in raw.split(","):
        item = item.strip()
        if item.isdigit():
            ids.append(int(item))
    return ids or list(DEFAULT_CONFIG_IDS)


def _json_name(alias, field="name", fallback="''"):
    return f"coalesce({alias}.{field}->>'en_GB', {alias}.{field}->>'en_US', {fallback})"


def _plain_name(alias, fallback="''"):
    return f"coalesce({alias}.name, {fallback})"


def _clean_line_product_name():
    product_name = _json_name("pt")
    return (
        "case "
        "when pol.full_product_name like 'Synced from Goodtill.%%' then "
        f"{product_name} "
        f"else coalesce(pol.full_product_name, pol.name, {product_name}) "
        "end"
    )


def _promotion_name():
    return (
        "case "
        "when lp.id = 15 then 'Buy 3 Get 1 FREE - Bubble Tea' "
        "else coalesce(lr.description->>'en_GB', lr.description->>'en_US', "
        f"{_json_name('lp')}, lr.reward_type, {_clean_line_product_name()}, 'Line discount') "
        "end"
    )


def _run(query, values):
    request.env.cr.execute(query, values)
    columns = [desc[0] for desc in request.env.cr.description]
    return columns, [dict(zip(columns, row)) for row in request.env.cr.fetchall()]


# ── Advanced Sales (period buckets) ─────────────────────────────────────────────

BUCKETS = {
    "hour":  ("to_char(date_trunc('hour', po.date_order), 'YYYY-MM-DD HH24:00')", "Hour"),
    "day":   ("to_char(po.date_order::date, 'YYYY-MM-DD (Dy)')", "Day"),
    "week":  ("to_char(date_trunc('week', po.date_order), 'IYYY \"W\"IW')", "Week"),
    "month": ("to_char(date_trunc('month', po.date_order), 'YYYY-MM (Mon)')", "Month"),
    "year":  ("to_char(date_trunc('year', po.date_order), 'YYYY')", "Year"),
}


def _bucket(params):
    b = (params.get("bucket") or "day").lower()
    return b if b in BUCKETS else "day"


# ── Sales Comparison (period vs period) ─────────────────────────────────────────

def _range_where(config_ids, date_from, date_to):
    where = ["po.state in %s", "po.config_id in %s"]
    values = [PAID_STATES, tuple(config_ids)]
    if date_from:
        where.append("po.date_order >= %s::date")
        values.append(date_from)
    if date_to:
        where.append("po.date_order < (%s::date + interval '1 day')")
        values.append(date_to)
    return " and ".join(where), values


def _comparison_metrics(config_ids, date_from, date_to):
    """Return an ordered list of (section, label, value) for one period."""
    where, values = _range_where(config_ids, date_from, date_to)

    request.env.cr.execute(
        f"""
            select
                count(*) as no_of_sales,
                coalesce(sum(po.amount_total - po.amount_tax) filter (where po.amount_tax > 0), 0) as vat_sales,
                coalesce(sum(po.amount_total - po.amount_tax) filter (where po.amount_tax = 0), 0) as non_vat_sales,
                coalesce(sum(po.amount_total - po.amount_tax), 0) as net_sales,
                coalesce(sum(po.amount_tax), 0) as vat_amount,
                coalesce(sum(po.amount_total), 0) as total,
                coalesce(avg(po.amount_total), 0) as avg_sale
            from pos_order po
            where {where}
        """,
        values,
    )
    s = request.env.cr.dictfetchone() or {}

    request.env.cr.execute(
        f"""
            select coalesce(sum(pol.qty * pol.price_unit * pol.discount / 100.0), 0) as line_discounts
            from pos_order_line pol
            join pos_order po on po.id = pol.order_id
            where {where} and coalesce(pol.is_reward_line, false) = false
        """,
        values,
    )
    line_disc = (request.env.cr.fetchone() or [0])[0] or 0

    request.env.cr.execute(
        f"""
            select {_json_name('ppm')} as method, sum(pay.amount) as amount, count(*) as cnt
            from pos_payment pay
            join pos_order po on po.id = pay.pos_order_id
            left join pos_payment_method ppm on ppm.id = pay.payment_method_id
            where {where}
            group by {_json_name('ppm')}
            order by method
        """,
        values,
    )
    payments = request.env.cr.fetchall()

    metrics = [
        ("Sales", "No of Sales", s.get("no_of_sales", 0), "int"),
        ("Sales", "VAT Sales", s.get("vat_sales", 0), "money"),
        ("Sales", "Non VAT Sales", s.get("non_vat_sales", 0), "money"),
        ("Sales", "Net Sales", s.get("net_sales", 0), "money"),
        ("Sales", "VAT Amount", s.get("vat_amount", 0), "money"),
        ("Sales", "Total", s.get("total", 0), "money"),
        ("Sales", "Avg Sale", s.get("avg_sale", 0), "money"),
        ("Discounts", "Line Discounts", line_disc, "money"),
    ]
    for method, amount, cnt in payments:
        metrics.append(("Payment Breakdown", method or "Unknown", amount or 0, "money"))
    return metrics


def _report_queries(params):
    where, values = _date_filters(params)
    line_where, line_values = _date_filters(params, "po")
    bucket_expr, _bucket_label = BUCKETS[_bucket(params)]
    return {
        "advanced_sales": (
            f"""
                select
                    {bucket_expr} as period,
                    count(*) as orders,
                    round(sum(po.amount_total - po.amount_tax)::numeric, 2) as net_sales,
                    round(sum(po.amount_tax)::numeric, 2) as vat_amount,
                    round(sum(po.amount_total)::numeric, 2) as gross_sales,
                    round(avg(po.amount_total)::numeric, 2) as avg_sale
                from pos_order po
                where {where}
                group by {bucket_expr}
                order by period
            """,
            values,
        ),
        "kpi_summary": (
            f"""
                select
                    count(*) as total_orders,
                    round(sum(po.amount_total)::numeric, 2) as total_gross_sales,
                    round(sum(po.amount_total - po.amount_tax)::numeric, 2) as total_net_sales,
                    round(sum(po.amount_tax)::numeric, 2) as total_tax,
                    round(avg(po.amount_total)::numeric, 2) as avg_order_value,
                    round(sum(po.amount_return)::numeric, 2) as total_change_given,
                    count(distinct po.date_order::date) as trading_days
                from pos_order po
                where {where}
            """,
            values,
        ),
        "daily_sales": (
            f"""
                select
                    po.date_order::date as date,
                    to_char(po.date_order::date, 'Day') as day,
                    rc.name as company,
                    pc.name as pos_config,
                    count(*) as orders,
                    round(sum(po.amount_total - po.amount_tax)::numeric, 2) as net_sales,
                    round(sum(po.amount_tax)::numeric, 2) as tax,
                    round(sum(po.amount_total)::numeric, 2) as gross_sales,
                    round(avg(po.amount_total)::numeric, 2) as avg_order,
                    round(sum(po.amount_paid)::numeric, 2) as paid,
                    round(sum(po.amount_return)::numeric, 2) as change
                from pos_order po
                left join res_company rc on rc.id = po.company_id
                left join pos_config pc on pc.id = po.config_id
                where {where}
                group by po.date_order::date, rc.name, pc.name
                order by date, company, pos_config
            """,
            values,
        ),
        "hourly_sales": (
            f"""
                select
                    to_char(extract(hour from po.date_order)::int, 'FM00') || ':00' as hour,
                    rc.name as company,
                    pc.name as pos_config,
                    count(*) as orders,
                    round(sum(po.amount_total)::numeric, 2) as gross_sales,
                    round(avg(po.amount_total)::numeric, 2) as avg_order
                from pos_order po
                left join res_company rc on rc.id = po.company_id
                left join pos_config pc on pc.id = po.config_id
                where {where}
                group by extract(hour from po.date_order), rc.name, pc.name
                order by hour, company, pos_config
            """,
            values,
        ),
        "product_sales": (
            f"""
                select
                    rc.name as company,
                    pc.name as pos_config,
                    coalesce(pt.default_code, '') as sku,
                    {_clean_line_product_name()} as product,
                    coalesce(string_agg(distinct {_json_name('posc')} , ', '), {_plain_name('cat')}) as category,
                    round(sum(pol.qty)::numeric, 3) as quantity,
                    round(sum(pol.price_subtotal)::numeric, 2) as net_sales,
                    round(sum(pol.price_subtotal_incl)::numeric, 2) as gross_sales,
                    round(sum(pol.price_subtotal_incl) / nullif(sum(pol.qty), 0)::numeric, 2) as avg_unit_price,
                    round(sum((pol.qty * pol.price_unit * pol.discount / 100.0))::numeric, 2) as discount_value
                from pos_order_line pol
                join pos_order po on po.id = pol.order_id
                left join res_company rc on rc.id = po.company_id
                left join pos_config pc on pc.id = po.config_id
                left join product_product pp on pp.id = pol.product_id
                left join product_template pt on pt.id = pp.product_tmpl_id
                left join product_category cat on cat.id = pt.categ_id
                left join pos_category_product_template_rel rel on rel.product_template_id = pt.id
                left join pos_category posc on posc.id = rel.pos_category_id
                where {line_where} and coalesce(pol.is_reward_line, false) = false
                group by rc.name, pc.name, pt.default_code, {_clean_line_product_name()}, {_plain_name('cat')}
                order by company, pos_config, gross_sales desc, product
            """,
            line_values,
        ),
        "category_sales": (
            f"""
                select
                    rc.name as company,
                    pc.name as pos_config,
                    coalesce(string_agg(distinct {_json_name('posc')} , ', '), {_plain_name('cat')}, 'Uncategorised') as category,
                    round(sum(pol.qty)::numeric, 3) as quantity,
                    round(sum(pol.price_subtotal)::numeric, 2) as net_sales,
                    round(sum(pol.price_subtotal_incl)::numeric, 2) as gross_sales,
                    round(sum((pol.qty * pol.price_unit * pol.discount / 100.0))::numeric, 2) as discount_value
                from pos_order_line pol
                join pos_order po on po.id = pol.order_id
                left join res_company rc on rc.id = po.company_id
                left join pos_config pc on pc.id = po.config_id
                left join product_product pp on pp.id = pol.product_id
                left join product_template pt on pt.id = pp.product_tmpl_id
                left join product_category cat on cat.id = pt.categ_id
                left join pos_category_product_template_rel rel on rel.product_template_id = pt.id
                left join pos_category posc on posc.id = rel.pos_category_id
                where {line_where} and coalesce(pol.is_reward_line, false) = false
                group by rc.name, pc.name, {_plain_name('cat')}
                order by company, pos_config, gross_sales desc, category
            """,
            line_values,
        ),
        "payment_summary": (
            f"""
                select
                    pay.payment_date::date as date,
                    rc.name as company,
                    pc.name as pos_config,
                    {_json_name('ppm')} as payment_method,
                    coalesce(pay.card_type, pay.card_brand, '') as card_type,
                    count(*) as count,
                    round(sum(pay.amount)::numeric, 2) as amount
                from pos_payment pay
                join pos_order po on po.id = pay.pos_order_id
                left join res_company rc on rc.id = po.company_id
                left join pos_config pc on pc.id = po.config_id
                left join pos_payment_method ppm on ppm.id = pay.payment_method_id
                where {where}
                group by pay.payment_date::date, rc.name, pc.name, {_json_name('ppm')}, coalesce(pay.card_type, pay.card_brand, '')
                order by date, company, pos_config, payment_method
            """,
            values,
        ),
        "discount_promotion_summary": (
            f"""
                select
                    po.date_order::date as date,
                    rc.name as company,
                    pc.name as pos_config,
                    {_promotion_name()} as promotion,
                    round(sum(case when coalesce(pol.is_reward_line, false) then abs(pol.qty) else pol.qty end)::numeric, 3) as quantity,
                    round(sum(case
                        when coalesce(pol.is_reward_line, false) then abs(pol.price_subtotal_incl)
                        else abs(pol.qty * pol.price_unit * pol.discount / 100.0)
                    end)::numeric, 2) as discount_value,
                    round(sum(coalesce(pol.points_cost, 0))::numeric, 2) as points_cost
                from pos_order_line pol
                join pos_order po on po.id = pol.order_id
                left join res_company rc on rc.id = po.company_id
                left join pos_config pc on pc.id = po.config_id
                left join product_product pp on pp.id = pol.product_id
                left join product_template pt on pt.id = pp.product_tmpl_id
                left join loyalty_reward lr on lr.id = pol.reward_id
                left join loyalty_program lp on lp.id = lr.program_id
                where {line_where}
                  and (coalesce(pol.is_reward_line, false) = true or coalesce(pol.discount, 0) <> 0)
                group by po.date_order::date, rc.name, pc.name, {_promotion_name()}
                order by date, company, pos_config, discount_value desc
            """,
            line_values,
        ),
        "session_summary": (
            f"""
                select
                    rc.name as company,
                    pc.name as pos_config,
                    ps.name as session,
                    ps.start_at::date as date,
                    coalesce(he.name, po.cashier, ru.login, '') as cashier,
                    count(*) as orders,
                    round(sum(po.amount_total - po.amount_tax)::numeric, 2) as net_sales,
                    round(sum(po.amount_tax)::numeric, 2) as tax,
                    round(sum(po.amount_total)::numeric, 2) as gross_sales,
                    round(avg(po.amount_total)::numeric, 2) as avg_order
                from pos_order po
                left join res_company rc on rc.id = po.company_id
                left join pos_config pc on pc.id = po.config_id
                left join pos_session ps on ps.id = po.session_id
                left join res_users ru on ru.id = po.user_id
                left join hr_employee he on he.id = po.employee_id
                where {where}
                group by rc.name, pc.name, ps.name, ps.start_at::date, coalesce(he.name, po.cashier, ru.login, '')
                order by company, pos_config, session, cashier
            """,
            values,
        ),
        "staff_sales": (
            f"""
                select
                    rc.name as company,
                    pc.name as pos_config,
                    coalesce(he.name, po.cashier, ru.login, 'Unknown') as cashier,
                    count(distinct po.id) as orders,
                    round(sum(po.amount_total - po.amount_tax)::numeric, 2) as net_sales,
                    round(sum(po.amount_total)::numeric, 2) as gross_sales,
                    round(avg(po.amount_total)::numeric, 2) as avg_order,
                    count(distinct po.date_order::date) as days_worked
                from pos_order po
                left join res_company rc on rc.id = po.company_id
                left join pos_config pc on pc.id = po.config_id
                left join res_users ru on ru.id = po.user_id
                left join hr_employee he on he.id = po.employee_id
                where {where}
                group by rc.name, pc.name, coalesce(he.name, po.cashier, ru.login, 'Unknown')
                order by company, pos_config, gross_sales desc
            """,
            values,
        ),
        "loyalty_balances": (
            """
                select
                    coalesce(lp.name->>'en_GB', lp.name->>'en_US', '') as program,
                    rc.name as company,
                    rp.name as customer,
                    lc.code,
                    round(lc.points::numeric, 2) as points,
                    lc.expiration_date,
                    count(lch.id) as total_transactions,
                    to_char(max(lch.create_date), 'YYYY-MM-DD') as last_activity
                from loyalty_card lc
                left join loyalty_program lp on lp.id = lc.program_id
                left join res_company rc on rc.id = lc.company_id
                left join res_partner rp on rp.id = lc.partner_id
                left join loyalty_card_update_balance lch on lch.card_id = lc.id
                where lp.id in (23, 24)
                group by lp.name, rc.name, rp.name, lc.code, lc.points, lc.expiration_date
                order by points desc, customer
            """,
            [],
        ),
    }


class BanarasReports(http.Controller):
    @http.route("/banaras/reports", type="http", auth="user", website=False)
    def reports(self, **params):
        query_map = _report_queries(params)

        # KPI summary
        _, kpi_rows = _run(*query_map["kpi_summary"])
        kpi = kpi_rows[0] if kpi_rows else {}

        report_data = {}
        for name in ["advanced_sales", "daily_sales", "hourly_sales", "product_sales", "category_sales",
                     "payment_summary", "discount_promotion_summary", "session_summary",
                     "staff_sales", "loyalty_balances"]:
            columns, rows = _run(*query_map[name])
            limit = 200 if name == "product_sales" else 100
            report_data[name] = {"columns": columns, "rows": rows[:limit], "count": len(rows)}

        return request.make_response(
            _render_page(params, report_data, kpi),
            headers=[("Content-Type", "text/html; charset=utf-8")],
        )

    @http.route("/banaras/reports/comparison", type="http", auth="user", website=False)
    def comparison(self, **params):
        config_ids = _config_ids(params)
        p1 = (params.get("date_from"), params.get("date_to"))
        p2 = (params.get("cmp_from"), params.get("cmp_to"))
        m1 = _comparison_metrics(config_ids, p1[0], p1[1]) if p1[0] else []
        m2 = _comparison_metrics(config_ids, p2[0], p2[1]) if p2[0] else []
        return request.make_response(
            _render_comparison(params, m1, m2),
            headers=[("Content-Type", "text/html; charset=utf-8")],
        )

    @http.route("/banaras/reports/<string:report_name>.csv", type="http", auth="user", website=False)
    def report_csv(self, report_name, **params):
        query_map = _report_queries(params)
        if report_name not in query_map:
            return request.not_found()
        columns, rows = _run(*query_map[report_name])
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
        return request.make_response(
            buffer.getvalue(),
            headers=[
                ("Content-Type", "text/csv; charset=utf-8"),
                ("Content-Disposition", f"attachment; filename={report_name}.csv"),
            ],
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _esc(value):
    return html.escape(str(value if value is not None else ""))


NUMBER_COLS = {
    "orders", "net_sales", "tax", "gross_sales", "avg_order", "avg_order_value",
    "paid", "change", "quantity", "discount_value", "points_cost", "amount",
    "count", "points", "total_orders", "total_gross_sales", "total_net_sales",
    "total_tax", "avg_unit_price", "days_worked", "total_transactions",
    "trading_days", "total_change_given",
}
MONEY_COLS = {
    "net_sales", "tax", "gross_sales", "avg_order", "paid", "change",
    "discount_value", "amount", "avg_unit_price", "total_gross_sales",
    "total_net_sales", "total_tax", "avg_order_value", "total_change_given",
}


def _fmt_cell(col, val):
    if val is None or val == "":
        return ""
    if col in MONEY_COLS:
        try:
            return f"£{float(val):,.2f}"
        except (ValueError, TypeError):
            pass
    if col in NUMBER_COLS:
        try:
            f = float(val)
            return f"{f:,.0f}" if f == int(f) else f"{f:,.2f}"
        except (ValueError, TypeError):
            pass
    return _esc(str(val))


def _render_table(title, data, csv_name=None, date_from="", date_to="", config_ids="9,13"):
    columns = data["columns"]
    rows = data["rows"]
    align = lambda c: ' class="num"' if c in NUMBER_COLS else ""
    header = "".join(f"<th{align(c)}>{_esc(c.replace('_', ' ').title())}</th>" for c in columns)

    # Totals row for numeric columns
    totals = {}
    for c in columns:
        if c in NUMBER_COLS and c not in {"avg_order", "avg_order_value", "avg_unit_price", "days_worked"}:
            try:
                totals[c] = sum(float(r.get(c) or 0) for r in rows)
            except (ValueError, TypeError):
                pass

    def render_row(row, cls=""):
        cells = "".join(f"<td{align(c)}>{_fmt_cell(c, row.get(c, ''))}</td>" for c in columns)
        return f'<tr{" class=" + repr(cls) if cls else ""}>{cells}</tr>'

    body = "".join(render_row(r) for r in rows)

    totals_row = ""
    if totals:
        cells = "".join(
            f'<td{align(c)}><strong>{_fmt_cell(c, totals[c]) if c in totals else ""}</strong></td>'
            for c in columns
        )
        totals_row = f'<tr class="totals-row"><td><strong>Total</strong></td>{cells[cells.index("</td>")+5:]}</tr>'

    csv_btn = ""
    if csv_name:
        csv_btn = (f'<a class="csv-btn" href="/banaras/reports/{csv_name}.csv'
                   f'?date_from={_esc(date_from)}&date_to={_esc(date_to)}&config_ids={_esc(config_ids)}">'
                   f'↓ CSV</a>')

    shown = len(rows)
    total_count = data["count"]
    count_label = f"{shown} of {total_count} rows" if shown < total_count else f"{total_count} rows"

    return f"""
        <section>
            <div class="section-head">
                <h2>{_esc(title)}</h2>
                <div class="section-actions">{csv_btn}<span class="row-count">{count_label}</span></div>
            </div>
            <div class="table-wrap">
                <table>
                    <thead><tr>{header}</tr></thead>
                    <tbody>{body or '<tr><td colspan="99" class="empty">No data for selected period</td></tr>'}{totals_row}</tbody>
                </table>
            </div>
        </section>
    """


def _num(v):
    try:
        return round(float(v or 0), 2)
    except (ValueError, TypeError):
        return 0.0


def _build_chart_data(report_data):
    """Aggregate report rows into series the front-end charts consume."""

    # 1. Daily sales trend — gross sales per date, split by branch
    daily = report_data["daily_sales"]["rows"]
    dates = sorted({r["date"].isoformat() if hasattr(r["date"], "isoformat") else str(r["date"]) for r in daily})
    companies = sorted({r["company"] for r in daily})
    daily_series = []
    for comp in companies:
        per_date = {d: 0.0 for d in dates}
        for r in daily:
            d = r["date"].isoformat() if hasattr(r["date"], "isoformat") else str(r["date"])
            if r["company"] == comp:
                per_date[d] += _num(r["gross_sales"])
        daily_series.append({"label": comp, "data": [round(per_date[d], 2) for d in dates]})

    # 2. Sales by branch — total gross per company
    branch_totals = {}
    for r in daily:
        branch_totals[r["company"]] = branch_totals.get(r["company"], 0.0) + _num(r["gross_sales"])

    # 3. Hourly sales — gross per hour (summed across branches)
    hourly = report_data["hourly_sales"]["rows"]
    hour_totals = {}
    for r in hourly:
        hour_totals[r["hour"]] = hour_totals.get(r["hour"], 0.0) + _num(r["gross_sales"])
    hours_sorted = sorted(hour_totals.keys())

    # 4. Top 10 products by gross sales
    products = report_data["product_sales"]["rows"]
    prod_totals = {}
    for r in products:
        prod_totals[r["product"]] = prod_totals.get(r["product"], 0.0) + _num(r["gross_sales"])
    top_products = sorted(prod_totals.items(), key=lambda kv: kv[1], reverse=True)[:10]

    # 5. Payment methods — total amount per method
    payments = report_data["payment_summary"]["rows"]
    pay_totals = {}
    for r in payments:
        pay_totals[r["payment_method"]] = pay_totals.get(r["payment_method"], 0.0) + _num(r["amount"])

    # 6. Category sales — gross per category (summed across branches)
    categories = report_data["category_sales"]["rows"]
    cat_totals = {}
    for r in categories:
        for cat in str(r["category"]).split(", "):
            cat_totals[cat] = cat_totals.get(cat, 0.0) + _num(r["gross_sales"])
    top_cats = sorted(cat_totals.items(), key=lambda kv: kv[1], reverse=True)[:12]

    # 7. Staff sales — gross per cashier
    staff = report_data["staff_sales"]["rows"]
    staff_totals = {}
    for r in staff:
        key = f'{r["cashier"]} ({r["pos_config"]})'
        staff_totals[key] = staff_totals.get(key, 0.0) + _num(r["gross_sales"])
    top_staff = sorted(staff_totals.items(), key=lambda kv: kv[1], reverse=True)[:12]

    return {
        "daily": {"labels": dates, "series": daily_series},
        "branch": {"labels": list(branch_totals.keys()), "data": [round(v, 2) for v in branch_totals.values()]},
        "hourly": {"labels": hours_sorted, "data": [round(hour_totals[h], 2) for h in hours_sorted]},
        "products": {"labels": [p[0] for p in top_products], "data": [round(p[1], 2) for p in top_products]},
        "payments": {"labels": list(pay_totals.keys()), "data": [round(v, 2) for v in pay_totals.values()]},
        "categories": {"labels": [c[0] for c in top_cats], "data": [round(c[1], 2) for c in top_cats]},
        "staff": {"labels": [s[0] for s in top_staff], "data": [round(s[1], 2) for s in top_staff]},
    }


def _render_kpi(kpi):
    def card(label, value, sub=""):
        sub_html = f'<div class="kpi-sub">{_esc(sub)}</div>' if sub else ""
        return f'<div class="kpi-card"><div class="kpi-label">{_esc(label)}</div><div class="kpi-value">{_esc(str(value))}</div>{sub_html}</div>'

    total_sales = kpi.get("total_gross_sales", 0) or 0
    total_net = kpi.get("total_net_sales", 0) or 0
    total_orders = kpi.get("total_orders", 0) or 0
    avg_order = kpi.get("avg_order_value", 0) or 0
    trading_days = kpi.get("trading_days", 0) or 0
    daily_avg = round(float(total_sales) / max(int(trading_days), 1), 2)

    cards = [
        card("Gross Sales", f"£{float(total_sales):,.2f}"),
        card("Net Sales", f"£{float(total_net):,.2f}", "excl. tax"),
        card("Total Orders", f"{int(total_orders):,}"),
        card("Avg Order Value", f"£{float(avg_order):,.2f}"),
        card("Trading Days", str(int(trading_days)), f"~£{daily_avg:,.2f}/day"),
    ]
    return f'<div class="kpi-row">{"".join(cards)}</div>'


def _render_dashboard():
    def chart_card(title, canvas_id, wide=False):
        cls = "chart-card wide" if wide else "chart-card"
        return (f'<div class="{cls}"><div class="chart-title">{_esc(title)}</div>'
                f'<div class="chart-body"><canvas id="{canvas_id}"></canvas></div></div>')

    return f"""
        <div class="chart-grid">
            {chart_card("Daily Sales Trend (by branch)", "chartDaily", wide=True)}
            {chart_card("Sales by Branch", "chartBranch")}
            {chart_card("Payment Methods", "chartPayments")}
            {chart_card("Sales by Hour", "chartHourly", wide=True)}
            {chart_card("Top Categories", "chartCategories")}
            {chart_card("Top 10 Products", "chartProducts")}
            {chart_card("Staff Sales", "chartStaff")}
        </div>
    """


def _render_page(params, report_data, kpi):
    date_from = _esc(params.get("date_from", ""))
    date_to = _esc(params.get("date_to", ""))
    config_ids_raw = params.get("config_ids", ",".join(str(i) for i in DEFAULT_CONFIG_IDS))
    config_ids = _esc(config_ids_raw)

    # Branch checkboxes
    selected = set(_config_ids(params))
    branch_checks = "".join(
        f'<label class="branch-label"><input type="checkbox" name="branch" value="{cid}" '
        f'{"checked" if cid in selected else ""} onchange="syncBranches()">'
        f' {name}</label>'
        for cid, name in POS_NAMES.items()
    )

    cur_bucket = _bucket(params)
    bucket_options = "".join(
        f'<option value="{key}"{" selected" if key == cur_bucket else ""}>{label}</option>'
        for key, (_expr, label) in BUCKETS.items()
    )

    kpi_html = _render_kpi(kpi)

    def tbl(name, title, csv_name=None):
        return _render_table(title, report_data[name],
                             csv_name=csv_name or name,
                             date_from=date_from, date_to=date_to,
                             config_ids=config_ids)

    # (tab_id, nav_label, report_name, section_title, csv_name)
    tab_defs = [
        ("advanced",   "Advanced Sales",   "advanced_sales",            f"Advanced Sales — by {BUCKETS[_bucket(params)][1]}", "advanced_sales"),
        ("daily",      "Daily Sales",      "daily_sales",               "Daily Sales",             "daily_sales"),
        ("hourly",     "Hourly",           "hourly_sales",              "Hourly Sales Breakdown",   None),
        ("products",   "Products",         "product_sales",             "Product Sales",           "product_sales"),
        ("categories", "Categories",       "category_sales",            "Category Sales",          "category_sales"),
        ("payments",   "Payments",         "payment_summary",           "Payment Summary",         "payment_summary"),
        ("promotions", "Promotions",       "discount_promotion_summary","Discounts & Promotions",  "discount_promotion_summary"),
        ("staff",      "Staff",            "staff_sales",               "Staff Sales Performance", "staff_sales"),
        ("sessions",   "Sessions",         "session_summary",           "Session Summary",         "session_summary"),
        ("loyalty",    "Loyalty",          "loyalty_balances",          "Loyalty Balances",        "loyalty_balances"),
    ]

    # Dashboard tab is first and active by default
    dash_btn = ('<button type="button" class="tab-btn active" data-tab="tab-dashboard" '
                'onclick="showTab(this)">📊 Dashboard</button>')
    tab_nav = dash_btn + "".join(
        f'<button type="button" class="tab-btn" '
        f'data-tab="tab-{tab_id}" onclick="showTab(this)">{_esc(nav_label)} '
        f'<span class="tab-badge">{report_data[rname]["count"]}</span></button>'
        for (tab_id, nav_label, rname, _title, _csv) in tab_defs
    )

    dash_panel = f'<div class="tab-panel active" id="tab-dashboard">{_render_dashboard()}</div>'
    tab_panels = dash_panel + "".join(
        f'<div class="tab-panel" id="tab-{tab_id}">{tbl(rname, title, csv_name)}</div>'
        for (tab_id, _nav, rname, title, csv_name) in tab_defs
    )

    tables = f'<div class="tab-nav">{tab_nav}</div>{tab_panels}'
    chart_json = json.dumps(_build_chart_data(report_data))

    return f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Banaras Reports</title>
    <style>
        *, *::before, *::after {{ box-sizing: border-box; }}
        body {{ margin: 0; font-family: -apple-system, Arial, sans-serif; color: #1f2933; background: #f0f2f5; }}
        header {{ background: #1a1f2e; color: white; padding: 18px 28px; display: flex; align-items: center; gap: 16px; }}
        header h1 {{ margin: 0; font-size: 20px; font-weight: 700; }}
        header .sub {{ font-size: 13px; color: #9aa5b4; margin-top: 2px; }}
        main {{ padding: 20px 28px 60px; max-width: 1600px; }}

        /* Filter bar */
        .filter-bar {{ background: white; border: 1px solid #dde3ec; padding: 14px 16px; margin-bottom: 16px;
                       display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }}
        .filter-bar label {{ display: grid; gap: 4px; font-size: 12px; font-weight: 600; color: #5a6475; }}
        .filter-bar input[type=date] {{ padding: 7px 10px; border: 1px solid #c8d0dc; font-size: 13px; }}
        .filter-bar input[type=hidden] {{ display: none; }}
        .branch-group {{ display: flex; gap: 10px; }}
        .branch-label {{ display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 500; cursor: pointer; }}
        .filter-bar button {{ padding: 8px 16px; border: 0; background: #2c5de5; color: white;
                              font-weight: 600; font-size: 13px; cursor: pointer; }}
        .filter-bar button:hover {{ background: #1e4abf; }}

        /* KPI cards */
        .kpi-row {{ display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; }}
        .kpi-card {{ background: white; border: 1px solid #dde3ec; padding: 16px 20px; flex: 1 1 160px; min-width: 140px; }}
        .kpi-label {{ font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .5px; color: #667085; margin-bottom: 6px; }}
        .kpi-value {{ font-size: 26px; font-weight: 700; color: #1a1f2e; }}
        .kpi-sub {{ font-size: 11px; color: #9aa5b4; margin-top: 3px; }}

        /* CSV export links */
        .csv-btn {{ font-size: 12px; color: #2c5de5; text-decoration: none; border: 1px solid #c5d3f7;
                    background: #eef3fd; padding: 4px 8px; white-space: nowrap; }}
        .csv-btn:hover {{ background: #dce8fb; }}

        /* Tab navigation */
        .tab-nav {{ display: flex; flex-wrap: wrap; gap: 2px; margin-bottom: 16px;
                    border-bottom: 2px solid #dde3ec; }}
        .tab-btn {{ border: 0; background: transparent; padding: 11px 16px; font-size: 13px;
                    font-weight: 600; color: #5a6475; cursor: pointer; border-bottom: 3px solid transparent;
                    margin-bottom: -2px; display: flex; align-items: center; gap: 7px; }}
        .tab-btn:hover {{ color: #1a1f2e; background: #e9edf4; }}
        .tab-btn.active {{ color: #2c5de5; border-bottom-color: #2c5de5; }}
        .tab-badge {{ font-size: 11px; font-weight: 700; background: #e3e8f0; color: #5a6475;
                      border-radius: 10px; padding: 1px 8px; min-width: 20px; text-align: center; }}
        .tab-btn.active .tab-badge {{ background: #2c5de5; color: white; }}
        .tab-panel {{ display: none; }}
        .tab-panel.active {{ display: block; }}
        .tab-panel section {{ margin-bottom: 0; }}

        /* Dashboard charts */
        .chart-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }}
        .chart-card {{ background: white; border: 1px solid #dde3ec; padding: 16px; }}
        .chart-card.wide {{ grid-column: 1 / -1; }}
        .chart-title {{ font-size: 14px; font-weight: 700; color: #1a1f2e; margin-bottom: 12px; }}
        .chart-body {{ position: relative; height: 300px; }}
        .chart-card.wide .chart-body {{ height: 320px; }}
        @media (max-width: 900px) {{ .chart-grid {{ grid-template-columns: 1fr; }} .chart-card.wide {{ grid-column: auto; }} }}

        /* Tables */
        section {{ background: white; border: 1px solid #dde3ec; margin-bottom: 16px; }}
        .section-head {{ display: flex; justify-content: space-between; align-items: center; gap: 12px;
                         padding: 13px 16px; border-bottom: 1px solid #dde3ec; }}
        .section-head h2 {{ margin: 0; font-size: 15px; font-weight: 700; }}
        .section-actions {{ display: flex; align-items: center; gap: 10px; }}
        .row-count {{ font-size: 12px; color: #9aa5b4; }}
        .table-wrap {{ overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th, td {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid #edf0f4; white-space: nowrap; }}
        th {{ background: #f7f8fa; font-size: 11px; font-weight: 700; text-transform: uppercase;
              letter-spacing: .4px; color: #5a6475; position: sticky; top: 0; }}
        th.num, td.num {{ text-align: right; }}
        tr:hover td {{ background: #fafbfc; }}
        .totals-row td {{ background: #f0f4ff; font-weight: 600; border-top: 2px solid #c5d3f7; }}
        .empty {{ text-align: center; color: #9aa5b4; padding: 28px; font-style: italic; }}
    </style>
</head>
<body>
    <header>
        <div>
            <h1>Banaras Paan — Reports</h1>
            <div class="sub">Sales, payments, staff &amp; loyalty — Rayners Lane and Hatch End</div>
        </div>
    </header>
    <main>
        <form method="get" action="/banaras/reports" id="filterForm">
            <div class="filter-bar">
                <label>Date From<input type="date" name="date_from" value="{date_from}"></label>
                <label>Date To<input type="date" name="date_to" value="{date_to}"></label>
                <input type="hidden" name="config_ids" id="configIdsInput" value="{config_ids}">
                <label>Branch
                    <div class="branch-group">{branch_checks}</div>
                </label>
                <label>Advanced period
                    <select name="bucket">{bucket_options}</select>
                </label>
                <button type="submit">Apply</button>
                <a class="cmp-link" href="/banaras/reports/comparison?date_from={date_from}&date_to={date_to}&config_ids={config_ids}">⇄ Comparison</a>
            </div>
        </form>
        {kpi_html}
        {tables}
    </main>
    <script src="/banaras_reports/static/lib/chart.umd.min.js"></script>
    <script>
        function syncBranches() {{
            var checked = Array.from(document.querySelectorAll('input[name=branch]:checked')).map(function(el) {{ return el.value; }});
            document.getElementById('configIdsInput').value = checked.join(',') || '9,13';
        }}
        function showTab(btn) {{
            var target = btn.getAttribute('data-tab');
            document.querySelectorAll('.tab-btn').forEach(function(b) {{ b.classList.toggle('active', b === btn); }});
            document.querySelectorAll('.tab-panel').forEach(function(p) {{ p.classList.toggle('active', p.id === target); }});
            history.replaceState(null, '', '#' + target);
        }}

        var CHART_DATA = {chart_json};
        var PALETTE = ['#2c5de5','#e5762c','#27ae60','#9b51e0','#eb5757','#f2c94c','#56ccf2','#bb6bd9','#219653','#f2994a','#6fcf97','#2d9cdb'];
        var gbp = function(v) {{ return '£' + Number(v).toLocaleString('en-GB', {{minimumFractionDigits: 2, maximumFractionDigits: 2}}); }};
        var moneyTip = {{ callbacks: {{ label: function(c) {{ return (c.dataset.label ? c.dataset.label + ': ' : '') + gbp(c.parsed.y != null ? c.parsed.y : c.parsed); }} }} }};

        function buildCharts() {{
            if (typeof Chart === 'undefined') return;
            Chart.defaults.font.family = '-apple-system, Arial, sans-serif';

            // 1. Daily sales trend (grouped bar by branch)
            new Chart(document.getElementById('chartDaily'), {{
                type: 'bar',
                data: {{ labels: CHART_DATA.daily.labels,
                    datasets: CHART_DATA.daily.series.map(function(s, i) {{
                        return {{ label: s.label, data: s.data, backgroundColor: PALETTE[i % PALETTE.length] }}; }}) }},
                options: {{ responsive: true, maintainAspectRatio: false,
                    plugins: {{ tooltip: moneyTip, legend: {{ position: 'bottom' }} }},
                    scales: {{ y: {{ beginAtZero: true, ticks: {{ callback: function(v) {{ return '£' + v; }} }} }} }} }}
            }});

            // 2. Sales by branch (doughnut)
            new Chart(document.getElementById('chartBranch'), {{
                type: 'doughnut',
                data: {{ labels: CHART_DATA.branch.labels,
                    datasets: [{{ data: CHART_DATA.branch.data, backgroundColor: PALETTE }}] }},
                options: {{ responsive: true, maintainAspectRatio: false,
                    plugins: {{ legend: {{ position: 'bottom' }},
                        tooltip: {{ callbacks: {{ label: function(c) {{ return c.label + ': ' + gbp(c.parsed); }} }} }} }} }}
            }});

            // 3. Payment methods (doughnut)
            new Chart(document.getElementById('chartPayments'), {{
                type: 'doughnut',
                data: {{ labels: CHART_DATA.payments.labels,
                    datasets: [{{ data: CHART_DATA.payments.data, backgroundColor: PALETTE }}] }},
                options: {{ responsive: true, maintainAspectRatio: false,
                    plugins: {{ legend: {{ position: 'bottom' }},
                        tooltip: {{ callbacks: {{ label: function(c) {{ return c.label + ': ' + gbp(c.parsed); }} }} }} }} }}
            }});

            // 4. Sales by hour (bar)
            new Chart(document.getElementById('chartHourly'), {{
                type: 'bar',
                data: {{ labels: CHART_DATA.hourly.labels,
                    datasets: [{{ label: 'Gross Sales', data: CHART_DATA.hourly.data, backgroundColor: '#2c5de5' }}] }},
                options: {{ responsive: true, maintainAspectRatio: false,
                    plugins: {{ tooltip: moneyTip, legend: {{ display: false }} }},
                    scales: {{ y: {{ beginAtZero: true, ticks: {{ callback: function(v) {{ return '£' + v; }} }} }} }} }}
            }});

            // 5. Top categories (horizontal bar)
            new Chart(document.getElementById('chartCategories'), {{
                type: 'bar',
                data: {{ labels: CHART_DATA.categories.labels,
                    datasets: [{{ label: 'Gross Sales', data: CHART_DATA.categories.data, backgroundColor: '#27ae60' }}] }},
                options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false,
                    plugins: {{ tooltip: {{ callbacks: {{ label: function(c) {{ return gbp(c.parsed.x); }} }} }}, legend: {{ display: false }} }},
                    scales: {{ x: {{ beginAtZero: true, ticks: {{ callback: function(v) {{ return '£' + v; }} }} }} }} }}
            }});

            // 6. Top 10 products (horizontal bar)
            new Chart(document.getElementById('chartProducts'), {{
                type: 'bar',
                data: {{ labels: CHART_DATA.products.labels,
                    datasets: [{{ label: 'Gross Sales', data: CHART_DATA.products.data, backgroundColor: '#9b51e0' }}] }},
                options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false,
                    plugins: {{ tooltip: {{ callbacks: {{ label: function(c) {{ return gbp(c.parsed.x); }} }} }}, legend: {{ display: false }} }},
                    scales: {{ x: {{ beginAtZero: true, ticks: {{ callback: function(v) {{ return '£' + v; }} }} }} }} }}
            }});

            // 7. Staff sales (horizontal bar)
            new Chart(document.getElementById('chartStaff'), {{
                type: 'bar',
                data: {{ labels: CHART_DATA.staff.labels,
                    datasets: [{{ label: 'Gross Sales', data: CHART_DATA.staff.data, backgroundColor: '#e5762c' }}] }},
                options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false,
                    plugins: {{ tooltip: {{ callbacks: {{ label: function(c) {{ return gbp(c.parsed.x); }} }} }}, legend: {{ display: false }} }},
                    scales: {{ x: {{ beginAtZero: true, ticks: {{ callback: function(v) {{ return '£' + v; }} }} }} }} }}
            }});
        }}

        window.addEventListener('load', buildCharts);

        // Restore tab from URL hash on load
        (function() {{
            var hash = window.location.hash.replace('#', '');
            if (hash) {{
                var btn = document.querySelector('.tab-btn[data-tab="' + hash + '"]');
                if (btn) showTab(btn);
            }}
        }})();
    </script>
</body>
</html>"""


# ── Comparison renderer ─────────────────────────────────────────────────────────

def _cmp_fmt(value, fmt):
    try:
        v = float(value or 0)
    except (ValueError, TypeError):
        return _esc(str(value))
    if fmt == "money":
        return f"£{v:,.2f}"
    return f"{v:,.0f}" if v == int(v) else f"{v:,.2f}"


def _cmp_delta(v1, v2):
    """Percentage change of period 2 relative to period 1."""
    try:
        a, b = float(v1 or 0), float(v2 or 0)
    except (ValueError, TypeError):
        return "", ""
    if a == 0:
        return ("", "") if b == 0 else ("+∞", "pos")
    pct = (b - a) / abs(a) * 100.0
    cls = "pos" if pct > 0 else ("neg" if pct < 0 else "")
    return (f"{pct:+.0f}%", cls)


def _render_comparison(params, m1, m2):
    date_from = _esc(params.get("date_from", ""))
    date_to = _esc(params.get("date_to", ""))
    cmp_from = _esc(params.get("cmp_from", ""))
    cmp_to = _esc(params.get("cmp_to", ""))
    config_ids = _esc(params.get("config_ids", ",".join(str(i) for i in DEFAULT_CONFIG_IDS)))

    # Merge both periods preserving order: keys are (section, label).
    d1 = {(s, l): (v, f) for (s, l, v, f) in m1}
    d2 = {(s, l): (v, f) for (s, l, v, f) in m2}
    order = []
    seen = set()
    for (s, l, _v, _f) in m1 + m2:
        if (s, l) not in seen:
            seen.add((s, l))
            order.append((s, l))

    rows_html = ""
    last_section = None
    for (section, label) in order:
        if section != last_section:
            rows_html += f'<tr class="cmp-section"><td colspan="4">{_esc(section)}</td></tr>'
            last_section = section
        v1, f1 = d1.get((section, label), (0, "money"))
        v2, f2 = d2.get((section, label), (0, f1))
        fmt = f1 or f2
        delta, dcls = _cmp_delta(v1, v2)
        rows_html += (
            f"<tr><td>{_esc(label)}</td>"
            f'<td class="num">{_cmp_fmt(v1, fmt)}</td>'
            f'<td class="num">{_cmp_fmt(v2, fmt)}</td>'
            f'<td class="num delta {dcls}">{_esc(delta)}</td></tr>'
        )

    has_data = bool(order)
    p1_label = f"{date_from or '—'} → {date_to or '—'}"
    p2_label = f"{cmp_from or '—'} → {cmp_to or '—'}"

    table = (
        f"""
        <section>
            <div class="section-head"><h2>Comparison Summary</h2></div>
            <div class="table-wrap"><table>
                <thead><tr>
                    <th>Metric</th>
                    <th class="num">Period 1<br><span class="hint">{_esc(p1_label)}</span></th>
                    <th class="num">Period 2<br><span class="hint">{_esc(p2_label)}</span></th>
                    <th class="num">Δ %</th>
                </tr></thead>
                <tbody>{rows_html}</tbody>
            </table></div>
        </section>
        """
        if has_data
        else '<section><div class="empty">Choose two date ranges and press Compare.</div></section>'
    )

    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Banaras Reports — Comparison</title>
<style>
*,*::before,*::after{{box-sizing:border-box}}
body{{margin:0;font-family:-apple-system,Arial,sans-serif;color:#1f2933;background:#f0f2f5}}
header{{background:#1a1f2e;color:#fff;padding:18px 28px}}
header h1{{margin:0;font-size:20px}}
header .sub{{font-size:13px;color:#9aa5b4;margin-top:2px}}
main{{padding:20px 28px 60px;max-width:1000px}}
.filter-bar{{background:#fff;border:1px solid #dde3ec;padding:14px 16px;margin-bottom:16px;display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end}}
.filter-bar label{{display:grid;gap:4px;font-size:12px;font-weight:600;color:#5a6475}}
.filter-bar input[type=date]{{padding:7px 10px;border:1px solid #c8d0dc;font-size:13px}}
.filter-bar button{{padding:8px 16px;border:0;background:#2c5de5;color:#fff;font-weight:600;font-size:13px;cursor:pointer}}
.filter-bar a{{font-size:12px;color:#2c5de5;text-decoration:none;align-self:center}}
section{{background:#fff;border:1px solid #dde3ec;margin-bottom:16px}}
.section-head{{padding:13px 16px;border-bottom:1px solid #dde3ec}}
.section-head h2{{margin:0;font-size:15px}}
.table-wrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{text-align:left;padding:8px 14px;border-bottom:1px solid #edf0f4;white-space:nowrap}}
th{{background:#f7f8fa;font-size:11px;font-weight:700;text-transform:uppercase;color:#5a6475}}
th .hint{{font-weight:500;text-transform:none;color:#9aa5b4}}
th.num,td.num{{text-align:right}}
.cmp-section td{{background:#eef2fb;font-weight:700;text-transform:uppercase;font-size:11px;letter-spacing:.4px;color:#3a4a6b}}
td.delta.pos{{color:#1e9e5a;font-weight:700}}
td.delta.neg{{color:#d23f3f;font-weight:700}}
.empty{{text-align:center;color:#9aa5b4;padding:28px;font-style:italic}}
</style></head>
<body>
<header><h1>Banaras Paan — Sales Comparison</h1><div class="sub">Period vs period — Rayners Lane &amp; Hatch End</div></header>
<main>
<form method="get" action="/banaras/reports/comparison">
  <div class="filter-bar">
    <label>Period 1 from<input type="date" name="date_from" value="{date_from}"></label>
    <label>Period 1 to<input type="date" name="date_to" value="{date_to}"></label>
    <label>Period 2 from<input type="date" name="cmp_from" value="{cmp_from}"></label>
    <label>Period 2 to<input type="date" name="cmp_to" value="{cmp_to}"></label>
    <input type="hidden" name="config_ids" value="{config_ids}">
    <button type="submit">Compare</button>
    <a href="/banaras/reports?date_from={date_from}&date_to={date_to}&config_ids={config_ids}">← Back to dashboard</a>
  </div>
</form>
{table}
</main></body></html>"""
