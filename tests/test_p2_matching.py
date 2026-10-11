"""Relevance of the products (B35): the product searched is the head of the name."""

import pytest

from backend.models import Product
from backend.services import matching
from backend.services.matching import RELEVANT_SCORE, Matcher, match_score, query_quantity, relevance
from backend.services.products import prepare_products

SUNFLOWER_QUERIES = ["huile de tournesols", "huile de tournesol", "huile tournesol", "Huile de Tournesol"]

SUNFLOWER_OILS = [
    ("Huile de tournesol Lesieur 1L", None),
    ("Lesieur Huile de tournesol", None),
    ("Lesieur Huile de tournesol", "Lesieur"),
    ("Huile de tournesol", "LESIEUR"),
    ("Huile de tournesol bio", None),
    ("Huile de tournesol CARREFOUR CLASSIC'", None),
    ("HUILE DE TOURNESOL", None),
]

# Contain the words of the query, but are another product
NOT_SUNFLOWER_OILS = [
    "Thon à l'huile de tournesol",
    "Sardines à l'huile de tournesol",
    "Mayonnaise à l'huile de tournesol",
    "Chips à l'huile de tournesol",
    "Thon albacore à l'huile de tournesol PETIT NAVIRE",
    "Thon huile de tournesol",
    "Maquereaux à l'huile de tournesol",
]


@pytest.mark.parametrize("query", SUNFLOWER_QUERIES)
@pytest.mark.parametrize("name, brand", SUNFLOWER_OILS)
def test_sunflower_oil_is_relevant(query, name, brand):
    match = Matcher(query).match(name, brand)
    assert match.relevant, match
    assert match.reason is None
    assert match.score >= RELEVANT_SCORE


@pytest.mark.parametrize("query", SUNFLOWER_QUERIES)
@pytest.mark.parametrize("name", NOT_SUNFLOWER_OILS)
def test_food_in_sunflower_oil_is_only_close(query, name):
    match = Matcher(query).match(name)
    assert not match.relevant
    assert 0 < match.relevance < 1  # at most in « Produits proches »
    assert match.score < RELEVANT_SCORE
    assert match.reason in ("complement", "other_product")


@pytest.mark.parametrize("query", SUNFLOWER_QUERIES)
def test_tuna_au_naturel_is_unrelated(query):
    match = Matcher(query).match("Thon au naturel")
    assert (match.relevance, match.score, match.reason) == (0.0, 0.0, "unrelated")


@pytest.mark.parametrize("query", ["thon huile de tournesol", "thon à l'huile de tournesol", "Thon huile tournesol"])
def test_tuna_query_keeps_tuna_in_sunflower_oil(query):
    assert Matcher(query).match("Thon à l'huile de tournesol").relevant
    assert Matcher(query).match("Thon albacore à l'huile de tournesol", "Petit Navire").relevant
    assert not Matcher(query).match("Huile de tournesol").relevant  # no tuna
    assert not Matcher(query).match("Thon à l'huile d'olive").relevant  # no sunflower


