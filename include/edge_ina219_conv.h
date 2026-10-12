/* SPDX-License-Identifier: GPL-2.0 */
/*
 * INA219 register map and conversions for edge_ina219.ko (Step 7).
 *
 * Plain C, integer only (the kernel has no floating point), usable from the
 * kernel and from userspace: tests/test_edge_ina219_conv.cpp compares every
 * value with Step 6-b's tools/ina219_decode.h, so the driver and ina219_raw
 * agree on the same register. Formulas from the TI INA219 datasheet (SBOS448):
 *   Bus Voltage (0x02)   bits 15..3 x 4 mV, bit 1 CNVR, bit 0 OVF
 *   Shunt Voltage (0x01) signed, 10 uV per bit
 *   Current_LSB          = 0.04096 / (Cal x R_shunt)
 *   Current (0x04)       signed, Current_LSB per bit
 *   Power (0x03)         unsigned, 20 x Current_LSB per bit
 */
#ifndef EDGE_INA219_CONV_H
#define EDGE_INA219_CONV_H

#ifdef __KERNEL__
#include <linux/types.h>
#else
#include <stdint.h>
typedef uint16_t u16;
typedef int16_t s16;
typedef int32_t s32;
typedef int64_t s64;
#endif

#define EDGE_INA219_REG_CONFIG	0x00
#define EDGE_INA219_REG_SHUNT	0x01
#define EDGE_INA219_REG_BUS	0x02
#define EDGE_INA219_REG_POWER	0x03
#define EDGE_INA219_REG_CURRENT	0x04
#define EDGE_INA219_REG_CAL	0x05
#define EDGE_INA219_NUM_REGS	6

/*
 * What the vendor sample writes (Step 6-a): 32 V range, gain /8 (320 mV),
 * 12-bit x 32 samples on both ADCs, continuous shunt + bus; Cal 26868 gives
 * Current_LSB = 0.1524 mA with the 0.01 ohm shunt the sample assumes.
 */
#define EDGE_INA219_CONFIG	0x0EEF
#define EDGE_INA219_CAL		26868
#define EDGE_INA219_SHUNT_MOHM	10

static inline s32 edge_ina219_bus_mv(u16 raw)
{
	return (raw >> 3) * 4;
}

static inline s32 edge_ina219_shunt_uv(u16 raw)
{
	return (s16)raw * 10;
}

/* Current_LSB in uA = 40960000 / (Cal x R[mohm]); cal must be non-zero. */
static inline s64 edge_ina219_current_ua(u16 raw, u16 cal, s32 shunt_mohm)
{
	return (s64)(s16)raw * 40960000 / ((s64)cal * shunt_mohm);
}

static inline s64 edge_ina219_power_uw(u16 raw, u16 cal, s32 shunt_mohm)
{
	return (s64)raw * 20 * 40960000 / ((s64)cal * shunt_mohm);
}

#endif /* EDGE_INA219_CONV_H */
