"""Relevance of a product for a search query (area of P2).

``Matcher(query).match(name, brand)`` gives, for one product:

- ``relevance``: what the results show. 1 = the product searched (main list,
  « Le moins cher », product picked by the basket); between 0 and 1 =
  « Produits proches » (share of the keywords found, at most 0.99); 0 = unrelated;
- ``score`` (``match_score``): from 0 to 1, to sort by relevance. A product is
  relevant exactly when its score is at least ``RELEVANT_SCORE``;
- ``reason``: why a product is not the one searched (one of ``REASONS``).

Everything here is pure and tested (tests/test_p2_matching.py).

**The product is the head of its name**: the start of the name, up to the first
complement (« à », « au », « aux », « à la », « sauce », « goût », « parfum »,
« saveur », « arôme », « façon », « avec », « fourré », « nappé », « pour »,
« en »...: ``COMPLEMENTS``). A brand in front of the name does not count. A
product is relevant when:

1. it holds every keyword of the query as whole words, plurals, accents and
   case ignored (« huile de tournesols » = « Huile de Tournesol » = « huile
   tournesol »; « Laitue » is not « lait »);
2. the main keyword of the query (its first one, « bio », « pur », « petits »...
   skipped) is in the head of the name or in the brand: « Thon à l'huile de
   tournesol » is not « huile de tournesol », but is « thon huile de tournesol »
   (otherwise: reason ``complement``);
   A name without the keyword but starting with a kind of it counts as it
   (``HYPONYMS``: « Spaghetti n°5 » or « Coquillettes » for « pâtes »,
   « Basmati » for « riz »). A brand in capitals at the end of the name
   (« … PETIT NAVIRE ») only counts for a query that is not a food: « Pizza
   THON » is not « thon »;
3. when the main keyword is a food (``PRODUCT_NOUNS``), no other food comes
   before it in the head: « Sauce tomate » is not « tomate », « Thon huile de
   tournesol » is not « huile de tournesol » (reason ``other_product``). A
   known brand in front (``KNOWN_BRANDS``: « Fruit d'Or », « Nestlé Dessert »)
   is not another food. « pur X » after a word that is not a cut of X is an
   ingredient: « Sablés pur beurre » is not « beurre », « Steak haché pur
   bœuf » is « bœuf » (reason ``complement``);
4. it is not a compound that is another product: « Eau de javel » for « eau »,
   « Pâte à tartiner » for « pâtes », « Beurre de cacahuète » or « Petit
   Beurre » for « beurre » (reason ``compound``, ``COMPOUNDS``): the other word
   follows the keyword (« de », « à », « pour »... between them), before any
   complement (« Eau aromatisée parfum citron » is water);
5. a word ending in -é, -ée, -és or -ées is not its form without the accent
   when both are common words (pâté ≠ pâtes, sucré ≠ sucre, purée ≠ pure);
6. « sans X » in the name: X is not in the product (« Bonbons sans sucre » for
   « sucre »); « sans X » in the query must be « sans X » in the name;
7. quantities of the query (« 1,5 l », « 6x1,5L », « 1kg ») are not words to
   find (``query_quantity``); a product of another size scores a little less;
8. « eau -javel »: a product holding an excluded word scores 0 (reason ``excluded``).
"""

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from backend.scrapers.parsing import Pack, parse_pack, quantity_spans

STOP_WORDS = frozenset(
    {
        "de",
        "du",
        "des",
        "d",
        "le",
        "la",
        "les",
        "l",
        "un",
        "une",
        "au",
        "aux",
        "et",
        "ou",
        "en",
        "a",
        "pour",
        "avec",
        "sans",
        "sur",
    }
)

# A product is relevant exactly when its match_score is at least this
RELEVANT_SCORE = 0.75

# Why a product is not the one searched (Match.reason, Product.match_reason)
REASONS = (
    "missing",  # some keywords are not in the name
    "complement",  # the main keyword only comes after « à », « au », « sauce »... (Thon à l'huile)
    "other_product",  # another food comes first (Sauce tomate for « tomate »)
    "compound",  # a compound that is another product (Eau de javel for « eau »)
    "excluded",  # holds a word excluded with « -mot »
    "unrelated",  # no keyword at all
)