@pytest.mark.parametrize(
    "query, name, brand, expected",
    [
        # Backlog B35
        ("pâtes", "Pâté de campagne", None, False),
        ("pates", "Pâté de campagne", None, False),
        ("sucre", "Lait concentré sucré", None, False),
        ("sucre", "Bonbons sans sucre", None, False),
        ("eau", "Eau de javel", None, False),
        ("lait", "Chocolat au lait", None, False),
        ("eau 1,5 l", "Eau minérale 6x1,5L", None, True),
        ("huile tournesol 1l", "Huile de tournesol", None, True),
        ("farine", "Farine de blé T45", None, True),
        # User feedback
        ("farine", "Gâteau à la farine de riz", None, False),
        ("farine", "Farine de riz", None, True),
        ("lait", "Lait demi-écrémé", "Lactel", True),
        ("eau", "Eau minérale naturelle", "Evian", True),
        ("eau", "Cristaline Eau de source", None, True),
        ("pâtes", "Pâtes coquillettes", "Panzani", True),
        ("pâtes", "Pâte à tartiner", None, False),
        ("sucre", "Sucre en poudre", None, True),
        ("sucre", "Sucre de canne", None, True),
        # Other realistic French cases
        ("jus d'orange", "Yaourt à l'orange", None, False),
        ("jus d'orange", "Pur jus d'orange", "Tropicana", True),
        ("jus d'orange", "Jus d'orange sans pulpe", None, True),
        ("orange", "Jus d'orange", None, False),
        ("beurre", "Biscuits au beurre", None, False),
        ("beurre", "Beurre doux", "Président", True),
        ("beurre", "Président Beurre doux", None, True),
        ("beurre", "Beurre de cacahuète", None, False),
        ("riz", "Riz basmati Taureau Ailé", None, True),
        ("riz", "Galettes de riz", None, False),
        ("riz", "Vinaigre de riz", None, False),
        ("café", "Glace au café", None, False),
        ("café", "Café moulu", "Carte Noire", True),
        ("café", "Capsules de café", None, True),
        # « Sauce tomate » is a sauce, not tomatoes: only close for « tomate »
        ("tomate", "Sauce tomate", None, False),
        ("tomates", "Tomates pelées", None, True),
        ("tomate", "Tomates cerises", None, True),
        ("sauce tomate", "Sauce tomate basilic", None, True),
        ("sauce tomate", "Pâtes sauce tomate", None, False),
        ("chocolat", "Chocolat au lait", None, True),
        ("chocolat au lait", "Chocolat au lait", "Milka", True),
        ("chocolat", "Biscuits nappés chocolat", None, False),
        ("chocolat", "Pâte à tartiner au chocolat", None, False),
        ("yaourt fraise", "Yaourt à la fraise", None, True),
        ("fraise", "Yaourt à la fraise", None, False),
        ("fraises", "Fraises gariguette", None, True),
        ("thon", "Thon à l'huile de tournesol", None, True),
        ("thon", "Miettes de thon", None, True),
        ("thon", "Salade de thon", None, False),
        ("huile", "Thon à l'huile", None, False),
        ("huile d'olive", "Sardines à l'huile d'olive", None, False),
        ("huile d'olive", "Huile d'olive vierge extra", "Puget", True),
        ("olive", "Huile d'olive", None, False),
        ("sel", "Beurre demi-sel", None, False),
        ("sel", "Sel fin de Guérande", None, True),
        ("vin", "Vinaigre de vin", None, False),
        ("vinaigre", "Cornichons au vinaigre", None, False),
        ("vinaigre", "Vinaigre de vin rouge", None, True),
        ("moutarde", "Mayonnaise à la moutarde", None, False),
        ("jambon", "Coquillettes au jambon", None, False),
        ("jambon", "Jambon blanc", "Herta", True),
        ("pomme", "Pommes de terre", None, False),
        ("pommes de terre", "Pommes de terre", None, True),
        ("petits pois", "Petits pois extra-fins", "Bonduelle", True),
        ("lait", "Laitue iceberg", None, False),
        ("lait", "Lait de coco", None, False),
        ("lait de coco", "Lait de coco", None, True),
        ("oeufs", "Œufs frais x12", None, True),
        ("oeufs", "Pâtes aux œufs", None, False),
        ("vanille", "Sucre vanillé", None, False),
        ("pain", "Pain de mie", None, True),
        ("pain", "Pain au chocolat", None, False),
        # A brand or a word that is not a food can be anywhere
        ("nutella", "Pâte à tartiner noisettes cacao", "Nutella", True),
        ("petit navire", "Thon albacore à l'huile d'olive PETIT NAVIRE", None, True),
        ("tournesol", "Huile de tournesol", None, True),
        # « sans » and exclusions
        ("lait sans lactose", "Lait demi-écrémé sans lactose", None, True),
        ("lait sans lactose", "Lait demi-écrémé", None, False),
        ("eau -javel", "Eau de javel", None, False),
        ("eau -gazeuse", "Eau minérale naturelle", None, True),
        ("eau -gazeuse", "Eau gazeuse", None, False),
    ],
)
def test_relevance_cases(query, name, brand, expected):
    match = Matcher(query).match(name, brand)
    assert match.relevant is expected, match
    assert (match.score >= RELEVANT_SCORE) is expected
    if expected:
        assert match.relevance == 1.0 and match.reason is None
    else:
        assert match.relevance < 1 and match.reason in matching.REASONS


def test_plurals_accents_and_case_are_the_same_query():
    names = ["Huile de tournesol", "Huiles de tournesol", "HUILE DE TOURNESOL", "huile tournesol"]
    for query in SUNFLOWER_QUERIES:
        assert {Matcher(query).match(name).relevant for name in names} == {True}


@pytest.mark.parametrize(
    "name, reason",
    [
        ("Thon à l'huile de tournesol", "complement"),
        ("Thon huile de tournesol", "other_product"),
        ("Huile d'olive", "missing"),
        ("Thon au naturel", "unrelated"),
        ("Huile de tournesol pour massage", "compound"),
    ],
)
def test_reasons(name, reason):
    assert Matcher("huile de tournesol").match(name).reason == reason


