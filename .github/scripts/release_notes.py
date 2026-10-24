"""Notes of a release, from CHANGELOG.md: ``python .github/scripts/release_notes.py 3.0.0``.

The section ``## [3.0.0]`` (Keep a Changelog) up to the next ``## ``; a
default text when the version has no section.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def notes(changelog: str, version: str) -> str:
    heading = re.compile(rf"^## \[?v?{re.escape(version)}\]?(\s|$)")
    lines, inside = [], False
    for line in changelog.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = bool(heading.match(line))
            continue
        if inside:
            lines.append(line)
    text = "\n".join(lines).strip()
    return text or f"PrixMalin {version}. Voir CHANGELOG.md."


if __name__ == "__main__":
    print(notes((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), sys.argv[1]))
