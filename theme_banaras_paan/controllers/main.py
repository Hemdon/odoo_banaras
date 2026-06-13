from odoo import http
from odoo.http import request


class BanarasPaanWebsite(http.Controller):
    @http.route(
        "/banaras-paan",
        type="http",
        auth="public",
        website=True,
        sitemap=True,
    )
    def banaras_paan_home(self, **kwargs):
        root_category = request.env.ref(
            "theme_banaras_paan.public_category_paan",
            raise_if_not_found=False,
        )
        categories = request.env["product.public.category"]
        products = request.env["product.template"]

        if root_category:
            categories = root_category.child_id.filtered(
                lambda category: category.website_id in (False, request.website)
            )
            if not categories:
                categories = root_category
            domain = request.website.sale_product_domain() + [
                ("public_categ_ids", "child_of", root_category.id),
            ]
            products = products.search(
                domain,
                order="website_sequence, name",
                limit=8,
            )

        return request.render(
            "theme_banaras_paan.homepage",
            {
                "paan_categories": categories,
                "featured_products": products,
                "root_category": root_category,
            },
        )
