"""Hardware-free checks for Step 10-a: the OLED DT node, edge_oled.c, edge_oled_ctl and oled_probe's guard.

Expected values come from outside our code: the OLED answers at 0x3c on the bus
i2cdetect calls c240000.i2c (Step 9, header pins 27/28), which the base device
tree labels gen2_i2c; Step 9's tools/ssd1306.h holds the bytes the panel took
(tests/test_edge_oled_proto.cpp compares the driver's copy with it).
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from test_edge_ina219_static import KDIR, code_only, decompile, function_body


REPO = Path(__file__).resolve().parents[1]
DTS_DIR = REPO / "dts"
MOD_DIR = REPO / "kernel" / "edge_oled"
DRIVER = MOD_DIR / "edge_oled.c"
UAPI = REPO / "include" / "edge_oled.h"
BUILD = REPO / "build"
CTL = BUILD / "edge_oled_ctl"
PROBE = BUILD / "oled_probe"
VERIFY = REPO / "scripts" / "verify_edge_oled.sh"

COMPATIBLE = "edge,edge-ssd1306"
CLIENT_NAME = COMPATIBLE.split(",", 1)[1]
ADDR = 0x3C

_built = False


def build():
    global _built
    if _built:
        return
    subprocess.run(["cmake", "-S", str(REPO), "-B", str(BUILD)], check=True, capture_output=True)
    r = subprocess.run(["cmake", "--build", str(BUILD), "--target", "edge_oled_ctl", "oled_probe",
                        "test_edge_oled_proto"], capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stdout[-2000:] + r.stderr[-2000:])
    _built = True


@unittest.skipUnless(shutil.which("dtc") and shutil.which("cpp") and KDIR.exists(),
                     "needs dtc, cpp and the kernel headers")
class OledOverlayTest(unittest.TestCase):
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
        for m in re.finditer(r"\t(fragment@\d+) \{(.*?)\n\t\};", dts, re.S):
            if "oled@" in m.group(2):
                return m.group(1), m.group(2)
        self.fail("no oled@ node in the overlay")

    def test_node_is_at_0x3c_with_driver_compatible_in_both_variants(self):
        for dtbo in self.dtbos:
            with self.subTest(dtbo=dtbo.name):
                _, body = self.fragment(decompile(dtbo))
                node = re.search(r"oled@([0-9a-f]+) \{(.*?)\};", body, re.S)
                self.assertEqual(int(node.group(1), 16), ADDR)
                self.assertIn(f'compatible = "{COMPATIBLE}";', node.group(2))
                self.assertIn(f"reg = <{ADDR:#04x}>;", node.group(2))

    def test_fragment_targets_gen2_i2c_not_the_ina219_bus(self):
        # Step 9 pitfall: the OLED is on pins 27/28 (c240000), not hdr40_i2c1 (c250000).
        dts = decompile(self.dtbos[0])
        name, _ = self.fragment(dts)
        fixups = re.search(r"__fixups__ \{(.*?)\};", dts, re.S).group(1)
        m = re.search(r"gen2_i2c = (\".*?\");", fixups)
        self.assertIsNotNone(m, "fragment target is not &gen2_i2c")
        self.assertIn(f"/{name}:target:0", m.group(1))
        hdr = re.search(r"hdr40_i2c1 = (\".*?\");", fixups)
        self.assertNotIn(f"/{name}:", hdr.group(1) if hdr else "")

    def test_label_is_the_controller_i2cdetect_calls_c240000(self):
        sym = Path("/proc/device-tree/__symbols__/gen2_i2c")
        if not sym.exists():
            self.skipTest("base device tree has no __symbols__/gen2_i2c")
        self.assertEqual(sym.read_bytes().rstrip(b"\0").decode(), "/bus@0/i2c@c240000")

    def test_overlay_applies_to_the_boot_fdt(self):
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
        node = "/bus@0/i2c@c240000/oled@3c"
        self.assertEqual(get(str(merged), node, "compatible"), COMPATIBLE)
        self.assertEqual(get("-tx", str(merged), node, "reg"), "3c")
        # The on-board chips on the same bus are untouched.
        self.assertIn("ina3221@40", get("-l", str(merged), "/bus@0/i2c@c240000").split())

    def test_client_name_is_no_other_drivers_i2c_id(self):
        aliases = Path("/lib/modules") / KDIR.parent.name / "modules.alias"
        if not aliases.exists():
            self.skipTest(f"{aliases} missing")
        taken = {line.split()[1][len("i2c:"):] for line in aliases.read_text().splitlines()
                 if line.startswith("alias i2c:")}
        self.assertNotIn(CLIENT_NAME, taken)

    def test_earlier_nodes_are_still_there(self):
        dts = decompile(self.dtbos[0])
        for c in ("edge,gpio-led", "edge,gpio-button", "edge,edge-ina219"):
            self.assertIn(f'compatible = "{c}";', dts)


class OledDriverContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = DRIVER.read_text() if DRIVER.exists() else ""
        cls.code = code_only(cls.src)

    def setUp(self):
        self.assertTrue(DRIVER.exists(), f"{DRIVER} missing")

    def body(self, name):
        b = function_body(self.src, name)
        self.assertIsNotNone(b, f"no {name}()")
        return b

    def test_is_an_i2c_driver_matched_by_dt_and_by_name(self):
        self.assertRegex(self.code, r'\{\s*\.compatible\s*=\s*"' + COMPATIBLE + r'"\s*\}')
        self.assertIn("MODULE_DEVICE_TABLE(of,", self.code)
        self.assertRegex(self.code, r'\{\s*"edge_oled"\s*,')   # new_device at a dead address
        self.assertIn("MODULE_DEVICE_TABLE(i2c,", self.code)
        self.assertRegex(self.code, r"\.probe_new\s*=\s*edge_oled_probe")
        self.assertRegex(self.code, r"\.remove\s*=\s*edge_oled_remove")

    def test_bytes_come_from_the_shared_headers(self):
        # The init bytes are checked against Step 9 by test_edge_oled_proto; none in the driver.
        self.assertIn('#include "edge_oled.h"', self.src)
        self.assertIn('#include "edge_oled_proto.h"', self.src)
        self.assertIn("edge_oled_init_seq", self.code)
        self.assertIn("edge_oled_window", self.code)
        self.assertNotRegex(self.code, r"0x(AE|AF|8D|A8|D5)\b")

    def test_transfers_are_plain_i2c_writes_and_errors_go_up(self):
        # [control byte][stream] is one I2C write message; a short count is an error too.
        body = self.body("edge_oled_send")
        self.assertIn("i2c_master_send(", body)
        self.assertRegex(body, r"if \(ret < 0\)\s*return ret;")
        self.assertIn("-EIO", body)
        self.assertNotIn("I2C_M_RD", self.code)          # SSD1306 cannot be read over I2C

    def test_no_retry_loops_or_sleeps(self):
        # Plan: no endless retry in probe. A transfer is tried once; the caller gets the errno.
        for fn in ("edge_oled_probe", "edge_oled_flush", "edge_oled_send"):
            with self.subTest(fn=fn):
                b = self.body(fn)
                self.assertNotRegex(b, r"\bwhile\b|\bgoto\s+retry|msleep|usleep_range")
        self.assertNotIn("dev_err_probe", self.body("edge_oled_flush"))

    def test_probe_fails_on_init_error_and_registers_last(self):
        b = self.body("edge_oled_probe")
        init, reg = b.find("edge_oled_flush("), b.find("misc_register(")
        self.assertTrue(0 <= init < reg, "probe: bring the panel up, then create /dev/edge_oled")
        self.assertIn("dev_err_probe(", b)

    def test_failed_transfer_forces_a_full_init_next_time(self):
        # After the OLED lost power the chip is back at reset (display off, no charge pump):
        # sending only a frame would show nothing. Any failure clears the flag, the next
        # flush sends the init sequence again.
        b = self.body("edge_oled_flush")
        self.assertIn("edge_oled_init_seq", b)
        self.assertRegex(b, r"if \(!oled->initialized\)")
        self.assertRegex(b, r"oled->initialized = (false|ret == 0|!ret)")

    def test_write_takes_exactly_one_frame(self):
        b = self.body("edge_oled_write")
        self.assertRegex(b, r"count != EDGE_OLED_FRAME_SIZE\)\s*return -EINVAL;")
        # Copied out of userspace before the lock: a bad pointer leaves the frame untouched.
        self.assertIn("memdup_user(", b)
        self.assertLess(b.index("memdup_user("), b.index("mutex_lock("))

    def test_ioctls(self):
        b = self.body("edge_oled_ioctl")
        for name in ("EDGE_OLED_IOC_CLEAR", "EDGE_OLED_IOC_FILL", "-ENOTTY"):
            self.assertIn(name, b)
        self.assertIn("get_user(", b)
        self.assertRegex(self.code, r"\.compat_ioctl\s*=\s*compat_ptr_ioctl")

    def test_unbind_with_an_open_file_is_safe(self):
        # remove() can run while /dev/edge_oled is open (sysfs unbind keeps the module):
        # the struct is reference counted, and every file operation checks the client.
        self.assertIn("struct kref", self.code)
        self.assertIn("kref_put(", self.body("edge_oled_release"))
        self.assertIn("kref_get(", self.body("edge_oled_open"))
        rm = self.body("edge_oled_remove")
        self.assertLess(rm.index("misc_deregister("), rm.index("oled->client = NULL"))
        self.assertIn("kref_put(", rm)
        for fn in ("edge_oled_write", "edge_oled_read", "edge_oled_ioctl"):
            with self.subTest(fn=fn):
                self.assertIn("-ENODEV", self.body(fn))
        self.assertNotIn("devm_kzalloc", self.code)       # must outlive the binding

    def test_remove_turns_the_display_off(self):
        self.assertIn("EDGE_OLED_CMD_DISPLAY_OFF", self.body("edge_oled_remove"))

    def test_scope_no_font_no_telemetry(self):
        # Step 10-b draws text, Step 10-c shows INA219 values: neither belongs here.
        self.assertNotRegex(self.code, r"(?i)glyph|font|ina219|hwmon")


@unittest.skipUnless(KDIR.exists(), "needs the kernel headers")
class OledBuildTest(unittest.TestCase):
    def test_module_builds_against_running_kernel(self):
        r = subprocess.run(["make", "-C", str(MOD_DIR)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertTrue((MOD_DIR / "edge_oled.ko").exists())
        self.assertNotRegex(r.stderr, r"\.[ch]:\d+:\d+: warning:")

    def test_protocol_vectors(self):
        build()
        r = subprocess.run([str(BUILD / "test_edge_oled_proto")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)


class CtlCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build()

    def run_ctl(self, *args):
        return subprocess.run([str(CTL), *args], capture_output=True, text=True, timeout=10)

    def test_usage_errors_exit_2(self):
        for args in ([], ["bogus"], ["fill"], ["fill", "0x100"], ["fill", "x"], ["edge", "clear"],
                     ["--dev"], ["--frobnicate"]):
            with self.subTest(args=args):
                r = self.run_ctl(*args)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("usage:", r.stderr)

    def test_missing_device_is_exit_1(self):
        r = self.run_ctl("--dev", "/nonexistent/edge_oled", "clear")
        self.assertEqual(r.returncode, 1)
        self.assertIn("/nonexistent/edge_oled", r.stderr)

    def test_frame_goes_through_write_and_clear_fill_through_ioctl(self):
        # A regular file stands in for the device: a picture is one 1024-byte write, and
        # clear / fill are ioctls (a regular file answers ENOTTY, so exit 1).
        with tempfile.TemporaryDirectory() as d:
            dev = Path(d) / "dev"
            dev.write_bytes(b"")
            r = self.run_ctl("--dev", str(dev), "pixel")
            self.assertEqual(r.returncode, 0, r.stderr)
            data = dev.read_bytes()
            self.assertEqual(len(data), 1024)
            self.assertEqual(data[0], 0x01)          # (0, 0): page 0, column 0, bit 0
            self.assertEqual(data[127], 0x01)        # (127, 0)
            self.assertEqual(data[7 * 128], 0x80)    # (0, 63): page 7, bit 7
            for cmd in (["clear"], ["fill", "0xff"]):
                with self.subTest(cmd=cmd):
                    r = self.run_ctl("--dev", str(dev), *cmd)
                    self.assertEqual(r.returncode, 1)
                    self.assertIn("ioctl", r.stderr)


class OledProbeGuardTest(unittest.TestCase):
    """Step 9 review: with edge_oled bound, oled_probe (I2C_RDWR, no EBUSY) would re-init the
    chip under the driver. It now checks /sys/bus/i2c/devices/<bus>-00<addr>/driver first."""

    @classmethod
    def setUpClass(cls):
        build()

    def fake_sysfs(self, d, bound):
        client = Path(d) / "bus" / "i2c" / "devices" / "250-003c"
        client.mkdir(parents=True)
        if bound:
            drv = Path(d) / "bus" / "i2c" / "drivers" / "edge_oled"
            drv.mkdir(parents=True)
            (client / "driver").symlink_to(drv)

    def run_probe(self, root, *args):
        env = dict(os.environ, OLED_PROBE_SYSFS=root)
        return subprocess.run([str(PROBE), "--bus", "250", *args], capture_output=True, text=True,
                              timeout=10, env=env)

    def test_refuses_a_bound_address(self):
        with tempfile.TemporaryDirectory() as d:
            self.fake_sysfs(d, bound=True)
            r = self.run_probe(d, "edge")
            self.assertEqual(r.returncode, 1)
            self.assertIn("250-003c", r.stderr)
            self.assertIn("edge_oled", r.stderr)
            self.assertIn("--force", r.stderr)
            self.assertNotIn("/dev/i2c-250", r.stderr)   # refused before opening the bus

    def test_force_skips_the_check(self):
        with tempfile.TemporaryDirectory() as d:
            self.fake_sysfs(d, bound=True)
            r = self.run_probe(d, "--force", "edge")
            self.assertEqual(r.returncode, 1)
            self.assertIn("/dev/i2c-250", r.stderr)      # got as far as opening the bus

    def test_unbound_client_is_not_refused(self):
        with tempfile.TemporaryDirectory() as d:
            self.fake_sysfs(d, bound=False)
            r = self.run_probe(d, "edge")
            self.assertIn("/dev/i2c-250", r.stderr)

    def test_drawing_lives_in_the_header(self):
        # oled_probe and edge_oled_ctl draw the same pictures from ssd1306.h.
        src = (REPO / "tools" / "oled_probe.cpp").read_text()
        self.assertIn("ssd1306::test_picture(", src)
        self.assertNotIn("set_pixel(", src)


class VerifyScriptTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(VERIFY.exists(), f"{VERIFY} missing")
        self.text = VERIFY.read_text()

    def test_syntax(self):
        r = subprocess.run(["bash", "-n", str(VERIFY)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_usage_error_exits_2(self):
        r = subprocess.run(["bash", str(VERIFY), "--bogus"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_needs_root_a_terminal_and_cleans_up(self):
        self.assertIn("EUID", self.text)
        self.assertIn("/dev/tty", self.text)
        self.assertIn("trap cleanup EXIT", self.text)

    def test_probe_init_is_seen_from_a_scrambled_panel(self):
        # Before insmod the panel shows inverse EDGE (oled_probe + i2ctransfer 0xA7); after
        # probe it must be dark: the driver's init (0xA6 normal) and clear both took effect.
        before = self.text[:self.text.index('insmod "$KO"', self.text.index("NODE present"))]
        self.assertIn("0xA7", before)
        self.assertRegex(self.text, r'ask "[^"]*(?i:dark)[^"]*"')

    def test_acceptance_pictures_come_from_userspace(self):
        for cmd in ("clear", "fill 0xff", "pattern", "pixel", "edge"):
            self.assertRegex(self.text, r'(\bctl|show "[^"]*") ' + cmd + r"\b")

    def test_oled_probe_is_refused_while_bound(self):
        after = self.text[self.text.index('insmod "$KO"', self.text.index("NODE present")):]
        self.assertIn('"$PROBE" --bus "$BUS" edge', after)
        self.assertIn("bound to driver edge_oled", after)

    def test_unbind_with_open_file_and_dead_address(self):
        self.assertRegex(self.text, r"\$DRV/unbind")
        self.assertRegex(self.text, r"\$DRV/bind")
        self.assertIn("ENODEV", self.text)
        self.assertIn("new_device", self.text)
        self.assertIn("delete_device", self.text)

    def test_unplug_check_is_optional_and_disconnects_everything(self):
        # Step 9: only VCC off still ACKs; all four wires.
        self.assertIn("--no-unplug", self.text)
        self.assertRegex(self.text, r"(?i)all four wires")
        self.assertIn("Remote I/O error", self.text)

    def test_exit_codes_documented(self):
        self.assertIn("0 = all checks passed, 1 = a check failed, 2 = environment/usage", self.text)


if __name__ == "__main__":
    unittest.main()
