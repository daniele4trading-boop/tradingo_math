"""Entrypoint del servizio: python -m pattern_go --config config.json"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config
from .runner import Runner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pattern GO — servizio di trading")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="solo startup e warmup, poi esce: verifica credenziali e dati",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )

    cfg = load_config(args.config)
    runner = Runner(cfg)
    if args.dry_run:
        runner.startup()
        return 0
    runner.install_signal_handlers()
    runner.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
