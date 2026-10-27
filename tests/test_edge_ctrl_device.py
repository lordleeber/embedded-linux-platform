"""Checks against a bound edge_ctrl (Step 13): the sysfs attributes vs raw I2C to the Blue Pill.

The client 1-0042 comes from the overlay's controller@42 node under gen2_i2c (i2c-1);
edge_ctrl.ko binds it after insmod and the driver core adds the attributes to
/sys/bus/i2c/devices/1-0042/. Without a bound driver these tests skip, unless
EDGE_CTRL_REQUIRE=1 (set by scripts/verify_edge_ctrl.sh after insmod). The write
tests need root (sysfs files cannot be world-writable) and skip otherwise.

Raw access uses i2ctransfer -f: with the driver bound, i2c-dev refuses 0x42 without
it (EBUSY, Step 7). The expected register values are written out here from
firmware/stm32f103/docs/register-map.md, not taken from the driver's header.
A0 must sit on a steady voltage (the divider midpoint), as for Step 12-b's tests.
"""

import errno
import os
from pathlib import Path
import statistics
import subprocess
import unittest

from test_stm32_i2c_target import ADC_SPREAD_MAX


BUS = os.environ.get("EDGE_CTRL_BUS", "1")
CLIENT = Path(f"/sys/bus/i2c/devices/{BUS}-0042")
DRV = Path("/sys/bus/i2c/drivers/edge_ctrl")
REQUIRED = os.environ.get("EDGE_CTRL_REQUIRE") == "1"
RO = ("device_id", "firmware_version", "protocol_version", "adc", "button", "button_presses")
RW = ("led", "status")
LED, STATUS = 0x20, 0x30
RO_WRITE, BAD_VALUE = 0x01, 0x04


def bound():
    return CLIENT.exists() and (CLIENT / "driver").resolve() == DRV.resolve()


def attr(name):
    return (CLIENT / name).read_text()


def store(name, text):
    with open(CLIENT / name, "w") as f:
        f.write(text)


def raw(*msgs):
    r = subprocess.run(["i2ctransfer", "-f", "-y", BUS, *msgs], capture_output=True, text=True,
                       timeout=5)
    if r.returncode:
        raise AssertionError(f"i2ctransfer {' '.join(msgs)}: {r.stderr.strip()}")
    return [int(b, 16) for b in r.stdout.split()]


def raw_read(reg, n=1):
    return raw("w1@0x42", hex(reg), f"r{n}@0x42")


class EdgeCtrlDeviceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not bound():
            if REQUIRED:
                raise AssertionError(f"{CLIENT} is not bound to edge_ctrl")
            raise unittest.SkipTest(f"{CLIENT} not bound to edge_ctrl")

    def need_root(self):
        if not os.access(CLIENT / "led", os.W_OK):
            self.skipTest("writing the attributes needs root")

    def tearDown(self):
        if os.access(CLIENT / "led", os.W_OK):
            store("led", "0")

    def test_attribute_modes(self):
        for name in RO:
            with self.subTest(attr=name):
                self.assertEqual((CLIENT / name).stat().st_mode & 0o777, 0o444)
        for name in RW:
            with self.subTest(attr=name):
                self.assertEqual((CLIENT / name).stat().st_mode & 0o777, 0o644)

    def test_identification_matches_raw(self):
        dev_id, major, minor, proto = raw_read(0x00, 4)
        self.assertEqual((dev_id, proto), (0xED, 0x11))
        self.assertEqual(attr("device_id"), "0xed\n")
        self.assertEqual(attr("firmware_version"), f"{major}.{minor}\n")
        self.assertEqual(attr("protocol_version"), f"{proto >> 4}.{proto & 0xF}\n")

    def test_adc_matches_raw(self):
        drv = [int(attr("adc")) for _ in range(20)]
        lohi = [raw_read(0x10, 2) for _ in range(20)]
        rawv = [lo | hi << 8 for lo, hi in lohi]
        self.assertTrue(all(0 <= v <= 4095 for v in drv), drv)
        self.assertLessEqual(abs(statistics.median(drv) - statistics.median(rawv)), ADC_SPREAD_MAX,
                             (drv, rawv))

    def test_button_matches_raw(self):
        # nobody is pressing: both sides read released and the same count
        state, presses = raw_read(0x12, 2)
        self.assertEqual(attr("button"), f"{state & 1}\n")
        self.assertEqual(attr("button_presses"), f"{presses}\n")

    def test_status_matches_raw(self):
        self.assertEqual(attr("status"), f"{raw_read(STATUS)[0]:#04x}\n")

    def test_led_write_reaches_the_board(self):
        self.need_root()
        for v in (1, 0, 1):
            store("led", f"{v}\n")
            self.assertEqual(raw_read(LED), [v])
            self.assertEqual(attr("led"), f"{v}\n")

    def test_bad_led_value_is_refused_before_the_bus(self):
        self.need_root()
        store("led", "1")
        store("status", "0xff")
        # "\n" is what `echo > led` sends. An empty string would test nothing: Python issues
        # no write() for it, and sysfs returns 0 for a 0-byte write without calling store.
        for text in ("2", "0x10", "-1", "on", "\n"):
            with self.subTest(text=text):
                with self.assertRaises(OSError) as cm:
                    store("led", text)
                self.assertEqual(cm.exception.errno, errno.EINVAL)
        # nothing reached the firmware: no BAD_VALUE, LED still on
        self.assertEqual(raw_read(STATUS), [0])
        self.assertEqual(raw_read(LED), [1])

    def test_status_write_one_to_clear(self):
        self.need_root()
        store("status", "0xff")
        raw("w2@0x42", "0x00", "0x55")  # write DEVICE_ID: RO_WRITE
        self.assertEqual(attr("status"), f"{RO_WRITE:#04x}\n")
        store("status", "0x02")  # another bit: nothing to clear
        self.assertEqual(attr("status"), f"{RO_WRITE:#04x}\n")
        store("status", "0x01")
        self.assertEqual(attr("status"), "0x00\n")
        self.assertEqual(raw_read(STATUS), [0])
        with self.assertRaises(OSError) as cm:
            store("status", "0x100")
        self.assertEqual(cm.exception.errno, errno.EINVAL)

    def test_many_reads(self):
        for i in range(200):
            self.assertEqual(attr("device_id"), "0xed\n", i)
            int(attr("adc"))


if __name__ == "__main__":
    unittest.main()
