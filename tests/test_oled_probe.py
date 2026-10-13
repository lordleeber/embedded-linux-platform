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
import unittest


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


def build():
    subprocess.run(["cmake", "-S", str(REPO), "-B", str(BUILD)], check=True, capture_output=True)
    subprocess.run(["cmake", "--build", str(BUILD), "--target", "oled_probe", "test_ssd1306"],
                   check=True, capture_output=True)


def run_tool(*args):
    return subprocess.run([str(TOOL), *args], capture_output=True, text=True, timeout=10)


def answers(bus, addr):
    """True when i2cdetect (read-byte probe) sees a device at addr on bus."""
    out = subprocess.run(["i2cdetect", "-y", "-r", str(bus), hex(addr), hex(addr)],
                         capture_output=True, text=True, timeout=10).stdout
    return re.search(rf"\b{addr:02x}\b", out.split("\n", 1)[1] if "\n" in out else "") is not None


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
        if shutil.which("i2cdetect") and answers(EMPTY_BUS, EMPTY_ADDR):
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


class VerifyScriptTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), f"{SCRIPT} missing")
        self.text = SCRIPT.read_text()

    def test_syntax(self):
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)

    def test_has_a_power_cycle_check(self):
        # Acceptance: after the OLED loses power the tool must bring it up again.
        self.assertIn("--no-power-cycle", self.text)
        self.assertRegex(self.text, r"(?i)unplug.*VCC")

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
