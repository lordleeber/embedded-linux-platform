"""Hardware-free checks for Step 10-b: text on the OLED, and edge_oled re-sending its settings.

The font and layout vectors are in tests/test_oled_text.cpp (classic 5x7 table, Step 9's
GDDRAM layout). Here: the vectors run, edge_oled_ctl's text / font commands write the
expected frame into a regular file standing in for /dev/edge_oled, the driver re-sends the
SSD1306 settings on every flush (Step 10-a carry-over: an OLED that lost power between two
writes ACKs again but stays dark), and the acceptance script's shape.
"""

from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from test_edge_ina219_static import code_only, function_body


REPO = Path(__file__).resolve().parents[1]
BUILD = REPO / "build"
CTL = BUILD / "edge_oled_ctl"
VECTORS = BUILD / "test_oled_text"
TEXT_H = REPO / "apps" / "oled_text.h"
DRIVER = REPO / "kernel" / "edge_oled" / "edge_oled.c"
VERIFY = REPO / "scripts" / "verify_edge_oled_text.sh"

# Classic 5x7 columns (bit 0 = top row), as in test_oled_text.cpp.
E = bytes([0x7F, 0x49, 0x49, 0x49, 0x41])
L = bytes([0x7F, 0x40, 0x40, 0x40, 0x40])
ONE = bytes([0x00, 0x42, 0x7F, 0x40, 0x00])
A = bytes([0x7E, 0x11, 0x11, 0x11, 0x7E])
BOX = bytes([0x7F, 0x41, 0x41, 0x41, 0x7F])

_built = False


def build():
    global _built
    if _built:
        return
    subprocess.run(["cmake", "-S", str(REPO), "-B", str(BUILD)], check=True, capture_output=True)
    r = subprocess.run(["cmake", "--build", str(BUILD), "--target", "edge_oled_ctl", "test_oled_text"],
                       capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stdout[-2000:] + r.stderr[-2000:])
    _built = True


class TextVectorsTest(unittest.TestCase):
    def test_vectors(self):
        build()
        r = subprocess.run([str(VECTORS)], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("OK (0 failure(s))", r.stdout)

    def test_renderer_has_no_io_and_no_telemetry(self):
        # Rendering only: the frame goes out through edge_oled_ctl (or Step 10-c's app).
        code = code_only(TEXT_H.read_text())
        self.assertNotRegex(code, r"#include <(fcntl|unistd|fstream|sys/ioctl)\.h>|\b(open|write|ioctl)\(")
        self.assertNotRegex(code, r"(?i)ina219|hwmon|sleep|timer|chrono")


class CtlTextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build()

    def run_ctl(self, *args):
        with tempfile.TemporaryDirectory() as d:
            dev = Path(d) / "dev"
            dev.write_bytes(b"")
            r = subprocess.run([str(CTL), "--dev", str(dev), *args], capture_output=True,
                               timeout=10)
            return r, dev.read_bytes()

    def test_one_line_per_argument(self):
        r, data = self.run_ctl("text", "EDGE", "LINE 2", "123456")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(data), 1024)
        self.assertEqual(data[0:5], E)
        self.assertEqual(data[128:133], L)
        self.assertEqual(data[256:261], ONE)
        self.assertFalse(any(data[384:]))
        self.assertEqual(r.stderr, b"")

    def test_newline_inside_an_argument_starts_a_line(self):
        r, data = self.run_ctl("text", "EDGE\nLINE 2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(data[128:133], L)

    def test_font_sheet(self):
        r, data = self.run_ctl("font")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(data[0:5], A)

    def test_clipped_and_unsupported_are_reported_but_drawn(self):
        r, data = self.run_ctl("text", "A" * 23, "<\t>")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(data), 1024)
        self.assertRegex(r.stderr, rb"2 character\(s\) clipped")
        self.assertRegex(r.stderr, rb"1 character\(s\) not in the font")
        self.assertEqual(data[128 + 6:128 + 11], BOX)

    def test_too_many_lines_are_clipped(self):
        r, data = self.run_ctl("text", *["X"] * 9)
        self.assertEqual(r.returncode, 0)
        self.assertRegex(r.stderr, rb"1 character\(s\) clipped")

    def test_usage(self):
        for args in (["text"], ["font", "x"]):
            with self.subTest(args=args):
                r, _ = self.run_ctl(*args)
                self.assertEqual(r.returncode, 2)
                self.assertIn(b"usage:", r.stderr)
                self.assertIn(b"text LINE", r.stderr)


