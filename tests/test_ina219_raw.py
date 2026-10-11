"""Checks for tools/ina219_raw.cpp, the Step 6-b INA219 reader without any Python library.

The tool opens /dev/i2c-7 through i2c-dev, reads the six INA219 registers with
I2C_RDWR (write the register pointer, repeated start, read two bytes) and
assembles each value MSB first, as the datasheet sends it. It never writes a
register. The decoding lives in tools/ina219_decode.h and is checked by the
C++ test vectors in tests/test_ina219_decode.cpp.
Hardware tests read the real chip on i2c-7 at 0x41, use i2c-tools as the
independent oracle, and run only with EDGE_INA219_HW=1, which
scripts/verify_ina219_raw.sh sets.
"""

import errno
import os
from pathlib import Path
import re
import subprocess
import unittest


REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "tools" / "ina219_raw.cpp"
DECODE = REPO / "tools" / "ina219_decode.h"
BUILD = REPO / "build"
TOOL = BUILD / "ina219_raw"
DECODE_TEST = BUILD / "test_ina219_decode"
# verify_ina219_raw.sh finds the bus by controller name and passes it down (code review, PR #10).
BUS = int(os.environ.get("EDGE_INA219_BUS", "7"))
ADDR = 0x41
HW = os.environ.get("EDGE_INA219_HW") == "1"
REG_LINE = re.compile(r"^0x0([0-5]) (\w+)\s+0x([0-9A-F]{4})$", re.M)


def build():
    subprocess.run(["cmake", "-S", str(REPO), "-B", str(BUILD)], check=True, capture_output=True)
    subprocess.run(["cmake", "--build", str(BUILD), "--target", "ina219_raw", "test_ina219_decode"],
                   check=True, capture_output=True)


def run_tool(*args):
    return subprocess.run([str(TOOL), *args], capture_output=True, text=True, timeout=10)


def registers(stdout):
    """{register number: raw value} from the tool's register table."""
    return {int(n): int(v, 16) for n, _, v in REG_LINE.findall(stdout)}


def i2cget_word(reg):
    """SMBus read word through i2c-tools: the bytes come back LSB first (SMBus convention)."""
    out = subprocess.run(["i2cget", "-y", str(BUS), hex(ADDR), hex(reg), "w"],
                         capture_output=True, text=True, check=True).stdout
    return int(out, 16)


def swap16(v):
    return (v & 0xFF) << 8 | v >> 8


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build()

    def test_decode_vectors_pass(self):
        r = subprocess.run([str(DECODE_TEST)], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stdout)


class SourceContractTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SRC.is_file(), f"{SRC} missing")
        self.src = SRC.read_text()

    def test_uses_i2c_dev_with_i2c_rdwr(self):
        # One I2C_RDWR = pointer write + repeated start + 2-byte read, like the sample's
        # read_i2c_block_data; no SMBus "read word", whose byte order is LSB first.
        self.assertIn("<linux/i2c-dev.h>", self.src)
        self.assertIn("I2C_RDWR", self.src)
        self.assertNotIn("I2C_SMBUS", self.src)
        self.assertNotIn("i2c/smbus.h", self.src)   # libi2c's helpers would hide the byte order

    def test_never_writes_a_register(self):
        # The only write is the one-byte register pointer: a read-only tool must not
        # change what the sample (or the driver later) configured.
        self.assertRegex(self.src, r"\.len\s*=\s*1\b")
        self.assertNotRegex(self.src, r"\.len\s*=\s*3\b")
        # Nor any other way to put bytes on the bus (code review, PR #10).
        self.assertNotIn("I2C_SLAVE", self.src)
        self.assertNotRegex(self.src, r"(?<![\w.])write\s*\(")

    def test_partial_transfer_is_an_error_with_errno_set(self):
        # ioctl(I2C_RDWR) may return a positive count < 2 without touching errno; the
        # message must not then say "Success" (code review, PR #10).
        self.assertRegex(self.src, r"errno\s*=\s*EIO")

    def test_byte_order_is_explicit(self):
        # Assemble with be16(), never by copying the two bytes into a uint16_t (host order).
        self.assertIn("be16(", self.src)
        self.assertNotRegex(self.src, r"memcpy\s*\(\s*&")
        self.assertNotIn("ntohs", self.src)

    def test_decoder_is_integer_only(self):
        # Step 7 moves the same arithmetic into the kernel, which has no floating point.
        text = DECODE.read_text()
        self.assertNotRegex(text, r"\b(double|float)\b")


class CliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build()

    def test_bad_argument_is_a_usage_error(self):
        r = run_tool("--bogus")
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage", r.stderr)

    def test_address_must_be_7_bit(self):
        for bad in ("0x80", "zz", "0x41x", "-1"):
            r = run_tool("--addr", bad)
            self.assertEqual(r.returncode, 2, bad)

    def test_missing_bus_is_exit_1(self):
        r = run_tool("--bus", "99")
        self.assertEqual(r.returncode, 1)
        self.assertIn("/dev/i2c-99", r.stderr)

    def test_bus_is_decimal(self):
        # i2c-N is a decimal number: a leading zero is not octal (code review, PR #10).
        # stderr names the bus whether it fails at open() or at the first read.
        for arg, dev in (("08", "/dev/i2c-8"), ("010", "/dev/i2c-10")):
            r = run_tool("--bus", arg, "--addr", "0x45")
            self.assertEqual(r.returncode, 1, arg)
            self.assertRegex(r.stderr, re.escape(dev) + r"(?!\d)", arg)
        r = run_tool("--bus", "0x7")
        self.assertEqual(r.returncode, 2)


