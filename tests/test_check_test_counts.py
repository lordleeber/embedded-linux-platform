"""Checks for scripts/check_test_counts.py (book claims vs. real unittest counts)."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_test_counts.py"
TEST_FILE = '''import unittest
class T(unittest.TestCase):
    def test_a(self): pass
    def test_b(self): pass
'''


class CheckTestCountsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "tests/test_x.py").write_text(TEST_FILE)

    def page(self, body):
        (self.root / "docs/p.html").write_text(f"<html><body>{body}</body></html>")

    def run_check(self):
        return subprocess.run([sys.executable, str(SCRIPT), str(self.root / "docs")],
                              cwd=self.root, text=True, capture_output=True, check=False)

    def test_matching_claim_passes(self):
        self.page('<span data-tests="tests/test_x.py">2</span>')
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_wrong_claim_fails(self):
        self.page('<span data-tests="tests/test_x.py">3</span>')
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("p.html", result.stdout)

    def test_missing_test_file_is_environment_error(self):
        self.page('<span data-tests="tests/test_missing.py">1</span>')
        result = self.run_check()
        self.assertEqual(result.returncode, 2)
        self.assertIn("ERROR p.html: tests/test_missing.py", result.stderr)

    def test_non_numeric_claim_is_environment_error(self):
        self.page('<span data-tests="tests/test_x.py">twelve</span>')
        result = self.run_check()
        self.assertEqual(result.returncode, 2)
        self.assertIn("ERROR p.html: claim 'twelve'", result.stderr)


if __name__ == "__main__":
    unittest.main()
