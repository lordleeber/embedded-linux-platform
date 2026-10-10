"""Hardware-free checks for Step 4: the DT overlay and its contract with edge_gpio.c.

The expected GPIO cell is derived from the SoC binding, not from the overlay:
header pin 29 is GPIO01 = PQ.05 (Jetson.GPIO pin table for Orin Nano), and
include/dt-bindings/gpio/tegra234-gpio.h defines
TEGRA234_MAIN_GPIO(port, offset) = PORT_<port> * 8 + offset with PORT_Q = 15,
so the cell must be 15 * 8 + 5 = 125 (0x7d).
"""

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
DTS_DIR = REPO / "dts"
DRIVER = REPO / "kernel" / "edge_gpio" / "edge_gpio.c"
KDIR = Path("/lib/modules") / subprocess.run(
    ["uname", "-r"], capture_output=True, text=True, check=True).stdout.strip() / "build"
BINDING = KDIR / "include" / "dt-bindings" / "gpio" / "tegra234-gpio.h"

COMPATIBLE = "edge,gpio-led"
BOARD_COMPATIBLE = "nvidia,p3768-0000+p3767-0005-super"  # first entry of /proc/device-tree/compatible
PQ5_CELL = 15 * 8 + 5


def decompile(dtbo):
    return subprocess.run(["dtc", "-q", "-I", "dtb", "-O", "dts", str(dtbo)],
                          capture_output=True, text=True, check=True).stdout


@unittest.skipUnless(shutil.which("dtc") and shutil.which("cpp") and BINDING.exists(),
                     "needs dtc, cpp and the kernel dt-bindings headers")
class OverlayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        out = Path(cls.tmp.name)
        res = subprocess.run(["make", "-s", "-C", str(DTS_DIR), f"OUT={out}"],
                             capture_output=True, text=True)
        cls.build = res
        cls.high = out / "edge-gpio-overlay.dtbo"
        cls.low = out / "edge-gpio-overlay-active-low.dtbo"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.assertEqual(self.build.returncode, 0, self.build.stderr)

    def test_binding_header_still_says_port_q_is_15(self):
        text = BINDING.read_text()
        self.assertRegex(text, r"#define\s+TEGRA234_MAIN_GPIO_PORT_Q\s+15\b")
        self.assertRegex(text, r"TEGRA234_MAIN_GPIO_PORT_##port \* 8\) \+ offset")

    def test_both_variants_are_built(self):
        self.assertTrue(self.high.is_file())
        self.assertTrue(self.low.is_file())

    def test_overlay_targets_this_board(self):
        dts = decompile(self.high)
        top = re.search(r"^\s*compatible = (.*);$", dts, re.M)
        self.assertIsNotNone(top)
        self.assertIn(f'"{BOARD_COMPATIBLE}', top.group(1).replace("\\0", '" "'))

    def test_node_has_driver_compatible(self):
        dts = decompile(self.high)
        self.assertRegex(dts, r"edge-led \{[^}]*compatible = \"" + re.escape(COMPATIBLE) + '"')

    def test_led_gpio_is_pq5_active_high(self):
        dts = decompile(self.high)
        m = re.search(r"led-gpios = <(0x[0-9a-f]+) (0x[0-9a-f]+) (0x[0-9a-f]+)>;", dts)
        self.assertIsNotNone(m, dts)
        self.assertEqual(int(m.group(2), 16), PQ5_CELL)
        self.assertEqual(int(m.group(3), 16), 0)  # GPIO_ACTIVE_HIGH

    def test_active_low_variant_sets_flag(self):
        dts = decompile(self.low)
        m = re.search(r"led-gpios = <(0x[0-9a-f]+) (0x[0-9a-f]+) (0x[0-9a-f]+)>;", dts)
        self.assertIsNotNone(m, dts)
        self.assertEqual(int(m.group(2), 16), PQ5_CELL)
        self.assertEqual(int(m.group(3), 16), 1)  # GPIO_ACTIVE_LOW

    def test_gpio_phandle_is_resolved_against_base_dt_symbol(self):
        # &gpio must be left as a fixup so the bootloader patches in the base DT's phandle.
        dts = decompile(self.high)
        self.assertRegex(dts, r"__fixups__ \{\s*gpio = \"/fragment@0/__overlay__/edge-led:led-gpios:0\";")

    def test_pad_state_drives_pq5_and_is_owned_by_edge_led(self):
        # JP6 boots pin 29's pad tristated (measured: pinconf tristate=1, LED never lit),
        # so the GPIO output register toggled but no voltage reached the pin. The node
        # must carry a "default" pinctrl state that un-tristates the pad; the platform
        # core applies it before probe().
        dts = decompile(self.high)
        node = re.search(r"edge-led \{(.*?)\n\t\t\t\};", dts, re.S)
        self.assertIsNotNone(node, dts)
        self.assertIn('pinctrl-names = "default";', node.group(1))
        ref = re.search(r"pinctrl-0 = <(0x[0-9a-f]+)>;", node.group(1))
        self.assertIsNotNone(ref, node.group(1))

        state = re.search(r"\{\s*phandle = <" + ref.group(1) + r">;(.*?)\n\t\t\t\};", dts, re.S)
        self.assertIsNotNone(state, "pinctrl-0 does not point at a state node in this overlay")
        body = state.group(1)
        self.assertIn('nvidia,pins = "soc_gpio32_pq5";', body)
        self.assertIn("nvidia,tristate = <0x00>;", body)
        self.assertIn("nvidia,enable-input = <0x00>;", body)

        # The state node lives under the SoC pin controller (base DT symbol "pinmux").
        fixups = re.search(r"__fixups__ \{(.*?)\};", dts, re.S).group(1)
        self.assertRegex(fixups, r'pinmux = "/fragment@\d+:target:0";')

    def test_pad_name_matches_nvidia_header_overlay(self):
        # Cross-check the pad name against NVIDIA's own 40-pin header overlay, not ours.
        vendor = Path("/boot/tegra234-p3767-0000+p3509-a02-hdr40.dtbo")
        if not vendor.exists():
            self.skipTest(f"{vendor} not present")
        pin29 = re.search(r"hdr40-pin29 \{(.*?)\};", decompile(vendor), re.S)
        self.assertIsNotNone(pin29)
        self.assertIn('nvidia,pins = "soc_gpio32_pq5";', pin29.group(1))
        self.assertIn('nvidia,pins = "soc_gpio32_pq5";', decompile(self.high))


class DriverContractTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(DRIVER.is_file(), f"{DRIVER} missing")
        self.src = DRIVER.read_text()

    def test_of_match_uses_overlay_compatible(self):
        self.assertIn(f'.compatible = "{COMPATIBLE}"', self.src)
        self.assertIn(f'compatible = "{COMPATIBLE}"', (DTS_DIR / "edge-gpio-overlay.dts").read_text())

    def test_requests_led_function_which_maps_to_led_gpios(self):
        # devm_gpiod_get(dev, "led", ...) looks up the DT property "led-gpios".
        self.assertRegex(self.src, r'devm_gpiod_get\(\s*\w+\s*,\s*"led"\s*,\s*GPIOD_OUT_LOW\s*\)')

    def test_no_legacy_integer_gpio_api(self):
        for legacy in ("gpio_request", "gpio_free", "gpio_set_value", "gpio_direction_output",
                       "of_get_named_gpio", "linux/gpio.h"):
            self.assertNotRegex(self.src, r"(?<![\w_])" + re.escape(legacy) + r"\b", legacy)

    def test_manual_unbind_is_disabled(self):
        # The misc device's file ops use per-device state; unbinding while a file is
        # open would free it under the reader. rmmod is already blocked by .owner.
        self.assertIn(".suppress_bind_attrs = true", self.src)


if __name__ == "__main__":
    unittest.main()
