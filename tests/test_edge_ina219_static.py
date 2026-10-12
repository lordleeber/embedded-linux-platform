"""Hardware-free checks for Step 7: the INA219 DT node, edge_ina219.c and its arithmetic.

Expected values come from outside our code: the base device tree labels the
header I2C controller (pins 3/5) hdr40_i2c1 = /bus@0/i2c@c250000, which
`i2cdetect -l` lists as c250000.i2c = i2c-7; the UPS module answers at 0x41
(Step 6-a scan). The chip sends registers MSB first while SMBus words are LSB
first (Step 6-b: i2cget showed Config as 0xef0e), so the driver must use the
_swapped SMBus helpers.
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
DTS_DIR = REPO / "dts"
MOD_DIR = REPO / "kernel" / "edge_ina219"
DRIVER = MOD_DIR / "edge_ina219.c"
BUILD = REPO / "build"
VERIFY = REPO / "scripts" / "verify_edge_ina219.sh"
KDIR = Path("/lib/modules") / subprocess.run(
    ["uname", "-r"], capture_output=True, text=True, check=True).stdout.strip() / "build"

COMPATIBLE = "edge,ina219"
ADDR = 0x41


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
    return re.sub(r"/\*.*?\*/", "", src[m.end():i - 1], flags=re.S)


def code_only(src):
    return re.sub(r"//.*", "", re.sub(r"/\*.*?\*/", "", src, flags=re.S))


@unittest.skipUnless(shutil.which("dtc") and shutil.which("cpp") and KDIR.exists(),
                     "needs dtc, cpp and the kernel headers")
class Ina219OverlayTest(unittest.TestCase):
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

    def fragment(self, dts):
        """The fragment holding the ina219 node: (fragment name, its body)."""
        for m in re.finditer(r"\t(fragment@\d+) \{(.*?)\n\t\};", dts, re.S):
            if "ina219@" in m.group(2):
                return m.group(1), m.group(2)
        self.fail("no ina219@ node in the overlay")

    def test_node_is_at_0x41_with_driver_compatible_in_both_variants(self):
        for dtbo in self.dtbos:
            with self.subTest(dtbo=dtbo.name):
                _, body = self.fragment(decompile(dtbo))
                node = re.search(r"ina219@([0-9a-f]+) \{(.*?)\};", body, re.S)
                self.assertEqual(int(node.group(1), 16), ADDR)
                self.assertIn(f'compatible = "{COMPATIBLE}";', node.group(2))
                self.assertIn(f"reg = <{ADDR:#04x}>;", node.group(2))

    def test_fragment_targets_the_header_i2c_label(self):
        # A phandle to a base-tree label is left for the bootloader to resolve: __fixups__.
        dts = decompile(self.dtbos[0])
        name, _ = self.fragment(dts)
        fixups = re.search(r"__fixups__ \{(.*?)\};", dts, re.S).group(1)
        m = re.search(r"hdr40_i2c1 = (\".*?\");", fixups)
        self.assertIsNotNone(m, "fragment target is not &hdr40_i2c1")
        self.assertIn(f"/{name}:target:0", m.group(1))

    def test_label_is_the_controller_i2cdetect_calls_c250000(self):
        sym = Path("/proc/device-tree/__symbols__/hdr40_i2c1")
        if not sym.exists():
            self.skipTest("base device tree has no __symbols__/hdr40_i2c1")
        self.assertEqual(sym.read_bytes().rstrip(b"\0").decode(), "/bus@0/i2c@c250000")

    def test_i2c_child_cells(self):
        # An I2C child's reg is one cell (the address) and no size.
        _, body = self.fragment(decompile(self.dtbos[0]))
        self.assertIn("#address-cells = <0x01>;", body)
        self.assertIn("#size-cells = <0x00>;", body)

    def test_overlay_applies_to_the_boot_fdt(self):
        # The same merge the bootloader does: base FDT + NVIDIA's camera overlay + ours.
        fdt = Path("/boot/dtb/kernel_tegra234-p3768-0000+p3767-0005-nv-super.dtb")
        cam = Path("/boot/tegra234-p3767-camera-p3768-imx219-A.dtbo")
        if not (shutil.which("fdtoverlay") and fdt.exists() and cam.exists()):
            self.skipTest("needs fdtoverlay and this board's /boot FDT")
        merged = Path(self.tmp.name) / "merged.dtb"
        r = subprocess.run(["fdtoverlay", "-i", str(fdt), "-o", str(merged), str(cam),
                            str(self.dtbos[0])], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        get = lambda *a: subprocess.run(["fdtget", *a], capture_output=True, text=True,
                                        check=True).stdout.strip()
        node = "/bus@0/i2c@c250000/ina219@41"
        self.assertEqual(get(str(merged), node, "compatible"), COMPATIBLE)
        self.assertEqual(get("-tx", str(merged), node, "reg"), "41")

    def test_gpio_nodes_are_still_there(self):
        dts = decompile(self.dtbos[0])
        self.assertIn('compatible = "edge,gpio-led";', dts)
        self.assertIn('compatible = "edge,gpio-button";', dts)


class Ina219DriverContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = DRIVER.read_text() if DRIVER.exists() else ""
        cls.code = code_only(cls.src)

    def setUp(self):
        self.assertTrue(DRIVER.exists(), f"{DRIVER} missing")

    def test_is_an_i2c_driver_matched_by_dt_and_by_name(self):
        self.assertRegex(self.code, r"static struct i2c_driver \w+ = \{")
        self.assertRegex(self.code, r'\{\s*\.compatible\s*=\s*"' + COMPATIBLE + r'"\s*\}')
        self.assertIn("MODULE_DEVICE_TABLE(of,", self.code)
        # The name table lets the script instantiate a client at a dead address (new_device).
        self.assertRegex(self.code, r'\{\s*"edge_ina219"\s*,')
        self.assertIn("MODULE_DEVICE_TABLE(i2c,", self.code)
        self.assertIn("module_i2c_driver(", self.code)

    def test_probe_and_remove_are_wired(self):
        self.assertRegex(self.code, r"\.probe_new\s*=\s*edge_ina219_probe")
        self.assertRegex(self.code, r"\.remove\s*=\s*edge_ina219_remove")

    def test_registers_go_through_swapped_smbus_words(self):
        # INA219 is MSB first; plain read/write_word_data would swap every value.
        self.assertIn("i2c_smbus_read_word_swapped(", self.code)
        self.assertIn("i2c_smbus_write_word_swapped(", self.code)
        self.assertNotRegex(self.code, r"i2c_smbus_(read|write)_word_data\(")

    def test_helpers_named_in_the_plan(self):
        for name in ("read_reg16", "write_reg16", "read_bus_voltage", "read_shunt_voltage"):
            with self.subTest(helper=name):
                self.assertIsNotNone(function_body(self.src, name), f"no {name}()")

    def test_probe_checks_the_chip_then_writes_calibration_before_config(self):
        body = function_body(self.src, "edge_ina219_probe")
        self.assertIsNotNone(body)
        read = body.find("read_reg16(")
        cal = body.find("EDGE_INA219_REG_CAL")
        cfg = body.find("EDGE_INA219_REG_CONFIG, EDGE_INA219_CONFIG")
        self.assertTrue(0 <= read < cal < cfg, "probe: read first, then Cal, then Config")

    def test_read_errors_are_returned_not_hidden(self):
        # A failed transfer is a negative errno from the SMBus helper; the attribute must
        # pass it on instead of printing a stale or zero value.
        for helper in ("read_bus_voltage", "read_shunt_voltage", "read_calibrated"):
            with self.subTest(helper=helper):
                body = function_body(self.src, helper)
                self.assertRegex(body, r"if \(ret < 0\)\s*return ret;")

    def test_arithmetic_comes_from_the_shared_header(self):
        self.assertIn('#include "edge_ina219_conv.h"', self.src)
        for fn in ("edge_ina219_bus_mv", "edge_ina219_shunt_uv",
                   "edge_ina219_current_ua", "edge_ina219_power_uw"):
            self.assertIn(fn + "(", self.code)

    def test_current_needs_a_calibration(self):
        # Cal 0 (power-on, or someone wrote it) would divide by zero.
        self.assertIn("-ENODATA", self.code)

    def test_no_hwmon_yet(self):
        # Step 8 adds hwmon; Step 7 keeps device-specific logic only.
        self.assertNotRegex(self.code, r"linux/hwmon\.h|hwmon_device_register")

    def test_sysfs_attributes_are_read_only(self):
        self.assertNotRegex(self.code, r"DEVICE_ATTR_(RW|WO)\(")
        for attr in ("registers", "bus_mv", "shunt_uv", "current_ua", "power_uw"):
            with self.subTest(attr=attr):
                self.assertRegex(self.code, r"DEVICE_ATTR_RO\(" + attr + r"\)")


@unittest.skipUnless(KDIR.exists(), "needs the kernel headers")
class Ina219BuildTest(unittest.TestCase):
    def test_module_builds_against_running_kernel(self):
        r = subprocess.run(["make", "-C", str(MOD_DIR)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertTrue((MOD_DIR / "edge_ina219.ko").exists())
        self.assertNotRegex(r.stderr, r"\.[ch]:\d+:\d+: warning:")

    def test_conversion_vectors(self):
        subprocess.run(["cmake", "-S", str(REPO), "-B", str(BUILD)], check=True, capture_output=True)
        r = subprocess.run(["cmake", "--build", str(BUILD), "--target", "test_edge_ina219_conv"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])
        r = subprocess.run([str(BUILD / "test_edge_ina219_conv")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)


class VerifyScriptTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(VERIFY.exists(), f"{VERIFY} missing")
        self.text = VERIFY.read_text()

    def test_syntax(self):
        r = subprocess.run(["bash", "-n", str(VERIFY)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_compares_with_ina219_raw_not_i2cget(self):
        # With the driver bound, i2c-dev's I2C_SLAVE refuses 0x41 (EBUSY): i2cget fails
        # without -f. ina219_raw uses I2C_RDWR, which has no such check.
        self.assertIn("ina219_raw", self.text)
        for line in self.text.splitlines():
            if re.search(r"\bi2cget\b", line) and not line.lstrip().startswith("#"):
                with self.subTest(line=line):
                    self.assertTrue("-f" in line or "busy" in line, "i2cget only to show EBUSY")

    def test_needs_root_and_cleans_up(self):
        self.assertIn("EUID", self.text)
        self.assertIn("trap cleanup EXIT", self.text)

    def test_dead_address_probe_fails(self):
        # new_device at an address nobody answers must make probe() fail, not bind.
        self.assertIn("new_device", self.text)
        self.assertIn("delete_device", self.text)

    def test_usage_error_exits_2(self):
        r = subprocess.run(["bash", str(VERIFY), "--bogus"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
