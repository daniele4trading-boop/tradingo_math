import argparse
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from tsentry_config import (
    TSENTRY_DB_PATH_ENV,
    ensure_tsentry_db_parent,
    get_tsentry_db_path,
)


ENGINE_SCRIPTS = {
    "prop": "tradingo_prop.py",
    "prop-fast": "tradingo_prop_fast.py",
    "hedge": "tradingo_hedge.py",
}


def init_state_db(db_path: str) -> None:
    """Ensure the shared state table exists before engines start."""
    ensure_tsentry_db_parent(db_path)
    with sqlite3.connect(db_path, timeout=10) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )


def build_engine_command(engine: str) -> list[str]:
    script_name = ENGINE_SCRIPTS[engine]
    script_path = Path(__file__).resolve().parent / script_name
    return [sys.executable, str(script_path)]


def run_single_engine(engine: str, env: dict[str, str]) -> int:
    command = build_engine_command(engine)
    return subprocess.call(command, env=env)


def run_both_engines(env: dict[str, str]) -> int:
    commands = [build_engine_command("hedge"), build_engine_command("prop")]
    processes = [subprocess.Popen(command, env=env) for command in commands]

    try:
        while True:
            exit_codes = [process.poll() for process in processes]
            if any(code is not None for code in exit_codes):
                return max(code or 0 for code in exit_codes)
            time.sleep(1)
    except KeyboardInterrupt:
        return 130
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run TradinGo TSentry engines with a shared SQLite DB path."
    )
    parser.add_argument(
        "engine",
        choices=[*ENGINE_SCRIPTS.keys(), "both"],
        help="Engine to run. Use 'both' to start hedge and prop together.",
    )
    parser.add_argument(
        "--db-path",
        default=get_tsentry_db_path(),
        help=f"SQLite DB path. Defaults to the {TSENTRY_DB_PATH_ENV} env var or the repo default.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = ensure_tsentry_db_parent(args.db_path)
    init_state_db(db_path)

    env = os.environ.copy()
    env[TSENTRY_DB_PATH_ENV] = db_path

    print(f"{TSENTRY_DB_PATH_ENV}={db_path}")
    if args.engine == "both":
        return run_both_engines(env)
    return run_single_engine(args.engine, env)


if __name__ == "__main__":
    raise SystemExit(main())
