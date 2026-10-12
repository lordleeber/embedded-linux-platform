"""Hardware-free checks for Steps 7-8: the INA219 DT node, edge_ina219.c and its arithmetic.

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

COMPATIBLE = "edge,edge-ina219"
# The I2C core names a DT client after its compatible minus the vendor prefix
# (of_modalias_node), and falls back to matching that name against every driver's
# i2c_device_id table. "ina219" is in the upstream ina2xx table (i2c:ina219 in
# modules.alias), so that name would let ina2xx bind our chip once loaded.
CLIENT_NAME = COMPATIBLE.split(",", 1)[1]
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

    def test_client_name_is_no_other_drivers_i2c_id(self):
        aliases = Path("/lib/modules") / KDIR.parent.name / "modules.alias"
        if not aliases.exists():
            self.skipTest(f"{aliases} missing")
        taken = {line.split()[1][len("i2c:"):]: line.split()[2]
                 for line in aliases.read_text().splitlines() if line.startswith("alias i2c:")}
        self.assertIn("ina219", taken, "sanity: upstream ina2xx should claim i2c:ina219")
        self.assertNotIn(CLIENT_NAME, taken, f"client name {CLIENT_NAME} matches {taken.get(CLIENT_NAME)}")

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

    def test_probe_reads_back_what_it_wrote(self):
        # INA219 has no ID register; an ACK only proves something answers at 0x41.
        # Reading Calibration and Config back after writing them rejects a chip that
        # does not keep them (probe fails with -ENODEV instead of binding).
        body = function_body(self.src, "edge_ina219_probe")
        cfg = body.find("EDGE_INA219_REG_CONFIG, EDGE_INA219_CONFIG")
        after = body[cfg:]
        self.assertRegex(after, r"read_reg16\(client, EDGE_INA219_REG_CAL\)")
        self.assertRegex(after, r"read_reg16\(client, EDGE_INA219_REG_CONFIG\)")
        self.assertIn("-ENODEV", after)

    def test_read_errors_are_returned_not_hidden(self):
        # A failed transfer is a negative errno from the SMBus helper; the attribute must
        # pass it on instead of printing a stale or zero value.
        for helper in ("read_bus_voltage", "read_shunt_voltage", "read_calibrated"):
            with self.subTest(helper=helper):
                body = function_body(self.src, helper)
                self.assertRegex(body, r"if \(ret < 0\)\s*return ret;")

    def test_arithmetic_comes_from_the_shared_header(self):
        # hwmon units (Documentation/hwmon/sysfs-interface.rst): in mV, curr mA, power uW.
        self.assertIn('#include "edge_ina219_conv.h"', self.src)
        for fn in ("edge_ina219_bus_mv", "edge_ina219_shunt_mv",
                   "edge_ina219_current_ma", "edge_ina219_power_uw"):
            self.assertIn(fn + "(", self.code)

    def test_current_needs_a_calibration(self):
        # Cal 0 (power-on, or someone wrote it) would divide by zero.
        self.assertIn("-ENODATA", self.code)

    def test_registers_with_hwmon(self):
        # Step 8: the standard subsystem instead of private attributes. devm_ ties the hwmon
        # device to the binding, so unbind / rmmod removes /sys/class/hwmon/hwmonN.
        self.assertIn("#include <linux/hwmon.h>", self.src)
        self.assertRegex(self.code, r'devm_hwmon_device_register_with_info\(\s*&client->dev,\s*"edge_ina219"')
        self.assertNotRegex(self.code, r"\bhwmon_device_register(_with_info)?\(")

    def test_hwmon_channels(self):
        # in0 = shunt, in1 = bus (as upstream ina2xx), one current, one power channel.
        info = re.findall(r"HWMON_CHANNEL_INFO\((\w+),([^)]*)\)", self.code)
        got = {kind: [c.strip() for c in chans.split(",")] for kind, chans in info}
        self.assertEqual(got.get("in"), ["HWMON_I_INPUT | HWMON_I_LABEL"] * 2)
        self.assertEqual(got.get("curr"), ["HWMON_C_INPUT"])
        self.assertEqual(got.get("power"), ["HWMON_P_INPUT"])

    def test_hwmon_files_are_read_only(self):
        body = function_body(self.src, "edge_ina219_is_visible")
        self.assertIsNotNone(body, "no edge_ina219_is_visible()")
        self.assertIn("return 0444;", body)
        self.assertNotRegex(body, r"\b0[0-7]*[2367][0-7]*\b|S_IW")
        self.assertNotIn(".write", self.code)

    def test_hwmon_read_returns_errors(self):
        # Each failed read reaches userspace as the errno, never as an old or zero value:
        # no value is kept between reads.
        body = function_body(self.src, "edge_ina219_read")
        self.assertIsNotNone(body, "no edge_ina219_read()")
        self.assertRegex(body, r"if \(ret\)\s*return ret;")
        self.assertNotRegex(self.code, r"^static (long|s32|int|s64) \w+;", "a cached value")

    def test_no_private_attributes(self):
        # Step 7's registers / bus_mv / ... are gone: hwmon is the only interface.
        self.assertNotRegex(self.code, r"DEVICE_ATTR|dev_groups|ATTRIBUTE_GROUPS")


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

    def test_i2cset_only_zeroes_and_restores_calibration(self):
        # Step 8 writes Cal 0 to see ENODATA, then the sample's 26868 (0x68F4, sent LSB
        # first as an SMBus word: 0xf468). -f because the driver owns 0x41.
        writes = [l for l in self.text.splitlines()
                  if re.search(r"\bi2cset\b", l) and not l.lstrip().startswith("#")]
        self.assertTrue(writes, "no i2cset")
        for line in writes:
            with self.subTest(line=line):
                self.assertRegex(line, r"i2cset -f -y \"\$BUS\" 0x41 0x05 (0x0000|0xf468) w")
        self.assertIn("0xf468", self.text)
        self.assertIn("No data available", self.text)

    def test_checks_hwmon_and_stale_nodes(self):
        self.assertIn("/hwmon", self.text)
        self.assertIn("ENODEV", self.text)     # read on a file opened before rmmod
        self.assertRegex(self.text, r"\$DRV/unbind")
        self.assertRegex(self.text, r"\$DRV/bind")

    def test_usage_error_exits_2(self):
        r = subprocess.run(["bash", str(VERIFY), "--bogus"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
