"""Tests for scripts/pad_pin29.py against a fake /dev/mem (a sparse file).

Expected register values come from the board, not from the script:
debugfs pinconf for soc_gpio32_pq5 read "pull=2 tristate=1 enable-input=1
function=rsvd0" at boot, and devmem read 0x00000458 at 0x02430068 in the same
boot. Writing 0x00000400 (tristate, input and pull cleared) lit the LED.
"""

from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "pad_pin29.py"
REG = 0x02430068
BOOT = 0x00000458
OPEN = 0x00000400


class PadPin29Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mem = Path(self.tmp.name) / "mem"
        with open(self.mem, "wb") as f:
            f.truncate(REG + 4096)

    def tearDown(self):
        self.tmp.cleanup()

    def poke(self, value):
        with open(self.mem, "r+b") as f:
            f.seek(REG)
            f.write(struct.pack("<I", value))

    def peek(self):
        with open(self.mem, "rb") as f:
            f.seek(REG)
            return struct.unpack("<I", f.read(4))[0]

    def run_script(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), "--mem", str(self.mem), *args],
                              capture_output=True, text=True)

    def test_show_decodes_boot_value(self):
        self.poke(BOOT)
        res = self.run_script("show")
        self.assertEqual(res.returncode, 0, res.stderr)
        for part in ("0x00000458", "tristate=1", "input=1", "pull=up"):
            self.assertIn(part, res.stdout)
        self.assertEqual(self.peek(), BOOT)

    def test_open_clears_tristate_input_and_pull(self):
        self.poke(BOOT)
        res = self.run_script("open")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.peek(), OPEN)

    def test_open_twice_is_a_noop(self):
        self.poke(OPEN)
        res = self.run_script("open")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.peek(), OPEN)

    def test_close_restores_boot_value(self):
        self.poke(OPEN)
        res = self.run_script("close")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.peek(), BOOT)

    def test_bits_outside_the_three_fields_are_kept(self):
        self.poke(0xABC00458)
        self.assertEqual(self.run_script("open").returncode, 0)
        self.assertEqual(self.peek(), 0xABC00400)
        self.assertEqual(self.run_script("close").returncode, 0)
        self.assertEqual(self.peek(), 0xABC00458)

    def test_unexpected_low_byte_is_refused_and_untouched(self):
        # Another function selected, or a wrong address: never write.
        for value in (0x00000459, 0x0000045C, 0x00000000 | 0x10, 0xFFFFFFFF):
            with self.subTest(value=hex(value)):
                self.poke(value)
                for cmd in ("open", "close"):
                    res = self.run_script(cmd)
                    self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
                    self.assertEqual(self.peek(), value)

    def test_usage_and_file_errors_exit_2(self):
        self.poke(BOOT)
        self.assertEqual(self.run_script().returncode, 2)
        self.assertEqual(self.run_script("toggle").returncode, 2)
        res = subprocess.run([sys.executable, str(SCRIPT), "--mem", str(self.mem) + ".nope", "show"],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)


if __name__ == "__main__":
    unittest.main()
