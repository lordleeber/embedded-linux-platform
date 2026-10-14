"""Checks for the Step 11 STM32F103 I2C target firmware (firmware/stm32f103/).

The Jetson is the I2C controller; the Blue Pill's I2C1 answers at 0x42 with four registers
(DEVICE_ID, FW_MAJOR, FW_MINOR, LED_CONTROL). The protocol lives in Core/Src/i2c_target.c
without any SPL call and is tested on the host by tests/test_i2c_target.cpp; main.c only
turns I2C1 interrupts into i2c_target_* calls and drives the PC13 LED.
The firmware build needs PlatformIO (~/.platformio/penv/bin/pio or PIO=...) and is skipped
without it. Hardware tests talk to the flashed board with i2c-tools and run only with
EDGE_STM32_HW=1, which scripts/verify_stm32_i2c.sh sets.
"""

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest


REPO = Path(__file__).resolve().parents[1]
FW = REPO / "firmware" / "stm32f103"
HEADER = FW / "Core" / "Inc" / "i2c_target.h"
CORE_C = FW / "Core" / "Src" / "i2c_target.c"
MAIN_C = FW / "Core" / "Src" / "main.c"
REGMAP = FW / "docs" / "register-map.md"
INI = FW / "platformio.ini"
SCRIPT = REPO / "scripts" / "verify_stm32_i2c.sh"
BUILD = REPO / "build"
VECTORS = BUILD / "test_i2c_target"
PIO = os.environ.get("PIO", str(Path.home() / ".platformio" / "penv" / "bin" / "pio"))
HW = os.environ.get("EDGE_STM32_HW") == "1"
BUS = os.environ.get("EDGE_STM32_BUS", "1")
ADDR = "0x42"


def defines(text):
    return {m[0]: int(m[1], 0) for m in re.findall(r"^#define (\w+) (0x[0-9A-Fa-f]+|\d+)", text, re.M)}


def code_only(text):
    """C source without comments, so a word in a comment does not satisfy or break a check."""
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)


class VectorsTest(unittest.TestCase):
    def test_host_vectors_pass(self):
        subprocess.run(["cmake", "-S", str(REPO), "-B", str(BUILD)], check=True, capture_output=True)
        subprocess.run(["cmake", "--build", str(BUILD), "--target", "test_i2c_target"],
                       check=True, capture_output=True)
        r = subprocess.run([str(VECTORS)], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stdout)


class RegisterMapTest(unittest.TestCase):
    """docs/register-map.md is what the Jetson side (Step 12-13) will be written from."""

    def setUp(self):
        self.d = defines(HEADER.read_text())
        self.rows = {int(a, 16): (name, acc, int(v, 16)) for a, name, acc, v in
                     re.findall(r"^\| (0x[0-9A-F]{2}) \| (\w+) \| (RO|RW) \| (0x[0-9A-F]{2}) \|",
                                REGMAP.read_text(), re.M)}

    def test_every_register_in_the_header_is_documented_with_its_value(self):
        want = {
            self.d["REG_DEVICE_ID"]: ("DEVICE_ID", "RO", self.d["DEVICE_ID_VALUE"]),
            self.d["REG_FW_MAJOR"]: ("FW_MAJOR", "RO", self.d["FW_VERSION_MAJOR"]),
            self.d["REG_FW_MINOR"]: ("FW_MINOR", "RO", self.d["FW_VERSION_MINOR"]),
            self.d["REG_LED_CONTROL"]: ("LED_CONTROL", "RW", 0),
        }
        self.assertEqual(self.rows, want)

    def test_address_and_unmapped_value(self):
        text = REGMAP.read_text()
        self.assertEqual(self.d["I2C_TARGET_ADDR"], 0x42)
        self.assertIn("**0x42**", text)
        self.assertIn(f"0x{self.d['REG_UNMAPPED_VALUE']:02X}", text)


