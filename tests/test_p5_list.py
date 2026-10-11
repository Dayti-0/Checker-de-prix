"""The shopping list (P5): pasted lists (B67), aisles (B65), export (B69), templates and usual items
(B68), version (B70), transactions, migrations and backups."""

import asyncio
import json
import sqlite3

import pytest

from backend import config, database
from backend.errors import AppError
from backend.models import (
    BasketComparison,
    BasketLine,
    CheckUpdate,
    ListItem,
    ListItemCreate,
    ListItemUpdate,
    Pick,
    Plan,
    PlanStore,
    Product,
    StoreBasket,
)
from backend.repos import shopping_list as repo
from backend.services import hooks, matching, shopping_list
from backend.services.categories import CATEGORIES, categorize
from backend.services.shopping_list import assignment_of, format_list, parse_list_text
from tests.conftest import run

# --- B67: pasted lists ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2 lait demi-écrémé", [("lait demi-écrémé", 2, None)]),
        ("farine 1kg", [("farine", 1, "1 kg")]),
        ("- beurre", [("beurre", 1, None)]),
        ("• œufs x12", [("œufs", 1, "12")]),
        ("3x yaourts", [("yaourts", 3, None)]),
        ("12 oeufs", [("oeufs", 1, "12")]),
        ("[ ] pâtes", [("pâtes", 1, None)]),
        ("[x] riz basmati", [("riz basmati", 1, None)]),
        ("1. café moulu", [("café moulu", 1, None)]),
        ("sucre (2)", [("sucre", 2, None)]),
        ("eau 6x1,5L", [("eau", 1, "6 x 1,5 L")]),
        ("500 g de beurre doux", [("beurre doux", 1, "500 g")]),
        ("tomates x 3", [("tomates", 3, None)]),
        ("thé : 2", [("thé", 2, None)]),
        ("pommes, poires ; bananes", [("pommes", 1, None), ("poires", 1, None), ("bananes", 1, None)]),
        ("lait + pain", [("lait", 1, None), ("pain", 1, None)]),
        # Packaging: so many packs of the product
        ("2 paquets de pâtes", [("pâtes", 2, None)]),
        ("3 boîtes de thon", [("thon", 3, None)]),
        ("chocolat noir 2 tablettes", [("chocolat noir", 2, None)]),
        ("paquet de riz", [("riz", 1, None)]),
        ("pack de 6 bières", [("bières", 1, "6")]),
        # Pieces: a target counted by the piece
        ("10 rouleaux de papier toilette", [("papier toilette", 1, "10")]),
        ("jambon 4 tranches", [("jambon", 1, "4")]),
        ("Oeufs (12)", [("Oeufs", 1, "12")]),
        # Unit names and fractions, a size alone after a comma
        ("2 kilos de pommes", [("pommes", 1, "2 kg")]),
        ("500 grammes de beurre", [("beurre", 1, "500 g")]),
        ("lessive 2,5 litres", [("lessive", 1, "2,5 L")]),
        ("1/2 litre de crème", [("crème", 1, "0,5 L")]),
        ("pâtes, 500g", [("pâtes", 1, "500 g")]),
        ("500g, pâtes", [("pâtes", 1, None)]),
        ("  \n- \n•\n123\n", []),
    ],
)
def test_parse_list_text_formats(text, expected):
    assert [(p.query, p.quantity, p.target) for p in parse_list_text(text)] == expected


def test_parse_merges_the_same_item_and_guesses_the_aisle():
    lines = parse_list_text("Farine\n2 farine\nlessive\n- FARINE 1 kg")
    assert [(p.query, p.quantity, p.target) for p in lines] == [("Farine", 4, "1 kg"), ("lessive", 1, None)]
    assert [p.category for p in lines] == ["Épicerie sucrée", "Entretien"]


def test_parse_keeps_at_most_the_size_of_a_list():
    lines = parse_list_text("\n".join(f"article {i}" for i in range(400)))
    assert len(lines) == shopping_list.MAX_ITEMS


# --- B65: aisles -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "aisle"),
    [
        ("lessive", "Entretien"),
        ("Lessive liquide 2L", "Entretien"),
        ("eau de javel", "Entretien"),
        ("eau", "Boissons"),
        ("lait demi-écrémé", "Crèmerie"),
        ("chocolat au lait", "Épicerie sucrée"),
        ("lait de coco", "Épicerie salée"),
        ("pommes de terre", "Fruits et légumes"),
        ("pommes", "Fruits et légumes"),
        ("pizza surgelée", "Surgelés"),
        ("croquettes chat", "Animaux"),
        ("couches", "Bébé"),
        ("dentifrice", "Hygiène et beauté"),
        ("baguette", "Boulangerie"),
        ("jambon", "Charcuterie et traiteur"),
        ("steak haché", "Viandes et poissons"),
        ("café", "Petit-déjeuner"),
        ("objet inconnu", "Autres"),
    ],
)
def test_categorize(query, aisle):
    assert categorize(query) == aisle
    assert aisle in CATEGORIES


