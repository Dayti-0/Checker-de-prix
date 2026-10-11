"""Supermarket aisles (« rayons ») of the shopping list (area of P5).

``categorize(query)`` guesses the aisle of a list item from its words. It is a
pure function: a small French dictionary, phrases first (« eau de javel »),
then a word that decides on its own (« surgelé »), then the first known word
of the query (the head noun: « chocolat au lait » is chocolate, not milk).
"""

from backend.services.matching import normalize

OTHER = "Autres"

# Display order of the aisles (the order of a walk in a typical supermarket)
CATEGORIES = (
    "Fruits et légumes",
    "Boulangerie",
    "Crèmerie",
    "Viandes et poissons",
    "Charcuterie et traiteur",
    "Épicerie salée",
    "Épicerie sucrée",
    "Petit-déjeuner",
    "Boissons",
    "Surgelés",
    "Hygiène et beauté",
    "Entretien",
    "Bébé",
    "Animaux",
    OTHER,
)

# Phrases checked before single words (normalised: no accents, lower case)
_PHRASES = {
    "eau de javel": "Entretien",
    "liquide vaisselle": "Entretien",
    "papier toilette": "Entretien",
    "papier hygienique": "Entretien",
    "sac poubelle": "Entretien",
    "sacs poubelle": "Entretien",
    "essuie tout": "Entretien",
    "pastilles lave vaisselle": "Entretien",
    "lave vaisselle": "Entretien",
    "gel douche": "Hygiène et beauté",
    "eau micellaire": "Hygiène et beauté",
    "brosse a dents": "Hygiène et beauté",
    "lait infantile": "Bébé",
    "lait de croissance": "Bébé",
    "petits pots": "Bébé",
    "petit pot": "Bébé",
    "lait de coco": "Épicerie salée",
    "lait corps": "Hygiène et beauté",
    "pate a tartiner": "Épicerie sucrée",
    "pates a tartiner": "Épicerie sucrée",
    "pomme de terre": "Fruits et légumes",
    "pommes de terre": "Fruits et légumes",
    "petits pois": "Épicerie salée",
    "pain de mie": "Boulangerie",
    "creme fraiche": "Crèmerie",
    "fromage blanc": "Crèmerie",
    "jus de fruits": "Boissons",
    "corn flakes": "Petit-déjeuner",
    "petit suisse": "Crèmerie",
    "petits suisses": "Crèmerie",
    "creme dessert": "Crèmerie",
}

# Words that decide the aisle wherever they are (« frites surgelées »)
_STRONG = {
    "surgele": "Surgelés",
    "surgelee": "Surgelés",
    "surgeles": "Surgelés",
    "surgelees": "Surgelés",
    "glace": "Surgelés",
    "glaces": "Surgelés",
    "bebe": "Bébé",
    "chat": "Animaux",
    "chats": "Animaux",
    "chien": "Animaux",
    "chiens": "Animaux",
}

_WORDS = {
    "Fruits et légumes": (
        "pomme banane orange citron clementine mandarine poire raisin fraise framboise kiwi ananas mangue melon "
        "pasteque peche abricot prune cerise avocat tomate salade laitue carotte courgette aubergine poivron "
        "concombre oignon echalote ail poireau chou brocoli epinard haricot champignon radis navet patate "
        "betterave celeri persil basilic coriandre ciboulette fruit legume"
    ),
    "Boulangerie": "pain baguette brioche croissant viennoiserie biscotte tortilla wrap pita",
    "Crèmerie": (
        "lait beurre yaourt yaourts yoghourt creme fromage emmental comte camembert mozzarella parmesan raclette "
        "chevre feta oeuf oeufs margarine skyr lacte kefir"
    ),
    "Viandes et poissons": (
        "viande boeuf steak hache poulet dinde porc veau agneau canard escalope cote roti filet poisson saumon "
        "cabillaud colin merlu crevette crevettes moule moules sardine maquereau"
    ),
    "Charcuterie et traiteur": (
        "jambon saucisson saucisse saucisses lardons bacon chorizo pate rillettes terrine knacki quiche pizza "
        "taboule surimi"
    ),
    "Épicerie salée": (
        "pates spaghetti tagliatelle macaroni coquillettes penne riz semoule quinoa lentilles pois chiches "
        "huile vinaigre sel poivre epice epices moutarde mayonnaise ketchup sauce conserve soupe bouillon "
        "olive olives cornichon chips crackers aperitif cacahuete thon"
    ),
    "Épicerie sucrée": (
        "sucre farine levure chocolat cacao biscuits gateau gateaux confiture miel compote bonbon bonbons "
        "caramel vanille madeleine cookies biscuit"
    ),
    "Petit-déjeuner": "cafe the tisane cereales muesli chicoree capsule capsules dosette dosettes",
    "Boissons": "eau jus soda cola limonade biere vin cidre champagne sirop boisson",
    "Hygiène et beauté": (
        "shampoing shampooing savon dentifrice deodorant rasoir coton mouchoir mouchoirs serviette protege "
        "tampon creme solaire lingette lingettes gel"
    ),
    "Entretien": (
        "lessive adoucissant javel eponge eponges detergent nettoyant vaisselle sopalin aluminium film "
        "poubelle desodorisant detartrant"
    ),
    "Bébé": "couche couches biberon",
    "Animaux": "croquette croquettes litiere patee",
}

_WORD_INDEX: dict[str, str] = {}
for _category, _words in _WORDS.items():
    for _word in _words.split():
        _WORD_INDEX.setdefault(_word, _category)


def _tokens(text: str) -> list[str]:
    return "".join(c if c.isalnum() else " " for c in normalize(text)).split()


def _singular(token: str) -> str:
    return token[:-1] if len(token) > 3 and token[-1] in "sx" else token


def categorize(query: str) -> str:
    """Aisle of a list item: ``categorize("lessive")`` → ``"Entretien"``."""
    tokens = _tokens(query or "")
    joined = " ".join(tokens)
    padded = f" {joined} "
    # Longest phrases first: « lait de croissance » before « lait »
    for phrase in sorted(_PHRASES, key=len, reverse=True):
        if f" {phrase} " in padded:
            return _PHRASES[phrase]
    for token in tokens:
        if token in _STRONG:
            return _STRONG[token]
    for token in tokens:
        category = _WORD_INDEX.get(token) or _WORD_INDEX.get(_singular(token))
        if category:
            return category
    return OTHER


def is_category(name: str) -> bool:
    return name in CATEGORIES


def category_order(name: str) -> int:
    """Position of an aisle in CATEGORIES (unknown aisles last)."""
    try:
        return CATEGORIES.index(name)
    except ValueError:
        return len(CATEGORIES)