class FirmwareSourceTest(unittest.TestCase):
    def setUp(self):
        self.core = code_only(CORE_C.read_text())
        self.main = code_only(MAIN_C.read_text())

    def test_protocol_core_has_no_hardware_access(self):
        self.assertNotRegex(self.core, r"#include\s+\"(stm32|misc)")
        self.assertNotRegex(self.core, r"\bI2C1\b|\bGPIO[A-E]\b|->(SR1|DR)\b")

    def test_main_sets_up_i2c1_on_pb6_pb7_at_the_protocol_address(self):
        for s in ("RCC_APB1Periph_I2C1", "GPIO_Pin_6", "GPIO_Pin_7", "GPIO_Mode_AF_OD",
                  "I2C_TARGET_ADDR << 1", "I2C_Ack_Enable", "I2C_Init(I2C1", "I2C_ITConfig(I2C1"):
            self.assertIn(s, self.main)

    def test_main_drives_the_active_low_pc13_led(self):
        self.assertIn("GPIO_Pin_13", self.main)
        self.assertRegex(self.main, r"GPIO_ResetBits\(GPIOC, GPIO_Pin_13\)")

    def test_interrupt_handlers_feed_the_core(self):
        for s in ("void I2C1_EV_IRQHandler(void)", "void I2C1_ER_IRQHandler(void)",
                  "i2c_target_write_start(", "i2c_target_rx(", "i2c_target_tx(", "i2c_target_stop("):
            self.assertIn(s, self.main)

    def test_read_ends_on_the_controllers_nack(self):
        # A read ends with the controller's NACK (AF), not STOPF (RM0008 slave transmitter):
        # AF must be cleared and must end the transaction, or the error interrupt never stops.
        self.assertIn("I2C_IT_AF", self.main)
        er = self.main[self.main.index("void I2C1_ER_IRQHandler(void)"):]
        self.assertIn("I2C_ClearITPendingBit(I2C1", er[:er.index("\n}")])
        self.assertIn("i2c_target_stop(", er[:er.index("\n}")])

    def test_transmit_is_driven_by_txe(self):
        # Step 11 measured that TXE with BUF always on returns no stale byte (docs/baseline.md);
        # the BUF on / off switching tried first is gone.
        self.assertIn("I2C_SR1_TXE", self.main)
        self.assertNotRegex(self.main, r"I2C_IT_BUF, DISABLE")

    def test_main_loop_does_not_sleep(self):
        # With WFI in the main loop and DBGMCU_CR.DBG_SLEEP cleared by a power cycle, SWD can no
        # longer read memory ("Examination failed"), so the board cannot be reflashed (Step 11).
        self.assertNotIn("__WFI", self.main)
        self.assertNotIn("__WFE", self.main)

    def test_scope_step11_only(self):
        # phase05 Step 11 "這一步不做": no ADC, watchdog, SPI, DMA, no Jetson kernel driver.
        for name in ("ADC", "IWDG", "WWDG", "SPI", "DMA"):
            for path in (CORE_C, MAIN_C, HEADER, FW / "Core" / "Inc" / "stm32f10x_conf.h"):
                self.assertNotRegex(code_only(path.read_text()), rf"\b{name}\w*", f"{name} in {path.name}")
        self.assertFalse((REPO / "kernel" / "edge_ctrl").exists())


class VendorTest(unittest.TestCase):
    def test_vendor_files_are_unchanged(self):
        lines = (FW / "vendor.sha256").read_text().split("\n")
        entries = [l.split("  ", 1) for l in lines if l]
        self.assertEqual(len(entries), 14)
        for digest, name in entries:
            self.assertEqual(hashlib.sha256((FW / name).read_bytes()).hexdigest(), digest, name)

    def test_build_uses_only_the_needed_spl_drivers(self):
        ini = INI.read_text()
        for f in ("misc.c", "stm32f10x_gpio.c", "stm32f10x_i2c.c", "stm32f10x_rcc.c"):
            self.assertIn(f"+<Library/{f}>", ini)
        self.assertNotIn("+<Start/core_cm3.c>", ini)
        self.assertNotIn("+<Start/>", ini)
        self.assertNotIn("+<Library/>", ini)
        self.assertNotRegex(ini, r"(?m)^framework")
        self.assertRegex(ini, r"(?m)^ *platformio/toolchain-gccarmnoneeabi@1\.120301\.0")


