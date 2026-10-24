"""B55, B56: journal of the searches, state of the retailers, snapshots and diagnostic report."""

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend import config, main
from backend.models import Location, Product, StoreResult, StoreSelection
from backend.repos import scrape_log
from backend.services import health, search
from backend.services import settings as settings_service
from tests.conftest import run

NOW = 1_800_000_000.0


def row(status="ok", query="farine", ago=60, source="html", from_cache=False, error=None, elapsed=800):
    return {
        "ts": NOW - ago,
        "store": "aldi",
        "store_ctx": "",
        "query": query,
        "status": status,
        "source": source if status == "ok" else None,
        "products": 3 if status == "ok" else 0,
        "priced": 3 if status == "ok" else 0,
        "elapsed_ms": elapsed,
        "error": error or (None if status == "ok" else f"Erreur {status}"),
        "from_cache": int(from_cache),
    }


def state_of(rows, **kwargs):
    kwargs.setdefault("primary", "html")
    return health.retailer_health("aldi", rows, NOW, label="Aldi", **kwargs)


# ---------------------------------------------------------------- state (pure)


def test_no_search_yet():
    h = state_of([])
    assert (h.state, h.state_label) == ("unknown", "Pas encore testé")
    assert h.success_rate_7d is None and h.last_success is None and h.national


def test_working_retailer():
    rows = [row(ago=60, elapsed=600), row(ago=120, elapsed=1000), row("empty", "kiwi", ago=180)]
    h = state_of(rows)
    assert (h.state, h.state_label) == ("ok", "Prêt")
    assert h.last_success == NOW - 60 and h.last_source == "html"
    assert h.searches_7d == 3 and h.success_rate_7d == pytest.approx(0.667)
    assert h.avg_elapsed_ms == 800  # (600 + 1000 + 800) / 3
    assert h.consecutive_failures == 0 and h.last_error is None


def test_cached_results_say_nothing_about_the_site():
    rows = [row("ok", from_cache=True, ago=10), row("error", ago=60), row(ago=120)]
    h = state_of(rows)
    assert h.state == "failing" and h.last_at == NOW - 60
    assert h.searches_7d == 2 and h.consecutive_failures == 1
    assert h.last_error == "Erreur error"


def test_old_searches_leave_the_7_day_rate():
    h = state_of([row(ago=60), row("error", ago=8 * 24 * 3600)])
    assert h.searches_7d == 1 and h.success_rate_7d == 1.0


def test_degraded_when_a_fallback_reader_worked():
    h = state_of([row(source="generic"), row(source="html", ago=600)])
    assert (h.state, h.state_label) == ("degraded", "Dégradé")
    assert (h.last_source, h.primary_source) == ("generic", "html")
    assert state_of([row(source="generic")], primary=None).state == "ok"


def test_probably_broken_after_three_different_queries():
    rows = [row("empty", "lait"), row("error", "farine", ago=120), row("empty", "sucre", ago=180), row(ago=240)]
    h = state_of(rows)
    assert (h.state, h.state_label) == ("broken", "Probablement cassé")
    assert h.consecutive_failures == 3 and h.last_error == "Erreur empty"


def test_the_same_query_three_times_is_not_broken():
    rows = [row("empty", "kiwi"), row("empty", "Kiwis", ago=120), row("empty", "kiwi", ago=180)]
    h = state_of(rows)
    assert h.state == "ok" and h.consecutive_failures == 3
    # Two different queries only
    assert state_of([row("empty", "lait"), row("empty", "sucre", ago=120), row(ago=180)]).state == "ok"


def test_blocked_and_store_required():
    blocked = state_of([row("blocked"), row(ago=120)])
    assert (blocked.state, blocked.state_label) == ("blocked", "Vérification requise")
    assert blocked.consecutive_failures == 1
    no_store = state_of([row(ago=120)], needs_store=True, has_store=False)
    assert (no_store.state, no_store.state_label) == ("store_required", "Magasin à choisir")
    with_store = state_of([row("store_required"), row(ago=120)], needs_store=True, has_store=True)
    assert with_store.state == "store_required"
    # A « Magasin à choisir » answer is neither a success nor a failure
    assert with_store.consecutive_failures == 0 and with_store.searches_7d == 1


def test_store_unknown_to_the_site():
    gone = "Ce magasin n'existe plus sur Courses U, choisissez-en un autre."
    rows = [
        {**row("store_required", error=gone), "store_ctx": "https://www.coursesu.com/drive-superu-x"},
        row(ago=600),
    ]
    kwargs = {"needs_store": True, "has_store": True}
    h = state_of(rows, store_ctx="https://www.coursesu.com/drive-superu-x", **kwargs)
    # The store is still saved, the site no longer knows it: why is shown
    assert (h.state, h.state_label, h.last_error) == ("store_required", "Magasin à choisir", gone)
    # Another store chosen since: that answer was about the old store
    h = state_of(rows, store_ctx="https://www.coursesu.com/drive-superu-y", **kwargs)
    assert (h.state, h.last_error, h.last_status) == ("ok", None, "ok")
    # No store at all: nothing to explain
    h = state_of(rows, store_ctx="", needs_store=True, has_store=False)
    assert (h.state, h.last_error) == ("store_required", None)


