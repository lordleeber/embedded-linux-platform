// INA219 register decoding for Step 6-b (tools/ina219_raw.cpp, tests/test_ina219_decode.cpp).
//
// Integer only, in mV / uV / uA / uW: Step 7 moves the same arithmetic into the kernel,
// which has no floating point. Formulas from the TI INA219 datasheet (SBOS448):
//   Bus Voltage (0x02)   bits 15..3 x 4 mV, bit 1 CNVR, bit 0 OVF
//   Shunt Voltage (0x01) signed, 10 uV per bit
//   Current_LSB          = 0.04096 / (Cal x R_shunt)
//   Current (0x04)       signed, Current_LSB per bit
//   Power (0x03)         unsigned, 20 x Current_LSB per bit
#pragma once

#include <cstdint>

namespace ina219 {

enum Reg : std::uint8_t {
    kConfig = 0x00,
    kShuntVoltage = 0x01,
    kBusVoltage = 0x02,
    kPower = 0x03,
    kCurrent = 0x04,
    kCalibration = 0x05,
};

// The chip sends every register MSB first, whatever the host's byte order.
inline std::uint16_t be16(const std::uint8_t b[2])
{
    return static_cast<std::uint16_t>(b[0] << 8 | b[1]);
}

inline std::int32_t bus_mV(std::uint16_t raw)
{
    return (raw >> 3) * 4;
}

inline bool conversion_ready(std::uint16_t raw)
{
    return raw & 0x2;
}

inline bool overflow(std::uint16_t raw)
{
    return raw & 0x1;
}

inline std::int32_t shunt_uV(std::uint16_t raw)
{
    return static_cast<std::int16_t>(raw) * 10;
}

// Ohm's law on the shunt voltage: needs no calibration, only the resistor value.
inline std::int64_t current_uA_from_shunt(std::uint16_t shunt_raw, std::int32_t shunt_mohm)
{
    return std::int64_t{shunt_uV(shunt_raw)} * 1000 / shunt_mohm;
}

// Current_LSB in uA = 0.04096 / (Cal x R[ohm]) x 1e6 = 40960000 / (Cal x R[mohm]).
// cal must be non-zero (0 is the power-on value: the chip then reports no current).
inline std::int64_t current_uA(std::uint16_t raw, std::uint16_t cal, std::int32_t shunt_mohm)
{
    return std::int64_t{static_cast<std::int16_t>(raw)} * 40960000 / (std::int64_t{cal} * shunt_mohm);
}

inline std::int64_t power_uW(std::uint16_t raw, std::uint16_t cal, std::int32_t shunt_mohm)
{
    return std::int64_t{raw} * 20 * 40960000 / (std::int64_t{cal} * shunt_mohm);
}

}  // namespace ina219
