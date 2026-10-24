"""B87: no Chromium download when Chrome or Edge starts (simulated launches)."""

import pytest

from backend import browser, browser_check, config


@pytest.fixture(autouse=True)
def auto_channel(monkeypatch):
    monkeypatch.setattr(config, "BROWSER_CHANNEL", "")
    monkeypatch.setattr(config, "REAL_CHROME_STORES", ())


def launcher(working: set[str], tried: list[str]):
    async def launch(channel: str) -> None:
        tried.append(channel)
        if channel not in working:
            raise RuntimeError(f"Executable doesn't exist for {channel}\nsecond line")

    return launch


def no_install():
    raise AssertionError("Chromium downloaded")


def test_edge_starts_nothing_is_downloaded(tmp_path, capsys):
    tried = []
    marker = tmp_path / ".prixmalin-navigateur"
    code = browser_check.main(["--install", "--marker", str(marker)], launcher({"msedge"}, tried), no_install)
    assert code == 0
    assert tried == ["chrome", "msedge"]  # chromium not even tried
    assert marker.read_text(encoding="utf-8").startswith("msedge playwright=")
    assert "Microsoft Edge" in capsys.readouterr().out


def test_chrome_first(tmp_path):
    tried = []
    assert browser_check.main([], launcher({"chrome", "msedge"}, tried), no_install) == 0
    assert tried == ["chrome"]


def test_chromium_downloaded_only_when_none_starts(tmp_path, capsys):
    tried, installs = [], []
    working = set()

    def install():
        installs.append(browser.PLAYWRIGHT_INSTALL_ARGS)
        working.add("chromium")
        return 0

    assert browser_check.main(["--install"], launcher(working, tried), install) == 0
    assert installs == [("-m", "playwright", "install", "chromium")]
    assert tried == ["chrome", "msedge", "chromium", "chromium"]
    out = capsys.readouterr().out
    assert "téléchargement de Chromium" in out and "second line" not in out


def test_nothing_starts(capsys):
    assert browser_check.main([], launcher(set(), []), no_install) == 1  # without --install: no download
    assert browser_check.main(["--install"], launcher(set(), []), lambda: 1) == 1
    assert "Aucun navigateur ne démarre" in capsys.readouterr().out


def test_forced_channel(monkeypatch):
    monkeypatch.setattr(config, "BROWSER_CHANNEL", "msedge")
    tried = []
    assert browser_check.main([], launcher({"msedge", "chrome"}, tried), no_install) == 0
    assert tried == ["msedge"]
    assert browser_check.channels_to_try() == ("msedge",)


def test_a_launch_that_hangs_is_given_up(monkeypatch):
    import asyncio

    async def hang(channel):
        if channel == "chrome":
            await asyncio.sleep(60)

    found, errors = asyncio.run(browser_check.first_working(["chrome", "msedge"], hang, timeout=-4.9))
    assert found == "msedge" and "chrome" in errors


def test_tip_for_the_dedicated_windows(monkeypatch, capsys):
    import backend.real_chrome as real_chrome

    monkeypatch.setattr(config, "REAL_CHROME_STORES", ("intermarche",))
    monkeypatch.setattr(real_chrome, "find_chrome", lambda configured="": None)
    assert browser_check.main([], launcher({"chromium"}, []), no_install) == 0
    assert "Intermarché et E.Leclerc ont besoin de Google Chrome" in capsys.readouterr().out
