"""Unit tests for scraper modules and search service."""

import asyncio
import re
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.models import AppConfig, ScrapedProduct, SearchResponse, StoreConfig
from backend.scrapers.aldi import AldiScraper
from backend.scrapers.carrefour import CarrefourScraper
from backend.scrapers.coursesu import CoursesUScraper
from backend.scrapers.intermarche import IntermarcheScraper
from backend.services.search import _is_relevant, _normalize


class TestNormalize(unittest.TestCase):
    def test_lowercase(self):
        self.assertEqual(_normalize("HELLO"), "hello")

    def test_strip_accents(self):
        self.assertEqual(_normalize("crème brûlée"), "creme brulee")

    def test_combined(self):
        self.assertEqual(_normalize("Étagère"), "etagere")


class TestIsRelevant(unittest.TestCase):
    def _product(self, name: str) -> ScrapedProduct:
        return ScrapedProduct(name=name, product_url="", store_name="Test")

    def test_matching_keyword(self):
        p = self._product("Huile de tournesol Bellasan")
        self.assertTrue(_is_relevant(p, "huile tournesol"))

    def test_no_match(self):
        p = self._product("Lait demi-écrémé")
        self.assertFalse(_is_relevant(p, "huile tournesol"))

    def test_stop_words_only(self):
        p = self._product("Anything")
        self.assertTrue(_is_relevant(p, "de la"))

    def test_accent_insensitive(self):
        p = self._product("Crème fraîche épaisse")
        self.assertTrue(_is_relevant(p, "creme fraiche"))


class TestPriceParser(unittest.TestCase):
    """Test the _parse_price static method shared by all scrapers."""

    def test_comma_price(self):
        self.assertEqual(AldiScraper._parse_price("2,49"), 2.49)

    def test_dot_price(self):
        self.assertEqual(AldiScraper._parse_price("0.69"), 0.69)

    def test_price_with_euro(self):
        self.assertEqual(AldiScraper._parse_price("3,99 €"), 3.99)

    def test_integer_price(self):
        self.assertEqual(AldiScraper._parse_price("5"), 5.0)

    def test_no_price(self):
        self.assertIsNone(AldiScraper._parse_price(""))

    def test_nbsp_in_price(self):
        self.assertEqual(AldiScraper._parse_price("1,49\xa0€"), 1.49)


class TestScraperInstantiation(unittest.TestCase):
    """Ensure all scrapers can be instantiated and have correct store names."""

    def test_aldi_store_name(self):
        self.assertEqual(AldiScraper().store_name, "Aldi")

    def test_carrefour_store_name(self):
        self.assertEqual(CarrefourScraper().store_name, "Carrefour")

    def test_coursesu_store_name(self):
        self.assertEqual(CoursesUScraper().store_name, "Courses U")

    def test_intermarche_store_name(self):
        self.assertEqual(IntermarcheScraper().store_name, "Intermarché")


class TestAldiSetupLocation(unittest.TestCase):
    def test_always_returns_true(self):
        scraper = AldiScraper()
        result = asyncio.get_event_loop().run_until_complete(
            scraper.setup_location("34000")
        )
        self.assertTrue(result)


class TestCarrefourSetupLocation(unittest.TestCase):
    def test_always_returns_true(self):
        scraper = CarrefourScraper()
        result = asyncio.get_event_loop().run_until_complete(
            scraper.setup_location("34000")
        )
        self.assertTrue(result)


class TestCarrefourApiParsing(unittest.TestCase):
    def test_parse_api_data_basic(self):
        scraper = CarrefourScraper()
        api_data = [{
            "data": {
                "products": [
                    {
                        "title": "Huile de tournesol",
                        "price": {"price": 2.49, "pricePerUnit": "2.49", "unit": "L"},
                        "image": "https://example.com/img.jpg",
                        "url": "/p/huile-123",
                    }
                ]
            }
        }]
        products = scraper._parse_api_data(api_data)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].name, "Huile de tournesol")
        self.assertEqual(products[0].price, 2.49)
        self.assertEqual(products[0].store_name, "Carrefour")
        self.assertIn("carrefour.fr", products[0].product_url)

    def test_parse_api_data_empty(self):
        scraper = CarrefourScraper()
        products = scraper._parse_api_data([{"data": {}}])
        self.assertEqual(len(products), 0)


class TestIntermarcheApiParsing(unittest.TestCase):
    def test_parse_api_data_basic(self):
        scraper = IntermarcheScraper()
        api_data = [{
            "products": [
                {
                    "name": "Farine de blé T55",
                    "price": 1.29,
                    "imageUrl": "https://example.com/farine.jpg",
                    "url": "/p/farine-456",
                }
            ]
        }]
        products = scraper._parse_api_data(api_data)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].name, "Farine de blé T55")
        self.assertEqual(products[0].price, 1.29)
        self.assertEqual(products[0].store_name, "Intermarché")


class TestCoursesUApiParsing(unittest.TestCase):
    def test_parse_api_data_basic(self):
        scraper = CoursesUScraper()
        api_data = [{
            "products": [
                {
                    "title": "Eau de source",
                    "currentPrice": 0.55,
                    "image": {"url": "https://example.com/eau.jpg"},
                    "slug": "/p/eau-789",
                }
            ]
        }]
        products = scraper._parse_api_data(api_data)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].name, "Eau de source")
        self.assertEqual(products[0].price, 0.55)
        self.assertEqual(products[0].store_name, "Courses U")


class TestModels(unittest.TestCase):
    def test_scraped_product_defaults(self):
        p = ScrapedProduct(name="Test", product_url="https://example.com", store_name="Store")
        self.assertIsNone(p.price)
        self.assertIsNone(p.price_per_unit)
        self.assertIsNone(p.image_url)

    def test_search_response_defaults(self):
        r = SearchResponse(query="test", results=[])
        self.assertEqual(r.errors, [])

    def test_app_config_defaults(self):
        c = AppConfig()
        self.assertIsNone(c.postal_code)
        self.assertEqual(c.stores, {})

    def test_app_config_with_stores(self):
        c = AppConfig(
            postal_code="75001",
            stores={"coursesu": StoreConfig(store_id="123", store_name="Super U Paris")},
        )
        self.assertEqual(c.postal_code, "75001")
        self.assertIn("coursesu", c.stores)
        self.assertEqual(c.stores["coursesu"].store_name, "Super U Paris")


if __name__ == "__main__":
    unittest.main()
