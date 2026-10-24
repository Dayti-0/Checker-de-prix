"""The basket through the running server (fake retailers of fake.py and catalog_p5.py):
honest comparison (B57), live basket over Server-Sent Events (B59), « Arrêter » cancels."""

import asyncio
import json
import time

import httpx
import pytest

from backend.services import search
from tests.e2e import fake
from tests.e2e.server import reset_data

HEADERS = {"X-PrixMalin": "1"}
STORES = ["aldi", "lidl", "carrefour", "intermarche", "coursesu", "leclerc"]


@pytest.fixture
def base(server):
    reset_data()
    fake.reset()
    yield server
    reset_data()
    fake.reset()


def add(base, query, **body):
    response = httpx.post(f"{base}/api/list", json={"query": query, **body}, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def demo_list(base):
    for query in ("beurre", "sucre", "lessive"):
        add(base, query)
    add(base, "jus d'orange", target="6 L")


def read_events(response):
    """(event, data) of a Server-Sent Events stream, as they arrive."""
    name = None
    for line in response.iter_lines():
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: ") and name:
            yield name, json.loads(line[6:])
            name = None


def test_demo_basket_is_honest(base):
    demo_list(base)
    comparison = httpx.post(f"{base}/api/basket/compare", json={"stores": STORES}, headers=HEADERS, timeout=30).json()
    baskets = {b["store"]: b for b in comparison["stores"]}
    # Carrefour has everything; Lidl is cheaper on what it has but lacks the orange juice
    assert comparison["best_store"] == "carrefour"
    assert comparison["ranking"][0] == "carrefour"
    assert baskets["lidl"]["missing"] == 1 and baskets["lidl"]["estimated"]
    juice = next(li for li in baskets["aldi"]["lines"] if li["query"] == "jus d'orange")
    assert (juice["product"]["name"], juice["packs"], juice["line_total"]) == ("Jus d'orange 6x1L", 1, 6.9)
    juice = next(li for li in baskets["carrefour"]["lines"] if li["query"] == "jus d'orange")
    assert (juice["packs"], juice["line_total"]) == (6, 8.7)
    # Retailers that could not be searched: reason and action, not ranked
    assert (baskets["intermarche"]["status"], baskets["intermarche"]["action"]) == ("unchecked", "choose_store")
    assert (baskets["coursesu"]["status"], baskets["coursesu"]["action"]) == ("unchecked", "unblock")
    assert "intermarche" not in comparison["ranking"] and "coursesu" not in comparison["ranking"]
    assert comparison["plans"][0]["kind"] == "single"


def test_the_basket_never_takes_a_close_product(base):
    """« huile de tournesol » with the real relevance (catalog_p2.py: tuna, sardines,
    chips and mayonnaise in sunflower oil, cheaper than the oils): only oils are
    taken, and a retailer without any oil leaves the item not found."""
    add(base, "huile de tournesol")
    comparison = httpx.post(
        f"{base}/api/basket/compare", json={"stores": ["aldi", "lidl", "carrefour"]}, headers=HEADERS, timeout=30
    ).json()
    taken = {}
    for basket in comparison["stores"]:
        (line,) = basket["lines"]
        assert line["status"] in ("found", "not_found"), line
        if line["status"] == "found":
            taken[basket["store"]] = line["product"]["name"]
    assert taken, comparison
    for store, name in taken.items():
        assert "huile de tournesol" in name.lower(), (store, name)
        assert not any(word in name.lower() for word in ("thon", "sardines", "chips", "mayonnaise")), (store, name)


def test_live_basket_fills_cell_by_cell(base, monkeypatch):
    demo_list(base)
    monkeypatch.setitem(fake.DELAYS, "*", 0.2)
    calls: list[str] = []

    async def counted(scraper, query, store):
        calls.append(scraper.key)
        return await fake.fake_scrape(scraper, query, store)

    monkeypatch.setattr(search, "_scrape", counted)
    events = []
    with httpx.stream("GET", f"{base}/api/basket/compare/stream", params={"stores": ",".join(STORES)}, timeout=60) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert "content-encoding" not in r.headers  # never held back by the compression
        for name, data in read_events(r):
            events.append((name, data))
    names = [n for n, _ in events]
    assert names[0] == "start" and names[-1] == "done"
    assert names.count("line") == events[0][1]["total"] == 24
    assert names.count("store") == 6
    done = events[-1][1]["comparison"]
    posted = httpx.post(f"{base}/api/basket/compare", json={"stores": STORES}, headers=HEADERS, timeout=30).json()
    assert [(b["store"], b["total"], b["estimated_total"]) for b in done["stores"]] == [
        (b["store"], b["total"], b["estimated_total"]) for b in posted["stores"]
    ]
    # One visit of the retailers that could not be searched, for the whole list (and none for the POST)
    assert (calls.count("coursesu"), calls.count("intermarche"), calls.count("aldi")) == (1, 1, 4)
    last = httpx.get(f"{base}/api/basket/last", headers=HEADERS).json()
    assert last["ranking"] == posted["ranking"]


def wait_for(condition, seconds=30.0):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.05)
    return condition()


def test_stop_cancels_the_searches(base, monkeypatch):
    demo_list(base)
    started: list[str] = []
    cancelled: list[str] = []

    async def hanging(scraper, query, store):
        started.append(scraper.key)
        try:
            await asyncio.sleep(120)
        except asyncio.CancelledError:
            cancelled.append(scraper.key)
            raise
        return []

    monkeypatch.setattr(search, "_scrape", hanging)
    with httpx.stream("GET", f"{base}/api/basket/compare/stream", params={"stores": "aldi,lidl"}, timeout=30) as r:
        events = read_events(r)  # kept: closing it would close the stream
        assert next(events)[0] == "start"
        assert wait_for(lambda: sorted(set(started)) == ["aldi", "lidl"])  # both sites are being searched
    # « Arrêter » closed the stream: the server notices and cancels both searches
    assert wait_for(lambda: sorted(set(cancelled)) == ["aldi", "lidl"])
    assert len(started) == 2  # and searches nothing more


def test_finished_stream_does_not_start_again(base):
    add(base, "beurre")
    response = httpx.get(f"{base}/api/basket/compare/stream", headers={"Last-Event-ID": "done-1234"})
    assert response.status_code == 204
    assert fake.state.scrapes == []
