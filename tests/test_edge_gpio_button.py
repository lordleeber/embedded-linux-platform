"""Checks for apps/edge_gpio_button.cpp, the Step 5-a userspace button reader.

The program asks gpiolib-cdev for edge events on /dev/gpiochip0 line 43 (header
pin 33) through the GPIO v2 uAPI and prints one line per debounced edge, in the
same format as Step 5-b's edge_button_wait. The source checks follow
<linux/gpio.h>: EDGE_RISING is "inactive to active", so with ACTIVE_LOW a rising
edge is a press. Hardware tests need no press (the program just blocks) and run
only with EDGE_GPIO_HW=1, which scripts/verify_edge_gpio_button.sh sets.
"""

import os
from pathlib import Path
import re
import signal
import subprocess
import time
import unittest


REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "apps" / "edge_gpio_button.cpp"
BUILD = REPO / "build"
CLI = BUILD / "edge_gpio_button"
CHIP = Path("/dev/gpiochip0")
LINE = 43
HW = os.environ.get("EDGE_GPIO_HW") == "1"


def build():
    subprocess.run(["cmake", "-S", str(REPO), "-B", str(BUILD)], check=True, capture_output=True)
    subprocess.run(["cmake", "--build", str(BUILD), "--target", "edge_gpio_button"],
                   check=True, capture_output=True)


def line_info():
    out = subprocess.run(["gpioinfo", CHIP.name], text=True, capture_output=True, check=True).stdout
    m = re.search(rf"^\s*line\s+{LINE}:(.*)$", out, re.M)
    return m.group(1) if m else ""


class SourceContractTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SRC.is_file(), f"{SRC} missing")
        self.src = SRC.read_text()

    def test_requests_line_43_through_the_v2_uapi(self):
        self.assertIn("GPIO_V2_GET_LINE_IOCTL", self.src)
        self.assertRegex(self.src, r"offsets\[0\]\s*=\s*43\b")
        self.assertIn("<linux/gpio.h>", self.src)
        self.assertNotIn("gpiod.h", self.src)  # no libgpiod, like Step 4-a

    def test_input_active_low_with_both_edges(self):
        for flag in ("GPIO_V2_LINE_FLAG_INPUT", "GPIO_V2_LINE_FLAG_ACTIVE_LOW",
                     "GPIO_V2_LINE_FLAG_EDGE_RISING", "GPIO_V2_LINE_FLAG_EDGE_FALLING"):
            self.assertIn(flag, self.src, flag)

    def test_asks_gpiolib_for_a_20ms_debounce(self):
        # Same 20 ms as edge_button.c, so the two versions can be compared.
        self.assertIn("GPIO_V2_LINE_ATTR_ID_DEBOUNCE", self.src)
        self.assertRegex(self.src, r"debounce_period_us\s*=\s*20000\b")

    def test_rising_edge_is_reported_as_pressed(self):
        self.assertRegex(self.src, r"GPIO_V2_LINE_EVENT_RISING_EDGE\s*\?\s*\"pressed\"|"
                                   r"pressed\s*=\s*ev\.id\s*==\s*GPIO_V2_LINE_EVENT_RISING_EDGE")

    def test_reads_whole_line_events(self):
        self.assertIn("gpio_v2_line_event", self.src)
        self.assertRegex(self.src, r"read\(\s*req\.fd\s*,")

    def test_signal_handler_only_sets_a_flag(self):
        # Step 5-b's review lesson: a signal between reads must not be lost.
        self.assertIn("volatile std::sig_atomic_t", self.src)
        self.assertNotRegex(self.src, r"sa_flags\s*=[^;]*SA_RESTART")


class CliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build()

    def run_cli(self, *args, env=None):
        return subprocess.run([str(CLI), *args], text=True, capture_output=True, env=env, timeout=10)

    def test_usage_errors_exit_2(self):
        for args in (("0",), ("-1",), ("x",), ("1", "2"), ("1x",)):
            with self.subTest(args=args):
                res = self.run_cli(*args)
                self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
                self.assertIn("usage", res.stderr)

    def test_missing_chip_exits_1(self):
        res = self.run_cli("1", env={"EDGE_GPIO_CHIP": "/nonexistent/gpiochip0"})
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("/nonexistent/gpiochip0", res.stderr)


@unittest.skipUnless(HW, "requests gpiochip0 line 43; set EDGE_GPIO_HW=1 (verify_edge_gpio_button.sh does)")
class HardwareTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build()

    def setUp(self):
        info = line_info()
        if "unused" not in info:
            self.fail(f"line {LINE} is busy (edge_button.ko loaded?): {info}")

    def start(self, *args):
        proc = subprocess.Popen([str(CLI), *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.reap, proc)
        deadline = time.monotonic() + 2
        while '"edge_gpio_button"' not in line_info() and time.monotonic() < deadline:
            time.sleep(0.02)
        return proc

    @staticmethod
    def reap(proc):
        if proc.poll() is None:
            proc.kill()
        proc.communicate()

    def test_line_is_held_as_active_low_input_while_waiting(self):
        self.start("1")
        info = line_info()
        self.assertIn('"edge_gpio_button"', info)
        self.assertRegex(info, r"\binput\b.*\bactive-low\b")

    def test_no_event_without_a_press(self):
        # Measured: for ~20 ms after the request the line reads "pressed", then settles,
        # and gpiolib reports that as an edge ("released") nobody made. Nobody touches the
        # button during these tests, so the program must still be waiting.
        proc = self.start("1")
        time.sleep(0.5)
        if proc.poll() is not None:
            self.fail("exited without a press: " + proc.communicate()[0])

    def test_second_instance_gets_busy(self):
        self.start("1")
        res = subprocess.run([str(CLI), "1"], text=True, capture_output=True, timeout=5)
        self.assertEqual(res.returncode, 1)
        self.assertIn("busy", res.stderr)

    def test_waiting_costs_no_cpu(self):
        proc = self.start("1")
        time.sleep(1.5)
        fields = Path(f"/proc/{proc.pid}/stat").read_text().rsplit(")", 1)[1].split()
        state, ticks = fields[0], int(fields[11]) + int(fields[12])  # utime + stime
        self.assertEqual(state, "S")
        self.assertLessEqual(ticks, 1)

    def test_signals_end_the_wait_and_release_the_line(self):
        for sig in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(sig=sig.name):
                proc = self.start("1")
                time.sleep(0.2)
                proc.send_signal(sig)
                out, err = proc.communicate(timeout=2)
                self.assertEqual(proc.returncode, 1)
                self.assertIn("interrupted", err)
                self.assertIn("unused", line_info())


if __name__ == "__main__":
    unittest.main()
