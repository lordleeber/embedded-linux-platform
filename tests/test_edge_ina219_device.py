"""Checks against a bound edge_ina219 (Step 7): sysfs attributes vs Step 6-b's ina219_raw.

The client 7-0041 is created by the overlay's ina219@41 node; edge_ina219.ko
binds it after insmod. Without a bound driver these tests skip, unless
EDGE_INA219_REQUIRE=1 (set by scripts/verify_edge_ina219.sh after insmod).
EDGE_INA219_BUS overrides the bus number (the script finds it by name).

Comparison with ina219_raw happens in the same second but not the same
conversion: the bus voltage may move a few LSB (4 mV each) and the current
with the load. Tolerances: 40 mV, 50 mA (Step 6-b's discharge readings moved
about 40 mA within 20 s).
"""

import os
from pathlib import Path
import re
import stat
import subprocess
import unittest


REPO = Path(__file__).resolve().parents[1]
BUS = int(os.environ.get("EDGE_INA219_BUS", "7"))
CLIENT = Path(f"/sys/bus/i2c/devices/{BUS}-0041")
DRV = Path("/sys/bus/i2c/drivers/edge_ina219")
RAW = REPO / "build" / "ina219_raw"
REQUIRED = os.environ.get("EDGE_INA219_REQUIRE") == "1"
ATTRS = ("registers", "bus_mv", "shunt_uv", "current_ua", "power_uw")


def ina219_raw():
    """Six raw registers and the two current paths from build/ina219_raw."""
    out = subprocess.run([str(RAW), "--bus", str(BUS)], capture_output=True, text=True,
                         check=True, timeout=10).stdout
    regs = [int(v, 16) for v in re.findall(r"^0x0\d \S+\s+(0x[0-9A-F]{4})$", out, re.M)]
    cur = re.search(r"^current \(reg\):\s+(-?\d+\.\d+) mA", out, re.M)
    return regs, (float(cur.group(1)) if cur else None)


class EdgeIna219DeviceTest(unittest.TestCase):
    def setUp(self):
        bound = (CLIENT / "driver").resolve() == DRV.resolve() if (CLIENT / "driver").exists() else False
        if not bound:
            if REQUIRED:
                self.fail(f"{CLIENT} not bound to edge_ina219 but EDGE_INA219_REQUIRE=1")
            self.skipTest(f"{CLIENT} not bound to edge_ina219 (overlay or module missing)")

    def attr(self, name):
        return (CLIENT / name).read_text()

    def registers(self):
        words = self.attr("registers").split()
        self.assertEqual(len(words), 6, words)
        return [int(w, 16) for w in words]

    def test_attributes_are_read_only_files(self):
        for name in ATTRS:
            with self.subTest(attr=name):
                st = (CLIENT / name).stat()
                self.assertEqual(stat.S_IMODE(st.st_mode), 0o444)

    def test_registers_format(self):
        self.assertRegex(self.attr("registers"), r"^(0x[0-9A-F]{4} ){5}0x[0-9A-F]{4}\n$")

    def test_probe_left_the_sample_settings(self):
        regs = self.registers()
        self.assertEqual(regs[0], 0x0EEF)
        self.assertEqual(regs[5], 26868)

    def test_bus_voltage_is_a_battery_voltage(self):
        # Same window as Step 6-a / 6-b: 3S lithium 9.0 .. 12.6 V, plus 0.2 V.
        self.assertTrue(9000 <= int(self.attr("bus_mv")) <= 12800, self.attr("bus_mv"))

    def test_values_are_integers_with_newline(self):
        for name in ATTRS[1:]:
            with self.subTest(attr=name):
                self.assertRegex(self.attr(name), r"^-?\d+\n$")

    def test_matches_ina219_raw(self):
        if not RAW.exists():
            self.skipTest(f"{RAW} not built")
        tool_regs, tool_ma = ina219_raw()
        regs = self.registers()
        bus_mv = int(self.attr("bus_mv"))
        cur_ma = int(self.attr("current_ua")) / 1000
        self.assertEqual(len(tool_regs), 6)
        self.assertEqual(regs[0], tool_regs[0], "Config")
        self.assertEqual(regs[5], tool_regs[5], "Calibration")
        tool_mv = (tool_regs[2] >> 3) * 4
        self.assertLessEqual(abs(bus_mv - tool_mv), 40, f"driver {bus_mv} mV, tool {tool_mv} mV")
        self.assertIsNotNone(tool_ma)
        self.assertLessEqual(abs(cur_ma - tool_ma), 50, f"driver {cur_ma} mA, tool {tool_ma} mA")

    def test_repeated_reads_do_not_fail(self):
        for _ in range(100):
            self.attr("bus_mv")
            self.attr("current_ua")


if __name__ == "__main__":
    unittest.main()
