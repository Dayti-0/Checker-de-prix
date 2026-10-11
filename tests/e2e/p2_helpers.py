"""Helpers of the P2 E2E tests (search page)."""

import re
import struct
import zlib

from playwright.sync_api import expect

STORES = ["aldi", "lidl", "carrefour", "intermarche", "coursesu"]
SUNFLOWER_FOOD = ["Thon", "Sardines", "Mayonnaise", "Chips"]


def _png() -> bytes:
    """A 1x1 grey PNG (fake thumbnails of catalog_p2)."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"\x00\x99")) + chunk(b"IEND", b"")
    )


PNG = _png()


def search(page, query, *, wait=True):
    """Search ``query`` with the form of the page and wait until every retailer answered."""
    box = page.get_by_role("searchbox", name="Produit à rechercher")
    box.fill(query)
    box.press("Enter")
    if wait:
        wait_done(page)


def wait_done(page):
    expect(page.locator("#results")).to_have_attribute("aria-busy", "false")
    expect(page.locator(".summary-progress")).to_have_count(0)


def choose_view(page, name):
    """« Tout trié » or « Par enseigne »."""
    page.get_by_role("radio", name=name).check()
    expect(page.get_by_role("radio", name=name)).to_be_checked()


def offers(page):
    return page.get_by_test_id("offers")


def main_rows(page):
    """Product rows of the main list of « Tout trié » (not the close products)."""
    return page.locator("[data-testid=offers] .offer-list .product")


def close_toggle(page, scope=None):
    return (scope or page).get_by_role("button", name=re.compile(r"^Produits proches \(\d+\)"))


def serve_thumbnails(page, seen=None):
    """Answer the fake thumbnails of catalog_p2 (and count the requests)."""

    def handle(route):
        if seen is not None:
            seen.append(route.request.url)
        route.fulfill(status=200, content_type="image/png", body=PNG)

    page.route("https://images.prixmalin.test/**", handle)


def no_horizontal_scroll(page):
    return page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
