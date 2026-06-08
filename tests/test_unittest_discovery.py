import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tsentry_config import (
    DEFAULT_TSENTRY_DB_PATH,
    TSENTRY_DB_PATH_ENV,
    get_tsentry_db_path,
)
from tsentry_runner import init_state_db


class RepositorySmokeTest(unittest.TestCase):
    def test_requirements_file_exists(self):
        repo_root = Path(__file__).resolve().parents[1]

        self.assertTrue((repo_root / "requirements.txt").is_file())

    def test_requirements_include_trading_dependencies(self):
        repo_root = Path(__file__).resolve().parents[1]
        requirements = (repo_root / "requirements.txt").read_text(encoding="utf-8")

        self.assertIn("numpy", requirements)
        self.assertIn("pandas", requirements)
        self.assertIn("streamlit", requirements)
        self.assertIn('MetaTrader5; platform_system == "Windows"', requirements)

    def test_tsentry_db_path_uses_default_without_env(self):
        original = os.environ.pop(TSENTRY_DB_PATH_ENV, None)
        try:
            self.assertEqual(get_tsentry_db_path(), DEFAULT_TSENTRY_DB_PATH)
        finally:
            if original is not None:
                os.environ[TSENTRY_DB_PATH_ENV] = original

    def test_tsentry_runner_initializes_state_db(self):
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state" / "tradingo.db"

            init_state_db(str(db_path))

            self.assertTrue(db_path.is_file())


if __name__ == "__main__":
    unittest.main()