def test_totals_given_by_the_journal_win():
    totals = health.Totals(
        searches_7d=451, ok_7d=1, avg_elapsed_ms=700, last_success=NOW - 3 * 86400, last_source="api"
    )
    h = state_of([row("error", ago=60)], totals=totals, primary="api")
    assert (h.searches_7d, h.success_rate_7d, h.avg_elapsed_ms) == (451, 0.002, 700)
    assert (h.last_success, h.last_source, h.state) == (NOW - 3 * 86400, "api", "failing")


def test_timeout_is_a_failure_but_not_broken():
    rows = [row("timeout", "a"), row("timeout", "b", ago=120), row("timeout", "c", ago=180)]
    h = state_of(rows)
    assert h.state == "failing" and h.consecutive_failures == 3


# ---------------------------------------------------------------- journal


def fake_scrape(outcomes):
    """Each call of search._scrape takes the next outcome: products or an exception."""
    queue = list(outcomes)

    async def scrape(scraper, query, store):
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        scraper.last_source = "html"
        return outcome

    return scrape


def test_searches_are_written_to_the_journal(monkeypatch):
    farine = [Product(store="aldi", name="Farine", price=0.79), Product(store="aldi", name="Farine bio")]
    monkeypatch.setattr(search, "_scrape", fake_scrape([farine, []]))

    async def scenario():
        await search.search_store("aldi", "farine")
        await search.search_store("aldi", "farine")  # from the cache
        await search.search_store("aldi", "kiwi")
        await settings_service.set_store("intermarche", StoreSelection(id="06814"))
        return await scrape_log.entries()

    rows = run(scenario())
    assert [(r["query"], r["status"], r["from_cache"]) for r in rows] == [
        ("kiwi", "empty", 0),
        ("farine", "ok", 1),
        ("farine", "ok", 0),
    ]
    first = rows[2]
    assert (first["store"], first["source"], first["products"], first["priced"]) == ("aldi", "html", 2, 1)
    assert first["error"] is None
    assert rows[0]["error"] == "Aucun produit trouvé chez Aldi."


def test_log_entry_of_a_store_and_purge():
    result = StoreResult(store="intermarche", label="Intermarché", status="blocked", message="Vérifiez" * 100)
    entry = health.log_entry(result, "lait", "06814", from_cache=False, now=NOW)
    assert entry["store_ctx"] == "06814" and len(entry["error"]) == 500 and entry["ts"] == NOW

    async def scenario():
        await scrape_log.insert(entry)
        await scrape_log.insert({**entry, "ts": NOW - 31 * 24 * 3600})
        removed = await scrape_log.purge(30 * 24 * 3600, now=NOW)
        rows = await scrape_log.entries(store="intermarche")
        await scrape_log.clear()
        return removed, rows, await scrape_log.entries()

    removed, rows, empty = run(scenario())
    assert removed == 1 and len(rows) == 1 and empty == []


def test_long_journals_keep_the_whole_week():
    """Hundreds of searches at the 5 retailers: the state still covers 7 days and 30 days."""

    def entry(ts, store, status, query):
        error = None if status == "ok" else "Intermarché ne répond pas."
        return {**row(status, query), "ts": ts, "store": store, "error": error}

    async def scenario():
        now = NOW
        await scrape_log.insert(entry(now - 3 * 86400, "intermarche", "ok", "farine"))
        for i in range(450):
            ts = now - 2 * 86400 + i * 60
            for key in ("aldi", "lidl", "carrefour", "coursesu"):
                await scrape_log.insert(entry(ts, key, "ok", f"q{i}"))
            await scrape_log.insert(entry(ts, "intermarche", "error", f"q{i}"))
            await scrape_log.insert({**entry(ts, "intermarche", "ok", f"q{i}"), "from_cache": 1})
        states = {h.key: h for h in await health.all_health(now)}
        rows = await scrape_log.entries(store="intermarche", limit=10_000)
        return states, rows

    states, rows = run(scenario())
    h = states["intermarche"]
    assert h.last_success == NOW - 3 * 86400
    assert h.searches_7d == 451 and h.success_rate_7d == round(1 / 451, 3)
    assert h.consecutive_failures == 450
    assert h.state == "store_required"  # no Intermarché store in these settings
    assert states["aldi"].searches_7d == 450 and states["aldi"].success_rate_7d == 1.0
    # The SQL figures are those of the pure function on every row
    real = [r for r in rows if not r["from_cache"]]
    assert health.totals_of(real, NOW) == health.Totals(
        searches_7d=h.searches_7d,
        ok_7d=1,
        avg_elapsed_ms=h.avg_elapsed_ms,
        last_success=h.last_success,
        last_source=h.last_source,
    )


# ---------------------------------------------------------------- API


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def write_snapshot(name, text="<html>page</html>"):
    config.DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    (config.DEBUG_DIR / name).write_text(text, encoding="utf-8")