# --- B69: export ---------------------------------------------------------------------------


def list_items():
    return [
        ListItem(id=1, query="farine", quantity=2, category="Épicerie sucrée"),
        ListItem(id=2, query="lessive", category="Entretien", note="la grande"),
        ListItem(id=3, query="lait", target="6 L", category="Crèmerie", checked=True),
    ]


def comparison():
    def line(item_id, query, name=None, total=None):
        line = BasketLine(item_id=item_id, query=query, quantity=1, status="found" if name else "not_found")
        if name:
            line.product = Product(store="x", name=name, price=total)
            line.line_total = total
        return line

    aldi = StoreBasket(
        store="aldi",
        label="Aldi",
        lines=[line(1, "farine", "Farine T55", 1.58), line(2, "lessive"), line(3, "lait", "Lait 6x1L", 5.4)],
    )
    lidl = StoreBasket(
        store="lidl",
        label="Lidl",
        lines=[line(1, "farine", "Farine T45", 1.5), line(2, "lessive", "Lessive 2L", 4.99), line(3, "lait")],
    )
    plan = Plan(
        kind="pair",
        stores=[
            PlanStore(store="lidl", label="Lidl", item_ids=[1, 2], total=6.49),
            PlanStore(store="aldi", label="Aldi", item_ids=[3], total=5.4),
        ],
    )
    return BasketComparison(stores=[aldi, lidl], plans=[plan])


def test_export_text_by_aisle():
    text = format_list(list_items())
    assert text == (
        "Ma liste de courses (3 articles)\n"
        "\n"
        "Crèmerie :\n"
        "[x] lait (6 L)\n"
        "Épicerie sucrée :\n"
        "- farine x2\n"
        "Entretien :\n"
        "- lessive (la grande)\n"
    )


def test_export_text_by_retailer_of_a_plan():
    assignment, labels = assignment_of(comparison(), plan=0)
    assert labels == {"lidl": "Lidl", "aldi": "Aldi"}
    text = format_list(list_items(), "txt", assignment, labels)
    assert text == (
        "Ma liste de courses (3 articles)\n"
        "\n"
        "LIDL\n"
        "Épicerie sucrée :\n"
        "- farine x2 : Farine T45, 1,50 €\n"
        "Entretien :\n"
        "- lessive : Lessive 2L, 4,99 € (la grande)\n"
        "Total Lidl : 6,49 €\n"
        "\n"
        "ALDI\n"
        "Crèmerie :\n"
        "[x] lait (6 L) : Lait 6x1L, 5,40 €\n"
        "Total Aldi : 5,40 €\n"
    )


def test_export_one_retailer_and_unknown_plans():
    assignment, labels = assignment_of(comparison(), store="aldi")
    assert assignment[2] == {"store": "aldi", "product": None, "price": None}
    text = format_list(list_items(), "txt", assignment, labels)
    assert "ALDI" in text and "- lessive (la grande)" in text and "Total Aldi : 6,98 €" in text
    assert assignment_of(comparison(), plan=5) == ({}, {})
    assert assignment_of(comparison(), store="carrefour") == ({}, {})
    assert assignment_of(None, plan=0) == ({}, {})


def test_export_csv():
    items = list_items()
    items[1].note = "=1+1"
    assignment, labels = assignment_of(comparison(), plan=0)
    rows = format_list(items, "csv", assignment, labels).splitlines()
    assert rows[0] == "Enseigne;Rayon;Article;Quantité;Objectif;Produit;Prix;Note;Coché"
    assert rows[1] == "Lidl;Épicerie sucrée;farine;2;;Farine T45;1,50;;non"
    assert rows[2] == "Lidl;Entretien;lessive;1;;Lessive 2L;4,99;'=1+1;non"
    assert rows[3] == "Aldi;Crèmerie;lait;1;6 L;Lait 6x1L;5,40;;oui"


def test_export_of_an_empty_list():
    assert format_list([]) == "Ma liste de courses (0 article)\n"
    assert format_list([ListItem(id=1, query="sel")]).startswith("Ma liste de courses (1 article)\n")


# --- Writes: one line per query, transactions, version -----------------------------------


def test_list_key_is_the_key_of_the_search():
    for query in ("Farine", "farine ", "Crème fraîche", "Œufs x12", "huile d'olive", "Pâtes"):
        assert repo.list_key(query) == matching.query_key(query)


