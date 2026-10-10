"""Checks for apps/edge_gpio_blink.cpp, the Step 4-a userspace GPIO blinker.

The program takes no arguments: /dev/gpiochip0 line 105 (header pin 29), five
500 ms on / 500 ms off cycles. Every test drives the pin, so they only run with
EDGE_GPIO_HW=1, which scripts/verify_edge_gpio_blink.sh sets. The binary is
built with CMake into build/.
"""

import os
from pathlib import Path
import re
import signal
import subprocess
import time
import unittest


REPO = Path(__file__).resolve().parents[1]
BUILD = REPO / "build"
CLI = BUILD / "edge_gpio_blink"
CHIP = Path("/dev/gpiochip0")
LINE = 105
HW = os.environ.get("EDGE_GPIO_HW") == "1"


def cli(timeout=30):
    return subprocess.run([str(CLI)], text=True, capture_output=True, timeout=timeout)


def line_info():
    out = subprocess.run(["gpioinfo", CHIP.name], text=True, capture_output=True, check=True).stdout
    m = re.search(rf"^\s*line\s+{LINE}:(.*)$", out, re.M)
    return m.group(1) if m else ""


@unittest.skipUnless(HW, "drives header pin 29; set EDGE_GPIO_HW=1 (verify_edge_gpio_blink.sh does)")
class HardwareTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Built only when the tests run, so a skipped run needs no compiler.
        subprocess.run(["cmake", "-S", str(REPO), "-B", str(BUILD)], check=True, capture_output=True)
        subprocess.run(["cmake", "--build", str(BUILD), "--target", "edge_gpio_blink"],
                       check=True, capture_output=True)

    def start(self):
        proc = subprocess.Popen([str(CLI)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.reap, proc)
        deadline = time.monotonic() + 2
        while '"edge_gpio_blink"' not in line_info() and time.monotonic() < deadline:
            time.sleep(0.02)
        return proc

    @staticmethod
    def reap(proc):
        # A hung first instance must not keep line 105 for the next test.
        if proc.poll() is None:
            proc.kill()
        proc.communicate()

    def setUp(self):
        self.assertIn("unused", line_info(), "line 105 must be free before the test")

    def test_blinks_then_releases_the_line(self):
        res = cli()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("unused", line_info())

    def test_line_is_owned_while_running_and_second_user_gets_busy(self):
        first = self.start()
        info = line_info()
        self.assertIn('"edge_gpio_blink"', info)
        self.assertIn("output", info)

        second = cli()
        self.assertEqual(second.returncode, 1)
        self.assertIn("request line 105", second.stderr)
        self.assertIn("busy", second.stderr)

        _, err = first.communicate(timeout=10)
        self.assertEqual(first.returncode, 0, err)
        self.assertIn("unused", line_info())

    def test_signal_while_lit_ends_low_and_releases(self):
        # Tegra keeps the last value after release, so a signal must not end the
        # program with the LED on: it stops the loop, writes 0, then releases.
        for sig in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(sig=sig.name):
                proc = self.start()
                time.sleep(0.2)  # inside the first 500 ms high half
                t0 = time.monotonic()
                proc.send_signal(sig)
                _, err = proc.communicate(timeout=5)
                self.assertLess(time.monotonic() - t0, 1.0)
                self.assertEqual(proc.returncode, 1, err)
                self.assertIn("interrupted", err)
                self.assertIn("unused", line_info())

if __name__ == "__main__":
    unittest.main()
