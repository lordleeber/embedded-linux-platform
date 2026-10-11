// Test vectors for tools/ina219_decode.h (Step 6-b), run by tests/test_ina219_raw.py.
//
// The expected values come from the INA219 datasheet and from what Step 6-a read on
// the board (Config 0x0EEF, Bus 0x609A = 12.364 V, Calibration 26868), not from the
// decoder itself. Exit status: 0 = all checks passed, 1 = a check failed.
#include <cstdint>
#include <cstdio>

#include "../tools/ina219_decode.h"

namespace {

int failures = 0;

#define CHECK_EQ(actual, expected)                                                         \
    do {                                                                                   \
        long long a_ = (actual), e_ = (expected);                                          \
        if (a_ != e_) {                                                                    \
            std::printf("FAIL %s:%d %s = %lld, expected %lld\n", __FILE__, __LINE__,      \
                        #actual, a_, e_);                                                  \
            ++failures;                                                                    \
        }                                                                                  \
    } while (0)

void test_be16_is_msb_first()
{
    // The chip sends the MSB first; i2cget's "w" mode (SMBus read word) assumes LSB first
    // and shows Config as 0xef0e.
    const std::uint8_t config[2] = {0x0E, 0xEF};
    const std::uint8_t bus[2] = {0x60, 0x9A};
    CHECK_EQ(ina219::be16(config), 0x0EEF);
    CHECK_EQ(ina219::be16(bus), 0x609A);
}

void test_bus_voltage_drops_the_status_bits()
{
    // Bits 15..3 are the value (LSB 4 mV), bit 1 CNVR, bit 0 OVF, bit 2 unused.
    CHECK_EQ(ina219::bus_mV(0x609A), 12364);
    CHECK_EQ(ina219::bus_mV(0x6098), 12364);
    CHECK_EQ(ina219::bus_mV(0x609B), 12364);
    CHECK_EQ(ina219::bus_mV(0xFFF8), 32764);
    CHECK_EQ(ina219::conversion_ready(0x609A), 1);
    CHECK_EQ(ina219::conversion_ready(0x6098), 0);
    CHECK_EQ(ina219::overflow(0x609B), 1);
    CHECK_EQ(ina219::overflow(0x609A), 0);
}

void test_shunt_is_signed_10uV_per_bit()
{
    CHECK_EQ(ina219::shunt_uV(0x0000), 0);
    CHECK_EQ(ina219::shunt_uV(0x0064), 1000);
    CHECK_EQ(ina219::shunt_uV(0x7FFF), 327670);
    CHECK_EQ(ina219::shunt_uV(0xFFFF), -10);
    CHECK_EQ(ina219::shunt_uV(0xFF9C), -1000);
    CHECK_EQ(ina219::shunt_uV(0x8000), -327680);
}

void test_current_from_shunt_is_ohms_law()
{
    // 1 mV across 0.01 ohm is 100 mA.
    CHECK_EQ(ina219::current_uA_from_shunt(0x0064, 10), 100000);
    CHECK_EQ(ina219::current_uA_from_shunt(0xFFFF, 10), -1000);
}

void test_current_register_uses_the_lsb_from_calibration()
{
    // Datasheet: Current_LSB = 0.04096 / (Cal * R_shunt) = 152.45 uA for Cal 26868, 0.01 ohm.
    // Integer arithmetic truncates toward zero: 100 LSB = 15244.8 uA -> 15244.
    CHECK_EQ(ina219::current_uA(100, 26868, 10), 15244);
    CHECK_EQ(ina219::current_uA(0xFF9C, 26868, 10), -15244);   // -100, two's complement
    CHECK_EQ(ina219::current_uA(0, 26868, 10), 0);
}

void test_power_is_20_current_lsbs_and_unsigned()
{
    // Power_LSB = 20 * Current_LSB = 3.049 mW; the Power register has no sign bit.
    CHECK_EQ(ina219::power_uW(100, 26868, 10), 304898);
    CHECK_EQ(ina219::power_uW(0x8000, 26868, 10), 99908983LL);
}

void test_register_and_shunt_agree()
{
    // The chip computes Current = Shunt * Cal / 4096; both paths must give the same
    // current within one Current LSB (152 uA).
    const std::uint16_t shunt = 100;                                  // 1 mV
    const std::uint16_t reg = shunt * 26868 / 4096;                   // 655
    long long diff = ina219::current_uA(reg, 26868, 10) - ina219::current_uA_from_shunt(shunt, 10);
    CHECK_EQ(diff < 0 ? -diff <= 153 : diff <= 153, 1);
}

}  // namespace

int main()
{
    test_be16_is_msb_first();
    test_bus_voltage_drops_the_status_bits();
    test_shunt_is_signed_10uV_per_bit();
    test_current_from_shunt_is_ohms_law();
    test_current_register_uses_the_lsb_from_calibration();
    test_power_is_20_current_lsbs_and_unsigned();
    test_register_and_shunt_agree();
    std::printf("%s (%d failure(s))\n", failures ? "FAILED" : "OK", failures);
    return failures ? 1 : 0;
}