def test_status_api(client, monkeypatch):
    monkeypatch.setattr(search, "_scrape", fake_scrape([[], RuntimeError("Target closed"), []]))
    for query in ("lait", "farine", "sucre"):
        assert client.get(f"/api/search/lidl?q={query}").status_code == 200
    write_snapshot("lidl.html")
    write_snapshot("lidl-blocked.html")
    write_snapshot("aldi-x.exe")  # not a snapshot
    states = {h["key"]: h for h in client.get("/api/status/retailers").json()}
    assert list(states) == ["aldi", "lidl", "carrefour", "intermarche", "coursesu", "leclerc"]
    lidl = states["lidl"]
    assert (lidl["state"], lidl["state_label"], lidl["consecutive_failures"]) == ("broken", "Probablement cassé", 3)
    assert lidl["last_error"] == "Aucun produit trouvé chez Lidl."
    assert sorted(s["name"] for s in lidl["snapshots"]) == ["lidl-blocked.html", "lidl.html"]
    assert states["aldi"]["state"] == "unknown" and states["aldi"]["snapshots"] == []
    assert states["intermarche"]["state"] == "store_required"
    assert states["coursesu"]["needs_store"] and not states["carrefour"]["national"]
    assert states["leclerc"]["needs_store"] and states["leclerc"]["state"] == "store_required"


def test_snapshot_api(client):
    write_snapshot("coursesu-stores.html", "<html><script>alert(1)</script></html>")
    response = client.get("/api/status/snapshot/coursesu-stores.html")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["content-security-policy"].startswith("sandbox")
    assert "alert(1)" in response.text
    (config.DATA_DIR / "secret.html").write_text("non", encoding="utf-8")
    for name in ("../secret.html", "..%2Fsecret.html", "coursesu-stores.txt", "autre.html", "coursesu-ABC.html"):
        assert client.get(f"/api/status/snapshot/{name}").status_code == 404, name
    assert client.get("/api/status/snapshot/aldi.html").status_code == 404  # not saved


def test_snapshot_names():
    for name in (
        "aldi.html",
        "coursesu-stores.html",
        "intermarche-20261009-101500-error.json",
        "lidl-blocked.png",
        "lidl-20261016-213000-error.txt",  # raw answer kept by save_debug_text
    ):
        assert health.SNAPSHOT_NAME.match(name), name
    for name in ("aldi.exe", "../aldi.html", "aldi/../x.html", "carrefourx.html", "x-aldi.html", "aldi-.html"):
        assert not health.SNAPSHOT_NAME.match(name), name


def test_diagnostic_zip(client, monkeypatch):
    async def located():
        await settings_service.modify(
            lambda s: setattr(s, "location", Location(postal_code="34320", city="Roujan", lat=43.5, lon=3.3))
        )
        await settings_service.set_store(
            "coursesu", StoreSelection(url="https://www.coursesu.com/drive-superu-roujan", name="Super U Roujan")
        )

    run(located())
    monkeypatch.setattr(search, "_scrape", fake_scrape([[]]))
    client.get("/api/search/aldi?q=farine")
    write_snapshot("aldi.html")
    (config.DATA_DIR / "logs").mkdir()
    (config.DATA_DIR / "logs" / "prixmalin.log").write_text("démarrage", encoding="utf-8")
    profile = config.DATA_DIR / "browser-profile" / "Default"
    profile.mkdir(parents=True)
    (profile / "Cookies").write_text("secret", encoding="utf-8")

    response = client.get("/api/status/diagnostic.zip")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"].startswith('attachment; filename="prixmalin-diagnostic-')
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = sorted(archive.namelist())
    assert names == [
        "LISEZMOI.txt",
        "captures/aldi.html",
        "etat.json",
        "logs/prixmalin.log",
        "recherches.json",
        "reglages.json",
        "versions.json",
    ]
    assert not any("browser-profile" in n or "Cookies" in n or n.endswith(".db") for n in names)
    settings = json.loads(archive.read("reglages.json"))
    assert settings == {
        "location": True,
        "location_has_coordinates": True,
        "show_browser": False,
        "stores": {"coursesu": {"chosen": True, "auto": False}},
    }
    everything = b"".join(archive.read(n) for n in names).decode("utf-8")
    for personal in ("34320", "Roujan", "drive-superu-roujan"):
        assert personal not in everything
    versions = json.loads(archive.read("versions.json"))
    assert versions["prixmalin"] and versions["python"] and "os" in versions
    journal = json.loads(archive.read("recherches.json"))
    assert journal[0]["query"] == "farine" and "store_ctx" not in journal[0]
    assert {h["key"] for h in json.loads(archive.read("etat.json"))} == {
        "aldi",
        "lidl",
        "carrefour",
        "intermarche",
        "coursesu",
        "leclerc",
    }


def test_diagnostic_skips_big_files(client, monkeypatch):
    monkeypatch.setattr(health, "DIAGNOSTIC_FILE_LIMIT", 10)
    write_snapshot("aldi.html", "x" * 100)
    archive = zipfile.ZipFile(io.BytesIO(client.get("/api/status/diagnostic.zip").content))
    assert "captures/aldi.html" not in archive.namelist()
