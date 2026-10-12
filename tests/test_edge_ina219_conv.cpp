// Test vectors for include/edge_ina219_conv.h (Step 7), run by tests/test_edge_ina219_static.py.
//
// The header is the arithmetic edge_ina219.ko runs in the kernel. Two kinds of checks:
// fixed vectors from the datasheet and the board (Step 6-a / 6-b readings), and a sweep
// that compares every value with Step 6-b's tools/ina219_decode.h, so the driver and
// ina219_raw cannot disagree on the same register value.
// Exit status: 0 = all checks passed, 1 = a check failed.
#include <cstdint>
#include <cstdio>

#include "../include/edge_ina219_conv.h"
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

void test_register_numbers_and_sample_settings()
{
    // Datasheet register map; Config and Calibration are what the vendor sample writes
    // (Step 6-a: 0x0EEF, 26868), which the driver writes again in probe().
    CHECK_EQ(EDGE_INA219_REG_CONFIG, 0x00);
    CHECK_EQ(EDGE_INA219_REG_SHUNT, 0x01);
    CHECK_EQ(EDGE_INA219_REG_BUS, 0x02);
    CHECK_EQ(EDGE_INA219_REG_POWER, 0x03);
    CHECK_EQ(EDGE_INA219_REG_CURRENT, 0x04);
    CHECK_EQ(EDGE_INA219_REG_CAL, 0x05);
    CHECK_EQ(EDGE_INA219_CONFIG, 0x0EEF);
    CHECK_EQ(EDGE_INA219_CAL, 26868);
    CHECK_EQ(EDGE_INA219_SHUNT_MOHM, 10);
}

void test_board_readings()
{
    // Step 6-a: Bus 0x609A = 12.364 V. Step 6-b on battery: Shunt 0xFD9B = -6.130 mV,
    // current -613.000 mA (shunt) / -612.997 mA (register), Power 0x0998 = 7488.295 mW.
    CHECK_EQ(edge_ina219_bus_mv(0x609A), 12364);
    CHECK_EQ(edge_ina219_bus_mv(0x609B), 12364);   // CNVR / OVF are not voltage
    CHECK_EQ(edge_ina219_shunt_uv(0xFD9B), -6130);
    CHECK_EQ(edge_ina219_shunt_uv(0x7FFF), 327670);
    CHECK_EQ(edge_ina219_current_ua(0xF04B, 26868, 10), -612997);
    CHECK_EQ(edge_ina219_power_uw(0x0998, 26868, 10), 7488295);
}

void test_same_arithmetic_as_ina219_raw()
{
    // Every 16-bit value through both decoders, at the sample's Cal and at the extremes.
    const std::uint16_t cals[] = {1, 4096, 26868, 0xFFFE};
    for (std::uint32_t r = 0; r <= 0xFFFF; ++r) {
        const auto raw = static_cast<std::uint16_t>(r);
        if (edge_ina219_bus_mv(raw) != ina219::bus_mV(raw) ||
            edge_ina219_shunt_uv(raw) != ina219::shunt_uV(raw)) {
            std::printf("FAIL voltage differs from ina219_decode.h at 0x%04X\n", raw);
            ++failures;
            return;
        }
        for (std::uint16_t cal : cals) {
            if (edge_ina219_current_ua(raw, cal, 10) != ina219::current_uA(raw, cal, 10) ||
                edge_ina219_power_uw(raw, cal, 10) != ina219::power_uW(raw, cal, 10)) {
                std::printf("FAIL current/power differs at raw 0x%04X cal %u\n", raw, cal);
                ++failures;
                return;
            }
        }
    }
}

}  // namespace

int main()
{
    test_register_numbers_and_sample_settings();
    test_board_readings();
    test_same_arithmetic_as_ina219_raw();
    if (failures == 0)
        std::printf("all edge_ina219_conv checks passed\n");
    return failures ? 1 : 0;
}
