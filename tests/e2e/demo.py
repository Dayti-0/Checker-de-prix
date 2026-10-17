"""PrixMalin with the fake retailers of tests/e2e/fake.py, for screenshots and manual checks.

    python -m tests.e2e.demo --port 8771                # data in a temporary folder
    python -m tests.e2e.demo --port 8771 --data demo-data --fixed

Each retailer answers after a random delay (0.3 to 2.5 s), or after a fixed
delay per retailer with ``--fixed`` (the same screenshots every time).
Nothing leaves the machine.
"""

import argparse
import os
import tempfile
from pathlib import Path

# Before importing the app: no warm-up of the (fake) retailer sites
os.environ["PRIXMALIN_WARMUP"] = "0"

import uvicorn  # noqa: E402

from tests.e2e import fake  # noqa: E402
from tests.e2e.server import make_app, use_data_dir  # noqa: E402

# Order in which the retailers answer with --fixed
FIXED_DELAYS = {"aldi": 0.4, "intermarche": 0.8, "lidl": 1.2, "coursesu": 1.6, "carrefour": 2.0}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="PrixMalin avec des enseignes simulées")
    parser.add_argument("--port", type=int, default=8771)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--data", type=Path, help="dossier de données (temporaire par défaut)")
    parser.add_argument("--fixed", action="store_true", help="délais fixes par enseigne")
    parser.add_argument("--fast", action="store_true", help="réponses immédiates")
    args = parser.parse_args(argv)

    data_dir = args.data or Path(tempfile.mkdtemp(prefix="prixmalin-demo-"))
    patcher = fake._Patcher()
    use_data_dir(patcher, data_dir.resolve())
    delays = {} if args.fast else FIXED_DELAYS if args.fixed else {"*": (0.3, 2.5)}
    fake.install(patcher, delays=delays)
    print(f"Démo PrixMalin : http://{args.host}:{args.port}  (données : {data_dir})")
    uvicorn.run(make_app(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
