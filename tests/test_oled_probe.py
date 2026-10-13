"""Checks for tools/oled_probe.cpp, the Step 9 SSD1306 userspace prototype.

The tool opens /dev/i2c-N through i2c-dev and writes to the OLED with I2C_RDWR:
every message is one control byte (0x00 = commands follow, 0x40 = display RAM
data follows) and then the bytes. It runs the full init sequence on every
invocation, so the result does not depend on what a previous run left. The SSD1306
is write-only over I2C (no RAM read-back), so the picture itself is checked by a
person in scripts/verify_oled_probe.sh; the protocol bytes are checked by the
C++ vectors in tests/test_ssd1306.cpp.
Hardware tests drive the real OLED and run only with EDGE_OLED_HW=1, which the
verify script sets (with EDGE_OLED_BUS / EDGE_OLED_ADDR).
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "tools" / "oled_probe.cpp"
HEADER = REPO / "tools" / "ssd1306.h"
BUILD = REPO / "build"
TOOL = BUILD / "oled_probe"
VECTORS = BUILD / "test_ssd1306"
SCRIPT = REPO / "scripts" / "verify_oled_probe.sh"
HW = os.environ.get("EDGE_OLED_HW") == "1"
BUS = int(os.environ.get("EDGE_OLED_BUS", "1"))
ADDR = int(os.environ.get("EDGE_OLED_ADDR", "0x3c"), 16)
MODES = ("clear", "pixel", "pattern", "edge", "off")
# Negative test target: bus 7 (header pins 3/5, the UPS's INA219 at 0x41) has nothing at 0x3d.
EMPTY_BUS, EMPTY_ADDR = 7, 0x3D


_built = False


def build():
    """Configure and build once per test run; every class calls this in setUpClass."""
    global _built
    if _built:
        return
    subprocess.run(["cmake", "-S", str(REPO), "-B", str(BUILD)], check=True, capture_output=True)
    subprocess.run(["cmake", "--build", str(BUILD), "--target", "oled_probe", "test_ssd1306"],
                   check=True, capture_output=True)
    _built = True


def run_tool(*args):
    return subprocess.run([str(TOOL), *args], capture_output=True, text=True, timeout=10)


def answers(bus, addr):
    """True when i2cdetect (read-byte probe) sees a device at addr on bus."""
    out = subprocess.run(["i2cdetect", "-y", "-r", str(bus), hex(addr), hex(addr)],
                         capture_output=True, text=True, timeout=10).stdout
    # Drop the header line and each row's "30:" label, which would match address 0x30.
    # The range holds one address, so "UU" (bound to a driver) also means it answers.
    cells = [c for line in out.splitlines()[1:] for c in line.split()[1:]]
    return f"{addr:02x}" in cells or "UU" in cells


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build()

    def test_protocol_vectors_pass(self):
        r = subprocess.run([str(VECTORS)], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stdout)


class SourceContractTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SRC.is_file(), f"{SRC} missing")
        self.src = SRC.read_text()

    def test_writes_through_i2c_rdwr(self):
        # I2C_RDWR carries the address in each message: no I2C_SLAVE, so no EBUSY once a
        # kernel driver (Step 10-a) binds the address, and no SMBus block limit of 32 bytes.
        self.assertIn("<linux/i2c-dev.h>", self.src)
        self.assertIn("I2C_RDWR", self.src)
        self.assertNotIn("I2C_SLAVE", self.src)
        self.assertNotIn("I2C_SMBUS", self.src)

    def test_never_reads(self):
        # SSD1306 has no display RAM read in I2C mode; a read would only prove the ACK.
        self.assertNotIn("I2C_M_RD", self.src)

    def test_protocol_bytes_live_in_the_header(self):
        # The tool sends what ssd1306.h builds; the bytes are checked by the C++ vectors.
        self.assertIn('#include "ssd1306.h"', self.src)
        self.assertIn("init_sequence()", self.src)
        self.assertIn("frame_writes(", self.src)
        self.assertNotRegex(self.src, r"0x(AE|AF|8D|A8)\b",
                            "command bytes belong in ssd1306.h (kDisplayOn / kDisplayOff)")

    def test_every_drawing_mode_inits_first(self):
        # Display ON after the frame, init before it: the order in main().
        body = self.src[self.src.index("int main("):]
        i, f, on = body.find("init_sequence()"), body.find("frame_writes("), body.find("kDisplayOn")
        self.assertTrue(0 <= i < f < on, "expected init_sequence() < frame_writes() < kDisplayOn")


class CliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build()

    def test_usage_errors_exit_2(self):
        for args in (["bogus"], ["edge", "clear"], ["--bus"], ["--bus", "x"], ["--bus", "010x"],
                     ["--addr", "0x78"], ["--addr", "0x02"], ["--frobnicate", "1"]):
            with self.subTest(args=args):
                r = run_tool(*args)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("usage:", r.stderr)

    def test_missing_bus_is_exit_1(self):
        r = run_tool("--bus", "250", "edge")
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stderr, r"/dev/i2c-250\b")

    def test_absent_address_is_remote_io_error(self):
        dev = Path(f"/dev/i2c-{EMPTY_BUS}")
        if not (dev.exists() and os.access(dev, os.R_OK | os.W_OK)):
            self.skipTest(f"{dev} not accessible")
        if not shutil.which("i2cdetect"):
            self.skipTest("i2cdetect missing: cannot check that the address is empty")
        if answers(EMPTY_BUS, EMPTY_ADDR):
            self.skipTest(f"something answers at {EMPTY_ADDR:#x} on i2c-{EMPTY_BUS}")
        r = run_tool("--bus", str(EMPTY_BUS), "--addr", hex(EMPTY_ADDR), "edge")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Remote I/O error", r.stderr)


@unittest.skipUnless(HW, "set EDGE_OLED_HW=1 with the OLED wired (scripts/verify_oled_probe.sh)")
class HardwareTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build()

    def tool(self, *args):
        return run_tool("--bus", str(BUS), "--addr", hex(ADDR), *args)

    def test_oled_answers(self):
        self.assertTrue(answers(BUS, ADDR), f"nothing at {ADDR:#x} on i2c-{BUS}")

    def test_every_mode_succeeds(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                r = self.tool(mode)
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_50_runs_in_a_row(self):
        # Each run re-inits; a flaky transfer anywhere in 50 x (init + 9 messages) fails it.
        for n in range(50):
            r = self.tool("edge")
            self.assertEqual(r.returncode, 0, f"run {n}: {r.stderr}")


# i2cdetect -y -r 1 0x30 0x3c with nothing at 0x30 and the OLED at 0x3c (row labels end in ':').
SCAN_30_EMPTY_3C_THERE = """     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:
10:
20:
30: -- -- -- -- -- -- -- -- -- -- -- -- 3c
40:
50:
60:
70:
"""


class ReviewFixTest(unittest.TestCase):
    """Code review findings on PR #13, each one red before its fix."""

    def test_scan_row_label_is_not_an_address(self):
        # 0x30 is the label of row "30:", not a device (finding 3).
        with mock.patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, SCAN_30_EMPTY_3C_THERE, "")
            self.assertFalse(answers(1, 0x30))
            self.assertTrue(answers(1, 0x3C))

    def test_absent_address_needs_i2cdetect(self):
        # Without i2cdetect nobody checks that 0x3d is empty: skip rather than write an
        # SSD1306 init to whatever might be there (finding 1).
        dev = Path(f"/dev/i2c-{EMPTY_BUS}")
        if not (dev.exists() and os.access(dev, os.R_OK | os.W_OK)):
            self.skipTest(f"{dev} not accessible")
        with mock.patch("shutil.which", return_value=None), \
                mock.patch(f"{__name__}.run_tool", side_effect=AssertionError("tool ran")):
            result = unittest.TestResult()
            CliTest("test_absent_address_is_remote_io_error").run(result)
        self.assertEqual(len(result.skipped), 1, result.errors + result.failures)

    def test_script_present_ignores_row_labels(self):
        # present() with a fake i2cdetect: 0x30 must not match the "30:" label (finding 2).
        text = SCRIPT.read_text()
        func = re.search(r"^present\(\) \{.*?^\}", text, re.M | re.S).group(0)
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "i2cdetect"
            fake.write_text("#!/bin/sh\ncat <<'EOF'\n" + SCAN_30_EMPTY_3C_THERE + "EOF\n")
            fake.chmod(0o755)
            env = dict(os.environ, PATH=f"{d}:{os.environ['PATH']}")
            for addr, want in (("0x30", 1), ("0x3c", 0)):
                with self.subTest(addr=addr):
                    r = subprocess.run(["bash", "-c", f"{func}\nBUS=1 ADDR={addr} present"], env=env)
                    self.assertEqual(r.returncode, want)

    def test_no_terminal_is_exit_2(self):
        # /dev/tty is mode 666, so -r passes even with no controlling terminal; the check
        # has to open it (finding 4). start_new_session drops the controlling terminal.
        r = subprocess.run(["bash", str(SCRIPT), "--bus", "250"], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=120, start_new_session=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("needs a terminal", r.stderr)

    def test_scramble_is_seen_before_the_repair(self):
        # A scramble that changed nothing would make "looks as before" pass trivially; the
        # person confirms the panel changed before oled_probe runs (finding 5).
        text = SCRIPT.read_text()
        block = text[text.index("i2ctransfer -y"):text.index("== absent address")]
        changed = re.search(r'ask "[^"]*(?i:inverse|inverted|mirrored)[^"]*"', block)
        self.assertIsNotNone(changed, "no question about the scrambled panel")
        self.assertLess(changed.start(), block.index("show edge"))

    def test_scramble_in_two_visible_stages(self):
        # Rerun 2026-10-13: the one-shot scramble (inverse + flips + contrast 0) left the
        # panel black, so nobody could tell which part took effect. Stage 1 (inverse,
        # upside down, vertical addressing) must be confirmed as such, then contrast 0 as
        # "dark", each before the repair.
        text = SCRIPT.read_text()
        block = text[text.index("== scrambled state"):text.index("== absent address")]
        sends = [m.start() for m in re.finditer(r"i2ctransfer -y", block)]
        self.assertEqual(len(sends), 2, "expected two i2ctransfer stages")
        first, second = block[sends[0]:sends[1]], block[sends[1]:]
        self.assertNotIn("0x81", first.splitlines()[0])
        self.assertIn("0x81 0x00", second.splitlines()[0])
        self.assertRegex(first, r'ask "[^"]*(?i:inverted|lit|white)[^"]*(?i:upside down)[^"]*"')
        self.assertRegex(second, r'ask "[^"]*(?i:dark|dim)[^"]*"')
        self.assertLess(re.search(r"ask ", second).start(), second.index("show edge"))

    def test_scramble_starts_from_a_known_picture(self):
        # Rerun 2026-10-13: stage 1 looked black because the hardware unit tests end with
        # mode "off" (display OFF); the scramble has to start from EDGE on screen.
        text = SCRIPT.read_text()
        block = text[text.index("== scrambled state"):text.index("== absent address")]
        first_send = block.index("i2ctransfer -y")
        self.assertRegex(block[:first_send], r"\btool edge\b")

    def test_stage_1_question_matches_what_the_panel_shows(self):
        # Measured one command at a time: A7 = black text on white, C0 = upside down,
        # A0 = mirrored at once (not only for later data), 20 01 = no visible change.
        text = SCRIPT.read_text()
        q = re.search(r'ask "Stage 1:[^"]*"', text).group(0)
        for word in ("white", "upside down", "mirrored"):
            self.assertIn(word, q)
        self.assertNotIn("only applies to data written later", text)

    def test_answer_timeout_leaves_time_to_look(self):
        # 120 s ran out while the person was checking a black panel up close.
        m = re.search(r"^ANSWER_TIMEOUT=(\d+)", SCRIPT.read_text(), re.M)
        self.assertGreaterEqual(int(m.group(1)), 300)

    def test_write_msg_takes_the_bytes_by_reference(self):
        # Finding 9: no copy of each message.
        self.assertRegex(SRC.read_text(), r"bool write_msg\(int fd, std::uint16_t addr, std::vector<std::uint8_t> &bytes\)")

    def test_build_runs_once_per_test_run(self):
        # Finding 10: the three classes share one configure + build.
        with mock.patch("subprocess.run") as run:
            build()
            build()
        self.assertLessEqual(run.call_count, 2)


class VerifyScriptTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), f"{SCRIPT} missing")
        self.text = SCRIPT.read_text()

    def test_syntax(self):
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)

    def test_has_a_power_cycle_check(self):
        # Acceptance: after the OLED loses power the tool must bring it up again.
        self.assertIn("--no-power-cycle", self.text)

    def test_power_cycle_disconnects_the_whole_module(self):
        # Measured 2026-10-13: with only VCC unplugged the SSD1306 still ACKed (exit 0) -
        # most likely fed through the SDA/SCL pull-ups. All four wires have to come off.
        self.assertRegex(self.text, r"(?i)all four wires")
        self.assertNotRegex(self.text, r"(?i)unplug the OLED's VCC wire")

    def test_power_on_reset_is_seen_before_the_tool_runs(self):
        # Proof the chip really lost power: after power-on reset the display is OFF (0xAE is
        # the reset state), so the panel is dark until oled_probe sends anything. Ask that
        # first, then run the tool.
        cycle = self.text[self.text.index("if [[ $CYCLE -eq 1 ]]"):]
        dark = re.search(r"ask \"[^\"]*(?i:dark)[^\"]*\"", cycle)
        self.assertIsNotNone(dark, "no 'dark?' question in the power-cycle block")
        self.assertLess(dark.start(), cycle.index("show edge"))

    def test_scrambles_state_with_an_independent_tool(self):
        # i2ctransfer leaves the controller inverted / mirrored / in vertical mode; the next
        # oled_probe run must undo all of it by itself.
        self.assertIn("i2ctransfer", self.text)
        for cmd in ("0xA7", "0xA0", "0xC0", "0x20 0x01"):
            self.assertIn(cmd, self.text)

    def test_reads_answers_with_a_timeout(self):
        self.assertRegex(self.text, r"read -r -t \"?\$?\w+")

    def test_exit_codes_documented(self):
        self.assertIn("0 = all checks passed, 1 = a check failed, 2 = environment/usage", self.text)


if __name__ == "__main__":
    unittest.main()