def test_simultaneous_additions_of_the_same_query_give_one_line():
    async def scenario():
        await asyncio.gather(
            shopping_list.add_item(ListItemCreate(query="Farine")),
            shopping_list.add_item(ListItemCreate(query="farine")),
            shopping_list.add_item(ListItemCreate(query=" FARINE ", quantity=2)),
        )
        return await shopping_list.get_list()

    items = run(scenario())
    assert len(items) == 1 and items[0].quantity == 4 and items[0].key == "farine"


def test_a_failed_addition_writes_nothing(monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("disque plein")

    async def scenario():
        await shopping_list.add_item(ListItemCreate(query="sel"))
        before = await shopping_list.get_version()
        monkeypatch.setattr(repo, "record_added", broken)
        with pytest.raises(RuntimeError):
            await shopping_list.add_item(ListItemCreate(query="poivre"))
        with pytest.raises(RuntimeError):
            await shopping_list.bulk_add([ListItemCreate(query="riz"), ListItemCreate(query="pâtes")])
        db = await database.get_db()
        return before, await shopping_list.get_version(), await shopping_list.get_list(), db.in_transaction

    before, after, items, open_transaction = run(scenario())
    assert [i.query for i in items] == ["sel"]
    assert after == before and not open_transaction


def test_too_long_pasted_list_writes_nothing(monkeypatch):
    monkeypatch.setattr(shopping_list, "MAX_ITEMS", 3)

    async def scenario():
        await shopping_list.add_item(ListItemCreate(query="sel"))
        with pytest.raises(AppError) as error:
            await shopping_list.bulk_add([ListItemCreate(query=q) for q in ("riz", "pâtes", "sucre")])
        return error.value, await shopping_list.get_list()

    error, items = run(scenario())
    assert error.code == "list_full" and [i.query for i in items] == ["sel"]


def test_version_increments_with_each_write():
    async def scenario():
        versions = [await shopping_list.get_version()]
        item = await shopping_list.add_item(ListItemCreate(query="sel"))
        versions.append(await shopping_list.get_version())
        await shopping_list.update_item(item.id, ListItemUpdate(quantity=2))
        versions.append(await shopping_list.get_version())
        await shopping_list.apply_checks([CheckUpdate(id=item.id, checked=True)])
        versions.append(await shopping_list.get_version())
        await shopping_list.finish("uncheck")
        versions.append(await shopping_list.get_version())
        await shopping_list.clear()
        versions.append(await shopping_list.get_version())
        return versions

    versions = run(scenario())
    assert versions == sorted(versions) and len(set(versions)) == len(versions)


def test_renaming_onto_another_line_is_refused():
    async def scenario():
        await shopping_list.add_item(ListItemCreate(query="sel"))
        pepper = await shopping_list.add_item(ListItemCreate(query="poivre"))
        with pytest.raises(AppError) as error:
            await shopping_list.update_item(pepper.id, ListItemUpdate(query="Sel"))
        renamed = await shopping_list.update_item(pepper.id, ListItemUpdate(query="poivre noir"))
        return error.value, renamed

    error, renamed = run(scenario())
    assert error.status_code == 409
    assert (renamed.query, renamed.key) == ("poivre noir", "poivre noir")


def test_latest_tick_wins():
    async def scenario():
        item = await shopping_list.add_item(ListItemCreate(query="sel"))
        await shopping_list.update_item(item.id, ListItemUpdate(checked=True, checked_at=2000.0))
        # A tick made earlier offline arrives later: ignored
        await shopping_list.apply_checks([CheckUpdate(id=item.id, checked=False, checked_at=1000.0)])
        kept = await shopping_list.get_item(item.id)
        await shopping_list.apply_checks([CheckUpdate(id=item.id, checked=False, checked_at=3000.0)])
        return kept, await shopping_list.get_item(item.id)

    kept, latest = run(scenario())
    assert (kept.checked, kept.checked_at) == (True, 2000.0)
    assert (latest.checked, latest.checked_at) == (False, 3000.0)


def test_adding_a_chosen_product_removes_pas_disponible_ici():
    async def scenario():
        item = await shopping_list.add_item(ListItemCreate(query="farine"))
        await shopping_list.update_item(item.id, ListItemUpdate(exclude_store="lidl"))
        product = Product(store="lidl", name="Farine T45", price=0.75, product_url="https://lidl.example/f")
        return await shopping_list.add_item(ListItemCreate(query="Farine", product=product))

    item = run(scenario())
    assert item.excluded == [] and item.picks["lidl"].name == "Farine T45"
    assert item.picks["lidl"].verified is False  # never read by PrixMalin: « prix non vérifié »
    assert item.quantity == 1  # choosing a product does not buy one more


def test_manual_price_gets_its_price_per_unit():
    async def scenario():
        item = await shopping_list.add_item(ListItemCreate(query="lait"))
        manual = {"store": "intermarche", "name": "Lait Pâturages", "price": 5.4, "quantity_label": "6 x 1 L"}
        return await shopping_list.update_item(item.id, ListItemUpdate.model_validate({"manual_price": manual}))

    pick = run(scenario()).picks["intermarche"]
    assert (pick.source, pick.unit_price, pick.unit) == ("manual", 0.9, "L")


# --- B68: templates and usual items -------------------------------------------------------


def test_template_round_trip_keeps_quantities_choices_and_targets():
    pick = Pick(store="lidl", name="Farine T45", price=0.75, product_url="https://lidl.example/f", picked_at=1.0)

    async def scenario():
        flour = await shopping_list.add_item(ListItemCreate(query="farine", quantity=2, target="2 kg"))
        await repo.update_fields(flour.id, picks={"lidl": pick.model_dump()}, excluded=["aldi"], compare=False)
        await shopping_list.add_item(ListItemCreate(query="lessive", category="Hygiène et beauté", note="2 L"))
        before = await shopping_list.get_list()
        template = await shopping_list.save_template("Courses de la semaine")
        await shopping_list.clear()
        after = await shopping_list.apply_template(template.id, "replace")
        return before, after

    before, after = run(scenario())
    fields = {"query", "quantity", "picks", "target", "note", "excluded", "compare", "category", "category_set"}
    assert [i.model_dump(include=fields) for i in after] == [i.model_dump(include=fields) for i in before]
    assert after[1].category_set and after[1].category == "Hygiène et beauté"


def test_usual_items_are_proposed_after_two_additions():
    async def scenario():
        for _ in range(2):
            item = await shopping_list.add_item(ListItemCreate(query="café"))
            await shopping_list.delete_item(item.id)
        once = await shopping_list.add_item(ListItemCreate(query="thé"))
        await shopping_list.delete_item(once.id)
        return await shopping_list.usual_items()

    assert [(u.query, u.count) for u in run(scenario())] == [("café", 2)]


# --- Backups ----------------------------------------------------------------------------------


def test_backup_providers_round_trip():
    assert {"shopping_list", "list_templates", "list_history"} <= set(hooks.backups())
    providers = hooks.backups()

    async def scenario():
        flour = await shopping_list.add_item(ListItemCreate(query="farine", quantity=2, target="1 kg"))
        await shopping_list.update_item(flour.id, ListItemUpdate(category="Boulangerie", note="T45"))
        await shopping_list.save_template("Semaine")
        saved = {name: await export() for name, (export, _) in providers.items() if name != "settings"}
        json.dumps(saved)  # a backup is JSON
        await shopping_list.clear()
        await shopping_list.delete_template((await shopping_list.list_templates())[0].id)
        await repo.replace_history([])
        for name, data in saved.items():
            await providers[name][1](data)
        return saved, await shopping_list.get_list(), await shopping_list.list_templates(), await repo.history_rows()

    saved, items, templates, history = run(scenario())
    assert [(i.query, i.quantity, i.target, i.category, i.category_set, i.note) for i in items] == [
        ("farine", 2, "1 kg", "Boulangerie", True, "T45")
    ]
    assert [(t.name, t.item_count) for t in templates] == [("Semaine", 1)]
    assert [(h["query"], h["count"]) for h in history] == [("farine", 1)]


# --- Migrations ---------------------------------------------------------------------------------

OLD_SCHEMA = """
CREATE TABLE search_cache (cache_key TEXT PRIMARY KEY, results_json TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE shopping_list (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    picks_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
"""


def test_migration_merges_duplicate_lines_of_version_2():
    aldi = {"store": "aldi", "name": "Farine T55", "price": 0.79}
    lidl = {"store": "lidl", "name": "Farine T45", "price": 0.75}
    with sqlite3.connect(config.DB_PATH) as db:
        db.executescript(OLD_SCHEMA)
        for query, quantity, picks in (
            ("Farine", 1, {"aldi": aldi}),
            ("sucre", 1, {}),
            ("farine ", 2, {"lidl": lidl}),
            ("FARINE", 98, "pas du json"),
        ):
            db.execute(
                "INSERT INTO shopping_list (query, quantity, picks_json, created_at) VALUES (?, ?, ?, 1.0)",
                (query, quantity, json.dumps(picks) if isinstance(picks, dict) else picks),
            )
    db.close()

    async def scenario():
        items = await shopping_list.get_list()
        with pytest.raises(sqlite3.IntegrityError):
            db = await database.get_db()
            await db.execute("INSERT INTO shopping_list (query, query_key, created_at) VALUES ('farine', 'farine', 1)")
        return items, await shopping_list.usual_items(), await shopping_list.get_version()

    items, usual, version = run(scenario())
    assert [(i.query, i.quantity, sorted(i.picks)) for i in items] == [
        ("Farine", 99, ["aldi", "lidl"]),
        ("sucre", 1, []),
    ]
    assert all(i.compare and not i.checked and i.excluded == [] for i in items)
    assert usual == [] and version == 0
