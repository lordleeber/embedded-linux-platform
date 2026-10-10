"""Checks for the Waveshare UPS Power Module (C) sample, third_party/waveshare_ups_c/ina219.py.

Step 6-a only explains the vendor's script; it is kept byte-for-byte (the checksum
pins it), so every claim the chapter makes about it is checked here instead:
the register traffic is replayed through a fake `smbus` module (no hardware),
and the numbers follow the INA219 datasheet (registers are big-endian 16-bit,
bus voltage LSB 4 mV in bits 15..3, shunt voltage LSB 10 uV, two's complement).
Hardware tests read the real chip on i2c-7 at 0x41 and run only with
EDGE_INA219_HW=1, which scripts/verify_ina219_sample.sh sets.
"""

import contextlib
import errno
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time
import types
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "third_party" / "waveshare_ups_c" / "ina219.py"
SAMPLE_SHA256 = "ceb770e56f2feae3af0b29dc237e94097e12704b555afc5024e3214efca748fb"
ORIGINAL = Path.home() / "UPS_Power_Module_C" / "ina219.py"
BUS, ADDR = 7, 0x41
HW = os.environ.get("EDGE_INA219_HW") == "1"


class FakeSMBus:
    """Records writes; reads come from a {register: [msb, lsb]} table."""

    def __init__(self, bus, regs=None):
        self.bus = bus
        self.regs = regs if regs is not None else {}
        self.writes = []

    def read_i2c_block_data(self, addr, reg, length):
        self.reads_from = addr
        return list(self.regs.get(reg, [0, 0]))[:length]

    def write_i2c_block_data(self, addr, reg, data):
        self.writes.append((addr, reg, list(data)))


