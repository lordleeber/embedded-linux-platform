// Test vectors for firmware/stm32f103/Core/Src/i2c_target.c (Step 11, register map v1.0 in
// Step 12-a, v1.1 with the ADC and button inputs in Step 12-b): the register protocol the Blue Pill answers on I2C, driven here by the same calls
// main.c makes from the I2C1 interrupts. The expected behaviour comes from i2c_target.h and
// docs/register-map.md.
// Exit status: 0 = all checks passed, 1 = a check failed.
#include <cstdint>
#include <cstdio>
#include <initializer_list>
#include <vector>

#include "../firmware/stm32f103/Core/Inc/i2c_target.h"

namespace {

int failures = 0;

void check_eq(const char *what, unsigned got, unsigned want)
{
    if (got != want) {
        std::printf("FAIL %s: got 0x%02X, want 0x%02X\n", what, got, want);
        ++failures;
    }
}

// i2cset -y BUS 0x42 reg byte... (i2ctransfer w<n>@0x42 reg byte...)
void write(i2c_target &t, std::initializer_list<uint8_t> bytes)
{
    i2c_target_write_start(&t);
    for (uint8_t b : bytes)
        i2c_target_rx(&t, b);
    i2c_target_stop(&t);
}

// i2ctransfer w1@0x42 reg r<n>@0x42: pointer write, repeated START, n bytes, NACK, STOP.
// TXE loads one byte ahead, so the hardware asks for n + 1 bytes and the last one is never
// sent (Step 11 measured that it does not reach the next read either).
std::vector<uint8_t> read_n(i2c_target &t, uint8_t reg, int n)
{
    i2c_target_write_start(&t);
    i2c_target_rx(&t, reg);
    i2c_target_read_start(&t);
    std::vector<uint8_t> out;
    for (int i = 0; i < n; ++i)
        out.push_back(i2c_target_tx(&t));
    (void)i2c_target_tx(&t);  // the preloaded byte the controller NACKs away
    i2c_target_stop(&t);
    return out;
}

// i2cget -y BUS 0x42 reg
uint8_t read_reg(i2c_target &t, uint8_t reg)
{
    return read_n(t, reg, 1)[0];
}

// i2ctransfer r<n>@0x42: a read with no pointer write starts at the stored pointer
std::vector<uint8_t> read_here(i2c_target &t, int n)
{
    i2c_target_read_start(&t);
    std::vector<uint8_t> out;
    for (int i = 0; i < n; ++i)
        out.push_back(i2c_target_tx(&t));
    (void)i2c_target_tx(&t);
    i2c_target_stop(&t);
    return out;
}

void check_bytes(const char *what, const std::vector<uint8_t> &got,
                 std::initializer_list<uint8_t> want)
{
    std::vector<uint8_t> w(want);
    if (got != w) {
        std::printf("FAIL %s: got", what);
        for (uint8_t b : got)
            std::printf(" 0x%02X", b);
        std::printf(", want");
        for (uint8_t b : w)
            std::printf(" 0x%02X", b);
        std::printf("\n");
        ++failures;
    }
}

i2c_target fresh()
{
    i2c_target t;
    i2c_target_init(&t);
    return t;
}

// fresh, with the power-on RESET bit cleared so a test sees only the flags it causes
i2c_target clean()
{
    i2c_target t = fresh();
    write(t, {REG_STATUS, STATUS_RESET});
    return t;
}

void test_identification_registers()
{
    i2c_target t = fresh();
    check_eq("DEVICE_ID", read_reg(t, REG_DEVICE_ID), 0xED);
    check_eq("FW_MAJOR", read_reg(t, REG_FW_MAJOR), 0x00);
    check_eq("FW_MINOR", read_reg(t, REG_FW_MINOR), 0x03);
    check_eq("PROTOCOL_VERSION 1.1", read_reg(t, REG_PROTOCOL_VERSION), 0x11);
    check_eq("WATCHDOG_STATUS placeholder", read_reg(t, REG_WATCHDOG_STATUS), 0x00);
    check_eq("address", I2C_TARGET_ADDR, 0x42);
    check_eq("register numbers", (REG_PROTOCOL_VERSION << 8) | REG_STATUS, 0x0330);
    check_eq("WATCHDOG_STATUS number", REG_WATCHDOG_STATUS, 0x31);
    check_eq("input register numbers",
             (REG_ADC_LOW << 24) | (REG_ADC_HIGH << 16) | (REG_BUTTON_STATE << 8) | REG_BUTTON_PRESSES,
             0x10111213);
}

void test_reset_state()
{
    i2c_target t = fresh();
    check_eq("LED off after reset", t.led, 0);
    check_eq("LED_CONTROL reads 0 after reset", read_reg(t, REG_LED_CONTROL), 0);
    check_eq("STATUS after reset: only RESET", read_reg(t, REG_STATUS), STATUS_RESET);
    check_bytes("inputs before the first sample", read_n(t, REG_ADC_LOW, 4), {0, 0, 0, 0});
    i2c_target u = fresh();
    check_bytes("read without a pointer write starts at DEVICE_ID", read_here(u, 2),
                {DEVICE_ID_VALUE, FW_VERSION_MAJOR});
}

void test_led_on_off()
{
    i2c_target t = clean();
    write(t, {REG_LED_CONTROL, 1});
    check_eq("LED on", t.led, 1);
    check_eq("LED_CONTROL reads 1", read_reg(t, REG_LED_CONTROL), 1);
    write(t, {REG_LED_CONTROL, 0});
    check_eq("LED off", t.led, 0);
    check_eq("LED_CONTROL reads 0", read_reg(t, REG_LED_CONTROL), 0);
    check_eq("valid writes leave STATUS clear", read_reg(t, REG_STATUS), 0);
}

void test_invalid_led_values_are_dropped_and_reported()
{
    for (uint8_t start : {0, 1}) {
        for (uint8_t bad : {2, 0x80, 0xFF}) {
            i2c_target t = clean();
            write(t, {REG_LED_CONTROL, start});
            write(t, {REG_LED_CONTROL, bad});
            check_eq("LED unchanged by an invalid value", t.led, start);
            check_eq("LED_CONTROL unchanged by an invalid value", read_reg(t, REG_LED_CONTROL),
                     start);
            check_eq("STATUS: BAD_VALUE", read_reg(t, REG_STATUS), STATUS_BAD_VALUE);
        }
    }
}

void test_read_only_registers_ignore_writes_and_report()
{
    for (uint8_t reg : {REG_DEVICE_ID, REG_FW_MAJOR, REG_FW_MINOR, REG_PROTOCOL_VERSION,
                        REG_ADC_LOW, REG_ADC_HIGH, REG_BUTTON_STATE, REG_BUTTON_PRESSES,
                        REG_WATCHDOG_STATUS}) {
        i2c_target t = clean();
        uint8_t before = read_reg(t, reg);
        write(t, {reg, 0x55});
        check_eq("RO register after a write", read_reg(t, reg), before);
        check_eq("STATUS: RO_WRITE", read_reg(t, REG_STATUS), STATUS_RO_WRITE);
        check_eq("LED untouched", t.led, 0);
    }
}

void test_unmapped_registers()
{
    for (uint8_t reg : {0x04, 0x0F, 0x14, 0x1F, 0x21, 0x2F, 0x32, 0x3F, 0x40, 0xFF}) {
        i2c_target t = clean();
        check_eq("unmapped reads 0xFF", read_reg(t, reg), REG_UNMAPPED_VALUE);
        check_eq("reading unmapped is not an error", read_reg(t, REG_STATUS), 0);
        write(t, {reg, 1});
        check_eq("unmapped still reads 0xFF", read_reg(t, reg), REG_UNMAPPED_VALUE);
        check_eq("STATUS: UNMAPPED_WRITE", read_reg(t, REG_STATUS), STATUS_UNMAPPED_WRITE);
        check_eq("write to unmapped leaves the LED alone", t.led, 0);
    }
}

void test_status_is_write_one_to_clear()
{
    i2c_target t = fresh();
    write(t, {REG_DEVICE_ID, 1});
    write(t, {REG_LED_CONTROL, 9});
    write(t, {0x50, 1});
    uint8_t all = STATUS_RESET | STATUS_RO_WRITE | STATUS_BAD_VALUE | STATUS_UNMAPPED_WRITE;
    check_eq("flags accumulate", read_reg(t, REG_STATUS), all);
    check_eq("reading STATUS does not clear it", read_reg(t, REG_STATUS), all);
    write(t, {REG_STATUS, STATUS_RO_WRITE});
    check_eq("only the written bit clears", read_reg(t, REG_STATUS), all & ~STATUS_RO_WRITE);
    write(t, {REG_STATUS, 0});
    check_eq("writing 0 clears nothing", read_reg(t, REG_STATUS), all & ~STATUS_RO_WRITE);
    write(t, {REG_STATUS, 0xFF});
    check_eq("0xFF clears all", read_reg(t, REG_STATUS), 0);
    check_eq("clearing STATUS is not itself an error", read_reg(t, REG_STATUS), 0);
}

void test_status_read_ahead_does_not_clear()
{
    // A read of 0x2F (unmapped) preloads 0x30: the STATUS byte is fetched but never sent.
    // A read-to-clear STATUS would lose its flags here without the Jetson seeing them.
    i2c_target t = clean();
    write(t, {REG_LED_CONTROL, 7});
    read_reg(t, 0x2F);
    check_eq("STATUS survives being preloaded", read_reg(t, REG_STATUS), STATUS_BAD_VALUE);
}

void test_bus_error()
{
    i2c_target t = clean();
    i2c_target_write_start(&t);
    i2c_target_rx(&t, REG_LED_CONTROL);
    i2c_target_bus_error(&t);  // BERR / ARLO / OVR in the middle of a write
    i2c_target_rx(&t, 1);      // a byte after the error is not data
    check_eq("write aborted by a bus error", t.led, 0);
    check_eq("STATUS: BUS_ERROR", read_reg(t, REG_STATUS), STATUS_BUS_ERROR);
    write(t, {REG_LED_CONTROL, 1});
    check_eq("next transaction works", t.led, 1);
    write(t, {REG_STATUS, STATUS_BUS_ERROR});
    check_eq("BUS_ERROR clears", read_reg(t, REG_STATUS), 0);

    // PR #21 review: no rollback. What arrived before the error has taken effect (the pointer,
    // and data bytes already written); the Jetson sees BUS_ERROR and sends the whole write again.
    i2c_target u = clean();
    i2c_target_write_start(&u);
    i2c_target_rx(&u, REG_LED_CONTROL);
    i2c_target_rx(&u, 1);
    i2c_target_bus_error(&u);
    check_eq("data byte before the error was applied", u.led, 1);
    check_bytes("pointer from the interrupted write stays", read_here(u, 1), {1});
}

void test_read_auto_increments()
{
    i2c_target t = clean();
    check_bytes("4 bytes from DEVICE_ID", read_n(t, REG_DEVICE_ID, 4),
                {DEVICE_ID_VALUE, FW_VERSION_MAJOR, FW_VERSION_MINOR, PROTOCOL_VERSION_VALUE});
    t.adc = 0x0ABC;
    check_bytes("the input block", read_n(t, 0x0F, 6), {0xFF, 0xBC, 0x0A, 0, 0, 0xFF});
    check_bytes("past the end of a block: unmapped", read_n(t, REG_PROTOCOL_VERSION, 3),
                {PROTOCOL_VERSION_VALUE, 0xFF, 0xFF});
    check_bytes("STATUS and WATCHDOG_STATUS", read_n(t, REG_STATUS, 2), {0x00, 0x00});
    check_bytes("wraps from 0xFF to 0x00", read_n(t, 0xFF, 2), {0xFF, DEVICE_ID_VALUE});
}

// Every address, from the register map (docs/register-map.md) rather than from the code: which
// ones are read-only, writable, or unmapped. A write of 0x55 must set exactly the matching bit.
void test_access_of_every_address()
{
    const uint8_t ro[] = {0x00, 0x01, 0x02, 0x03, 0x10, 0x11, 0x12, 0x13, 0x31};
    for (int reg = 0; reg < 0x100; ++reg) {
        if (reg == REG_LED_CONTROL || reg == REG_STATUS)
            continue;
        bool is_ro = false;
        for (uint8_t r : ro)
            is_ro = is_ro || r == reg;
        i2c_target t = clean();
        write(t, {(uint8_t)reg, 0x55});
        char what[48];
        std::snprintf(what, sizeof what, "STATUS after writing 0x%02X", reg);
        check_eq(what, read_reg(t, REG_STATUS), is_ro ? STATUS_RO_WRITE : STATUS_UNMAPPED_WRITE);
    }
}

void test_adc_is_little_endian_12_bit()
{
    i2c_target t = clean();
    for (uint16_t v : {0x000, 0x001, 0x0FF, 0x100, 0x7FF, 0x800, 0xFFF}) {
        t.adc = v;
        std::vector<uint8_t> b = read_n(t, REG_ADC_LOW, 2);
        check_eq("ADC_LOW", b[0], v & 0xFF);
        check_eq("ADC_HIGH", b[1], v >> 8);
    }
}

void test_inputs_are_a_snapshot_taken_when_the_read_starts()
{
    // A new conversion lands between the two bytes of one read, across the byte boundary at
    // 0x7FF -> 0x800 (half of VDDA). Bytes from two samples would read 0x8FF.
    i2c_target t = clean();
    t.adc = 0x7FF;
    i2c_target_write_start(&t);
    i2c_target_rx(&t, REG_ADC_LOW);
    i2c_target_read_start(&t);
    uint8_t low = i2c_target_tx(&t);
    t.adc = 0x800;
    t.button = BUTTON_PRESSED;
    t.presses = 9;
    uint8_t high = i2c_target_tx(&t);
    uint8_t button = i2c_target_tx(&t);
    uint8_t presses = i2c_target_tx(&t);
    i2c_target_stop(&t);
    check_eq("ADC from one sample", (unsigned)(high << 8 | low), 0x7FF);
    check_eq("button from the same moment", button, 0);
    check_eq("presses from the same moment", presses, 0);
    check_bytes("the next read sees the new sample", read_n(t, REG_ADC_LOW, 4),
                {0x00, 0x08, BUTTON_PRESSED, 9});
}

void test_preloaded_byte_does_not_latch_anything()
{
    // PR #21 review: reading 0x0F makes TXE fetch 0x10 too. Nothing may happen because of that
    // fetch; the next read of 0x10 / 0x11 sees the sample current when it starts.
    i2c_target t = clean();
    t.adc = 0x123;
    read_reg(t, 0x0F);
    t.adc = 0x456;
    check_bytes("ADC after a read that ran into 0x10", read_n(t, REG_ADC_LOW, 2), {0x56, 0x04});
    t.adc = 0x789;
    read_n(t, REG_ADC_LOW, 1);  // LOW only; TXE fetches HIGH
    t.adc = 0xABC;
    check_bytes("HIGH alone, in a later read", read_n(t, REG_ADC_HIGH, 1), {0x0A});
}

void test_button_registers()
{
    i2c_target t = clean();
    t.button = BUTTON_PRESSED;
    t.presses = 0xFF;
    check_bytes("pressed, 255 presses", read_n(t, REG_BUTTON_STATE, 2), {BUTTON_PRESSED, 0xFF});
    t.button = 0;
    t.presses = 0;  // the counter wraps
    check_bytes("released, wrapped", read_n(t, REG_BUTTON_STATE, 2), {0, 0});
    write(t, {REG_BUTTON_PRESSES, 0});
    check_eq("the counter is not clearable", read_reg(t, REG_STATUS), STATUS_RO_WRITE);
}

void test_read_does_not_move_the_pointer()
{
    // Only writes move the pointer: the byte TXE loads ahead (and any byte read) must not, or
    // the next read starting at the stored pointer would be one or more registers off.
    i2c_target t = clean();
    read_n(t, REG_FW_MAJOR, 3);
    check_bytes("next read starts at the written pointer again", read_here(t, 1),
                {FW_VERSION_MAJOR});
    check_bytes("and again", read_here(t, 2), {FW_VERSION_MAJOR, FW_VERSION_MINOR});
    read_reg(t, REG_LED_CONTROL);
    check_bytes("one-byte read, then a read with no pointer write", read_here(t, 1), {0x00});
}

void test_read_after_data_in_the_same_transaction()
{
    // i2ctransfer w2@0x42 0x20 0x01 r1@0x42: the data byte moved the cursor to 0x21, but a read
    // starts at the stored pointer, so the Jetson reads back the value it just wrote.
    i2c_target t = clean();
    i2c_target_write_start(&t);
    i2c_target_rx(&t, REG_LED_CONTROL);
    i2c_target_rx(&t, 1);
    i2c_target_read_start(&t);
    check_eq("read after a data byte starts at the pointer", i2c_target_tx(&t), 1);
    i2c_target_stop(&t);
}

void test_pointer_survives_the_transaction()
{
    i2c_target t = clean();
    write(t, {REG_FW_MINOR});  // pointer only, no data
    check_eq("pointer-only write keeps the LED", t.led, 0);
    check_eq("read after a pointer-only write", read_here(t, 1)[0], FW_VERSION_MINOR);
    write(t, {REG_LED_CONTROL, 1});
    check_bytes("pointer is where the write started, not after it", read_here(t, 1), {1});
    check_eq("STATUS clear", read_reg(t, REG_STATUS), 0);
}

void test_write_auto_increments()
{
    i2c_target t = clean();
    write(t, {REG_LED_CONTROL, 1, 0});  // 0x20 = 1, then 0x21 (unmapped) = 0
    check_eq("first data byte to LED_CONTROL", t.led, 1);
    check_eq("second data byte went to 0x21", read_reg(t, REG_STATUS), STATUS_UNMAPPED_WRITE);
    i2c_target u = fresh();
    write(u, {REG_STATUS, STATUS_RESET, 0x55});  // clear RESET, then 0x31 (RO)
    check_eq("STATUS cleared then RO_WRITE from WATCHDOG_STATUS", read_reg(u, REG_STATUS),
             STATUS_RO_WRITE);
    i2c_target v = clean();
    write(v, {0x1F, 0, 1});  // 0x1F (unmapped) = 0, then 0x20 = 1
    check_eq("write crossing into LED_CONTROL", v.led, 1);
    check_eq("the unmapped byte is still reported", read_reg(v, REG_STATUS), STATUS_UNMAPPED_WRITE);
}

void test_repeated_start_write_takes_a_new_pointer()
{
    i2c_target t = clean();
    i2c_target_write_start(&t);
    i2c_target_rx(&t, REG_LED_CONTROL);
    i2c_target_write_start(&t);  // repeated START, write again
    i2c_target_rx(&t, REG_FW_MAJOR);
    i2c_target_stop(&t);
    check_eq("second write's first byte is a pointer, not data", t.led, 0);
    check_bytes("pointer is FW_MAJOR", read_here(t, 1), {FW_VERSION_MAJOR});
    check_eq("no error recorded", read_reg(t, REG_STATUS), 0);
}

void test_bytes_outside_a_write_are_ignored()
{
    i2c_target t = clean();
    write(t, {REG_LED_CONTROL});
    i2c_target_rx(&t, 1);  // e.g. after a bus error ended the transaction
    check_eq("stray byte after STOP", t.led, 0);
    i2c_target_rx(&t, REG_DEVICE_ID);
    check_bytes("stray byte does not move the pointer", read_here(t, 1), {0});
    i2c_target_write_start(&t);
    i2c_target_rx(&t, REG_LED_CONTROL);
    i2c_target_stop(&t);  // aborted before the data byte
    i2c_target_rx(&t, 1);
    check_eq("stray byte after an aborted write", t.led, 0);
    check_bytes("pointer still LED_CONTROL after an aborted write", read_here(t, 1), {0});
    i2c_target_read_start(&t);
    i2c_target_rx(&t, 1);  // a byte during a read cannot happen; it must not write either
    i2c_target_stop(&t);
    check_eq("byte during a read", t.led, 0);
}

}  // namespace

int main()
{
    test_identification_registers();
    test_reset_state();
    test_led_on_off();
    test_invalid_led_values_are_dropped_and_reported();
    test_read_only_registers_ignore_writes_and_report();
    test_unmapped_registers();
    test_status_is_write_one_to_clear();
    test_status_read_ahead_does_not_clear();
    test_bus_error();
    test_read_auto_increments();
    test_access_of_every_address();
    test_adc_is_little_endian_12_bit();
    test_inputs_are_a_snapshot_taken_when_the_read_starts();
    test_preloaded_byte_does_not_latch_anything();
    test_button_registers();
    test_read_does_not_move_the_pointer();
    test_read_after_data_in_the_same_transaction();
    test_pointer_survives_the_transaction();
    test_write_auto_increments();
    test_repeated_start_write_takes_a_new_pointer();
    test_bytes_outside_a_write_are_ignored();
    if (failures) {
        std::printf("%d check(s) failed\n", failures);
        return 1;
    }
    std::printf("all i2c_target vectors passed\n");
    return 0;
}