def test_scores_rank_the_head_first():
    scores = {
        name: match_score(name, "huile de tournesol") for name in ("Huile de tournesol", "Lesieur Huile de tournesol")
    }
    assert scores["Huile de tournesol"] == 1.0
    assert RELEVANT_SCORE <= scores["Lesieur Huile de tournesol"] < 1.0
    assert match_score("Huile d'olive", "huile de tournesol") > match_score(
        "Thon à l'huile de tournesol", "huile de tournesol"
    )
    assert (
        0 <= match_score("Thon au naturel", "huile de tournesol") < match_score("Huile d'olive", "huile de tournesol")
    )


def test_brand_given_separately_counts():
    assert match_score("Pâte à tartiner", "nutella", brand="Nutella") >= RELEVANT_SCORE
    assert match_score("Pâte à tartiner", "nutella") == 0.0
    assert matching.is_relevant("Beurre doux", "président", brand="Président")


def test_quantities_of_the_query():
    assert query_quantity("eau 1,5 l") == (1.5, "L")
    assert query_quantity("eau 6x1,5L") == (9.0, "L")
    assert query_quantity("farine 1kg") == (1.0, "kg")
    assert query_quantity("farine") is None
    assert matching.keywords("eau 1,5 l") == ["eau"]
    # Another size is still the product, a little lower
    assert match_score("Eau minérale 50cl", "eau 1,5 l") < match_score("Eau minérale 1,5L", "eau 1,5 l")
    assert relevance("Eau minérale 50cl", "eau 1,5 l") == 1.0


def test_no_keyword_matches_everything():
    assert relevance("N'importe quoi", "de la") == 1.0
    assert Matcher("").match("Farine").relevant


def test_prepare_products_keeps_close_products_out_of_the_main_list():
    products = [
        Product(store="aldi", name="Thon à l'huile de tournesol", price=1.2, product_url="https://a/1"),
        Product(store="aldi", name="Huile de tournesol 1L", price=1.99, product_url="https://a/2"),
        Product(store="aldi", name="Thon au naturel", price=0.9, product_url="https://a/3"),
        Product(store="aldi", name="Huile de tournesol", brand="Lesieur", price=2.5, product_url="https://a/4"),
    ]
    prepared = prepare_products(products, "huile de tournesols")
    assert [(p.name, p.relevance) for p in prepared] == [
        ("Huile de tournesol 1L", 1.0),
        ("Huile de tournesol", 1.0),
        ("Thon à l'huile de tournesol", 0.99),
        ("Thon au naturel", 0.0),
    ]
    assert [p.match_reason for p in prepared] == [None, None, "complement", "unrelated"]
    assert all(p.match_score >= RELEVANT_SCORE for p in prepared[:2])
    assert all(p.match_score < RELEVANT_SCORE for p in prepared[2:])


# Real names that must stay in the main list (the filter must not hide them)
@pytest.mark.parametrize(
    "query, name",
    [
        ("poulet", "Escalopes de poulet"),
        ("poulet", "Filet de poulet"),
        ("thon", "Steak de thon"),
        ("boeuf", "Steak haché pur bœuf"),
        ("café", "Café en grains"),
        ("café", "Capsules compatibles Nespresso café"),
        ("beurre", "Plaquette de beurre doux"),
        ("sucre", "Morceaux de sucre"),
        ("oeufs", "6 oeufs de poules élevées en plein air"),
        ("jambon", "Tranches de jambon blanc"),
        ("saumon", "Pavé de saumon"),
        ("chocolat", "Tablette de chocolat noir"),
        ("sel", "Gros sel de mer"),
        ("jus d'orange", "100% pur jus d'orange"),
        ("huile de tournesol", "Huile de tournesol LESIEUR la bouteille de 1L"),
        ("huile de tournesol", "Huile pour friture tournesol"),
        ("pâte à crêpes", "Pâte à crêpes"),
        ("lait", "Lait UHT 1/2 écrémé"),
        ("eau", "Eau minérale naturelle plate"),
        ("pâtes", "Pâtes Spaghetti n°5"),
        ("riz", "Riz long grain"),
        ("tomates", "Tomates grappe"),
        ("crème fraîche", "Crème fraîche épaisse 30% MG"),
    ],
)
def test_real_names_stay_relevant(query, name):
    assert Matcher(query).match(name).relevant