@unittest.skipUnless(Path(PIO).exists() or shutil.which("pio"), "PlatformIO not installed")
class FirmwareBuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pio = PIO if Path(PIO).exists() else shutil.which("pio")
        cls.r = subprocess.run([pio, "run", "-d", str(FW)], capture_output=True, text=True, timeout=900)
        cls.elf = FW / ".pio" / "build" / "bluepill" / "firmware.elf"
        tc = Path.home() / ".platformio" / "packages" / "toolchain-gccarmnoneeabi" / "bin"
        cls.nm = tc / "arm-none-eabi-nm"

    def test_builds(self):
        self.assertEqual(self.r.returncode, 0, self.r.stdout[-3000:])
        self.assertTrue((FW / ".pio" / "build" / "bluepill" / "firmware.bin").is_file())

    def test_irq_handlers_are_ours_not_the_weak_default(self):
        # A misspelled handler name links fine and leaves the vector on Default_Handler.
        out = subprocess.run([str(self.nm), str(self.elf)], capture_output=True, text=True, check=True).stdout
        sym = {n: (t, a) for a, t, n in (l.split() for l in out.splitlines() if len(l.split()) == 3)}
        for h in ("I2C1_EV_IRQHandler", "I2C1_ER_IRQHandler"):
            self.assertEqual(sym[h][0], "T", h)
            self.assertNotEqual(sym[h][1], sym["Default_Handler"][1], h)


def i2c(*args):
    return subprocess.run(list(args), capture_output=True, text=True, timeout=5)


def get(reg):
    r = i2c("i2cget", "-y", BUS, ADDR, hex(reg))
    if r.returncode:
        raise AssertionError(f"i2cget {hex(reg)}: {r.stderr.strip()}")
    return int(r.stdout, 16)


def put(reg, value):
    r = i2c("i2cset", "-y", BUS, ADDR, hex(reg), hex(value))
    if r.returncode:
        raise AssertionError(f"i2cset {hex(reg)} {hex(value)}: {r.stderr.strip()}")


@unittest.skipUnless(HW, "set EDGE_STM32_HW=1 (scripts/verify_stm32_i2c.sh) to talk to the board")
class HardwareTest(unittest.TestCase):
    def tearDown(self):
        put(0x20, 0)

    def test_identification(self):
        self.assertEqual([get(r) for r in (0x00, 0x01, 0x02)], [0xED, 0x00, 0x01])

    def test_led_control_round_trip_and_invalid_values(self):
        for v in (1, 0, 1):
            put(0x20, v)
            self.assertEqual(get(0x20), v)
        put(0x20, 2)
        self.assertEqual(get(0x20), 1, "invalid value must leave LED_CONTROL alone")

    def test_read_only_and_unmapped(self):
        put(0x00, 0x55)
        self.assertEqual(get(0x00), 0xED)
        self.assertEqual(get(0x10), 0xFF)

    def test_alternating_registers_never_return_the_previous_byte(self):
        # The stale-preload bug would make each read return the register read before it.
        put(0x20, 1)
        want = {0x00: 0xED, 0x01: 0x00, 0x02: 0x01, 0x20: 0x01}
        for _ in range(25):
            for reg, value in want.items():
                self.assertEqual(get(reg), value, hex(reg))

    def test_multi_byte_read_repeats_the_register(self):
        r = i2c("i2ctransfer", "-y", BUS, f"w1@{ADDR}", "0x02", f"r3@{ADDR}")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split(), ["0x01", "0x01", "0x01"])


class VerifyScriptTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), f"{SCRIPT} missing")
        self.src = SCRIPT.read_text()

    def test_syntax(self):
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)

    def test_finds_the_bus_by_controller_and_scans_with_read(self):
        self.assertIn("c240000.i2c", self.src)
        self.assertIn("i2cdetect -y -r", self.src)

    def test_asks_a_person_about_the_led_after_draining_input(self):
        self.assertIn("drain_tty", self.src)
        self.assertRegex(self.src, r"ask\(\) \{\n(.*\n)?\s+drain_tty")
        self.assertIn("--no-look", self.src)

    def test_led_off_on_exit_and_unit_tests_on_the_board(self):
        self.assertRegex(self.src, r"trap .*EXIT")
        self.assertIn("0x20 0", self.src)
        self.assertIn("EDGE_STM32_HW=1", self.src)

    def test_shared_bus_still_has_the_oled(self):
        self.assertIn("3c", self.src)

    def test_usage_error_exits_2(self):
        r = subprocess.run(["bash", str(SCRIPT), "--bogus"], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 2, r.stderr)


if __name__ == "__main__":
    unittest.main()
