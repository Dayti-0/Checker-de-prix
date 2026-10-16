from backend.scrapers.aldi import AldiScraper
from backend.scrapers.base import BaseScraper
from backend.scrapers.carrefour import CarrefourScraper
from backend.scrapers.coursesu import CoursesUScraper
from backend.scrapers.intermarche import IntermarcheScraper
from backend.scrapers.leclerc import LeclercScraper
from backend.scrapers.lidl import LidlScraper

# Display order in the interface
SCRAPERS: dict[str, BaseScraper] = {
    s.key: s
    for s in (
        AldiScraper(),
        LidlScraper(),
        CarrefourScraper(),
        IntermarcheScraper(),
        CoursesUScraper(),
        LeclercScraper(),
    )
}
