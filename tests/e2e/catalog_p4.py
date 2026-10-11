"""Fake Courses U store directory, town table and site of the P4 E2E tests (and of the demo).

SYNTHETIC data: the stores, their ids and their addresses are made up around
Montpellier and Béziers (and one near Bordeaux), not read on coursesu.com.

- ``backend.services.stores.fetch_coursesu_directory``: ``STORES`` (or raises
  ``DIRECTORY_ERROR`` when a test sets it);
- ``backend.services.stores.commune_index``: the towns of ``COMMUNES``;
- ``backend.services.stores.fetch_site_store``: ``SITE_STORE``, what the
  Courses U pages show after « Ouvrir le site » (``{"link": url}`` or None);
- the first-launch assistant does not open by itself (a test turns it on with
  ``settings.AUTO_ONBOARDING``);
- each test starts with an empty journal of searches and an empty store cache.
"""

import sqlite3
from pathlib import Path

from backend import config
from backend.models import StoreOption
from backend.scrapers import SCRAPERS
from backend.services import settings as settings_service
from backend.services import stores as stores_service

PRODUCTS: dict = {}


def _store(store_id, name, slug, address, services=("Drive",)):
    postal_code, city = address.rsplit(", ", 1)[1].split(" ", 1)
    return StoreOption(
        id=store_id,
        name=name,
        address=address,
        url=f"https://www.coursesu.com/drive-{slug}",
        services=list(services),
        postal_code=postal_code,
        city=city,
    )


STORES = [
    _store("11111", "Super U Roujan", "superu-roujan", "Avenue de Pézenas, 34320 Roujan", ("Drive", "Livraison")),
    _store("22222", "Super U Pézenas", "superu-pezenas", "Route de Béziers, 34120 Pézenas"),
    _store(
        "33333",
        "U Express Montpellier Près d'Arènes",
        "uexpress-montpellier-pres-darenes",
        "12 avenue de Palavas, 34070 Montpellier",
        ("Drive", "Retrait"),
    ),
    _store("44444", "Hyper U Lattes", "hyperu-lattes", "Route de Pérols, 34970 Lattes", ("Drive", "Livraison")),
    _store(
        "55555",
        "Super U Clermont-l'Hérault",
        "superu-clermont-lherault",
        "Zone de la Salamane, 34800 Clermont-l'Hérault",
    ),
    _store("66666", "Super U Bédarieux", "superu-bedarieux", "Avenue Jean Jaurès, 34600 Bédarieux"),
    _store("77777", "Super U Sérignan", "superu-serignan", "Route de Valras, 34410 Sérignan"),
    _store("88888", "Super U Gignac", "superu-gignac", "Avenue du Mas Salat, 34150 Gignac"),
    _store("99999", "Marché U Saint-Chinian", "marcheu-saint-chinian", "Grand rue, 34360 Saint-Chinian"),
    _store("95524", "Super U Eysines", "superu-eysines", "Avenue du Médoc, 33320 Eysines"),
]

# geo.api.gouv.fr /communes (fields nom, codesPostaux, centre), SYNTHETIC excerpt
COMMUNES = [
    {"nom": name, "codesPostaux": [cp], "centre": {"type": "Point", "coordinates": [lon, lat]}}
    for name, cp, lat, lon in [
        ("Roujan", "34320", 43.505, 3.311),
        ("Pézenas", "34120", 43.459, 3.423),
        ("Montpellier", "34070", 43.591, 3.884),
        ("Lattes", "34970", 43.567, 3.900),
        ("Clermont-l'Hérault", "34800", 43.627, 3.432),
        ("Bédarieux", "34600", 43.616, 3.157),
        ("Sérignan", "34410", 43.281, 3.277),
        ("Gignac", "34150", 43.652, 3.551),
        ("Saint-Chinian", "34360", 43.422, 2.946),
        ("Eysines", "33320", 44.884, -0.650),
    ]
]

# Set by the tests (reset before each one)
DIRECTORY_ERROR: Exception | None = None
SITE_STORE: dict | None = None
_fake = None


async def fake_directory(department_name=None):
    await _fake._wait("coursesu")
    if DIRECTORY_ERROR is not None:
        raise DIRECTORY_ERROR
    return {"stores": [s.model_copy() for s in STORES], "method": "blocs"}


async def fake_commune_index(refresh=False):
    return stores_service.build_commune_index(COMMUNES)


async def fake_site_store():
    return dict(SITE_STORE) if SITE_STORE else {"link": None, "id": None, "name": None}


def reset_p4() -> None:
    global DIRECTORY_ERROR, SITE_STORE
    DIRECTORY_ERROR = None
    SITE_STORE = None
    SCRAPERS["coursesu"].site_opened_at = None
    db_path = Path(config.DB_PATH)
    if not db_path.exists():
        return
    with sqlite3.connect(db_path, timeout=5) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for table in ("scrape_log", "stores_cache"):
            if table in tables:
                db.execute(f"DELETE FROM {table}")  # noqa: S608 (fixed table names)
    db.close()


def install(fake, mp) -> None:
    global _fake
    _fake = fake
    mp.setattr(stores_service, "fetch_coursesu_directory", fake_directory)
    mp.setattr(stores_service, "commune_index", fake_commune_index)
    mp.setattr(stores_service, "fetch_site_store", fake_site_store)
    mp.setattr(settings_service, "AUTO_ONBOARDING", False)
    base_reset = fake.reset

    def reset() -> None:
        base_reset()
        reset_p4()

    mp.setattr(fake, "reset", reset)
