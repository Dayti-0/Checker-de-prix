"""Accessibility checks with axe-core (vendor/axe.min.js, version 4.12.1, MPL-2.0).

``assert_accessible(page)`` fails on any *serious* or *critical* violation of the
WCAG 2.2 A/AA rules and of axe's best practices.
"""

from pathlib import Path

AXE_SOURCE = (Path(__file__).parent / "vendor" / "axe.min.js").read_text(encoding="utf-8")
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]
BLOCKING = ("serious", "critical")

_RUN = """async (tags) => {
    const result = await axe.run(document, {runOnly: {type: "tag", values: tags}});
    return result.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        help: v.help,
        nodes: v.nodes.slice(0, 5).map((n) => n.target.join(" ")),
    }));
}"""


def violations(page, tags=TAGS) -> list[dict]:
    """Every violation of the current page (axe is injected the first time)."""
    # page.evaluate is not subject to the Content-Security-Policy of the page
    if not page.evaluate("() => typeof window.axe !== 'undefined'"):
        page.evaluate(AXE_SOURCE)
    return page.evaluate(_RUN, tags)


def assert_accessible(page, label: str = "") -> None:
    blocking = [v for v in violations(page) if v["impact"] in BLOCKING]
    details = "\n".join(f"  [{v['impact']}] {v['id']}: {v['help']} {v['nodes']}" for v in blocking)
    assert not blocking, f"axe {label}:\n{details}"
