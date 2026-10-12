"""Checks against a bound edge_ina219 (Steps 7-8): hwmon files vs Step 6-b's ina219_raw.

The client 7-0041 is created by the overlay's ina219@41 node; edge_ina219.ko
binds it after insmod and registers one hwmon device under it
(/sys/bus/i2c/devices/7-0041/hwmon/hwmonN, also /sys/class/hwmon/hwmonN).
Without a bound driver these tests skip, unless EDGE_INA219_REQUIRE=1 (set by
scripts/verify_edge_ina219.sh after insmod). EDGE_INA219_BUS overrides the bus
number (the script finds it by name).

hwmon units (Documentation/hwmon/sysfs-interface.rst): in*_input mV,
curr*_input mA, power*_input uW. in0 is the shunt voltage, in1 the bus voltage.

Comparison with ina219_raw happens in the same second but not the same
conversion: the bus voltage may move a few LSB (4 mV each) and the current
with the load. Tolerances: 40 mV, 50 mA (Step 6-b's discharge readings moved
about 40 mA within 20 s), and what 50 mA means for the other two: 0.5 mV across
the 0.01 ohm shunt (plus 0.5 mV for hwmon's whole-mV rounding), 700 mW at up to
12.8 V plus margin.
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
INPUTS = ("in0_input", "in1_input", "curr1_input", "power1_input")
LABELS = {"in0_label": "shunt", "in1_label": "bus"}
STEP7_ATTRS = ("registers", "bus_mv", "shunt_uv", "current_ua", "power_uw")


def ina219_raw():
    """Six raw registers and the decoded values (mV / mA / mW) from build/ina219_raw."""
    out = subprocess.run([str(RAW), "--bus", str(BUS)], capture_output=True, text=True,
                         check=True, timeout=10).stdout
    regs = [int(v, 16) for v in re.findall(r"^0x0\d \S+\s+(0x[0-9A-F]{4})$", out, re.M)]
    values = {}
    for key, label, unit in (("shunt_mv", r"shunt voltage:", "mV"),
                             ("current_ma", r"current \(reg\):", "mA"),
                             ("power_mw", r"power \(reg\):", "mW")):
        m = re.search(r"^" + label + r"\s+(-?\d+\.\d+) " + unit, out, re.M)
        values[key] = float(m.group(1)) if m else None
    return regs, values


class EdgeIna219HwmonTest(unittest.TestCase):
    def setUp(self):
        bound = (CLIENT / "driver").resolve() == DRV.resolve() if (CLIENT / "driver").exists() else False
        if not bound:
            if REQUIRED:
                self.fail(f"{CLIENT} not bound to edge_ina219 but EDGE_INA219_REQUIRE=1")
            self.skipTest(f"{CLIENT} not bound to edge_ina219 (overlay or module missing)")
        devs = sorted((CLIENT / "hwmon").glob("hwmon*"))
        self.assertEqual(len(devs), 1, f"hwmon devices under {CLIENT}: {devs}")
        self.hwmon = devs[0]

    def read(self, name):
        return (self.hwmon / name).read_text()

    def value(self, name):
        return int(self.read(name))

    def test_name_and_class_link(self):
        self.assertEqual(self.read("name"), "edge_ina219\n")
        link = Path("/sys/class/hwmon") / self.hwmon.name
        self.assertEqual(link.resolve(), self.hwmon.resolve())

    def test_exactly_one_edge_ina219_in_the_class(self):
        names = [p.name for p in Path("/sys/class/hwmon").iterdir()
                 if (p / "name").read_text() == "edge_ina219\n"]
        self.assertEqual(names, [self.hwmon.name])

    def test_files_are_read_only(self):
        for name in INPUTS + tuple(LABELS):
            with self.subTest(file=name):
                self.assertEqual(stat.S_IMODE((self.hwmon / name).stat().st_mode), 0o444)

    def test_only_the_declared_channels(self):
        found = {p.name for p in self.hwmon.iterdir() if re.match(r"(in|curr|power)\d+_", p.name)}
        self.assertEqual(found, set(INPUTS) | set(LABELS))

    def test_labels(self):
        for name, label in LABELS.items():
            with self.subTest(file=name):
                self.assertEqual(self.read(name), label + "\n")

    def test_private_step7_attributes_are_gone(self):
        for name in STEP7_ATTRS:
            with self.subTest(attr=name):
                self.assertFalse((CLIENT / name).exists())

    def test_values_are_integers_with_newline(self):
        for name in INPUTS:
            with self.subTest(file=name):
                self.assertRegex(self.read(name), r"^-?\d+\n$")

    def test_bus_voltage_is_a_battery_voltage(self):
        # Same window as Step 6-a / 6-b: 3S lithium 9.0 .. 12.6 V, plus 0.2 V; in mV, not V.
        self.assertTrue(9000 <= self.value("in1_input") <= 12800, self.read("in1_input"))

    def test_matches_ina219_raw(self):
        if not RAW.exists():
            self.skipTest(f"{RAW} not built")
        tool_regs, tool = ina219_raw()
        bus_mv = self.value("in1_input")
        shunt_mv = self.value("in0_input")
        cur_ma = self.value("curr1_input")
        power_mw = self.value("power1_input") / 1000
        self.assertEqual(len(tool_regs), 6)
        self.assertEqual(tool_regs[0], 0x0EEF, "Config")
        self.assertEqual(tool_regs[5], 26868, "Calibration")
        tool_mv = (tool_regs[2] >> 3) * 4
        self.assertLessEqual(abs(bus_mv - tool_mv), 40, f"hwmon {bus_mv} mV, tool {tool_mv} mV")
        for key, mine, tol in (("shunt_mv", shunt_mv, 1.0), ("current_ma", cur_ma, 50),
                               ("power_mw", power_mw, 700)):
            with self.subTest(value=key):
                self.assertIsNotNone(tool[key], f"ina219_raw printed no {key}")
                self.assertLessEqual(abs(mine - tool[key]), tol, f"hwmon {mine}, tool {tool[key]}")

    def test_1000_reads_of_every_input(self):
        # Every read goes to the chip; none may fail or come back malformed.
        for name in INPUTS:
            with self.subTest(file=name):
                path = self.hwmon / name
                for i in range(1000):
                    text = path.read_text()
                    self.assertRegex(text, r"^-?\d+\n$", f"read {i}")


if __name__ == "__main__":
    unittest.main()
