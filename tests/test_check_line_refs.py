"""Checks for scripts/check_line_refs.py (line numbers cited in the textbook prose vs. source files)."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_line_refs.py"


def ref(spec, expect, text):
    return f'<span data-ref="{spec}" data-expect="{expect}">{text}</span>'


class CheckLineRefsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "src").mkdir()
        (self.root / "src/run.sh").write_text("set -e\ntrap cleanup EXIT\nmake -C mod\n"
                                              "echo a\necho b\ngrep '<x>' log\n")

    def page(self, body):
        (self.root / "docs/p.html").write_text(f"<html><body><p>{body}</p></body></html>")

    def run_check(self, *args):
        argv = list(args) or [str(self.root / "docs")]
        return subprocess.run([sys.executable, str(SCRIPT), *argv],
                              cwd=self.root, text=True, capture_output=True, check=False)

    def assertExit(self, code, result):
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)

    def test_matching_reference_passes(self):
        self.page("腳本用 trap 卸載（第 " + ref("src/run.sh:2", "trap cleanup EXIT", "2") + " 行）")
        result = self.run_check()
        self.assertExit(0, result)
        self.assertIn("line refs checked: 1", result.stdout)

    def test_range_and_several_ranges(self):
        self.page("第 " + ref("src/run.sh:2-3", "trap…make", "2–3") + " 行；第 "
                  + ref("src/run.sh:1,4-5", "set -e|echo a…echo b", "1、4–5") + " 行")
        self.assertExit(0, self.run_check())

    def test_expected_text_outside_the_range_fails(self):
        # The script gained a line above: line 2 is no longer the trap.
        self.page("第 " + ref("src/run.sh:3", "trap cleanup EXIT", "3") + " 行")
        result = self.run_check()
        self.assertExit(1, result)
        self.assertIn("p.html: src/run.sh:3", result.stdout)

    def test_range_past_the_end_of_the_file_fails(self):
        self.page("第 " + ref("src/run.sh:6-9", "grep", "6–9") + " 行")
        self.assertExit(1, self.run_check())

    def test_shown_numbers_must_match_the_reference(self):
        self.page("第 " + ref("src/run.sh:2", "trap", "3") + " 行")
        result = self.run_check()
        self.assertExit(1, result)
        self.assertIn("shows", result.stdout)

    def test_expected_text_must_be_on_the_first_line(self):
        # "make -C" is inside 2-3 but not on line 2: a range that slid by one line must fail.
        self.page("第 " + ref("src/run.sh:2-3", "make -C", "2–3") + " 行")
        self.assertExit(1, self.run_check())

    def test_first_and_last_line(self):
        self.page("第 " + ref("src/run.sh:3-5", "make -C…echo b", "3–5") + " 行")
        self.assertExit(0, self.run_check())
        # The range grew by one line at the end: the last line no longer matches.
        self.page("第 " + ref("src/run.sh:3-6", "make -C…echo b", "3–6") + " 行")
        self.assertExit(1, self.run_check())

    def test_text_without_tail_must_be_on_every_end_of_the_range(self):
        # No "…": the one piece pins both ends, so a single-line reference cannot quietly grow.
        self.page("第 " + ref("src/run.sh:2-3", "trap", "2–3") + " 行")
        self.assertExit(1, self.run_check())

    def test_one_expected_text_per_range(self):
        self.page("第 " + ref("src/run.sh:1,4", "set -e", "1、4") + " 行")
        self.assertExit(1, self.run_check())

    def test_expected_text_is_html_unescaped(self):
        self.page("第 " + ref("src/run.sh:6", "grep '&lt;x&gt;'", "6") + " 行")
        self.assertExit(0, self.run_check())

    def test_path_colon_line_form(self):
        self.page("<code>src/run.sh:" + ref("src/run.sh:3", "make -C", "3") + "</code>")
        self.assertExit(0, self.run_check())

    def test_unmarked_line_reference_fails(self):
        self.page("卸載在第 26–31 行")
        result = self.run_check()
        self.assertExit(1, result)
        self.assertIn("unmarked", result.stdout)

    def test_unmarked_path_colon_line_fails(self):
        self.page("腳本會自己 build（<code>scripts/verify.sh:42</code>）")
        self.assertExit(1, self.run_check())

    def test_dash_marks_a_non_source_line(self):
        # e.g. a row on the OLED screen, not a line of a file
        self.page('畫面的<span data-ref="-">第 2 行</span>')
        self.assertExit(0, self.run_check())

    def test_terminal_output_and_listings_are_not_prose(self):
        self.page('</p><pre class="out">error at 第 5 行 and x.c:12</pre>'
                  '<figure class="listing"><figcaption>src/run.sh:1–2 — demo</figcaption>'
                  '<pre data-start="1">set -e</pre></figure><p>')
        self.assertExit(0, self.run_check())

    def test_missing_source_is_environment_error(self):
        self.page("第 " + ref("src/missing.sh:1", "x", "1") + " 行")
        result = self.run_check()
        self.assertExit(2, result)
        self.assertIn("ERROR p.html: src/missing.sh", result.stderr)

    def test_malformed_reference_fails(self):
        self.page("第 " + ref("src/run.sh", "x", "1") + " 行")
        self.assertExit(1, self.run_check())

    def test_line_zero_and_reversed_ranges_fail(self):
        # line 0 would read lines[-1] (the last line); 6-2 would read nothing
        self.page("第 " + ref("src/run.sh:0", "grep", "0") + " 行")
        self.assertExit(1, self.run_check())
        self.page("第 " + ref("src/run.sh:6-2", "grep…trap", "6–2") + " 行")
        self.assertExit(1, self.run_check())

    def test_empty_head_or_tail_fails(self):
        for expect in ("…", "…EXIT", "trap…", ""):
            with self.subTest(expect=expect):
                self.page("第 " + ref("src/run.sh:2", expect, "2") + " 行")
                self.assertExit(1, self.run_check())

    def test_escaped_pipe_is_part_of_the_text(self):
        (self.root / "src/p.sh").write_text("ls | wc -l\n")
        self.page("第 " + ref("src/p.sh:1", "ls &#124; wc", "1") + " 行")
        self.assertExit(0, self.run_check())

    def test_attribute_order_and_nested_markup(self):
        self.page('第 <span class="x" data-expect="trap" data-ref="src/run.sh:2"><b>2</b></span> 行')
        self.assertExit(0, self.run_check())
        self.page('第 <span data-expect="trap" data-ref="src/run.sh:3"><b>3</b></span> 行')
        self.assertExit(1, self.run_check())

    def test_unmarked_reference_behind_markup_or_entities_fails(self):
        for text in ("第 <code>91</code> 行", "第&nbsp;91&nbsp;行", "第 91 至 93 行", "第 91 到 93 行",
                     "第 91～93 行", "第 4 和 9 行", "<code>meta/x.bb:12</code>", "<code>conf/local.conf:3</code>",
                     "<code>x.dtsi:7</code>", "<code>Kconfig:4</code>"):
            with self.subTest(text=text):
                self.page(text)
                self.assertExit(1, self.run_check())

    def test_plain_numbers_are_not_line_references(self):
        self.page("時間 14:25、比例 1.5:1、位址 0x41、i2c-7、第 3 章")
        self.assertExit(0, self.run_check())

    def test_figcaption_text_is_prose_but_the_listing_range_is_not(self):
        cap = ('</p><figure class="listing"><figcaption>src/run.sh:1–2 — Step 9 改了第 2 行</figcaption>'
               '<pre data-start="1">set -e</pre></figure><p>')
        self.page(cap)
        self.assertExit(1, self.run_check())
        self.page(cap.replace("第 2 行", "第 " + ref("src/run.sh:2", "trap", "2") + " 行"))
        self.assertExit(0, self.run_check())

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                              cwd=self.root, text=True, capture_output=True, check=True).stdout.strip()

    def test_pinned_reference_reads_the_commit(self):
        self.git("init", "-q")
        self.git("add", "src/run.sh")
        self.git("commit", "-qm", "old")
        rev = self.git("rev-parse", "--short", "HEAD")
        (self.root / "src/run.sh").write_text("# new header\nset -e\ntrap cleanup EXIT\n")
        self.page("第 " + ref(f"src/run.sh@{rev}:2", "trap cleanup EXIT", "2") + " 行")
        self.assertExit(0, self.run_check())
        self.page("第 " + ref("src/run.sh:2", "trap cleanup EXIT", "2") + " 行")
        self.assertExit(1, self.run_check())

    def test_usage_error_is_exit_2(self):
        self.assertExit(2, self.run_check("--skip"))
        self.assertExit(2, self.run_check(str(self.root / "nope")))


if __name__ == "__main__":
    unittest.main()
