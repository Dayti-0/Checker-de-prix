"""P5: saved lists (templates) deleted lately, kept for « Annuler »
(POST /api/templates/restore), like the lines of the list (p5_003)."""


async def up(db) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS template_trash (
            id INTEGER PRIMARY KEY,
            template_json TEXT NOT NULL,
            deleted_at REAL NOT NULL
        )""")
