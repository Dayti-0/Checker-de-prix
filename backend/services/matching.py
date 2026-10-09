"""Relevance of a product name for a search query."""

import re
import unicodedata

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


def normalize(text: str) -> str:
    """Lowercase, remove accents and ligatures."""
    text = text.lower().replace("œ", "oe").replace("æ", "ae")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalize(text))


def stem(token: str) -> str:
    """Very small French stemmer: plural and feminine endings."""
    if len(token) > 3 and token[-1] in "sx":
        token = token[:-1]
    if len(token) > 4 and token.endswith("e"):
        token = token[:-1]
    return token


def keywords(query: str) -> list[str]:
    return [t for t in tokenize(query) if t not in STOP_WORDS and (len(t) > 1 or t.isdigit())]


def relevance(product_text: str, query: str) -> float:
    """Share of the query keywords found as whole words in the product text."""
    wanted = keywords(query)
    if not wanted:
        return 1.0
    present = {stem(t) for t in tokenize(product_text)}
    found = sum(1 for word in wanted if stem(word) in present)
    return round(found / len(wanted), 2)


def query_key(query: str) -> str:
    """Canonical form of a query, used for caching and merging list items."""
    return " ".join(tokenize(query))


def match_score(name: str, query: str) -> float:
    """How well a product name matches a query, from 0 to 1 (1 = every keyword).

    Contract between the lots (P2 improves it): the search, the basket and the
    alerts all rank products with it.
    """
    return relevance(name, query)
