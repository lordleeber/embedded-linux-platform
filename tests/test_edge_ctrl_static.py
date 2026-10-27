"""Hardware-free checks for Step 13: the controller@42 DT node, edge_ctrl.c and its register header.

Expected values come from outside the driver: the Blue Pill answers on i2c-1 (header
pins 27 / 28), which the base device tree labels gen2_i2c = /bus@0/i2c@c240000 (the
same bus as Step 10-a's oled@3c), at 0x42 (Step 11). The register map is the
firmware's (firmware/stm32f103/docs/register-map.md); build/test_edge_ctrl_regs
runs the driver's header against the firmware's own state machine.
"""

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
DTS_DIR = REPO / "dts"
MOD_DIR = REPO / "kernel" / "edge_ctrl"
DRIVER = MOD_DIR / "edge_ctrl.c"
BUILD = REPO / "build"
VERIFY = REPO / "scripts" / "verify_edge_ctrl.sh"
KDIR = Path("/lib/modules") / subprocess.run(
    ["uname", "-r"], capture_output=True, text=True, check=True).stdout.strip() / "build"

COMPATIBLE = "edge,edge-ctrl"
# The I2C core names the client after the compatible minus the vendor prefix and also
# matches that name against every driver's i2c_device_id table (Step 7's lesson).
CLIENT_NAME = COMPATIBLE.split(",", 1)[1]
ADDR = 0x42
RO_ATTRS = ("device_id", "firmware_version", "protocol_version", "adc", "button", "button_presses")
RW_ATTRS = ("led", "status")


def decompile(dtbo):
    return subprocess.run(["dtc", "-q", "-I", "dtb", "-O", "dts", str(dtbo)],
                          capture_output=True, text=True, check=True).stdout


def code_only(src):
    return re.sub(r"//.*", "", re.sub(r"/\*.*?\*/", "", src, flags=re.S))


def function_body(src, name):
    """Return the body of a top-level C function without its comments (brace matching)."""
    m = re.search(r"^\w[^;{]*\b" + re.escape(name) + r"\([^;{]*\)\s*\{", src, re.M)
    if not m:
        return None
    depth, i = 1, m.end()
    while depth:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    return code_only(src[m.end():i - 1])


@unittest.skipUnless(shutil.which("dtc") and shutil.which("cpp") and KDIR.exists(),
                     "needs dtc, cpp and the kernel headers")
class CtrlOverlayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        out = Path(cls.tmp.name)
        cls.build = subprocess.run(["make", "-s", "-C", str(DTS_DIR), f"OUT={out}"],
                                   capture_output=True, text=True)
        cls.dtbo = out / "edge-gpio-overlay.dtbo"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.assertEqual(self.build.returncode, 0, self.build.stderr)
        self.dts = decompile(self.dtbo)

    def fragment(self):
        for m in re.finditer(r"\t(fragment@\d+) \{(.*?)\n\t\};", self.dts, re.S):
            if "controller@" in m.group(2):
                return m.group(1), m.group(2)
        self.fail("no controller@ node in the overlay")

    def test_node_is_at_0x42_with_driver_compatible(self):
        _, body = self.fragment()
        node = re.search(r"controller@([0-9a-f]+) \{(.*?)\};", body, re.S)
        self.assertEqual(int(node.group(1), 16), ADDR)
        self.assertIn(f'compatible = "{COMPATIBLE}";', node.group(2))
        self.assertIn(f"reg = <{ADDR:#04x}>;", node.group(2))
        self.assertIn("#address-cells = <0x01>;", body)
        self.assertIn("#size-cells = <0x00>;", body)

    def test_fragment_targets_gen2_i2c(self):
        name, _ = self.fragment()
        fixups = re.search(r"__fixups__ \{(.*?)\};", self.dts, re.S).group(1)
        m = re.search(r"gen2_i2c = (\".*?\");", fixups)
        self.assertIsNotNone(m, "no fragment targets &gen2_i2c")
        self.assertIn(f"/{name}:target:0", m.group(1))

    def test_overlay_applies_to_the_boot_fdt(self):
        fdt = Path("/boot/dtb/kernel_tegra234-p3768-0000+p3767-0005-nv-super.dtb")
        cam = Path("/boot/tegra234-p3767-camera-p3768-imx219-A.dtbo")
        if not (shutil.which("fdtoverlay") and fdt.exists() and cam.exists()):
            self.skipTest("needs fdtoverlay and this board's /boot FDT")
        merged = Path(self.tmp.name) / "merged.dtb"
        r = subprocess.run(["fdtoverlay", "-i", str(fdt), "-o", str(merged), str(cam),
                            str(self.dtbo)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        get = lambda *a: subprocess.run(["fdtget", *a], capture_output=True, text=True,
                                        check=True).stdout.strip()
        node = "/bus@0/i2c@c240000/controller@42"
        self.assertEqual(get(str(merged), node, "compatible"), COMPATIBLE)
        self.assertEqual(get("-tx", str(merged), node, "reg"), "42")
        # the earlier nodes stay where they were
        self.assertEqual(get(str(merged), "/bus@0/i2c@c240000/oled@3c", "compatible"), "edge,edge-ssd1306")
        self.assertEqual(get(str(merged), "/bus@0/i2c@c250000/ina219@41", "compatible"), "edge,edge-ina219")

    def test_client_name_is_no_other_drivers_i2c_id(self):
        aliases = KDIR.parent / "modules.alias"
        if not aliases.exists():
            self.skipTest(f"{aliases} missing")
        taken = {l.split()[1][len("i2c:"):] for l in aliases.read_text().splitlines()
                 if l.startswith("alias i2c:")}
        self.assertIn("ina219", taken, "sanity: modules.alias lists i2c ids")
        self.assertNotIn(CLIENT_NAME, taken)


class CtrlDriverContractTest(unittest.TestCase):
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
        self.assertRegex(self.code, r'\{\s*"edge_ctrl"\s*,')  # new_device at a dead address
        self.assertIn("MODULE_DEVICE_TABLE(i2c,", self.code)
        self.assertRegex(self.code, r"\.probe_new\s*=\s*edge_ctrl_probe")
        self.assertRegex(self.code, r"\.remove\s*=\s*edge_ctrl_remove")
        self.assertIn('#include "edge_ctrl_regs.h"', self.src)

    def test_read_reg_is_one_transfer_with_repeated_start(self):
        # Pointer write + read in one i2c_transfer(): the adapter lock keeps any other
        # bus user (i2ctransfer, edge_oled) from moving the firmware's pointer in between.
        body = function_body(self.src, "read_reg")
        self.assertIsNotNone(body, "no read_reg()")
        self.assertRegex(body, r"i2c_transfer\(client->adapter, \w+, 2\)")
        self.assertIn("I2C_M_RD", body)
        self.assertRegex(body, r"-EIO")  # a partial transfer is not a success

    def test_write_reg_sends_pointer_and_value(self):
        body = function_body(self.src, "write_reg")
        self.assertIsNotNone(body, "no write_reg()")
        self.assertRegex(body, r"i2c_master_send\(client, \w+, 2\)")
        self.assertRegex(body, r"-EIO")

    def test_attributes(self):
        for a in RO_ATTRS:
            with self.subTest(attr=a):
                self.assertRegex(self.code, rf"\bDEVICE_ATTR_RO\({a}\)")
        for a in RW_ATTRS:
            with self.subTest(attr=a):
                self.assertRegex(self.code, rf"\bDEVICE_ATTR_RW\({a}\)")
        # dev_groups: the driver core adds the files with the binding and removes them with it
        self.assertRegex(self.code, r"\.dev_groups\s*=\s*edge_ctrl_groups")
        self.assertNotIn("sysfs_create_group", self.code)

    def test_adc_is_one_two_byte_read(self):
        # Two separate reads may come from two conversions (register-map.md).
        body = function_body(self.src, "adc_show")
        self.assertIsNotNone(body, "no adc_show()")
        self.assertRegex(body, r"read_reg\([^,]+, EDGE_CTRL_REG_ADC_LOW, \w+, 2\)")
        self.assertEqual(body.count("read_reg("), 1)
        self.assertIn("edge_ctrl_adc(", body)

    def test_led_value_checked_before_anything_is_sent(self):
        body = function_body(self.src, "led_store")
        self.assertIsNotNone(body, "no led_store()")
        check, send = body.find("edge_ctrl_led_ok("), body.find("write_reg(")
        self.assertTrue(0 <= check < send, "led_ok() before write_reg()")
        self.assertIn("-EINVAL", body[check:send])

    def test_probe_checks_id_and_protocol(self):
        body = function_body(self.src, "edge_ctrl_probe")
        self.assertIsNotNone(body, "no edge_ctrl_probe()")
        self.assertRegex(body, r"read_reg\(client, EDGE_CTRL_REG_DEVICE_ID, \w+, 4\)")
        self.assertIn("EDGE_CTRL_DEVICE_ID", body)
        self.assertIn("edge_ctrl_protocol_ok(", body)
        self.assertIn("-ENODEV", body)

    def test_errors_are_returned_and_nothing_is_cached(self):
        # A bus that times out as a whole (Step 11: SCL shorted to GND) is not this chip's
        # fault: every access returns the errno and the next one tries again. No state is
        # kept, no "dead" flag, and nothing is logged per access (tegra-i2c already logs).
        for fn in ("read_reg", "write_reg"):
            with self.subTest(fn=fn):
                self.assertRegex(function_body(self.src, fn), r"return ret < 0 \? ret : -EIO;")
        self.assertNotRegex(self.code, r"^static (u8|u16|int|long|bool) \w+;", re.M)
        for m in re.finditer(r"^static ssize_t (\w+_(show|store))\(", self.src, re.M):
            with self.subTest(fn=m.group(1)):
                self.assertNotRegex(function_body(self.src, m.group(1)), r"dev_(err|warn|info)")

    def test_out_of_scope(self):
        # Step 13 does not do the heartbeat (Step 14) or poll() (Step 19), and is not hwmon.
        for word in ("HEARTBEAT", ".poll", "misc_register", "miscdevice", "hwmon",
                     "delayed_work", "wait_queue"):
            with self.subTest(word=word):
                self.assertNotIn(word, self.code)


@unittest.skipUnless(KDIR.exists(), "needs the kernel headers")
class CtrlBuildTest(unittest.TestCase):
    def test_module_builds_against_running_kernel(self):
        r = subprocess.run(["make", "-C", str(MOD_DIR)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertTrue((MOD_DIR / "edge_ctrl.ko").exists())
        self.assertNotRegex(r.stderr, r"\.[ch]:\d+:\d+: warning:")

    def test_register_vectors_against_the_firmware(self):
        subprocess.run(["cmake", "-S", str(REPO), "-B", str(BUILD)], check=True, capture_output=True)
        r = subprocess.run(["cmake", "--build", str(BUILD), "--target", "test_edge_ctrl_regs"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])
        r = subprocess.run([str(BUILD / "test_edge_ctrl_regs")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)


class CtrlVerifyScriptTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(VERIFY.exists(), f"{VERIFY} missing")
        self.text = VERIFY.read_text()

    def test_syntax(self):
        r = subprocess.run(["bash", "-n", str(VERIFY)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_needs_root_and_cleans_up(self):
        self.assertIn("EUID", self.text)
        self.assertIn("trap cleanup EXIT", self.text)

    def test_compares_with_raw_i2c_using_force(self):
        # With the driver bound, i2c-dev refuses 0x42 without -f (EBUSY, Step 7).
        raw = [l for l in self.text.splitlines()
               if re.search(r"\bi2c(transfer|get|set)\b", l)
               and not l.lstrip().startswith("#") and "command -v" not in l]
        self.assertTrue(any("i2ctransfer" in l for l in raw), "no i2ctransfer comparison")
        for line in raw:
            with self.subTest(line=line):
                self.assertTrue(" -f" in line or "busy" in line, "raw access without -f")

    def test_dead_address_unbind_and_unplug(self):
        self.assertIn("new_device", self.text)
        self.assertIn("delete_device", self.text)
        self.assertRegex(self.text, r"\$DRV/unbind")
        self.assertRegex(self.text, r"\$DRV/bind")
        self.assertIn("--no-unplug", self.text)

    def test_usage_error_exits_2(self):
        r = subprocess.run(["bash", str(VERIFY), "--bogus"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
