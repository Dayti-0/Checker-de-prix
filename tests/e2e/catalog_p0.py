"""Hostile products of the P0 security tests (search « pirate »)."""

XSS_NAME = "Pirate <img src=x onerror=\"document.title='XSS-OK'\">"

PRODUCTS = {
    "aldi": [
        {
            "name": XSS_NAME,
            "brand": "<b>gras</b>",
            "price": 1.0,
            "product_url": "javascript:document.title='XSS-OK'",
            "image_url": "javascript:document.title='XSS-OK'",
            "promo": "<script>document.title='XSS-OK'</script>",
        }
    ],
}