# Words that start a complement of the product name (rule 2), without accents
COMPLEMENTS = frozenset(
    """
    a au aux avec pour en sur dans sauce sauces gout gouts parfum parfums parfume
    parfumee parfumes parfumees saveur saveurs arome aromes aromatise aromatisee
    aromatises aromatisees facon fourre fourree fourres fourrees nappe nappee
    nappes nappees enrobe enrobee enrobes enrobees garni garnie garnis garnies
    farci farcie farcis farcies recette special speciale speciaux speciales
    """.split()
)

# Words placed before the product in a query (« bio farine », « petits pois »):
# the main keyword is the next one
QUALIFIERS = frozenset(
    """
    bio pur pure extra fin fine fins fines gros grosse grosses petit petite petits
    petites mini maxi demi grand grande grands grandes nouveau nouvelle vrai vraie
    vieux vieille jeune jeunes premium classique original originale
    """.split()
)

# Foods that are a product on their own (rule 3): « Thon » in « Thon huile de
# tournesol », « Sauce » in « Sauce tomate ». A short list, to complete when a
# search shows another product first. Not the cuts and shapes of a food
# (escalope, steak, filet, pavé, miettes, tranches...): « Escalopes de poulet »
# are chicken.
PRODUCT_NOUNS = """
abricot agneau ail amande ananas anchois artichaut asperge aubergine avocat
baguette banane barre beignet betterave beurre biere biscotte biscuit blini
boeuf boisson bonbon bouillon boulette brioche brocoli brownie burger
cabillaud cacahuete cacao cafe cake camembert canard cannelloni caramel carotte
cassoulet cereale champignon chips chocolat chorizo chou chouquette cidre
citron clementine colin compote comte concentre concombre confiserie confiture
cookie cornichon coulis courgette couscous crabe creme crepe crevette
croissant croque croquette crouton dessert dinde echalote emmental endive
entremets epinard farine fenouil feta financier flan fraise framboise frite
fromage fruit galette gateau gaufre gaufrette gelee glace gnocchi gratin hachis hareng
haricot huile jambon jus ketchup kiwi lait lardon lasagne legume lentille levure
limonade liqueur madeleine mais mangue maquereau margarine mayonnaise melon merguez
miel moule mousse moutarde mozzarella muesli muffin myrtille navet nectar
noisette noix nougat nouille nugget oeuf oignon olive omelette orange pain palet
pamplemousse parmentier pastis pate peche pesto pizza poire poireau pois poisson
poivre poivron pomme porc potage poulet praline pruneau puree quiche quinoa
radis raisin ratatouille ravioli rillette riz sable salade sandwich sardine sauce
saucisse saucisson saumon sel semoule sirop soda soupe sucre surimi taboule
tarte tartelette terrine the thon tisane tomate tortilla truite vanille veau
veloute vermicelle viande vin vinaigre vinaigrette wrap yaourt
""".split()

# Cuts and shapes of a food: « Steak haché pur bœuf » is beef, « Sablés pur beurre » is not butter
CUTS = frozenset(
    """
    steak steaks hache haches escalope escalopes filet filets pave paves miette miettes tranche tranches
    morceau morceaux emince eminces roti rotis cube cubes lamelle lamelles rondelle rondelles
    aiguillette aiguillettes cuisse cuisses haut hauts blanc blancs aile ailes bavette bavettes
    entrecote entrecotes faux rumsteck onglet onglets plaquette plaquettes motte mottes bloc blocs
    portion portions
    """.split()
)

# « pur beurre », « pure laine »: the next word is what the product is made of
PURE = frozenset(("pur", "pure", "purs", "pures"))

# Kinds of a food that names often give alone (rule 2): « Spaghetti n°5 BARILLA » are « pâtes »
HYPONYMS = {
    "pâtes": (
        "spaghetti",
        "spaghettis",
        "penne",
        "pennes",
        "coquillettes",
        "macaroni",
        "macaronis",
        "tagliatelle",
        "tagliatelles",
        "fettuccine",
        "fusilli",
        "torsades",
        "torti",
        "farfalle",
        "papillons",
        "linguine",
        "rigatoni",
        "tortiglioni",
        "conchiglie",
        "coudes",
        "capellini",
        "pappardelle",
        "orecchiette",
        "gemelli",
        "cavatappi",
    ),
    "riz": ("basmati", "thaï", "arborio", "carnaroli"),
}

