"""Fake E.Leclerc drives and site of the P8 E2E tests (and of the demo).

SYNTHETIC data: the drives, their numbers, addresses and coordinates are made
up around Montpellier and Béziers, except Le Crès Montpellier (number 093401
and host fd3 attested; its address is made up). Nothing is read on
leclercdrive.fr.

- ``backend.services.stores.fetch_leclerc_nearby``: ``LECLERC_STORES`` (the
  service ranks them by distance and keeps them in its cache), or raises
  ``NEARBY_ERROR`` when a test sets it;
- ``backend.services.stores.fetch_leclerc_site_store``: the tab of the
  E.Leclerc window after « Ouvrir le site », on ``SITE_STORE_LECLERC`` (the
  address of a drive) or on the portal when it is None;
- products of « lait » (trial search of the assistant) and of « farine » /
  « huile de tournesol » (tests/e2e/fake.py ``BASE_CATALOG``).
"""

from backend.models import StoreOption
from backend.scrapers import SCRAPERS
from backend.services import stores as stores_service

PRODUCTS = {
    "leclerc": [{"name": "Lait demi-écrémé", "brand": "Marque Repère", "price": 1.09, "quantity_label": "1 L"}],
}

HOST = "https://fd3-courses.leclercdrive.fr"


def _drive(no_pl, name, slug, address, lat, lon, no_pr=None, services=("Drive",)):
    postal_code, city = address.rsplit(", ", 1)[1].split(" ", 1)
    return StoreOption(
        id=no_pl,
        name=f"E.Leclerc Drive {name}",
        address=address,
        url=f"{HOST}/magasin-{no_pl}-{no_pr or no_pl}-{slug}",
        services=list(services),
        postal_code=postal_code,
        city=city,
        lat=lat,
        lon=lon,
    )


LECLERC_STORES = [
    _drive("093401", "Le Crès Montpellier", "Le-Cres-Montpellier", "Route de Nîmes, 34920 Le Crès", 43.648, 3.940),
    _drive(
        "093401",
        "Montpellier Comédie",
        "Montpellier-Comedie",
        "Place de la Comédie, 34000 Montpellier",
        43.6085,
        3.8797,
        no_pr="193402",
        services=("Retrait piéton",),
    ),
    _drive("190601", "Lattes", "Lattes", "Route de Pérols, 34970 Lattes", 43.567, 3.900),
    _drive(
        "190501",
        "Saint-Jean-de-Védas",
        "Saint-Jean-de-Vedas",
        "Rue de la Gare, 34430 Saint-Jean-de-Védas",
        43.577,
        3.826,
    ),
    _drive("191501", "Mauguio", "Mauguio", "Avenue de la Mer, 34130 Mauguio", 43.616, 4.008),
    _drive("191601", "Sète", "Sete", "Route de Montpellier, 34200 Sète", 43.403, 3.693),
    _drive(
        "191401",
        "Clermont-l'Hérault",
        "Clermont-lHerault",
        "Zone de la Salamane, 34800 Clermont-l'Hérault",
        43.627,
        3.432,
    ),
    _drive("191201", "Pézenas", "Pezenas", "Route de Béziers, 34120 Pézenas", 43.459, 3.423),
    _drive("191301", "Bédarieux", "Bedarieux", "Avenue Jean Jaurès, 34600 Bédarieux", 43.616, 3.157),
    _drive("191101", "Béziers Montimaran", "Beziers-Montimaran", "Rue de Montimaran, 34500 Béziers", 43.334, 3.237),
]

# Set by the tests (reset before each one)
NEARBY_ERROR: Exception | None = None
SITE_STORE_LECLERC: str | None = None
_fake = None


async def fake_nearby(location):
    await _fake._wait("leclerc")
    if NEARBY_ERROR is not None:
        raise NEARBY_ERROR
    return [s.model_copy() for s in LECLERC_STORES]


async def fake_site_store():
    return {"url": SITE_STORE_LECLERC or "https://www.leclercdrive.fr/", "html": "", "cookie": None}


def reset_p8() -> None:
    global NEARBY_ERROR, SITE_STORE_LECLERC
    NEARBY_ERROR = None
    SITE_STORE_LECLERC = None
    SCRAPERS["leclerc"].site_opened_at = None


def install(fake, mp) -> None:
    global _fake
    _fake = fake
    mp.setattr(stores_service, "fetch_leclerc_nearby", fake_nearby)
    mp.setattr(stores_service, "fetch_leclerc_site_store", fake_site_store)
    base_reset = fake.reset

    def reset() -> None:
        base_reset()
        reset_p8()

    mp.setattr(fake, "reset", reset)