class VerifyScriptTest(unittest.TestCase):
    SCRIPT = REPO / "scripts" / "verify_ina219_raw.sh"

    def test_bad_argument_is_a_usage_error(self):
        r = subprocess.run(["bash", str(self.SCRIPT), "--bogus"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("usage", r.stderr)

    def test_finds_the_bus_by_controller_name(self):
        # i2c-N numbers are handed out at boot; c250000.i2c is header pins 3/5.
        text = self.SCRIPT.read_text()
        self.assertIn("i2cdetect -l", text)
        self.assertIn("c250000.i2c", text)

    def test_scans_with_read_byte_probing(self):
        # Step 6-a: Tegra i2c has no SMBus Quick Write; plain `i2cdetect -y 7` skips 0x41.
        self.assertRegex(self.SCRIPT.read_text(), r"i2cdetect -y -r")

    def test_unit_tests_get_the_bus_found_by_name(self):
        # Not a hard-coded 7 inside the tests either (code review, PR #10).
        self.assertRegex(self.SCRIPT.read_text(), r'EDGE_INA219_BUS="\$BUS"')

    def test_tool_failure_while_unplugged_counts(self):
        # An I/O error in the sampling loop gives empty output, which awk reads as 0 mA;
        # it must be a FAIL instead (code review, PR #10).
        self.assertRegex(self.SCRIPT.read_text(), r'snap="\$\(tool\)"\s*\|\|\s*\{?\s*fail')

    def test_ctrl_c_while_unplugged_says_plug_back_in(self):
        # Interrupting the unplug window must not leave the Jetson on battery unnoticed.
        text = self.SCRIPT.read_text()
        m = re.search(r"^on_int\(\)\s*\{.*?^\}", text, re.M | re.S)
        self.assertIsNotNone(m, "no on_int() handler")
        self.assertIn("PLUG", m.group(0))
        self.assertRegex(text, r"trap on_int INT")

    def test_failed_i2cget_leaves_no_error_text_as_a_value(self):
        # The error text must not reach swap16's arithmetic later (code review, PR #10).
        self.assertRegex(self.SCRIPT.read_text(), r"unset 'word\[\$reg\]'")

    def test_i2cset_writes_back_the_value_already_there(self):
        # The i2cset round trip must not change the configuration: it writes Calibration
        # with what was just read (word mode, so LSB first), never a constant.
        text = self.SCRIPT.read_text()
        self.assertRegex(text, r"i2cset -y \S+ \S+ 0x05 \"?\$\w+\"? w")


@unittest.skipUnless(HW, "set EDGE_INA219_HW=1 (scripts/verify_ina219_raw.sh)")
class HardwareTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build()

    def read_all(self):
        r = run_tool("--bus", str(BUS))
        self.assertEqual(r.returncode, 0, r.stderr)
        regs = registers(r.stdout)
        self.assertEqual(sorted(regs), [0, 1, 2, 3, 4, 5], r.stdout)
        return r.stdout, regs

    def test_registers_are_not_a_dead_bus(self):
        # A bus with nothing pulling SDA low reads 0xFFFF everywhere; all zeros is as suspect.
        _, regs = self.read_all()
        self.assertFalse(all(v == 0xFFFF for v in regs.values()), regs)
        self.assertFalse(all(v == 0x0000 for v in regs.values()), regs)

    def test_matches_i2cget_after_the_byte_swap(self):
        # Config and Calibration do not change between the two reads; i2cget's word read
        # shows them LSB first, so the tool's value is i2cget's swapped.
        _, regs = self.read_all()
        for reg in (0x00, 0x05):
            self.assertEqual(regs[reg], swap16(i2cget_word(reg)), hex(reg))

    def test_bus_voltage_is_a_3s_battery(self):
        out, regs = self.read_all()
        m = re.search(r"^bus voltage:\s+(\d+\.\d{3}) V", out, re.M)
        self.assertIsNotNone(m, out)
        volts = float(m.group(1))
        self.assertTrue(9.0 <= volts <= 12.8, volts)
        self.assertAlmostEqual(volts, (regs[2] >> 3) * 0.004, places=6)

    def test_absent_address_is_an_io_error(self):
        # What the tool reports when the module is unplugged: no ACK -> EREMOTEIO.
        r = run_tool("--bus", str(BUS), "--addr", "0x45")
        self.assertEqual(r.returncode, 1)
        self.assertIn(os.strerror(errno.EREMOTEIO), r.stderr)
        self.assertIn("0x45", r.stderr)


if __name__ == "__main__":
    unittest.main()
