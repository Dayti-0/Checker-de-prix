"""P5: target, aisle, note, comparison and ticks of each list item; one line per query.

Lines whose queries only differ by case, accents or spaces (« Farine » and
« farine ») are merged into the oldest one (quantities added, choices kept),
then a UNIQUE index on the normalised query prevents new duplicates.
"""

import json

from backend.repos.shopping_list import list_key

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


async def up(db) -> None:
    cursor = await db.execute("PRAGMA table_info(shopping_list)")
    existing = {row[1] for row in await cursor.fetchall()}
    for name, ddl in COLUMNS.items():
        if name not in existing:
            await db.execute(f"ALTER TABLE shopping_list ADD COLUMN {name} {ddl}")

    cursor = await db.execute("SELECT id, query, quantity, picks_json FROM shopping_list ORDER BY id")
    kept: dict[str, dict] = {}
    for row_id, query, quantity, picks_json in await cursor.fetchall():
        key = list_key(query)
        try:
            picks = json.loads(picks_json or "{}")
        except ValueError:
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
