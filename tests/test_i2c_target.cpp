// Test vectors for firmware/stm32f103/Core/Src/i2c_target.c (Step 11): the register protocol
// the Blue Pill answers on I2C, driven here by the same calls main.c makes from the I2C1
// interrupts. The expected behaviour comes from i2c_target.h and docs/register-map.md.
// Exit status: 0 = all checks passed, 1 = a check failed.
#include <cstdint>
#include <cstdio>
#include <initializer_list>

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

// i2cset -y BUS 0x42 reg byte...
void write(i2c_target &t, std::initializer_list<uint8_t> bytes)
{
    i2c_target_write_start(&t);
    for (uint8_t b : bytes)
        i2c_target_rx(&t, b);
    i2c_target_stop(&t);
}

// i2cget -y BUS 0x42 reg: pointer write, repeated START, one byte read, NACK, STOP
uint8_t read_reg(i2c_target &t, uint8_t reg)
{
    i2c_target_write_start(&t);
    i2c_target_rx(&t, reg);
    uint8_t b = i2c_target_tx(&t);
    i2c_target_stop(&t);
    return b;
}

i2c_target fresh()
{
    i2c_target t;
    i2c_target_init(&t);
    return t;
}

void test_identification_registers()
{
    i2c_target t = fresh();
    check_eq("DEVICE_ID", read_reg(t, REG_DEVICE_ID), 0xED);
    check_eq("FW_MAJOR", read_reg(t, REG_FW_MAJOR), 0x00);
    check_eq("FW_MINOR", read_reg(t, REG_FW_MINOR), 0x01);
    check_eq("address", I2C_TARGET_ADDR, 0x42);
}

void test_reset_state()
{
    i2c_target t = fresh();
    check_eq("LED off after reset", t.led, 0);
    check_eq("LED_CONTROL reads 0 after reset", read_reg(t, REG_LED_CONTROL), 0);
    i2c_target u = fresh();
    check_eq("read without a pointer write: DEVICE_ID", i2c_target_tx(&u), DEVICE_ID_VALUE);
}

void test_led_on_off()
{
    i2c_target t = fresh();
    write(t, {REG_LED_CONTROL, 1});
    check_eq("LED on", t.led, 1);
    check_eq("LED_CONTROL reads 1", read_reg(t, REG_LED_CONTROL), 1);
    write(t, {REG_LED_CONTROL, 0});
    check_eq("LED off", t.led, 0);
    check_eq("LED_CONTROL reads 0", read_reg(t, REG_LED_CONTROL), 0);
}

void test_invalid_led_values_are_dropped()
{
    for (uint8_t start : {0, 1}) {
        for (uint8_t bad : {2, 0x80, 0xFF}) {
            i2c_target t = fresh();
            write(t, {REG_LED_CONTROL, start});
            write(t, {REG_LED_CONTROL, bad});
            check_eq("LED unchanged by an invalid value", t.led, start);
            check_eq("LED_CONTROL unchanged by an invalid value", read_reg(t, REG_LED_CONTROL),
                     start);
        }
    }
}

void test_read_only_registers_ignore_writes()
{
    i2c_target t = fresh();
    write(t, {REG_DEVICE_ID, 0x55});
    write(t, {REG_FW_MAJOR, 0x55});
    write(t, {REG_FW_MINOR, 0x55});
    check_eq("DEVICE_ID after a write", read_reg(t, REG_DEVICE_ID), DEVICE_ID_VALUE);
    check_eq("FW_MAJOR after a write", read_reg(t, REG_FW_MAJOR), FW_VERSION_MAJOR);
    check_eq("FW_MINOR after a write", read_reg(t, REG_FW_MINOR), FW_VERSION_MINOR);
    check_eq("LED untouched", t.led, 0);
}

void test_unmapped_registers()
{
    for (uint8_t reg : {0x03, 0x0F, 0x10, 0x1F, 0x21, 0x30, 0xFF}) {
        i2c_target t = fresh();
        write(t, {reg, 1});
        check_eq("unmapped reads 0xFF", read_reg(t, reg), REG_UNMAPPED_VALUE);
        check_eq("write to unmapped leaves the LED alone", t.led, 0);
    }
}

void test_no_auto_increment()
{
    i2c_target t = fresh();
    i2c_target_write_start(&t);
    i2c_target_rx(&t, REG_DEVICE_ID);
    for (int i = 0; i < 3; ++i)
        check_eq("multi-byte read repeats the register", i2c_target_tx(&t), DEVICE_ID_VALUE);
    i2c_target_stop(&t);
    check_eq("pointer still DEVICE_ID", i2c_target_tx(&t), DEVICE_ID_VALUE);
}

void test_pointer_survives_the_transaction()
{
    i2c_target t = fresh();
    write(t, {REG_FW_MINOR});  // pointer only, no data
    check_eq("pointer-only write keeps the LED", t.led, 0);
    check_eq("separate read uses the pointer", i2c_target_tx(&t), FW_VERSION_MINOR);
    write(t, {REG_LED_CONTROL, 1});
    check_eq("pointer moved by a data write", i2c_target_tx(&t), 1);
}

void test_extra_data_bytes_are_dropped()
{
    i2c_target t = fresh();
    write(t, {REG_LED_CONTROL, 1, 0, 0});
    check_eq("only the first data byte counts", t.led, 1);
}

void test_repeated_start_write_takes_a_new_pointer()
{
    i2c_target t = fresh();
    i2c_target_write_start(&t);
    i2c_target_rx(&t, REG_LED_CONTROL);
    i2c_target_write_start(&t);  // repeated START, write again
    i2c_target_rx(&t, REG_FW_MAJOR);
    i2c_target_stop(&t);
    check_eq("second write's first byte is a pointer, not data", t.led, 0);
    check_eq("pointer is FW_MAJOR", i2c_target_tx(&t), FW_VERSION_MAJOR);
}

void test_bytes_outside_a_write_are_ignored()
{
    i2c_target t = fresh();
    write(t, {REG_LED_CONTROL});
    i2c_target_rx(&t, 1);  // e.g. after a bus error ended the transaction
    check_eq("stray byte after STOP", t.led, 0);
    i2c_target_rx(&t, REG_DEVICE_ID);
    check_eq("stray byte does not move the pointer", i2c_target_tx(&t), 0);
    i2c_target_write_start(&t);
    i2c_target_rx(&t, REG_LED_CONTROL);
    i2c_target_stop(&t);  // aborted before the data byte
    i2c_target_rx(&t, 1);
    check_eq("stray byte after an aborted write", t.led, 0);
    i2c_target_rx(&t, REG_DEVICE_ID);
    check_eq("pointer still LED_CONTROL after an aborted write", i2c_target_tx(&t), 0);
}

}  // namespace

int main()
{
    test_identification_registers();
    test_reset_state();
    test_led_on_off();
    test_invalid_led_values_are_dropped();
    test_read_only_registers_ignore_writes();
    test_unmapped_registers();
    test_no_auto_increment();
    test_pointer_survives_the_transaction();
    test_extra_data_bytes_are_dropped();
    test_repeated_start_write_takes_a_new_pointer();
    test_bytes_outside_a_write_are_ignored();
    if (failures) {
        std::printf("%d check(s) failed\n", failures);
        return 1;
    }
    std::printf("all i2c_target vectors passed\n");
    return 0;
}
