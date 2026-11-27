"""Keep implementation files and technical notes in their respective directories."""
from pathlib import Path
import unittest


class RepositoryLayoutTests(unittest.TestCase):
    def test_root_contains_no_loose_modules_or_technical_notes(self):
        root = Path(__file__).resolve().parents[1]
        files = (path.name for path in root.iterdir() if path.is_file())
        misplaced = [name for name in files if
                     name.lower().endswith((".py", ".lua", ".ps1", ".md"))
                     and name not in {"README.md", "CONTRIBUTING.md", "AGENTS.md", "SECURITY.md",
                                      "CHANGELOG.md", "CODE_OF_CONDUCT.md"}]
        self.assertEqual(misplaced, [], "Use bridge/, reframework/, scripts/, tools/ or docs/.")