# Brands that start names and hold a food (rule 3): « Fruit d'Or Huile de tournesol » is oil
KNOWN_BRANDS = (
    "fruit d'or",
    "nestlé dessert",
    "côte d'or",
    "bonne maman",
    "tropicana",
    "brioche pasquier",
)

# Words between a keyword and the other word of its compound: « eau de parfum », « crème pour les mains »
LINKS = frozenset("de d du des a au aux la l le les pour en".split())

# Compounds that are another product (rule 4): keyword, words that make it another product
# when they follow it (« Eau de javel »)
COMPOUNDS = [
    (
        "eau",
        (
            "javel",
            "toilette",
            "cologne",
            "micellaire",
            "vie",
            "parfum",
            "démaquillante",
            "coco",
            "rose",
            "fleur",
            "oxygénée",
            "déminéralisée",
            "florale",
        ),
    ),
    (
        "pâte",
        (
            "tartiner",
            "feuilletée",
            "brisée",
            "sablée",
            "pizza",
            "dentifrice",
            "modeler",
            "amande",
            "fruits",
            "coing",
            "crêpes",
            "brick",
        ),
    ),
    ("lait", ("coco", "corps", "toilette", "démaquillant", "solaire", "hydratant", "bébé", "croissance", "amande")),
    ("sucre", ("bonbon", "bonbons", "sucette", "sucettes", "confiserie", "orge")),
    ("huile", ("massage", "moteur", "corps", "solaire", "bébé", "essentielle", "cheveux", "visage")),
    ("beurre", ("cacahuète", "cacahuètes", "karité", "cacao")),
    ("pain", ("chocolat", "raisins", "épices", "lait")),
    ("riz", ("lait",)),
    ("pomme", ("terre", "dauphines", "noisettes")),
    ("crème", ("solaire", "mains", "visage", "corps", "hydratante", "dépilatoire", "rasage")),
    ("sel", ("vaisselle", "régénérant", "déneigement")),
    ("vinaigre", ("ménager",)),
    ("oeuf", ("pâques", "chocolat", "surprise")),
]
# ... or when they come right before it (« Petit Beurre LU »)
COMPOUNDS_BEFORE = [("beurre", ("petit", "petits"))]


def normalize(text: str) -> str:
    """Lowercase, remove accents and ligatures."""
    text = text.lower().replace("œ", "oe").replace("æ", "ae")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalize(text))


def stem(token: str) -> str:
    """Very small French stemmer: plural and feminine endings (sucrées -> sucr, pâtes -> pate)."""
    if len(token) > 3 and token[-1] in "sx":
        token = token[:-1]
    if len(token) > 4 and token.endswith("ee"):
        token = token[:-1]
    if len(token) > 4 and token.endswith("e"):
        token = token[:-1]
    return token


@dataclass(frozen=True)
class Word:
    plain: str  # without accents
    stem: str
    # Ends in -é, -ée, -és, -ées (pâté, sucrée)
    e_form: bool
    # Written with accents: its form can be trusted (« PATE », « pates » cannot)
    accented: bool
    # Written in capitals (« PETIT NAVIRE »)
    upper: bool = False

    @property
    def content(self) -> bool:
        """A word that says what the product is (not « de », « 1kg » or « T45 »)."""
        return self.plain not in STOP_WORDS and self.plain.isalpha() and len(self.plain) > 1


_WORD = re.compile(r"[^\W_]+")
_E_FORM = re.compile(r"é(?:e|es|s)?$")


def words_of(text: str) -> list[Word]:
    words = []
    text = (text or "").replace("œ", "oe").replace("Œ", "OE").replace("æ", "ae").replace("Æ", "AE")
    for original in _WORD.findall(text):
        raw = original.lower()
        plain = "".join(re.findall(r"[a-z0-9]+", normalize(raw)))
        if plain:
            upper = original.isupper() and len(plain) > 1 and plain.isalpha()
            words.append(Word(plain, stem(plain), bool(_E_FORM.search(raw)), plain != raw, upper))
    return words


def _stem_of(word: str) -> str:
    return stem("".join(tokenize(word)))


