"""Checks for the STM32F103 I2C target firmware (firmware/stm32f103/, Step 11, 12-a and 12-b).

The Jetson is the I2C controller; the Blue Pill's I2C1 answers at 0x42 with register map v1.1
(Step 12-a: identification, PROTOCOL_VERSION, LED_CONTROL, STATUS, WATCHDOG_STATUS; reads and
writes auto-increment inside a transaction. Step 12-b: ADC on PA0 and a button on PA1, read
from a snapshot taken when each read starts; the debounce is in Core/Src/debounce.c). The protocol lives in Core/Src/i2c_target.c
without any SPL call and is tested on the host by tests/test_i2c_target.cpp; main.c only
turns I2C1 interrupts into i2c_target_* calls and drives the PC13 LED.
The firmware build needs PlatformIO (~/.platformio/penv/bin/pio or PIO=...) and is skipped
without it. Hardware tests talk to the flashed board with i2c-tools and run only with
EDGE_STM32_HW=1, which scripts/verify_stm32_i2c.sh sets.
"""

import hashlib
import json
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
DEBOUNCE_C = FW / "Core" / "Src" / "debounce.c"
DEBOUNCE_H = FW / "Core" / "Inc" / "debounce.h"
MAIN_C = FW / "Core" / "Src" / "main.c"
REGMAP = FW / "docs" / "register-map.md"
INI = FW / "platformio.ini"
SCRIPT = REPO / "scripts" / "verify_stm32_i2c.sh"
BUILD = REPO / "build"
VECTORS = BUILD / "test_i2c_target"
DEBOUNCE_VECTORS = BUILD / "test_debounce"
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
    @classmethod
    def setUpClass(cls):
        subprocess.run(["cmake", "-S", str(REPO), "-B", str(BUILD)], check=True, capture_output=True)

    def run_vectors(self, target, exe):
        subprocess.run(["cmake", "--build", str(BUILD), "--target", target], check=True, capture_output=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_host_vectors_pass(self):
        self.run_vectors("test_i2c_target", VECTORS)

    def test_debounce_vectors_pass(self):
        self.run_vectors("test_debounce", DEBOUNCE_VECTORS)


class RegisterMapTest(unittest.TestCase):
    """docs/register-map.md is what the Jetson side (Step 13) will be written from."""

    def setUp(self):
        self.d = defines(HEADER.read_text())
        self.text = REGMAP.read_text()
        self.rows = {int(a, 16): (name, acc, int(v, 16)) for a, name, acc, v in
                     re.findall(r"^\| (0x[0-9A-F]{2}) \| (\w+) \| (RO|RW|RW1C) \| (0x[0-9A-F]{2}) \|",
                                self.text, re.M)}

    def test_every_register_in_the_header_is_documented_with_its_value(self):
        d = self.d
        want = {
            d["REG_DEVICE_ID"]: ("DEVICE_ID", "RO", d["DEVICE_ID_VALUE"]),
            d["REG_FW_MAJOR"]: ("FW_MAJOR", "RO", d["FW_VERSION_MAJOR"]),
            d["REG_FW_MINOR"]: ("FW_MINOR", "RO", d["FW_VERSION_MINOR"]),
            d["REG_PROTOCOL_VERSION"]: ("PROTOCOL_VERSION", "RO", d["PROTOCOL_VERSION_VALUE"]),
            d["REG_ADC_LOW"]: ("ADC_LOW", "RO", 0),
            d["REG_ADC_HIGH"]: ("ADC_HIGH", "RO", 0),
            d["REG_BUTTON_STATE"]: ("BUTTON_STATE", "RO", 0),
            d["REG_BUTTON_PRESSES"]: ("BUTTON_PRESSES", "RO", 0),
            d["REG_LED_CONTROL"]: ("LED_CONTROL", "RW", 0),
            d["REG_STATUS"]: ("STATUS", "RW1C", d["STATUS_RESET"]),
            d["REG_WATCHDOG_STATUS"]: ("WATCHDOG_STATUS", "RO", d["WATCHDOG_STATUS_VALUE"]),
        }
        self.assertEqual(self.rows, want)
        self.assertEqual((d["PROTOCOL_VERSION_VALUE"], d["FW_VERSION_MAJOR"], d["FW_VERSION_MINOR"]),
                         (0x11, 0, 3))

    def test_status_bits_are_documented(self):
        bits = {int(b): name for b, name in re.findall(r"^\| (\d) \| (\w+) \|", self.text, re.M)}
        want = {self.d[k].bit_length() - 1: k.removeprefix("STATUS_") for k in
                ("STATUS_RO_WRITE", "STATUS_UNMAPPED_WRITE", "STATUS_BAD_VALUE",
                 "STATUS_BUS_ERROR", "STATUS_RESET")}
        self.assertEqual(bits, want)

    def test_layout_byte_order_and_versioning_rules_are_written_down(self):
        for s in ("0x00–0x0F", "0x10–0x1F", "0x20–0x2F", "0x30–0x3F",
                  "auto-increment", "little-endian", "write-1-to-clear", "major", "minor"):
            self.assertIn(s, self.text)

    def test_inputs_are_documented(self):
        # Step 12-b: resolution, reference, sampling, the snapshot rule, pins, button bits.
        for s in ("12-bit", "VDDA", "PA0", "PA1", "快照", "PRESSED", "BUTTON_PRESSES",
                  f"{defines(DEBOUNCE_H.read_text())['DEBOUNCE_MS']} ms", "1.1"):
            self.assertIn(s, self.text)

    def test_bus_error_is_not_documented_as_a_rollback(self):
        # PR #21 review: bytes received before a bus error have already been applied (pointer,
        # data); the map must say so instead of calling the transaction void.
        self.assertNotIn("作廢", self.text)
        self.assertIn("已經生效", self.text)

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
        for src in (self.core, code_only(DEBOUNCE_C.read_text())):
            self.assertNotRegex(src, r"#include\s+\"(stm32|misc)")
            self.assertNotRegex(src, r"\bI2C1\b|\bADC1\b|\bGPIO[A-E]\b|->(SR1|DR)\b")

    def test_adc1_samples_pa0_continuously_after_calibration(self):
        for s in ("RCC_APB2Periph_ADC1", "RCC_ADCCLKConfig(RCC_PCLK2_Div6)", "GPIO_Pin_0",
                  "GPIO_Mode_AIN", "ADC_ContinuousConvMode = ENABLE", "ADC_Channel_0",
                  "ADC_SampleTime_239Cycles5", "ADC_ResetCalibration(ADC1)",
                  "ADC_StartCalibration(ADC1)", "ADC_SoftwareStartConvCmd(ADC1, ENABLE)"):
            self.assertIn(s, self.main)
        # main() publishes each conversion with one 16-bit store; the I2C interrupt copies it
        # into the read's snapshot (i2c_target_read_start), never byte by byte.
        loop = self.main[self.main.index("for (;;)"):]
        self.assertRegex(loop, r"target\.adc = ADC_GetConversionValue\(ADC1\)")

    def test_button_on_pa1_with_pull_up_debounced_by_systick(self):
        for s in ("GPIO_Pin_1", "GPIO_Mode_IPU", "SysTick_Config(SystemCoreClock / 1000)"):
            self.assertIn(s, self.main)
        tick = self.handler("SysTick_Handler")
        self.assertIn("debounce_tick(", tick)
        self.assertIn("GPIO_Pin_1", tick)
        self.assertIn("target.button", tick)
        self.assertIn("target.presses", tick)

    def test_main_sets_up_i2c1_on_pb6_pb7_at_the_protocol_address(self):
        for s in ("RCC_APB1Periph_I2C1", "GPIO_Pin_6", "GPIO_Pin_7", "GPIO_Mode_AF_OD",
                  "I2C_TARGET_ADDR << 1", "I2C_Ack_Enable", "I2C_Init(I2C1", "I2C_ITConfig(I2C1"):
            self.assertIn(s, self.main)

    def test_main_drives_the_active_low_pc13_led(self):
        self.assertIn("GPIO_Pin_13", self.main)
        self.assertRegex(self.main, r"GPIO_ResetBits\(GPIOC, GPIO_Pin_13\)")

    def handler(self, name):
        body = self.main[self.main.index(f"void {name}(void)"):]
        return body[:body.index("\n}")]

    def test_interrupt_handlers_feed_the_core(self):
        for s in ("void I2C1_EV_IRQHandler(void)", "void I2C1_ER_IRQHandler(void)",
                  "i2c_target_write_start(", "i2c_target_read_start(", "i2c_target_rx(",
                  "i2c_target_tx(", "i2c_target_stop(", "i2c_target_bus_error("):
            self.assertIn(s, self.main)

    def test_read_start_comes_before_the_first_transmit(self):
        # ADDR and TXE can be in the same SR1 snapshot; the first byte of a read must come from
        # the stored pointer, so read_start() has to run before tx().
        ev = self.handler("I2C1_EV_IRQHandler")
        self.assertLess(ev.index("i2c_target_read_start("), ev.index("i2c_target_tx("))

    def test_bus_errors_are_recorded_and_reset_the_peripheral(self):
        # PR #17 review: after BERR / ARLO nothing reset I2C1, so a stuck BUSY (ES096) needed the
        # RESET button. AF is the normal end of a read and must not count as a bus error.
        er = self.handler("I2C1_ER_IRQHandler")
        self.assertIn("i2c_target_bus_error(", er)
        for flag in ("I2C_SR1_BERR", "I2C_SR1_ARLO", "I2C_SR1_OVR"):
            self.assertIn(flag, er)
        self.assertRegex(self.main, r"I2C_SoftwareResetCmd\(I2C1, ENABLE\)")
        self.assertRegex(self.main, r"I2C_SoftwareResetCmd\(I2C1, DISABLE\)")
        self.assertIn("i2c1_regs_init(", er)
        af = er[er.index("I2C_SR1_AF"):]
        self.assertNotIn("bus_error", af[:af.index(";")])

    def test_pending_byte_is_taken_before_a_new_address(self):
        # PR #17 review: one SR1 snapshot can hold RXNE (the last data byte, not read yet) and
        # ADDR (a repeated START). write_start() first would turn that data byte into a pointer.
        ev = self.handler("I2C1_EV_IRQHandler")
        self.assertLess(ev.index("I2C_SR1_RXNE"), ev.index("I2C_SR1_ADDR"))

    def test_read_ends_on_the_controllers_nack(self):
        # A read ends with the controller's NACK (AF), not STOPF (RM0008 slave transmitter):
        # AF must be cleared and must end the transaction, or the error interrupt never stops.
        er = self.handler("I2C1_ER_IRQHandler")
        self.assertIn("I2C_SR1_AF", er)
        self.assertIn("I2C_ClearITPendingBit(I2C1", er)
        self.assertIn("i2c_target_stop(", er)

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

    def test_scope_step12b_only(self):
        # phase05 Step 12-b "這一步不做": no real watchdog (Phase 6), no SPI, no DMA, no
        # Jetson kernel driver (Step 13), no interrupt line to tell the Jetson about the button.
        for name in ("IWDG", "WWDG", "SPI", "DMA", "EXTI"):
            for path in (CORE_C, MAIN_C, HEADER, DEBOUNCE_C, DEBOUNCE_H,
                         FW / "Core" / "Inc" / "stm32f10x_conf.h"):
                self.assertNotRegex(code_only(path.read_text()), rf"\b{name}\w*", f"{name} in {path.name}")
        self.assertFalse((REPO / "kernel" / "edge_ctrl").exists())


class VendorTest(unittest.TestCase):
    def test_vendor_files_are_unchanged(self):
        lines = (FW / "vendor.sha256").read_text().split("\n")
        entries = [l.split("  ", 1) for l in lines if l]
        self.assertEqual(len(entries), 16)
        for digest, name in entries:
            self.assertEqual(hashlib.sha256((FW / name).read_bytes()).hexdigest(), digest, name)

    def test_build_uses_only_the_needed_spl_drivers(self):
        ini = INI.read_text()
        for f in ("misc.c", "stm32f10x_adc.c", "stm32f10x_gpio.c", "stm32f10x_i2c.c", "stm32f10x_rcc.c"):
            self.assertIn(f"+<Library/{f}>", ini)
        self.assertNotIn("+<Start/core_cm3.c>", ini)
        self.assertNotIn("+<Start/>", ini)
        self.assertNotIn("+<Library/>", ini)
        self.assertNotRegex(ini, r"(?m)^framework")
        self.assertRegex(ini, r"(?m)^ *platformio/toolchain-gccarmnoneeabi@1\.120301\.0")

    def test_firmware_is_built_with_warnings_as_errors(self):
        # PR #17 review: the host build only compiles i2c_target.c with -Werror; main.c and the
        # vendor files go through PlatformIO only (all of them build clean with these flags).
        flags = INI.read_text().split("build_flags =", 1)[1].split("\n\n", 1)[0].split()
        for f in ("-Wall", "-Wextra", "-Werror"):
            self.assertIn(f, flags)


def pio_core_dir():
    return Path(os.environ.get("PLATFORMIO_CORE_DIR", Path.home() / ".platformio"))


def pinned_toolchain():
    """bin/ of the installed toolchain-gccarmnoneeabi 1.120301.0, or None. PlatformIO names the
    directory toolchain-gccarmnoneeabi or, next to another version, toolchain-gccarmnoneeabi@<v>."""
    for d in sorted(pio_core_dir().glob("packages/toolchain-gccarmnoneeabi*")):
        try:
            if json.loads((d / "package.json").read_text()).get("version") == "1.120301.0":
                return d / "bin"
        except (OSError, ValueError):
            continue
    return None


def pio_exe():
    return PIO if Path(PIO).exists() else shutil.which("pio")


# PR #17 review: only when PlatformIO and the pinned toolchain are already installed, so a
# plain `unittest discover` never downloads packages (and an offline machine skips, not fails).
@unittest.skipUnless(pio_exe() and pinned_toolchain(), "PlatformIO or toolchain-gccarmnoneeabi 1.120301.0 not installed")
class FirmwareBuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = subprocess.run([pio_exe(), "run", "-d", str(FW)], capture_output=True, text=True, timeout=300)
        cls.elf = FW / ".pio" / "build" / "bluepill" / "firmware.elf"
        cls.nm = pinned_toolchain() / "arm-none-eabi-nm"

    def test_builds(self):
        self.assertEqual(self.r.returncode, 0, self.r.stdout[-3000:])
        self.assertTrue((FW / ".pio" / "build" / "bluepill" / "firmware.bin").is_file())

    def test_irq_handlers_are_ours_not_the_weak_default(self):
        # A misspelled handler name links fine and leaves the vector on Default_Handler.
        out = subprocess.run([str(self.nm), str(self.elf)], capture_output=True, text=True, check=True).stdout
        sym = {n: (t, a) for a, t, n in (l.split() for l in out.splitlines() if len(l.split()) == 3)}
        for h in ("I2C1_EV_IRQHandler", "I2C1_ER_IRQHandler", "SysTick_Handler"):
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


def xfer(*msgs):
    """i2ctransfer -y BUS msgs...; the bytes read, as ints."""
    r = i2c("i2ctransfer", "-y", BUS, *msgs)
    if r.returncode:
        raise AssertionError(f"i2ctransfer {' '.join(msgs)}: {r.stderr.strip()}")
    return [int(b, 16) for b in r.stdout.split()]


# Register map v1.1 as the Jetson expects it (docs/register-map.md), written out here rather
# than taken from i2c_target.h so a wrong header does not pass by agreeing with itself.
RO = {0x00: 0xED, 0x01: 0x00, 0x02: 0x03, 0x03: 0x11, 0x31: 0x00}
INPUTS = (0x10, 0x11, 0x12, 0x13)  # read-only, value depends on the wiring
ADC_LOW, BUTTON_STATE, BUTTON_PRESSES = 0x10, 0x12, 0x13
LED, STATUS = 0x20, 0x30
RO_WRITE, UNMAPPED_WRITE, BAD_VALUE = 0x01, 0x02, 0x04
# Largest max - min of the ADC over a burst of reads with the input held still. Measured spread
# over 300 reads was 10-19 counts (GND, midpoint, 3.3 V; docs/baseline.md); twice that is the limit.
# A value built from two conversions is off by 256, but only if the input crosses a HIGH-byte
# boundary (0x7FF / 0x800); the divider here sits at about 2068, so this catches noise, not tearing.
ADC_SPREAD_MAX = 40


def adc_reads(n):
    out = []
    for _ in range(n):
        lo, hi = xfer(f"w1@{ADDR}", "0x10", f"r2@{ADDR}")
        out.append(hi << 8 | lo)
    return out


@unittest.skipUnless(HW, "set EDGE_STM32_HW=1 (scripts/verify_stm32_i2c.sh) to talk to the board")
class HardwareTest(unittest.TestCase):
    def setUp(self):
        # PR #21 review: start from LED off too, so a test run on its own does not depend on
        # what the board was left with.
        put(LED, 0)
        put(STATUS, 0xFF)

    def tearDown(self):
        put(LED, 0)
        put(STATUS, 0xFF)

    def assertStatus(self, want, msg=None):
        self.assertEqual(get(STATUS), want, msg)
        put(STATUS, 0xFF)

    def test_identification(self):
        self.assertEqual([get(r) for r in (0x00, 0x01, 0x02, 0x03)], [0xED, 0x00, 0x03, 0x11])

    def test_every_register_reads_as_documented(self):
        for reg in range(0x100):
            if reg in INPUTS:
                continue
            want = RO.get(reg, {LED: 0, STATUS: 0}.get(reg, 0xFF))
            self.assertEqual(get(reg), want, hex(reg))
        lo, hi, button, _ = xfer(f"w1@{ADDR}", "0x10", f"r4@{ADDR}")
        self.assertLessEqual(hi, 0x0F, "ADC is 12-bit")
        self.assertEqual(button, 0, "nobody presses the button during the unit tests")
        self.assertStatus(0, "reading, even unmapped registers, is not an error")

    def test_every_write_that_must_be_dropped_is_reported(self):
        presses = get(BUTTON_PRESSES)
        for reg in range(0x100):
            if reg in (LED, STATUS):
                continue
            put(reg, 0x55)
            if reg not in INPUTS:
                self.assertEqual(get(reg), RO.get(reg, 0xFF), hex(reg))
            self.assertStatus(RO_WRITE if reg in RO or reg in INPUTS else UNMAPPED_WRITE, hex(reg))
        self.assertEqual(get(LED), 0, "no dropped write reached LED_CONTROL")
        self.assertEqual(get(BUTTON_PRESSES), presses, "writing 0x55 to 0x13 must not reach the counter")

    def test_led_control_round_trip_and_invalid_values(self):
        for v in (1, 0, 1):
            put(LED, v)
            self.assertEqual(get(LED), v)
        self.assertStatus(0)
        for bad in (2, 0x80, 0xFF):
            put(LED, bad)
            self.assertEqual(get(LED), 1, f"{bad:#x} must leave LED_CONTROL alone")
            self.assertStatus(BAD_VALUE, hex(bad))

    def test_status_is_write_one_to_clear(self):
        put(0x00, 1)
        put(LED, 9)
        self.assertEqual(get(STATUS), RO_WRITE | BAD_VALUE)
        self.assertEqual(get(STATUS), RO_WRITE | BAD_VALUE, "reading must not clear")
        put(STATUS, RO_WRITE)
        self.assertEqual(get(STATUS), BAD_VALUE)
        put(STATUS, 0)
        self.assertEqual(get(STATUS), BAD_VALUE)
        self.assertStatus(BAD_VALUE)
        self.assertEqual(get(STATUS), 0)

    def test_status_survives_a_read_that_runs_into_it(self):
        # TXE fetches 0x30 while 0x2F is being sent; that STATUS byte never reaches the Jetson.
        put(LED, 7)
        self.assertEqual(xfer(f"w1@{ADDR}", "0x2f", f"r1@{ADDR}"), [0xFF])
        self.assertStatus(BAD_VALUE)

    def test_multi_byte_read_auto_increments(self):
        self.assertEqual(xfer(f"w1@{ADDR}", "0x00", f"r4@{ADDR}"), [0xED, 0x00, 0x03, 0x11])
        self.assertEqual(xfer(f"w1@{ADDR}", "0x03", f"r2@{ADDR}"), [0x11, 0xFF])
        self.assertEqual(xfer(f"w1@{ADDR}", "0x30", f"r2@{ADDR}"), [0x00, 0x00])
        self.assertEqual(xfer(f"w1@{ADDR}", "0xff", f"r2@{ADDR}"), [0xFF, 0xED])

    def test_reads_never_move_the_pointer(self):
        # Step 11 carried this over: with auto-increment, the byte TXE loads ahead of the NACK
        # would push the pointer one register further on every read. Only writes move it.
        for n in (1, 2, 3, 4):
            xfer(f"w1@{ADDR}", "0x01", f"r{n}@{ADDR}")
            self.assertEqual(xfer(f"r1@{ADDR}"), [0x00], f"after r{n}")
            self.assertEqual(xfer(f"r3@{ADDR}"), [0x00, 0x03, 0x11], f"after r{n}")

    def test_write_then_read_in_one_transaction_reads_the_pointer(self):
        # The data byte moves the cursor to 0x21; the read after the repeated START must start
        # at the stored pointer (0x20) again.
        for v in (1, 0):
            self.assertEqual(xfer(f"w2@{ADDR}", "0x20", hex(v), f"r1@{ADDR}"), [v])
        self.assertStatus(0)

    def test_write_auto_increments(self):
        xfer(f"w3@{ADDR}", "0x1f", "0x00", "0x01")  # 0x1F (unmapped) = 0, 0x20 = 1
        self.assertEqual(get(LED), 1)
        self.assertStatus(UNMAPPED_WRITE)
        xfer(f"w3@{ADDR}", "0x20", "0x00", "0x00")  # LED = 0, then 0x21 (unmapped)
        self.assertEqual(get(LED), 0)
        self.assertStatus(UNMAPPED_WRITE)

    def test_alternating_reads_never_return_a_stale_byte(self):
        # Single- and multi-byte reads mixed: a byte left over from the read before, or a
        # pointer moved by a read, shows up as a wrong value here.
        put(LED, 1)
        for i in range(25):
            self.assertEqual(xfer(f"w1@{ADDR}", "0x00", f"r4@{ADDR}"), [0xED, 0x00, 0x03, 0x11], i)
            self.assertEqual(get(LED), 1, i)
            self.assertEqual(xfer(f"w1@{ADDR}", "0x30", f"r2@{ADDR}"), [0x00, 0x00], i)
            self.assertEqual(get(0x02), 0x03, i)

    def test_adc_bytes_come_from_one_conversion(self):
        # Wherever PA0 is wired, a burst of 2-byte reads stays within the noise. Two bytes from
        # different conversions are 256 counts off only when the input crosses 0x7FF / 0x800.
        vals = adc_reads(300)
        self.assertLessEqual(max(vals), 0xFFF)
        self.assertLessEqual(max(vals) - min(vals), ADC_SPREAD_MAX, sorted(set(vals)))

    def test_adc_after_a_read_that_ran_into_it(self):
        # PR #21 review: reading 0x0F makes TXE fetch 0x10. Nothing may be latched by that.
        base = adc_reads(50)
        for _ in range(50):
            xfer(f"w1@{ADDR}", "0x0f", f"r1@{ADDR}")
            lo, hi = xfer(f"w1@{ADDR}", "0x10", f"r2@{ADDR}")
            v = hi << 8 | lo
            self.assertLessEqual(abs(v - sorted(base)[25]), ADC_SPREAD_MAX, hex(v))

    def test_button_released_and_counter_steady(self):
        # Nobody touches the button during the unit tests.
        before = get(BUTTON_PRESSES)
        self.assertEqual(get(BUTTON_STATE), 0)
        self.assertEqual(xfer(f"w1@{ADDR}", "0x12", f"r2@{ADDR}"), [0, before])

    def test_read_after_the_value_changed(self):
        # PR #17 review: TXE loads a byte before the controller's NACK. A value can only change
        # through a write, whose bytes land in the same DR, so the next read must see the new value.
        for i in range(20):
            put(LED, i % 2)
            self.assertEqual(get(LED), i % 2, f"round {i}")
            self.assertEqual(xfer(f"r1@{ADDR}"), [i % 2], f"round {i}: no pointer write")


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

    def test_checks_register_map_v1(self):
        # Step 12-a: PROTOCOL_VERSION, STATUS after each dropped write, auto-increment both
        # ways, and reads that must not move the pointer.
        for s in ("0x03 0x11", "STATUS", "0x30 0xff", "r4@", "w3@", "pointer"):
            self.assertIn(s, self.src)

    def test_checks_the_inputs_with_a_person_moving_the_wire(self):
        # Step 12-b: A0 on GND / divider midpoint / 3.3 V, the button held, released and pressed
        # several times (real contact bounce); --no-touch keeps only what needs no hands.
        for s in ("--no-touch", "A0", "GND", "3.3", "midpoint", "HOLD", "BUTTON_PRESSES",
                  "ADC_GND_MAX", "ADC_VCC_MIN", "ADC_MID_MIN", "ADC_MID_MAX", "wait_enter"):
            self.assertIn(s, self.src)
        self.assertRegex(self.src, r"wait_enter\(\) \{\n(.*\n)?\s+drain_tty")

    def test_checks_the_snapshot_with_a_floating_input(self):
        # Step 12-b: the divider never crosses 0x800, so tearing is checked with A0 floating,
        # and with ADC_HIGH as the 3rd byte of a read from 0x0F: the F103 fetches byte 2 almost
        # together with byte 1, byte 3 only after byte 1 has gone out (docs/baseline.md).
        for s in ("float", "w1@$ADDR 0x0f r3@$ADDR", "TEAR_N", "TEAR_LIMIT", "0x800"):
            self.assertIn(s, self.src)
        self.assertLess(self.src.index("float"), self.src.index("to the midpoint"))

    def test_adc_spread_limit_matches_the_unit_test(self):
        m = re.search(r"^ADC_SPREAD_MAX=(\d+)", self.src, re.M)
        self.assertIsNotNone(m)
        self.assertEqual(int(m[1]), ADC_SPREAD_MAX)

    def test_shared_bus_still_has_the_oled(self):
        self.assertIn("3c", self.src)

    def test_usage_error_exits_2(self):
        r = subprocess.run(["bash", str(SCRIPT), "--bogus"], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 2, r.stderr)


if __name__ == "__main__":
    unittest.main()
