"""Hardware-free checks for Step 10-c: build/telemetry_display against a fake hwmon tree.

The fake tree has the shape of /sys/class/hwmon (hwmonN/name, in1_input, curr1_input,
power1_input, as Step 8's edge_ina219 exposes them) and a regular file stands in for
/dev/edge_oled. The expected picture of each frame is drawn by Step 10-b's
`edge_oled_ctl text`, so this checks the app against the tool the panel was verified with.
"""

import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
import unittest


REPO = Path(__file__).resolve().parents[1]
BUILD = REPO / "build"
APP = BUILD / "telemetry_display"
CTL = BUILD / "edge_oled_ctl"
VECTORS = BUILD / "test_telemetry"
VERIFY = REPO / "scripts" / "verify_telemetry_display.sh"
FRAME = 1024

_built = False


def build():
    global _built
    if _built:
        return
    subprocess.run(["cmake", "-S", str(REPO), "-B", str(BUILD)], check=True, capture_output=True)
    r = subprocess.run(["cmake", "--build", str(BUILD), "--target", "telemetry_display",
                        "edge_oled_ctl", "test_telemetry"], capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stdout[-2000:] + r.stderr[-2000:])
    _built = True


def hwmon(root, n, name, **values):
    d = Path(root) / f"hwmon{n}"
    d.mkdir(parents=True)
    (d / "name").write_text(name + "\n")
    for key, v in values.items():
        (d / key).write_text(f"{v}\n")
    return d


def expected_frame(tmp, lines):
    """The frame edge_oled_ctl text draws for these 8 lines (Step 10-b)."""
    ref = Path(tmp) / "ref"
    ref.write_bytes(b"")
    subprocess.run([str(CTL), "--dev", str(ref), "text", *lines], check=True, capture_output=True)
    return ref.read_bytes()


class VectorsTest(unittest.TestCase):
    def test_vectors(self):
        build()
        r = subprocess.run([str(VECTORS)], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stdout)


class AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "hwmon"
        self.root.mkdir()
        self.dev = Path(self.tmp.name) / "dev"
        self.dev.write_bytes(b"")

    def tearDown(self):
        self.tmp.cleanup()

    def run_app(self, *args, timeout=10):
        return subprocess.run([str(APP), "--hwmon-root", str(self.root), "--dev", str(self.dev),
                               *args], capture_output=True, text=True, timeout=timeout)

    def last_frame(self):
        data = self.dev.read_bytes()
        self.assertGreaterEqual(len(data), FRAME)
        self.assertEqual(len(data) % FRAME, 0)
        return data[-FRAME:]

    def test_shows_bat_voltage_current_power(self):
        hwmon(self.root, 0, "pwmfan")                          # a decoy before ours
        hwmon(self.root, 4, "edge_ina219", in1_input=11924, curr1_input=-555,
              power1_input=6530000, in0_input=-6)
        r = self.run_app("--interval-ms", "20", "--count", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.dev.read_bytes()), 3 * FRAME)   # one whole frame per refresh
        want = expected_frame(self.tmp.name, ["BAT: 81.22 %", "V: 11.92 V", "I: -0.56 A", "P:  6.53 W",
                                              "", "", "", "OK #3"])
        self.assertEqual(self.last_frame(), want)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[-1], "#3 V=11924 I=-555 P=6530000 oled=ok")

    def test_no_sensor_is_shown_not_fatal(self):
        hwmon(self.root, 0, "pwmfan")
        r = self.run_app("--interval-ms", "20", "--count", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        want = expected_frame(self.tmp.name, ["BAT: --.-- %", "V: --.-- V", "I: --.-- A", "P: --.-- W",
                                              "", "", "", "NO SENSOR #2"])
        self.assertEqual(self.last_frame(), want)
        self.assertIn("V=- I=- P=-", r.stdout)

    def test_a_failing_channel_goes_stale(self):
        d = hwmon(self.root, 4, "edge_ina219", in1_input=11924, curr1_input=-555,
                  power1_input=6530000)
        p = subprocess.Popen([str(APP), "--hwmon-root", str(self.root), "--dev", str(self.dev),
                              "--interval-ms", "50", "--stale-ms", "200", "--count", "12"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(0.12)
        (d / "curr1_input").unlink()                           # reads fail from here on
        out, err = p.communicate(timeout=10)
        self.assertEqual(p.returncode, 0, err)
        want = expected_frame(self.tmp.name, ["BAT: 81.22 %", "V: 11.92 V", "I: --.-- A", "P:  6.53 W",
                                              "", "", "", "STALE I #12"])
        self.assertEqual(self.last_frame(), want)
        self.assertRegex(err, r"curr1_input")                  # the reason is on stderr
        self.assertLessEqual(err.count("curr1_input"), 1)      # once per failure streak

    def test_sensor_found_again_under_a_new_hwmon_number(self):
        # rmmod / insmod or unbind / bind gives a new hwmonN (Step 8): look it up again.
        d = hwmon(self.root, 4, "edge_ina219", in1_input=11924, curr1_input=-555,
                  power1_input=6530000)
        p = subprocess.Popen([str(APP), "--hwmon-root", str(self.root), "--dev", str(self.dev),
                              "--interval-ms", "50", "--count", "10"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(0.12)
        d.rename(self.root / "hwmon5")
        (self.root / "hwmon5" / "in1_input").write_text("12000\n")
        out, err = p.communicate(timeout=10)
        self.assertEqual(p.returncode, 0, err)
        self.assertIn("V=12000", out.splitlines()[-1])

    def test_oled_write_failure_keeps_running_and_exits_1(self):
        hwmon(self.root, 4, "edge_ina219", in1_input=11924, curr1_input=-555,
              power1_input=6530000)
        self.dev.unlink()                                      # /dev/edge_oled is gone
        r = self.run_app("--interval-ms", "20", "--count", "3")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(len(r.stdout.splitlines()), 3)        # still refreshed 3 times
        self.assertIn(str(self.dev), r.stderr)
        self.assertEqual(r.stderr.count(str(self.dev)), 1)     # reported once, not per tick

    def test_signal_stops_cleanly_and_blanks_the_panel(self):
        hwmon(self.root, 4, "edge_ina219", in1_input=11924, curr1_input=-555,
              power1_input=6530000)
        for sig in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(sig=sig.name):
                self.dev.write_bytes(b"")
                p = subprocess.Popen([str(APP), "--hwmon-root", str(self.root), "--dev",
                                      str(self.dev), "--interval-ms", "1000"],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                deadline = time.monotonic() + 5
                while self.dev.stat().st_size < FRAME and time.monotonic() < deadline:
                    time.sleep(0.02)
                t0 = time.monotonic()
                p.send_signal(sig)
                out, err = p.communicate(timeout=5)
                self.assertLess(time.monotonic() - t0, 0.5)    # not waiting out the 1 s tick
                self.assertEqual(p.returncode, 0, err)
                self.assertEqual(self.last_frame(), bytes(FRAME))  # blank: nothing stale stays

    def test_usage(self):
        for args in (["--interval-ms", "0"], ["--interval-ms", "x"], ["--count", "-1"],
                     ["--stale-ms"], ["--bogus"], ["extra"]):
            with self.subTest(args=args):
                r = self.run_app(*args)
                self.assertEqual(r.returncode, 2)
                self.assertIn("usage:", r.stderr)


class ScopeTest(unittest.TestCase):
    def test_driver_and_renderer_untouched_by_policy(self):
        # phase04: no battery policy in the kernel; this step does not change the OLED driver.
        drv = (REPO / "kernel" / "edge_oled" / "edge_oled.c").read_text()
        self.assertNotRegex(drv, r"(?i)ina219|hwmon|telemetry")
        src = (REPO / "apps" / "telemetry.h").read_text()
        # A percentage from the vendor's voltage formula is shown, but nothing acts on it.
        self.assertNotRegex(src, r"(?i)low.?batt|threshold|alarm|notify|socket")


class VerifyScriptTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(VERIFY.exists(), f"{VERIFY} missing")
        self.text = VERIFY.read_text()

    def test_syntax_and_usage(self):
        r = subprocess.run(["bash", "-n", str(VERIFY)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run(["bash", str(VERIFY), "--bogus"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_root_terminal_cleanup_and_no_leftover_process(self):
        self.assertIn("EUID", self.text)
        self.assertIn("/dev/tty", self.text)
        self.assertIn("trap cleanup EXIT", self.text)
        self.assertIn("setsid", self.text)
        self.assertIn("pgrep", self.text)
        self.assertIn("0 = all checks passed, 1 = a check failed, 2 = environment/usage", self.text)

    def test_values_compared_with_hwmon(self):
        self.assertRegex(self.text, r"in1_input")
        # the person compares BAT with the vendor's formula applied to hwmon's voltage
        self.assertRegex(self.text, r"- 9000\) / 36")
        self.assertRegex(self.text, r"curr1_input")

    def test_sensor_unbind_and_bind(self):
        self.assertIn("INA_DRV=/sys/bus/i2c/drivers/edge_ina219", self.text)
        self.assertRegex(self.text, r"\$INA_DRV/unbind")
        self.assertRegex(self.text, r"\$INA_DRV/bind")
        self.assertIn("NO SENSOR", self.text)

    def test_long_refresh_watch_from_step_10b(self):
        # PR #15 review: every flush re-sends the settings while lit; watch for minutes.
        self.assertIn("--watch-seconds", self.text)
        self.assertIn("WATCH_SEC=30", self.text)     # 3 minutes was too long to stand and look
        self.assertRegex(self.text, r"(?i)flicker")

    def test_signal_shutdown_checked(self):
        self.assertRegex(self.text, r"kill -TERM -- -")
        self.assertRegex(self.text, r"(?i)blank|dark")

    def test_questions_discard_keys_pressed_while_waiting(self):
        # First hardware run: an Enter pressed during the 3-minute watch sat in the tty buffer
        # and answered the next question (empty = no) before the person saw it. Every prompt
        # first drains what is pending on /dev/tty.
        for fn in ("ask", "wait_enter"):
            body = re.search(fn + r"\(\) \{(.*?)\n\}", self.text, re.S)
            self.assertIsNotNone(body, fn)
            self.assertRegex(body.group(1), r"drain_tty")
        drain = re.search(r"drain_tty\(\) \{(.*?)\}", self.text, re.S)
        self.assertIsNotNone(drain)
        self.assertRegex(drain.group(1), r"read -r -t 0")

    def test_oled_unplug_is_optional(self):
        self.assertIn("--no-unplug", self.text)
        self.assertRegex(self.text, r"(?i)all four wires")


if __name__ == "__main__":
    unittest.main()