# Words that differ from their -é form (rule 5), compared by stem
_AMBIGUOUS = frozenset(_stem_of(w) for w in ("pâte", "sucre", "glace", "sale", "râpe", "grille", "côte", "pure"))
_QUALIFIER_STEMS = frozenset(stem(w) for w in QUALIFIERS)
_COMPOUND_STEMS = [
    (_stem_of(word), frozenset(_stem_of(other) for other in others), frozenset()) for word, others in COMPOUNDS
] + [(_stem_of(word), frozenset(), frozenset(_stem_of(other) for other in others)) for word, others in COMPOUNDS_BEFORE]
_CUT_STEMS = frozenset(stem(w) for w in CUTS)
_KNOWN_BRANDS = [tuple(w.plain for w in words_of(brand)) for brand in KNOWN_BRANDS]
_HYPONYMS = [(words_of(word)[0], tuple(words_of(" ".join(kinds)))) for word, kinds in HYPONYMS.items()]


def _spelled_e_form(word: Word) -> bool:
    """Ends in -é, -ée...: by its accents, or « ee » without accents (« PUREE », but « PATE » may be either)."""
    return word.e_form or (not word.accented and word.plain.endswith(("ee", "ees")))


# Foods by stem, with their -é forms (« puree » is purée, never « Pure »)
_NOUN_FORMS: dict[str, frozenset[bool]] = {}
for _noun in PRODUCT_NOUNS:
    _word = words_of(_noun)[0]
    _NOUN_FORMS[_word.stem] = _NOUN_FORMS.get(_word.stem, frozenset()) | {_spelled_e_form(_word)}
_NOUN_STEMS = frozenset(_NOUN_FORMS)


def is_food(word: Word) -> bool:
    """``word`` is a food of ``PRODUCT_NOUNS`` (« Pure » is not « purée », « Pâté » is not « pâte »)."""
    forms = _NOUN_FORMS.get(word.stem)
    if not forms:
        return False
    return word.stem not in _AMBIGUOUS or _spelled_e_form(word) in forms


def _same(wanted: Word, found: Word) -> bool:
    if wanted.stem != found.stem:
        return False
    if wanted.stem in _AMBIGUOUS and wanted.e_form != found.e_form:
        # « pates » written without accents may be either: only trust accents
        return not (found.e_form or found.accented)
    return True


@dataclass(frozen=True)
class ParsedQuery:
    words: tuple[Word, ...]  # keywords, in the order of the query
    # « lait sans lactose »: words that must come after « sans » in the name too
    without: tuple[Word, ...]
    excluded: frozenset[str]  # stems of the words after « - »
    quantity: tuple[float, str] | None
    # Stems of every word of the query, stop words included (« lait de coco »)
    all_stems: frozenset[str]

    @property
    def main(self) -> Word | None:
        """The product searched: the first keyword, « bio », « pur », « petits »... skipped."""
        for word in self.words:
            if word.plain not in QUALIFIERS:
                return word
        return self.words[0] if self.words else None


_EXCLUSION = re.compile(r"(?:^|\s)-\s*([^\W\d_][^\W_]*)")


def _strip_quantities(text: str) -> str:
    for start, end in reversed(quantity_spans(text)):
        text = text[:start] + " " + text[end:]
    return text


def query_quantity(query: str) -> tuple[float, str] | None:
    """Quantity asked in a query: « eau 1,5 l » -> (1.5, 'L'), « 6x1,5L » -> (9.0, 'L'), « 1kg » -> (1.0, 'kg')."""
    query = query or ""
    spans = quantity_spans(query)
    if not spans:
        return None
    pack = parse_pack(query[spans[0][0] : spans[0][1]])
    return (round(pack.total, 6), pack.unit) if pack else None


def _keyword(word: Word) -> bool:
    return word.plain not in STOP_WORDS and (len(word.plain) > 1 or word.plain.isdigit())


def _negated(words: list[Word]) -> set[int]:
    """Positions of the words negated by « sans » (« sans gluten ni lactose »)."""
    negated: set[int] = set()
    negating = False
    for index, word in enumerate(words):
        if word.plain == "sans":
            negating = True
            continue
        if negating:
            if word.plain in ("ni", "de", "d", "aucun", "aucune"):
                continue
            negated.add(index)
            negating = index + 1 < len(words) and words[index + 1].plain in ("ni", "et")
    return negated


