import os
from pathlib import Path


DEFAULT_TSENTRY_DB_PATH = "C:/tradingo_math/tradingo.db"
TSENTRY_DB_PATH_ENV = "TSENTRY_DB_PATH"


def get_tsentry_db_path() -> str:
    """Return the shared SQLite database path used by the trading engines."""
    return os.environ.get(TSENTRY_DB_PATH_ENV, DEFAULT_TSENTRY_DB_PATH)


def ensure_tsentry_db_parent(db_path: str | None = None) -> str:
    """Create the parent directory for the configured SQLite database."""
    resolved_path = db_path or get_tsentry_db_path()
    parent = Path(resolved_path).expanduser().parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)
    return resolved_path