def load_sample(regs=None):
    """Import the sample with `smbus` replaced; returns (module, list of buses opened)."""
    opened = []

    def factory(bus):
        b = FakeSMBus(bus, regs)
        opened.append(b)
        return b

    fake = types.ModuleType("smbus")
    fake.SMBus = factory
    with mock.patch.dict(sys.modules, {"smbus": fake}):
        spec = importlib.util.spec_from_file_location("ina219_sample", SAMPLE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    mod.smbus = fake  # module-level name the class looks up at construction time
    return mod, opened


def run_main_once(regs):
    """Run the sample as __main__ for one loop; returns (stdout, the fake bus)."""
    opened = []

    def factory(bus):
        b = FakeSMBus(bus, regs)
        opened.append(b)
        return b

    fake = types.ModuleType("smbus")
    fake.SMBus = factory
    out = io.StringIO()

    def stop(_):
        raise KeyboardInterrupt

    with mock.patch.dict(sys.modules, {"smbus": fake}), \
            mock.patch("time.sleep", stop), mock.patch("sys.stdout", out):
        with contextlib.suppress(KeyboardInterrupt):
            runpy.run_path(str(SAMPLE), run_name="__main__")
    return out.getvalue(), opened[0]


def be(value):
    """16-bit value as the two bytes the chip sends, MSB first."""
    value &= 0xFFFF
    return [value >> 8, value & 0xFF]


class VendoredCopyTest(unittest.TestCase):
    def test_copy_is_unmodified(self):
        self.assertTrue(SAMPLE.is_file(), f"{SAMPLE} missing")
        self.assertEqual(hashlib.sha256(SAMPLE.read_bytes()).hexdigest(), SAMPLE_SHA256)

    @unittest.skipUnless(ORIGINAL.is_file(), "no ~/UPS_Power_Module_C/ina219.py on this machine")
    def test_copy_matches_the_file_on_the_board(self):
        self.assertEqual(SAMPLE.read_bytes(), ORIGINAL.read_bytes())


class InitSequenceTest(unittest.TestCase):
    def test_main_talks_to_bus_7_address_0x41(self):
        # The class defaults to addr 0x40, but __main__ passes 0x41 (the UPS C module).
        _, bus = run_main_once({2: be(0x609A)})
        self.assertEqual(bus.bus, BUS)
        self.assertEqual({w[0] for w in bus.writes}, {ADDR})

    def test_writes_calibration_then_config_big_endian(self):
        mod, opened = load_sample()
        mod.INA219(addr=ADDR)
        self.assertEqual(opened[0].writes, [
            (ADDR, 0x05, [0x68, 0xF4]),   # calibration 26868
            (ADDR, 0x00, [0x0E, 0xEF]),   # config: see test_config_fields
        ])

    def test_config_fields(self):
        # BRNG=0 (16 V), PG=01 (/2, 80 mV), BADC=SADC=1101 (12-bit, 32 samples), MODE=111.
        cfg = 0x0EEF
        self.assertEqual(cfg >> 13 & 1, 0)
        self.assertEqual(cfg >> 11 & 3, 1)
        self.assertEqual(cfg >> 7 & 0xF, 0xD)
        self.assertEqual(cfg >> 3 & 0xF, 0xD)
        self.assertEqual(cfg & 7, 7)

    def test_lsb_constants_follow_from_calibration(self):
        # Datasheet: Cal = trunc(0.04096 / (Current_LSB * R_shunt)), Power_LSB = 20 * Current_LSB.
        # With R_shunt = 0.01 ohm, Cal 26868 gives 0.15245 mA; the code rounds it to 0.1524.
        mod, _ = load_sample()
        ina = mod.INA219(addr=ADDR)
        lsb_from_cal = 0.04096 / (ina._cal_value * 0.01) * 1000   # mA
        self.assertAlmostEqual(ina._current_lsb, lsb_from_cal, delta=0.0001)
        self.assertAlmostEqual(ina._power_lsb, 20 * ina._current_lsb / 1000, places=9)

    def test_comments_disagree_with_the_code(self):
        # The chapter points these out: the comments describe another calibration.
        text = SAMPLE.read_text()
        self.assertIn("Cal = 13434", text)
        self.assertIn("self._cal_value = 26868", text)
        self.assertIn("Current LSB = 100uA per bit", text)
        self.assertIn("self._current_lsb = 0.1524", text)


class ConversionTest(unittest.TestCase):
    def setUp(self):
        self.mod, self.opened = load_sample()
        self.ina = self.mod.INA219(addr=ADDR)
        self.regs = self.opened[0].regs

    def test_bus_voltage_drops_status_bits(self):
        # Bits 1/0 are CNVR/OVF, bit 2 unused; 0x609A >> 3 = 3091 -> 12.364 V (seen on the board).
        for raw in (0x609A, 0x6098, 0x609B):
            self.regs[2] = be(raw)
            self.assertAlmostEqual(self.ina.getBusVoltage_V(), 12.364, places=6)

    def test_read_is_msb_first(self):
        self.regs[2] = [0x60, 0x9A]
        self.assertAlmostEqual(self.ina.getBusVoltage_V(), 12.364, places=6)
        self.regs[2] = [0x9A, 0x60]   # byte-swapped would be 0x9A60 -> 19.756 V
        self.assertNotAlmostEqual(self.ina.getBusVoltage_V(), 12.364, places=3)

    def test_shunt_is_signed_10uV_per_bit(self):
        cases = {0x0000: 0.0, 0x0064: 1.0, 0xFFFF: -0.01, 0xFF9C: -1.0, 0x8000: -327.68}
        for raw, mv in cases.items():
            self.regs[1] = be(raw)
            self.assertAlmostEqual(self.ina.getShuntVoltage_mV(), mv, places=6, msg=hex(raw))

    def test_current_is_signed(self):
        self.regs[4] = be(100)
        self.assertAlmostEqual(self.ina.getCurrent_mA(), 15.24, places=6)
        self.regs[4] = be(-100)
        self.assertAlmostEqual(self.ina.getCurrent_mA(), -15.24, places=6)

    def test_power(self):
        self.regs[3] = be(100)
        self.assertAlmostEqual(self.ina.getPower_W(), 0.3048, places=6)


class MainLoopTest(unittest.TestCase):
    def test_prints_the_board_reading(self):
        out, _ = run_main_once({2: be(0x609A)})
        self.assertEqual(out.splitlines(), [
            "Load Voltage:  12.364 V",
            "Current:        0.000000 A",
            "Power:          0.000000 W",
            "Percentage:     93.44 %",
        ])

    def test_percentage_is_linear_9_to_12_6_V_and_clamped(self):
        # (V - 9) / 3.6: a 3S Li-ion pack, 3.0 V .. 4.2 V per cell.
        for volts, pct in ((9.0, "0.00"), (10.8, "50.00"), (12.6, "100.00"),
                           (8.0, "0.00"), (13.0, "100.00")):
            raw = round(volts / 0.004) << 3
            out, _ = run_main_once({2: be(raw)})
            self.assertIn("Percentage:    {:6.2f} %".format(float(pct)), out, volts)

    def test_discharge_shows_negative_current(self):
        out, _ = run_main_once({2: be(0x5A00), 4: be(-6562)})   # -6562 * 0.1524 mA ~ -1 A
        self.assertIn("Current:       -1.000049 A", out)


class VerifyScriptTest(unittest.TestCase):
    SCRIPT = REPO / "scripts" / "verify_ina219_sample.sh"

    def test_bad_argument_is_a_usage_error(self):
        r = subprocess.run(["bash", str(self.SCRIPT), "--bogus"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("usage", r.stderr)

    def test_scans_with_read_byte_probing(self):
        # Tegra i2c cannot do SMBus Quick Write, so plain `i2cdetect -y 7` skips 0x40-0x4f
        # and never shows 0x41; -r probes with a read instead.
        self.assertRegex(self.SCRIPT.read_text(), r"i2cdetect -y -r")


@unittest.skipUnless(HW, "set EDGE_INA219_HW=1 (scripts/verify_ina219_sample.sh)")
class HardwareTest(unittest.TestCase):
    def read(self, reg, addr=ADDR):
        import smbus
        bus = smbus.SMBus(BUS)
        try:
            d = bus.read_i2c_block_data(addr, reg, 2)
        finally:
            bus.close()
        return d[0] << 8 | d[1]

    def first_block(self):
        proc = subprocess.Popen([sys.executable, "-u", str(SAMPLE)], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        try:
            lines = [proc.stdout.readline().strip() for _ in range(4)]
        finally:
            proc.kill()
            proc.communicate()
        return dict(line.split(":", 1) for line in lines if ":" in line)

    def test_script_prints_a_plausible_battery_voltage(self):
        block = self.first_block()
        volts = float(block["Load Voltage"].split()[0])
        self.assertTrue(9.0 <= volts <= 12.8, volts)   # 3S pack
        pct = float(block["Percentage"].split()[0])
        self.assertAlmostEqual(pct, max(0, min((volts - 9) / 3.6 * 100, 100)), delta=0.01)

    def test_chip_keeps_what_the_script_wrote(self):
        self.first_block()
        self.assertEqual(self.read(0x00), 0x0EEF)
        self.assertEqual(self.read(0x05), 0x68F4)

    def test_reading_power_clears_the_conversion_ready_bit(self):
        # Datasheet: CNVR (bus voltage bit 1) is set when a conversion finishes and cleared
        # by reading the Power register. 12-bit x 32 samples is 17.02 ms per channel, so
        # bus + shunt is ~34 ms; 0.1 s later a fresh result must be there.
        # A conversion can finish between the two reads (< 1 ms of ~34 ms), so try a few times.
        self.first_block()
        cleared = 0
        for _ in range(5):
            self.read(0x03)
            cleared += not self.read(0x02) & 0b10
        self.assertGreater(cleared, 0, "CNVR still set right after reading Power")
        time.sleep(0.1)
        raw = self.read(0x02)
        self.assertTrue(raw & 0b10, f"CNVR not set 0.1 s later: {raw:#06x}")
        self.assertFalse(raw & 0b01, f"OVF set: {raw:#06x}")

    def test_absent_address_is_an_io_error(self):
        # What the script hits if the module is unplugged: no ACK -> EREMOTEIO.
        with self.assertRaises(OSError) as ctx:
            self.read(0x00, addr=0x45)
        self.assertEqual(ctx.exception.errno, errno.EREMOTEIO)


if __name__ == "__main__":
    unittest.main()
