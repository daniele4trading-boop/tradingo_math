import unittest
from pathlib import Path


class RepositorySmokeTest(unittest.TestCase):
    def test_requirements_file_exists(self):
        repo_root = Path(__file__).resolve().parents[1]

        self.assertTrue((repo_root / "requirements.txt").is_file())


if __name__ == "__main__":
    unittest.main()