@lru_cache(maxsize=256)
def parse_query(query: str) -> ParsedQuery:
    """Keywords, excluded words (« eau -javel ») and quantity (« 1,5 l ») of a query."""
    query = query or ""
    excluded = frozenset(w.stem for m in _EXCLUSION.finditer(query) for w in words_of(m.group(1)))
    text = _EXCLUSION.sub(" ", query)
    quantity = query_quantity(text)
    every = words_of(_strip_quantities(text))
    negated = _negated(every)
    words = tuple(w for i, w in enumerate(every) if i not in negated and _keyword(w))
    without = tuple(w for i, w in enumerate(every) if i in negated and _keyword(w))
    return ParsedQuery(words, without, excluded, quantity, frozenset(w.stem for w in every))


def keywords(query: str) -> list[str]:
    """Plain keywords of a query (without stop words, quantities and excluded words)."""
    return [w.plain for w in parse_query(query or "").words]


def head_end(words: list[Word]) -> int:
    """Where the head of a name ends: at its first complement after a word saying what it is.

    « Thon à l'huile de tournesol » -> 1 (« Thon »), « Sauce tomate basilic » -> 3
    (a complement word in front is the product itself).
    """
    seen = False
    for index, word in enumerate(words):
        if seen and word.plain in COMPLEMENTS:
            return index
        seen = seen or word.content
    return len(words)


def _brand_offset(words: list[Word], brand: list[Word]) -> int:
    """Number of words of a brand written in front of the name.

    The brand given apart (« Lesieur » + « Lesieur Huile de tournesol »), or a
    known brand (« Fruit d'Or Huile de tournesol », « Nestlé » + « Dessert
    Chocolat noir »). Never the whole name.
    """
    plains = [w.plain for w in words]
    given = [b.plain for b in brand]
    offset = len(given) if given and plains[: len(given)] == given else 0
    for known in _KNOWN_BRANDS:
        size = len(known)
        if plains[:size] == list(known):
            offset = max(offset, size)
        elif given and len(given) < size and list(known[: len(given)]) == given:
            rest = list(known[len(given) :])
            if plains[: len(rest)] == rest:
                offset = max(offset, len(rest))
    return offset if offset < len(words) else 0


def _capital_tail(words: list[Word]) -> list[Word]:
    """Brand in capitals at the end of a name in lower case (« Thon à l'huile d'olive PETIT NAVIRE 160g »)."""
    if not any(not w.upper and w.content for w in words):
        return []
    tail: list[Word] = []
    for word in reversed(words):
        if not word.plain.isalpha():
            if tail:
                break
            continue
        if not word.upper:
            break
        tail.append(word)
    return tail


# Content words allowed between a keyword and the other word of its compound
# (« Crème de jour visage », « Huile de tournesol pour massage »)
_COMPOUND_GAP = 2


def _is_compound(q: ParsedQuery, words: list[Word], negated: set[int]) -> bool:
    """A keyword of the query is part of a compound that is another product (rule 4)."""
    keyword_stems = {w.stem for w in q.words}
    for index, word in enumerate(words):
        if index in negated or word.stem not in keyword_stems:
            continue
        for compound, after, before in _COMPOUND_STEMS:
            if word.stem != compound:
                continue
            previous = words[index - 1] if index else None
            if previous is not None and previous.stem in before and previous.stem not in q.all_stems:
                return True
            gap = 0
            for following in words[index + 1 :]:
                if following.plain in LINKS:
                    continue
                if following.stem in after and following.stem not in q.all_stems:
                    return True
                if following.plain in COMPLEMENTS or gap >= _COMPOUND_GAP:
                    break
                gap += following.content
    return False


def _kinds(main: Word) -> tuple[Word, ...]:
    """The kinds of ``main`` that count as it in front of a name (« spaghetti » for « pâtes »)."""
    return next((kinds for word, kinds in _HYPONYMS if _same(main, word)), ())


def _ingredient(q: ParsedQuery, head: list[Word], position: int) -> bool:
    """« Sablés pur beurre »: the main keyword follows « pur » after a word that is not a cut of it."""
    if position == 0 or head[position - 1].plain not in PURE:
        return False
    return any(
        w.content and w.stem not in _CUT_STEMS and w.plain not in QUALIFIERS and w.stem not in q.all_stems
        for w in head[: position - 1]
    )