class DriverRefreshTest(unittest.TestCase):
    """Step 10-a carry-over: OLED unplugged and reconnected with no write in between."""

    @classmethod
    def setUpClass(cls):
        cls.src = DRIVER.read_text()
        cls.flush = function_body(cls.src, "edge_oled_flush")

    def test_settings_go_out_on_every_flush(self):
        # The chip came back at its reset state (display off) and ACKs; the driver cannot
        # read that over I2C, so the settings may not depend on ->initialized.
        self.assertIn("edge_oled_init_seq", self.flush)
        self.assertNotRegex(self.flush, r"if \(!oled->initialized\)\s*\{?\s*ret = edge_oled_send\(oled, EDGE_OLED_CONTROL_CMD, edge_oled_init_seq")

    def test_display_on_after_every_frame(self):
        self.assertRegex(self.flush, r"if \(!ret\)\s*ret = edge_oled_send\(oled, EDGE_OLED_CONTROL_CMD, &on, 1\);")

    def test_display_off_only_before_the_first_frame(self):
        # A refresh must not blank the panel: Display OFF (the first init byte) is skipped
        # once the panel is up.
        self.assertRegex(self.flush, r"if \(oled->initialized\)")
        m = re.search(r"if \(oled->initialized\)\s*\{([^}]*)\}", self.flush)
        self.assertIsNotNone(m)
        self.assertRegex(m.group(1), r"seq\+\+|seq \+= 1|seq = edge_oled_init_seq \+ 1")

    def test_still_no_font_in_the_driver(self):
        self.assertNotRegex(code_only(self.src), r"(?i)glyph|font|ina219|hwmon")


class VerifyTextScriptTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(VERIFY.exists(), f"{VERIFY} missing")
        self.text = VERIFY.read_text()

    def test_syntax_and_usage(self):
        r = subprocess.run(["bash", "-n", str(VERIFY)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run(["bash", str(VERIFY), "--bogus"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_needs_root_a_terminal_and_cleans_up(self):
        self.assertIn("EUID", self.text)
        self.assertIn("/dev/tty", self.text)
        self.assertIn("trap cleanup EXIT", self.text)
        self.assertIn("0 = all checks passed, 1 = a check failed, 2 = environment/usage", self.text)

    def test_phase04_strings(self):
        self.assertRegex(self.text, r"show \"[^\"]*\" font\b")
        self.assertRegex(self.text, r'show "[^"]*" text EDGE "LINE 2" 123456')

    def test_clipping_and_unsupported_are_checked(self):
        self.assertIn("clipped", self.text)
        self.assertIn("not in the font", self.text)

    def test_refresh_does_not_blank(self):
        self.assertRegex(self.text, r"(?i)black|blink")

    def test_refresh_picture_is_up_before_the_person_looks(self):
        # First hardware run: the person pressed Enter, looked up and missed 1/5 (0.6 s), and
        # answered no although nothing blinked. Draw first, then ask them to watch, slower.
        watch = self.text.index('wait_enter "Look at the OLED')
        self.assertRegex(self.text[:watch][-300:], r'ctl text "REFRESH 0/5"')
        loop = self.text[watch:self.text.index("done", watch)]
        self.assertIn("sleep 1", loop)
        q = re.search(r'ask "([^"]*blink[^"]*)"', self.text).group(1)
        self.assertNotRegex(q, r"1\.\.5")     # one question: blink or not

    def test_sliver_question_names_what_is_left_of_l(self):
        self.assertRegex(self.text, r"vertical line")

    def test_replug_without_a_write_in_between(self):
        # The repro from Step 10-a: nothing may be drawn between disconnecting and the
        # dark-panel question; the next draw after that is the check.
        self.assertIn("--no-unplug", self.text)
        start = self.text.index("Disconnect all four wires")
        dark = self.text.index("dark", self.text.index("Reconnect all four wires"))
        self.assertNotRegex(self.text[start:dark], r"\b(ctl|show)\b")
        self.assertRegex(self.text[dark:], r'show "[^"]*" text')


if __name__ == "__main__":
    unittest.main()
