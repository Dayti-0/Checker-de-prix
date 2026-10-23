"""Does a browser start for PrixMalin? ``python -m backend.browser_check [--install] [--marker FILE]``

lancer.bat runs it at the first launch (then again after an update of the
dependencies). Each channel of ``browser.CHANNEL_ORDER`` (the installed
Chrome, then Edge, then the Chromium of Playwright; only ``PRIXMALIN_BROWSER``
when it is set) is started briefly without a window (15 s at most). Chrome
or Edge is installed on almost every PC: then nothing is downloaded. Only
when none starts, ``--install`` downloads the Chromium of Playwright (about
150 Mo, ``browser.PLAYWRIGHT_INSTALL_ARGS``). ``--marker`` writes the
channel found in FILE (lancer.bat skips the check while it exists).

Exit code 0: a browser starts; 1: none.
"""

import argparse
import asyncio
import subprocess
import sys
from collections.abc import Awaitable, Callable, Iterable
from importlib import metadata
from pathlib import Path

from backend import config
from backend.browser import CHANNEL_ORDER, PLAYWRIGHT_INSTALL_ARGS
from backend.errors import short_error

CHECK_TIMEOUT_SECONDS = 15.0

LABELS = {"chrome": "Google Chrome", "msedge": "Microsoft Edge", "chromium": "Chromium (fourni par Playwright)"}

Launcher = Callable[[str], Awaitable[None]]


async def launch_channel(channel: str, timeout: float = CHECK_TIMEOUT_SECONDS) -> None:
    """Start ``channel`` without a window, then close it (raises when it does not start)."""
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel=channel, headless=True, timeout=timeout * 1000)
        await browser.close()


async def first_working(
    channels: Iterable[str], launch: Launcher = launch_channel, timeout: float = CHECK_TIMEOUT_SECONDS
) -> tuple[str | None, dict[str, str]]:
    """The first channel that starts, and why the others did not."""
    errors: dict[str, str] = {}
    for channel in channels:
        try:
            await asyncio.wait_for(launch(channel), timeout + 5)
        except Exception as e:  # noqa: BLE001 (any failure: the next channel)
            errors[channel] = short_error(e) or type(e).__name__
            continue
        return channel, errors
    return None, errors


def channels_to_try() -> tuple[str, ...]:
    return (config.BROWSER_CHANNEL,) if config.BROWSER_CHANNEL else tuple(CHANNEL_ORDER)


def install_chromium() -> int:
    return subprocess.run([sys.executable, *PLAYWRIGHT_INSTALL_ARGS], check=False).returncode  # noqa: S603


def _write_marker(path: Path | None, channel: str) -> None:
    if path is None:
        return
    try:
        version = metadata.version("playwright")
    except metadata.PackageNotFoundError:
        version = "?"
    try:
        path.write_text(f"{channel} playwright={version}\n", encoding="utf-8")
    except OSError as e:
        print(f"  (repère {path} non écrit : {e})")


def _dedicated_windows_tip() -> None:
    """Intermarché and E.Leclerc need the installed Chrome or Edge (backend/real_chrome.py)."""
    if not config.REAL_CHROME_STORES:
        return
    from backend.real_chrome import find_chrome

    if find_chrome(config.CHROME_PATH) is None:
        print("  Attention : Intermarché et E.Leclerc ont besoin de Google Chrome ou de Microsoft Edge.")
        print("  Installez Google Chrome (https://www.google.com/chrome/) pour comparer leurs prix.")


def main(
    argv: list[str] | None = None, launch: Launcher = launch_channel, install: Callable[[], int] = install_chromium
) -> int:
    parser = argparse.ArgumentParser(description="Vérifie qu'un navigateur démarre pour PrixMalin")
    parser.add_argument("--install", action="store_true", help="télécharger Chromium si aucun ne démarre")
    parser.add_argument("--marker", type=Path, help="fichier où noter le navigateur trouvé")
    args = parser.parse_args(argv)

    print("  Recherche d'un navigateur pour PrixMalin…", flush=True)
    working, errors = asyncio.run(first_working(channels_to_try(), launch))
    if working is None and args.install:
        print("  Ni Chrome ni Edge ne démarrent : téléchargement de Chromium (environ 150 Mo, une seule fois)…")
        for channel, error in errors.items():
            print(f"    {LABELS.get(channel, channel)} : {error}")
        if install() == 0:
            working, errors = asyncio.run(first_working(("chromium",), launch))
    if working is None:
        print("  [ERREUR] Aucun navigateur ne démarre : installez Google Chrome, puis relancez PrixMalin.")
        return 1
    print(f"  Navigateur de PrixMalin : {LABELS.get(working, working)}", flush=True)
    _write_marker(args.marker, working)
    _dedicated_windows_tip()
    return 0


if __name__ == "__main__":
    sys.exit(main())
