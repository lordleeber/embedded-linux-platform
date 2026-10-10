"""Hardware-free checks for Step 5-b: the button DT node, edge_button.c and the event header.

Expected values come from the SoC binding and NVIDIA's own header overlay, not
from our overlay: header pin 33 is GPIO13 = PH.00 (Jetson.GPIO pin table for
Orin Nano), so TEGRA234_MAIN_GPIO(H, 0) = 7 * 8 + 0 = 56 (PORT_H = 7 in the
binding header), and /boot/tegra234-p3767-0000+p3509-a02-hdr40.dtbo names its
pad "soc_gpio21_ph0".
The button pulls the pin to GND when pressed, so the GPIO is active-low
(GPIO_ACTIVE_LOW = 1) and the pad needs a pull-up (TEGRA_PIN_PULL_UP = 2).
"""

import fcntl
import os
from pathlib import Path
import re
import signal
import struct
import shutil
import subprocess
import tempfile
import threading
import time
import unittest


REPO = Path(__file__).resolve().parents[1]
DTS_DIR = REPO / "dts"
DRIVER = REPO / "kernel" / "edge_button" / "edge_button.c"
HEADER = REPO / "include" / "edge_button.h"
BUILD = REPO / "build"
WAIT = BUILD / "edge_button_wait"
KDIR = Path("/lib/modules") / subprocess.run(
    ["uname", "-r"], capture_output=True, text=True, check=True).stdout.strip() / "build"
BINDING = KDIR / "include" / "dt-bindings" / "gpio" / "tegra234-gpio.h"

COMPATIBLE = "edge,gpio-button"
PH0_CELL = 7 * 8 + 0


def decompile(dtbo):
    return subprocess.run(["dtc", "-q", "-I", "dtb", "-O", "dts", str(dtbo)],
                          capture_output=True, text=True, check=True).stdout


def function_body(src, name):
    """Return the body of a top-level C function without its comments (brace matching)."""
    m = re.search(r"^\w[^;{]*\b" + re.escape(name) + r"\([^;{]*\)\s*\{", src, re.M)
    if not m:
        return None
    depth, i = 1, m.end()
    while depth:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    return re.sub(r"/\*.*?\*/", "", src[m.end():i - 1], flags=re.S)  # code only, no comments


@unittest.skipUnless(shutil.which("dtc") and shutil.which("cpp") and BINDING.exists(),
                     "needs dtc, cpp and the kernel dt-bindings headers")
class ButtonOverlayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        out = Path(cls.tmp.name)
        cls.build = subprocess.run(["make", "-s", "-C", str(DTS_DIR), f"OUT={out}"],
                                   capture_output=True, text=True)
        cls.dtbos = [out / "edge-gpio-overlay.dtbo", out / "edge-gpio-overlay-active-low.dtbo"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.assertEqual(self.build.returncode, 0, self.build.stderr)

    def node(self, dts):
        m = re.search(r"edge-button \{(.*?)\n\t\t\t\};", dts, re.S)
        self.assertIsNotNone(m, "no edge-button node in the overlay")
        return m.group(1)

    def test_node_has_driver_compatible_in_both_variants(self):
        # The LED polarity flag must not change the button: both dtbos carry it.
        for dtbo in self.dtbos:
            with self.subTest(dtbo=dtbo.name):
                self.assertIn(f'compatible = "{COMPATIBLE}";', self.node(decompile(dtbo)))

    def test_button_gpio_is_ph0_active_low(self):
        for dtbo in self.dtbos:
            with self.subTest(dtbo=dtbo.name):
                m = re.search(r"button-gpios = <(0x[0-9a-f]+) (0x[0-9a-f]+) (0x[0-9a-f]+)>;",
                              self.node(decompile(dtbo)))
                self.assertIsNotNone(m)
                self.assertEqual(int(m.group(2), 16), PH0_CELL)
                self.assertEqual(int(m.group(3), 16), 1)  # GPIO_ACTIVE_LOW

    def test_button_gpio_phandle_is_a_fixup_to_base_gpio(self):
        dts = decompile(self.dtbos[0])
        fixups = re.search(r"__fixups__ \{(.*?)\};", dts, re.S).group(1)
        gpio = re.search(r'gpio = (".*?");', fixups)
        self.assertIsNotNone(gpio)
        self.assertRegex(gpio.group(1), r"/fragment@\d+/__overlay__/edge-button:button-gpios:0")

    def test_pad_state_is_input_with_pull_up_and_output_off(self):
        # Pressed = pin shorted to GND: the pad must never drive (tristate=1), must
        # sample the pin (enable-input=1) and must idle high (pull-up).
        dts = decompile(self.dtbos[0])
        node = self.node(dts)
        self.assertIn('pinctrl-names = "default";', node)
        ref = re.search(r"pinctrl-0 = <(0x[0-9a-f]+)>;", node)
        self.assertIsNotNone(ref, node)
        state = re.search(r"\{\s*phandle = <" + ref.group(1) + r">;(.*?)\n\t\t\t\};", dts, re.S)
        self.assertIsNotNone(state, "pinctrl-0 does not point at a state node in this overlay")
        body = state.group(1)
        self.assertIn('nvidia,pins = "soc_gpio21_ph0";', body)
        self.assertIn("nvidia,pull = <0x02>;", body)
        self.assertIn("nvidia,tristate = <0x01>;", body)
        self.assertIn("nvidia,enable-input = <0x01>;", body)

    def test_pad_name_matches_nvidia_header_overlay(self):
        vendor = Path("/boot/tegra234-p3767-0000+p3509-a02-hdr40.dtbo")
        if not vendor.exists():
            self.skipTest(f"{vendor} not present")
        pin33 = re.search(r"hdr40-pin33 \{(.*?)\};", decompile(vendor), re.S)
        self.assertIsNotNone(pin33)
        self.assertIn('nvidia,pins = "soc_gpio21_ph0";', pin33.group(1))

    def test_led_node_is_unchanged(self):
        # Step 4's LED must still be there with its own GPIO and pad.
        dts = decompile(self.dtbos[0])
        self.assertRegex(dts, r'edge-led \{[^}]*compatible = "edge,gpio-led"')
        self.assertIn('nvidia,pins = "soc_gpio32_pq5";', dts)


class ButtonDriverContractTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(DRIVER.is_file(), f"{DRIVER} missing")
        self.src = DRIVER.read_text()

    def test_of_match_uses_overlay_compatible(self):
        self.assertIn(f'.compatible = "{COMPATIBLE}"', self.src)
        self.assertIn(f'compatible = "{COMPATIBLE}"', (DTS_DIR / "edge-gpio-overlay.dts").read_text())

    def test_requests_button_as_input(self):
        # devm_gpiod_get(dev, "button", ...) looks up the DT property "button-gpios".
        self.assertRegex(self.src, r'devm_gpiod_get\(\s*\w+\s*,\s*"button"\s*,\s*GPIOD_IN\s*\)')

    def test_irq_comes_from_the_gpio_on_both_edges(self):
        self.assertIn("gpiod_to_irq(", self.src)
        self.assertRegex(self.src, r"IRQF_TRIGGER_RISING\s*\|\s*IRQF_TRIGGER_FALLING")
        self.assertRegex(self.src, r"devm_request(_threaded)?_irq\(")

    def test_hard_irq_handler_does_not_sleep(self):
        name = re.search(r"devm_request_irq\(\s*\w+\s*,\s*\w+\s*,\s*(\w+)", self.src)
        self.assertIsNotNone(name, "devm_request_irq(dev, irq, <handler>, ...) not found")
        body = function_body(self.src, name.group(1))
        self.assertIsNotNone(body, name.group(1))
        for sleeping in ("_cansleep", "mutex_lock", "msleep", "GFP_KERNEL", "copy_to_user",
                         "wait_event", "cancel_delayed_work_sync"):
            self.assertNotIn(sleeping, body, sleeping)

    def test_reader_sleeps_on_a_wait_queue_and_is_woken(self):
        self.assertIn("wait_event_interruptible(", self.src)
        self.assertIn("wake_up_interruptible(", self.src)
        self.assertIn("O_NONBLOCK", self.src)

    def test_irq_is_requested_before_the_initial_state_is_read(self):
        # Reading first leaves a gap: a press there raises no IRQ, "last" is stale, and the
        # whole press/release pair vanishes without a seq gap (code review, PR #7).
        probe = function_body(self.src, "edge_button_probe")
        self.assertIsNotNone(probe)
        self.assertLess(probe.index("devm_request_irq("), probe.index("gpiod_get_value_cansleep("))

    def test_event_leaves_the_queue_only_after_copy_to_user(self):
        # kfifo_get before copy_to_user loses the event on EFAULT: peek, copy, then skip.
        body = function_body(self.src, "edge_button_read")
        self.assertIsNotNone(body)
        self.assertNotIn("kfifo_get(", body)
        self.assertIn("kfifo_peek(", body)
        self.assertLess(body.index("copy_to_user("), body.index("kfifo_skip("))

    def test_timestamp_is_taken_at_the_edge_not_in_the_work(self):
        # The work runs >= 20 ms after the last edge; the event should carry the time of
        # the first edge of the burst, taken in the IRQ handler.
        self.assertIn("ktime_get_ns(", function_body(self.src, "edge_button_irq"))
        self.assertNotIn("ktime_get", function_body(self.src, "edge_button_work"))

    def test_pending_debounce_work_is_cancelled_on_teardown(self):
        self.assertIn("cancel_delayed_work_sync(", self.src)

    def test_no_legacy_integer_gpio_api(self):
        for legacy in ("gpio_request", "gpio_free", "gpio_get_value", "gpio_to_irq",
                       "gpio_direction_input", "of_get_named_gpio", "linux/gpio.h"):
            self.assertNotRegex(self.src, r"(?<![\w_])" + re.escape(legacy) + r"\b", legacy)

    def test_manual_unbind_is_disabled(self):
        self.assertIn(".suppress_bind_attrs = true", self.src)

    def test_event_layout_comes_from_shared_header(self):
        self.assertIn('#include "edge_button.h"', self.src)


class EventHeaderTest(unittest.TestCase):
    def compile(self, compiler, lang):
        # static_assert sizes/offsets are written from the layout the header promises,
        # not read back from it: 8-byte timestamp, then two 4-byte fields, no padding.
        src = ('#include <stddef.h>\n#include "edge_button.h"\n'
               "_Static_assert(sizeof(struct edge_button_event) == 16, \"size\");\n"
               "_Static_assert(offsetof(struct edge_button_event, timestamp_ns) == 0, \"ts\");\n"
               "_Static_assert(offsetof(struct edge_button_event, seq) == 8, \"seq\");\n"
               "_Static_assert(offsetof(struct edge_button_event, pressed) == 12, \"pressed\");\n"
               "int main(void) { return 0; }\n")
        if lang == "c++":
            src = src.replace("_Static_assert", "static_assert")
        return subprocess.run([compiler, "-x", lang, "-std=" + ("c11" if lang == "c" else "c++17"),
                               "-Wall", "-Werror", "-fsyntax-only", "-I", str(HEADER.parent), "-"],
                              input=src, text=True, capture_output=True, check=False)

    def test_layout_in_c(self):
        res = self.compile("gcc", "c")
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_layout_in_cxx(self):
        res = self.compile("g++", "c++")
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_only_fixed_size_types(self):
        text = HEADER.read_text()
        for banned in ("unsigned long", "unsigned int", " long ", "size_t", " int ", "bool"):
            self.assertNotIn(banned, text, banned.strip())


class WaitCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(["cmake", "-S", str(REPO), "-B", str(BUILD)], check=True, capture_output=True)
        subprocess.run(["cmake", "--build", str(BUILD), "--target", "edge_button_wait"],
                       check=True, capture_output=True)

    def run_wait(self, *args, env=None):
        return subprocess.run([str(WAIT), *args], text=True, capture_output=True, env=env, timeout=10)

    def test_usage_errors_exit_2(self):
        for args in (("0",), ("-1",), ("x",), ("1", "2"), ("1x",)):
            with self.subTest(args=args):
                res = self.run_wait(*args)
                self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
                self.assertIn("usage", res.stderr)

    def start_on_fifo(self, count, stdout):
        """Run edge_button_wait on a named pipe standing in for /dev/edge_button."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fifo = Path(tmp.name) / "edge_button"
        os.mkfifo(fifo)
        proc = subprocess.Popen([str(WAIT), str(count)], stdout=stdout, stderr=subprocess.PIPE,
                                env={"EDGE_BUTTON_DEV": str(fifo)})
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        writer = os.open(fifo, os.O_WRONLY)  # returns once the program has opened it
        self.addCleanup(os.close, writer)
        return proc, writer

    @staticmethod
    def event(seq, pressed, ns=1_500_000_000):
        return struct.pack("=QII", ns, seq, pressed)  # include/edge_button.h layout

    def test_prints_events_read_from_the_device(self):
        proc, writer = self.start_on_fifo(2, subprocess.PIPE)
        os.write(writer, self.event(1, 1, 1_000_000_001) + self.event(2, 0, 2_000_000_002))
        out, err = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 0, err)
        self.assertEqual(out, b"seq=1 pressed t=1.000000001\nseq=2 released t=2.000000002\n")

    def test_sigterm_while_blocked_in_read_exits_1(self):
        proc, _ = self.start_on_fifo(1, subprocess.PIPE)
        time.sleep(0.3)
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 1)
        self.assertIn(b"interrupted", err)

    def test_sigterm_between_reads_is_not_lost(self):
        # The signal lands while the program is stuck writing stdout (a full pipe), not
        # inside read(). An empty handler forgets it and the next read() sleeps forever,
        # so `timeout` in the acceptance script could hang (code review, PR #7).
        rd, wr = os.pipe()
        fcntl.fcntl(wr, 1031, 4096)  # F_SETPIPE_SZ: about 100 lines fill it
        proc, writer = self.start_on_fifo(100000, wr)
        os.close(wr)
        os.write(writer, b"".join(self.event(i, i % 2) for i in range(1, 401)))
        time.sleep(0.5)                       # now blocked in write() on the full pipe
        proc.send_signal(signal.SIGTERM)
        time.sleep(0.2)

        def drain():                          # unblock it; EOF once the program exits
            while os.read(rd, 65536):
                pass
        threading.Thread(target=drain, daemon=True).start()
        self.addCleanup(os.close, rd)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.fail("SIGTERM between reads was lost: still running 3 s later")
        self.assertEqual(proc.returncode, 1)
        self.assertIn(b"interrupted", proc.stderr.read())

    def test_missing_device_exits_1(self):
        res = self.run_wait("1", env={"EDGE_BUTTON_DEV": "/nonexistent/edge_button"})
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("/nonexistent/edge_button", res.stderr)


if __name__ == "__main__":
    unittest.main()