def _same_quantity(wanted: tuple[float, str], pack: Pack) -> bool:
    amount, unit = wanted
    return unit == pack.unit and any(abs(value - amount) < 1e-6 for value in (pack.total, pack.size))


@dataclass(frozen=True)
class Match:
    # 1 = relevant ; between 0 and 1 = "Produits proches" (share of the keywords, at most 0.99)
    relevance: float
    score: float  # match_score
    # Why the product is not the one searched (one of REASONS), None when it is
    reason: str | None = None

    @property
    def relevant(self) -> bool:
        return self.relevance >= 1


class Matcher:
    """Scores products for one query (parsed once)."""

    def __init__(self, query: str) -> None:
        self.query = parse_query(query or "")

    def match(self, name: str, brand: str | None = None) -> Match:
        q = self.query
        words = words_of(name)
        brand_words = words_of(brand or "")
        negated = _negated(words)
        present = [w for i, w in enumerate(words) if i not in negated] + brand_words
        stems = {w.stem for w in present}
        if q.excluded & stems:
            return Match(0.0, 0.0, "excluded")
        if not q.words and not q.without:
            return Match(1.0, 1.0)

        main = q.main
        offset = _brand_offset(words, brand_words)
        head = words[offset:]
        end = head_end(head)
        kinds = _kinds(main) if main is not None else ()

        def is_main(word: Word) -> bool:
            return _same(main, word) or any(_same(kind, word) for kind in kinds)

        # Where the product searched is in the head (« Spaghetti n°5 » for « pâtes »)
        position = None
        if main is not None:
            position = next((i for i in range(end) if i + offset not in negated and is_main(head[i])), None)

        absent = [w for i, w in enumerate(words) if i in negated]
        found = [w for w in q.words if any(_same(w, p) for p in present) or (w == main and position is not None)]
        found_without = [w for w in q.without if any(_same(w, a) for a in absent)]
        coverage = (len(found) + len(found_without)) / (len(q.words) + len(q.without))
        if not coverage:
            return Match(0.0, 0.0, "unrelated")

        reason = None if coverage == 1 else "missing"
        score = 0.85 * coverage
        if main is not None and main in found:
            food = is_food(main)
            # A brand holding the keyword: given apart, written in front, or in
            # capitals at the end, this one never for a food (« Pizza THON »)
            in_brand = any(_same(main, w) for w in brand_words + words[:offset]) or (
                not food and any(_same(main, w) for w in _capital_tail(words))
            )
            if position is None and not in_brand:
                reason = reason or "complement"
            else:
                score += 0.05
                first = next((w for w in head if w.content), None)
                if first is not None and is_main(first):
                    score += 0.1
                if position is not None and not in_brand and food:
                    before = [w for w in head[:position] if w.content and w.stem not in q.all_stems]
                    if any(is_food(w) for w in before):
                        reason = reason or "other_product"
                    elif _ingredient(q, head, position):
                        reason = reason or "complement"
        if reason is None and _is_compound(q, words, negated):
            reason = "compound"
        if q.quantity:
            pack = parse_pack(name)
            if pack and not _same_quantity(q.quantity, pack):
                score -= 0.05
        if reason is None:
            return Match(1.0, round(max(RELEVANT_SCORE, min(1.0, score)), 2))
        if reason != "missing":
            score *= 0.5
        return Match(round(min(coverage, 0.99), 2), round(max(0.01, min(RELEVANT_SCORE - 0.01, score)), 2), reason)


def relevance(product_text: str, query: str) -> float:
    """What the results show: 1 = relevant, between 0 and 1 = "Produits proches", 0 = unrelated."""
    return Matcher(query).match(product_text).relevance


def is_relevant(name: str, query: str, brand: str | None = None) -> bool:
    """``name`` (of ``brand``) is the product searched with ``query``."""
    return Matcher(query).match(name, brand).relevant


def query_key(query: str) -> str:
    """Canonical form of a query, used for caching and merging list items."""
    return " ".join(tokenize(query))


def match_score(name: str, query: str, *, brand: str | None = None) -> float:
    """How well a product name matches a query, from 0 to 1 (contract between the lots).

    The search sorts by it and the basket picks its products with it: a product
    is the one searched exactly when its score is at least ``RELEVANT_SCORE``
    (its ``relevance`` is then 1).
    """
    return Matcher(query).match(name, brand).score
