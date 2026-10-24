"""P5: target, aisle, note, comparison and ticks of each list item; one line per query.

Lines whose queries only differ by case, accents or spaces (« Farine » and
« farine ») are merged into the oldest one (quantities added, choices kept),
then a UNIQUE index on the normalised query prevents new duplicates. A line
without a Latin letter nor digit (« 🍌 », « !!! ») has no key (NULL): kept as
it is, never merged with another one. Written in one transaction: an
interrupted migration leaves the table as it was.
"""

import json
import re
import unicodedata

COLUMNS = {
    "query_key": "TEXT",
    "target": "TEXT",
    "category": "TEXT",
    "note": "TEXT",
    "compare": "INTEGER NOT NULL DEFAULT 1",
    "excluded_json": "TEXT NOT NULL DEFAULT '[]'",
    "checked": "INTEGER NOT NULL DEFAULT 0",
    "checked_at": "REAL",
}


def key_of(query: str) -> str:
    """matching.query_key as it was when this migration was written (frozen copy)."""
    text = (query or "").lower().replace("œ", "oe").replace("æ", "ae")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", text))


async def up(db) -> None:
    await db.execute("BEGIN IMMEDIATE")
    try:
        await _up(db)
    except BaseException:
        await db.rollback()
        raise
    await db.commit()


async def _up(db) -> None:
    cursor = await db.execute("PRAGMA table_info(shopping_list)")
    existing = {row[1] for row in await cursor.fetchall()}
    for name, ddl in COLUMNS.items():
        if name not in existing:
            await db.execute(f"ALTER TABLE shopping_list ADD COLUMN {name} {ddl}")

    cursor = await db.execute("SELECT id, query, quantity, picks_json FROM shopping_list ORDER BY id")
    kept: dict[str, dict] = {}
    for row_id, query, quantity, picks_json in await cursor.fetchall():
        key = key_of(query)
        if not key:
            continue  # no key: the line stays as it is (query_key NULL)
        try:
            picks = json.loads(picks_json or "{}")
        except ValueError:
            picks = {}
        if not isinstance(picks, dict):
            picks = {}
        first = kept.get(key)
        if first is None:
            kept[key] = {"id": row_id, "quantity": quantity, "picks": picks}
            continue
        first["quantity"] = min(99, first["quantity"] + quantity)
        first["picks"].update(picks)  # the latest choice of a retailer wins
        await db.execute("DELETE FROM shopping_list WHERE id = ?", (row_id,))
    for key, line in kept.items():
        await db.execute(
            "UPDATE shopping_list SET query_key = ?, quantity = ?, picks_json = ? WHERE id = ?",
            (key, line["quantity"], json.dumps(line["picks"]), line["id"]),
        )
    await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS shopping_list_query_key ON shopping_list(query_key)")
