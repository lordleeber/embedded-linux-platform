/* Step 11: the STM32F103's I2C target (slave) register protocol, without any hardware access.
 *
 * The Jetson is the controller and starts every transaction; this side only answers. The
 * interrupt handlers in main.c turn the I2C1 peripheral's events into the four calls below,
 * so the same code runs on the Blue Pill and in the host test (tests/test_i2c_target.cpp).
 *
 *   write: START 0x42+W  reg  [data]  STOP         first byte = register pointer,
 *                                                  second byte = data, later bytes ignored
 *   read:  START 0x42+W  reg  RESTART 0x42+R  byte... STOP
 *          every byte of a read is the selected register (no auto-increment in Step 11)
 *
 * The pointer stays where the last write put it. Writes to read-only or unmapped registers
 * and LED_CONTROL values other than 0 / 1 are acknowledged on the bus and then dropped; the
 * Jetson finds out by reading the register back. Unmapped registers read as 0xFF.
 * docs/register-map.md is the human-readable copy of this file; a test keeps them equal.
 */
#ifndef I2C_TARGET_H
#define I2C_TARGET_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define I2C_TARGET_ADDR 0x42 /* 7-bit address, the project's choice */

#define REG_DEVICE_ID 0x00   /* RO */
#define REG_FW_MAJOR 0x01    /* RO */
#define REG_FW_MINOR 0x02    /* RO */
#define REG_LED_CONTROL 0x20 /* RW: 0 = off, 1 = on, reset 0 */

#define DEVICE_ID_VALUE 0xED
#define FW_VERSION_MAJOR 0
#define FW_VERSION_MINOR 1
#define REG_UNMAPPED_VALUE 0xFF

enum i2c_target_state {
    I2C_TARGET_IDLE,     /* between transactions */
    I2C_TARGET_WANT_REG, /* write started: next byte is the register pointer */
    I2C_TARGET_WANT_DATA,
    I2C_TARGET_DISCARD, /* data byte taken: further bytes of this write are dropped */
};

struct i2c_target {
    uint8_t ptr;
    uint8_t led; /* LED_CONTROL; main.c drives PC13 from it */
    enum i2c_target_state state;
};

void i2c_target_init(struct i2c_target *t);
/* address matched with the write bit (also after a repeated START) */
void i2c_target_write_start(struct i2c_target *t);
/* one byte received from the controller */
void i2c_target_rx(struct i2c_target *t, uint8_t byte);
/* the next byte to send to the controller */
uint8_t i2c_target_tx(const struct i2c_target *t);
/* STOP, NACK from the controller or a bus error: the transaction is over */
void i2c_target_stop(struct i2c_target *t);

#ifdef __cplusplus
}
#endif

#endif
