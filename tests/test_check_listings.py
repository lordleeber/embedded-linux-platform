"""Checks for scripts/check_listings.py (textbook code listings vs. source files)."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_listings.py"
SOURCE = "int a;\nint b;\nint c &lt;\nint d;\n"


def listing(path, a, b, body):
    return (f'<figure class="listing"><figcaption>{path}:{a}–{b} — demo</figcaption>\n'
            f'<pre data-start="{a}" data-hot="{a}">{body}</pre></figure>')


class CheckListingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "src").mkdir()
        (self.root / "src/x.c").write_text("int a;\nint b;\nint c <\nint d;\n")

    def page(self, *figs):
        (self.root / "docs/p.html").write_text("<html><body>" + "".join(figs) + "</body></html>")

    def run_check(self):
        return subprocess.run([sys.executable, str(SCRIPT), str(self.root / "docs")],
                              cwd=self.root, text=True, capture_output=True, check=False)

    def test_matching_listing_passes(self):
        self.page(listing("src/x.c", 2, 3, "int b;\nint c &lt;"))
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("listings checked: 1", result.stdout)

    def test_shifted_line_numbers_fail(self):
        self.page(listing("src/x.c", 1, 2, "int b;\nint c &lt;"))
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("p.html: src/x.c:1–2", result.stdout)

    def test_data_start_must_match_caption(self):
        fig = listing("src/x.c", 2, 3, "int b;\nint c &lt;").replace('data-start="2"', 'data-start="1"')
        self.page(fig)
        self.assertEqual(self.run_check().returncode, 1)

    def test_markup_in_the_caption_does_not_hide_the_listing(self):
        # check_line_refs.py marks line numbers inside captions with a <span>.
        fig = listing("src/x.c", 1, 2, "int b;\nint c &lt;").replace(
            "— demo", '— 改了第 <span data-ref="src/x.c:2" data-expect="int b">2</span> 行')
        self.page(fig)
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("listings checked: 1", result.stdout)

    def test_missing_source_is_environment_error(self):
        self.page(listing("src/missing.c", 1, 1, "x"))
        result = self.run_check()
        self.assertEqual(result.returncode, 2)
        self.assertIn("ERROR p.html: src/missing.c", result.stderr)

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                              cwd=self.root, text=True, capture_output=True, check=True).stdout.strip()

    def test_pinned_listing_reads_the_commit_not_the_worktree(self):
        # A chapter about an older step quotes code a later step removed: PATH@REV.
        self.git("init", "-q")
        self.git("add", "src/x.c")
        self.git("commit", "-qm", "old")
        rev = self.git("rev-parse", "--short", "HEAD")
        (self.root / "src/x.c").write_text("int z;\n")
        self.page(listing(f"src/x.c@{rev}", 2, 3, "int b;\nint c &lt;"))
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("listings checked: 1", result.stdout)
        self.page(listing(f"src/x.c@{rev}", 1, 1, "int z;"))
        self.assertEqual(self.run_check().returncode, 1)

    def test_unknown_revision_is_environment_error(self):
        self.git("init", "-q")
        self.page(listing("src/x.c@deadbeef", 1, 1, "int a;"))
        result = self.run_check()
        self.assertEqual(result.returncode, 2)
        self.assertIn("ERROR p.html: src/x.c@deadbeef", result.stderr)

    def test_at_sign_in_an_existing_path_is_not_a_revision(self):
        # Device-tree style names (bus@0) are file names, not PATH@REV.
        (self.root / "src/bus@0.c").write_text("int x;\n")
        self.page(listing("src/bus@0.c", 1, 1, "int x;"))
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
