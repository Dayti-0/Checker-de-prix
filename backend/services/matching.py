"""Relevance of a product name for a search query (area of P2).

``match_score(name, query)`` (0 to 1) ranks products and lets the basket pick
one; ``relevance`` is what the results show (1 = relevant, between 0 and 1 =
"Produits proches", 0 = unrelated). Everything here is pure and tested
(tests/test_p2_matching.py).

Rules, on top of "every keyword of the query in the name":

1. a word ending in -é, -ée, -és or -ées is not its form without the accent when
   both are common words (pâté ≠ pâtes, sucré ≠ sucre);
2. « sans X » : X is not in the product (« Bonbons sans sucre »);
3. bonus when the first keyword of the query is the first word of the name;
4. penalty when the main keyword only comes after « au », « à la », « aux »,
   « goût », « parfum », « saveur » or « arôme » (« Chocolat au lait » for « lait »);
5. penalty for compounds that are another product (« Eau de javel » for « eau »);
6. quantities of the query (« 1,5 l », « 6x1,5L », « 1kg ») are not words to find
   (``query_quantity``), a product of that size gets a small bonus;
7. « eau -javel » : a product holding an excluded word scores 0.
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

# A product is relevant when it holds every keyword and scores at least this
RELEVANT_SCORE = 0.75

# Words after which the next one is a taste, not the product itself (rule 4)
_MODIFIERS = frozenset({"au", "aux", "gout", "parfum", "parfums", "saveur", "saveurs", "arome", "aromes", "aromatise"})
# « à la », « à l' » once normalised
_MODIFIER_PAIRS = frozenset({("a", "la"), ("a", "l")})


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


_WORD = re.compile(r"[^\W_]+")
_E_FORM = re.compile(r"é(?:e|es|s)?$")


def words_of(text: str) -> list[Word]:
    words = []
    for raw in _WORD.findall((text or "").lower().replace("œ", "oe").replace("æ", "ae")):
        plain = "".join(re.findall(r"[a-z0-9]+", normalize(raw)))
        if plain:
            words.append(Word(plain, stem(plain), bool(_E_FORM.search(raw)), plain != raw))
    return words


# Words that differ from their -é form (rule 1), compared by stem
_AMBIGUOUS = frozenset(stem(normalize(w)) for w in ("pâte", "sucre", "glace", "sale", "râpe", "grille", "côte"))


def _same(wanted: Word, found: Word) -> bool:
    if wanted.stem != found.stem:
        return False
    if wanted.stem in _AMBIGUOUS and wanted.e_form != found.e_form:
        # « pates » written without accents may be either: only trust accents
        return not (found.e_form or found.accented)
    return True


# Compounds that are another product (rule 5): keyword, words that make it another product
_COMPOUNDS = [
    ("eau", ("javel", "toilette", "cologne", "micellaire", "vie", "parfum", "parfumée", "démaquillante")),
    (
        "pâte",
        ("tartiner", "feuilletée", "brisée", "sablée", "pizza", "dentifrice", "modeler", "amande", "fruits", "coing"),
    ),
    ("lait", ("coco", "corps", "toilette", "démaquillant", "solaire", "hydratant", "bébé", "croissance", "amande")),
    ("sucre", ("bonbon", "bonbons", "sucette", "sucettes", "confiserie", "orge")),
    ("huile", ("massage", "moteur", "corps", "solaire", "bébé")),
]
_COMPOUND_STEMS = [
    (stem(normalize(word)), frozenset(stem(normalize(other)) for other in others)) for word, others in _COMPOUNDS
]


@dataclass(frozen=True)
class ParsedQuery:
    words: tuple[Word, ...]  # keywords, in the order of the query
    excluded: frozenset[str]  # stems of the words after « - »
    quantity: tuple[float, str] | None
    # Stems of every word of the query, stop words included (« lait de coco »)
    all_stems: frozenset[str]


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


@lru_cache(maxsize=256)
def parse_query(query: str) -> ParsedQuery:
    """Keywords, excluded words (« eau -javel ») and quantity (« 1,5 l ») of a query."""
    query = query or ""
    excluded = frozenset(w.stem for m in _EXCLUSION.finditer(query) for w in words_of(m.group(1)))
    text = _EXCLUSION.sub(" ", query)
    quantity = query_quantity(text)
    every = words_of(_strip_quantities(text))
    words = tuple(w for w in every if w.plain not in STOP_WORDS and (len(w.plain) > 1 or w.plain.isdigit()))
    return ParsedQuery(words, excluded, quantity, frozenset(w.stem for w in every))


def keywords(query: str) -> list[str]:
    """Plain keywords of a query (without stop words, quantities and excluded words)."""
    return [w.plain for w in parse_query(query or "").words]


@dataclass(frozen=True)
class Match:
    # 1 = relevant ; between 0 and 1 = "Produits proches" (share of the keywords, at most 0.99)
    relevance: float
    score: float  # match_score

    @property
    def relevant(self) -> bool:
        return self.relevance >= 1


class Matcher:
    """Scores product names for one query (parsed once)."""

    def __init__(self, query: str) -> None:
        self.query = parse_query(query or "")

    def match(self, name: str, brand: str | None = None) -> Match:
        q = self.query
        name_words = words_of(name)
        every = name_words + words_of(brand or "")
        present, negated = _present(every)
        if q.excluded and any(w.stem in q.excluded for w in present):
            return Match(0.0, 0.0)
        if not q.words:
            return Match(1.0, 1.0)
        found = [w for w in q.words if any(_same(w, p) for p in present)]
        if not found:
            return Match(0.0, 0.0)
        coverage = len(found) / len(q.words)
        score = 0.9 * coverage
        main = q.words[0]
        head = next((w for w in name_words if w.plain not in STOP_WORDS and not w.plain.isdigit()), None)
        if head is not None and _same(main, head):
            score += 0.1
        if main in found and _only_as_modifier(main, every, negated):
            score *= 0.5
        if _is_compound(q, present):
            score *= 0.3
        if q.quantity:
            pack = parse_pack(name)
            if pack and _same_quantity(q.quantity, pack):
                score += 0.05
        score = round(min(1.0, score), 2)
        if coverage == 1 and score >= RELEVANT_SCORE:
            return Match(1.0, score)
        return Match(round(min(coverage, 0.99), 2), score)


def _present(words: list[Word]) -> tuple[list[Word], set[int]]:
    """Words of the product except those negated by « sans » (« sans gluten ni lactose »)."""
    present, negated = [], set()
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
            continue
        present.append(word)
    return present, negated


def _only_as_modifier(main: Word, words: list[Word], negated: set[int]) -> bool:
    """The main keyword only comes after « au », « à la », « goût »... (rule 4)."""
    positions = [i for i, w in enumerate(words) if i not in negated and _same(main, w)]
    for i in positions:
        before = words[i - 1].plain if i >= 1 else None
        before2 = words[i - 2].plain if i >= 2 else None
        if before not in _MODIFIERS and (before2, before) not in _MODIFIER_PAIRS:
            return False
    return bool(positions)


def _is_compound(q: ParsedQuery, present: list[Word]) -> bool:
    stems = {w.stem for w in present}
    keyword_stems = {w.stem for w in q.words}
    return any(
        word in stems and word in keyword_stems and (others & stems) - q.all_stems for word, others in _COMPOUND_STEMS
    )


def _same_quantity(wanted: tuple[float, str], pack: Pack) -> bool:
    amount, unit = wanted
    return unit == pack.unit and any(abs(value - amount) < 1e-6 for value in (pack.total, pack.size))


def relevance(product_text: str, query: str) -> float:
    """What the results show: 1 = relevant, between 0 and 1 = "Produits proches", 0 = unrelated."""
    return Matcher(query).match(product_text).relevance


def query_key(query: str) -> str:
    """Canonical form of a query, used for caching and merging list items."""
    return " ".join(tokenize(query))


def match_score(name: str, query: str) -> float:
    """How well a product name matches a query, from 0 to 1 (contract between the lots).

    The search sorts by it and the basket picks its products with it. A product
    is relevant when it holds every keyword and scores at least ``RELEVANT_SCORE``.
    """
    return Matcher(query).match(name).score
