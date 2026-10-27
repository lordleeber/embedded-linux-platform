// Test vectors for include/edge_ctrl_regs.h (Step 13), run by tests/test_edge_ctrl_static.py.
//
// The header is what edge_ctrl.ko knows about the Blue Pill's register map. The expected
// values do not come from the header itself: every check drives the firmware's own register
// state machine (firmware/stm32f103/Core/Src/i2c_target.c, the code running on the board) with
// the same transactions the driver sends, then decodes the answer with the header's helpers.
// If the two sides disagree on an address, the byte order or which values are accepted, a
// check fails here instead of on the board.
// Exit status: 0 = all checks passed, 1 = a check failed.
#include <cstdint>
#include <cstdio>
#include <vector>

#include "../firmware/stm32f103/Core/Inc/i2c_target.h"
#include "../include/edge_ctrl_regs.h"

namespace {

int failures = 0;

void check_eq(const char *what, unsigned got, unsigned want)
{
    if (got != want) {
        std::printf("FAIL %s: got 0x%X, want 0x%X\n", what, got, want);
        ++failures;
    }
}

// What edge_ctrl.ko's read_reg() puts on the bus: one i2c_transfer of a pointer write and an
// n-byte read with a repeated START. TXE loads one byte the controller never takes.
std::vector<uint8_t> read_n(i2c_target &t, uint8_t reg, int n)
{
    i2c_target_write_start(&t);
    i2c_target_rx(&t, reg);
    i2c_target_read_start(&t);
    std::vector<uint8_t> out;
    for (int i = 0; i < n; ++i)
        out.push_back(i2c_target_tx(&t));
    (void)i2c_target_tx(&t);
    i2c_target_stop(&t);
    return out;
}

// What write_reg() sends: i2c_master_send() of { reg, value }.
void write_reg(i2c_target &t, uint8_t reg, uint8_t value)
{
    i2c_target_write_start(&t);
    i2c_target_rx(&t, reg);
    i2c_target_rx(&t, value);
    i2c_target_stop(&t);
}

void test_addresses_match_the_firmware()
{
    check_eq("addr", EDGE_CTRL_ADDR, I2C_TARGET_ADDR);
    check_eq("DEVICE_ID", EDGE_CTRL_REG_DEVICE_ID, REG_DEVICE_ID);
    check_eq("FW_MAJOR", EDGE_CTRL_REG_FW_MAJOR, REG_FW_MAJOR);
    check_eq("FW_MINOR", EDGE_CTRL_REG_FW_MINOR, REG_FW_MINOR);
    check_eq("PROTOCOL_VERSION", EDGE_CTRL_REG_PROTOCOL, REG_PROTOCOL_VERSION);
    check_eq("ADC_LOW", EDGE_CTRL_REG_ADC_LOW, REG_ADC_LOW);
    check_eq("ADC_HIGH", EDGE_CTRL_REG_ADC_LOW + 1, REG_ADC_HIGH);
    check_eq("BUTTON_STATE", EDGE_CTRL_REG_BUTTON_STATE, REG_BUTTON_STATE);
    check_eq("BUTTON_PRESSES", EDGE_CTRL_REG_BUTTON_PRESSES, REG_BUTTON_PRESSES);
    check_eq("LED_CONTROL", EDGE_CTRL_REG_LED, REG_LED_CONTROL);
    check_eq("STATUS", EDGE_CTRL_REG_STATUS, REG_STATUS);
    check_eq("device id value", EDGE_CTRL_DEVICE_ID, DEVICE_ID_VALUE);
    check_eq("pressed bit", EDGE_CTRL_BUTTON_PRESSED, BUTTON_PRESSED);
}

// probe() reads 0x00-0x03 in one go and needs a 1.x map with the 1.1 inputs.
void test_probe_accepts_this_firmware()
{
    i2c_target t;
    i2c_target_init(&t);
    std::vector<uint8_t> id = read_n(t, EDGE_CTRL_REG_DEVICE_ID, 4);
    check_eq("id", id[0], EDGE_CTRL_DEVICE_ID);
    check_eq("fw major", id[1], FW_VERSION_MAJOR);
    check_eq("fw minor", id[2], FW_VERSION_MINOR);
    check_eq("protocol ok", edge_ctrl_protocol_ok(id[3]), 1);
}

void test_protocol_versions()
{
    // version rules (register-map.md): same major, minor at least the one we know
    const struct { unsigned v; int ok; } cases[] = {
        { 0x11, 1 }, { 0x12, 1 }, { 0x1F, 1 },
        { 0x10, 0 },  // Step 12-a: no ADC / button yet
        { 0x21, 0 }, { 0x01, 0 },
        { 0xFF, 0 },  // Step 11 firmware: no 0x03
    };
    for (const auto &c : cases) {
        char what[32];
        std::snprintf(what, sizeof what, "protocol 0x%02X", c.v);
        check_eq(what, edge_ctrl_protocol_ok(c.v), c.ok);
    }
}

// Every 12-bit value comes back unchanged through a 2-byte read and edge_ctrl_adc().
void test_adc_decodes_every_value()
{
    i2c_target t;
    i2c_target_init(&t);
    int bad = 0;
    for (unsigned v = 0; v < 4096; ++v) {
        t.adc = v;
        std::vector<uint8_t> b = read_n(t, EDGE_CTRL_REG_ADC_LOW, 2);
        if (edge_ctrl_adc(b[0], b[1]) != v)
            ++bad;
    }
    check_eq("adc values decoded wrong", bad, 0);
    // bits 7:4 of ADC_HIGH are not part of the value
    check_eq("high nibble masked", edge_ctrl_adc(0x34, 0xF2), 0x234);
}

void test_button_and_presses_in_one_read()
{
    i2c_target t;
    i2c_target_init(&t);
    t.button = BUTTON_PRESSED;
    t.presses = 200;
    std::vector<uint8_t> b = read_n(t, EDGE_CTRL_REG_BUTTON_STATE, 2);
    check_eq("pressed", edge_ctrl_pressed(b[0]), 1);
    check_eq("presses", b[1], 200);
    t.button = 0;
    check_eq("released", edge_ctrl_pressed(read_n(t, EDGE_CTRL_REG_BUTTON_STATE, 1)[0]), 0);
}

// The driver refuses LED values itself (EINVAL, nothing sent). It must refuse exactly what
// the firmware would drop with BAD_VALUE, no more and no less.
void test_led_values_match_what_the_firmware_takes()
{
    int bad = 0;
    for (unsigned v = 0; v < 256; ++v) {
        i2c_target t;
        i2c_target_init(&t);
        t.status = 0;
        write_reg(t, EDGE_CTRL_REG_LED, (uint8_t)v);
        int firmware_ok = !(t.status & STATUS_BAD_VALUE) && t.led == v;
        if (edge_ctrl_led_ok(v) != firmware_ok) {
            std::printf("FAIL LED value %u: driver %d, firmware %d\n", v, edge_ctrl_led_ok(v),
                        firmware_ok);
            ++bad;
        }
    }
    failures += bad;
}

}  // namespace

int main()
{
    test_addresses_match_the_firmware();
    test_probe_accepts_this_firmware();
    test_protocol_versions();
    test_adc_decodes_every_value();
    test_button_and_presses_in_one_read();
    test_led_values_match_what_the_firmware_takes();
    std::printf("%s (%d failure(s))\n", failures ? "FAILED" : "OK", failures);
    return failures ? 1 : 0;
}
