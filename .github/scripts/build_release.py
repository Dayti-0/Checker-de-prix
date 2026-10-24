"""Zip of a release of PrixMalin: ``python .github/scripts/build_release.py 3.0.0 dist``.

Only the files tracked by git that the user needs (the app, its launchers,
its documentation): no tests, no CI, no development files. The ``.bat`` files
are written with CRLF line endings whatever the checkout (cmd.exe needs them).
Everything is in a folder ``PrixMalin-<version>/`` of ``dist/PrixMalin-<version>.zip``.
"""

import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Folders and files of the zip (everything else stays out: tests/, .github/, CLAUDE.md...)
FOLDERS = ("backend/", "frontend/", "docs/")
FILES = (
    "lancer.bat",
    "installer-raccourci.bat",
    "mettre-a-jour.bat",
    "requirements.txt",
    "requirements.in",
    "pyproject.toml",
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
)
EXCLUDED_PARTS = ("__pycache__",)
EXCLUDED_SUFFIXES = (".pyc", ".pyo")


def tracked_files(root: Path = ROOT) -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)  # noqa: S607
    return [name for name in out.stdout.decode("utf-8").split("\0") if name]


def selected(names: list[str]) -> list[str]:
    keep = []
    for name in names:
        if not (name in FILES or name.startswith(FOLDERS)):
            continue
        if any(part in EXCLUDED_PARTS for part in name.split("/")) or name.endswith(EXCLUDED_SUFFIXES):
            continue
        keep.append(name)
    return sorted(keep)


def crlf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def build(version: str, dist: Path, root: Path = ROOT) -> Path:
    folder = f"PrixMalin-{version}"
    dist.mkdir(parents=True, exist_ok=True)
    target = dist / f"{folder}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in selected(tracked_files(root)):
            path = root / name
            if not path.is_file():
                continue
            data = path.read_bytes()
            if name.endswith(".bat"):
                data = crlf(data)
            archive.writestr(f"{folder}/{name}", data)
    return target


if __name__ == "__main__":
    print(build(sys.argv[1], Path(sys.argv[2] if len(sys.argv) > 2 else "dist")))
