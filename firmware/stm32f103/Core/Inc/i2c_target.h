/* Step 11 / 12-a / 12-b: the STM32F103's I2C target (slave) register protocol, without any
 * hardware access. Register map v1.1 (PROTOCOL_VERSION 0x11).
 *
 * The Jetson is the controller and starts every transaction; this side only answers. The
 * interrupt handlers in main.c turn the I2C1 peripheral's events into the calls below, so the
 * same code runs on the Blue Pill and in the host test (tests/test_i2c_target.cpp).
 *
 *   write: START 0x42+W  reg  data...  STOP         first byte = register pointer,
 *                                                   data bytes go to reg, reg+1, ...
 *   read:  START 0x42+W  reg  RESTART 0x42+R  byte...  STOP
 *          bytes come from reg, reg+1, ... (0xFF wraps to 0x00)
 *
 * Auto-increment only lives inside one transaction: the stored pointer is the register byte of
 * the last write and nothing else moves it. A read without a pointer write starts there again.
 * That is what makes the byte TXE loads ahead of the controller's NACK harmless: it is fetched,
 * never sent, and does not shift the next read.
 *
 * Writes to read-only or unmapped registers and LED_CONTROL values other than 0 / 1 are
 * acknowledged on the bus (the F103 ACKs before the firmware sees the byte), dropped, and
 * recorded in STATUS. STATUS is write-1-to-clear, not read-to-clear: a preloaded byte is "read"
 * by the firmware without reaching the Jetson, and must not clear anything. Unmapped registers
 * read as 0xFF; reading is never an error (a multi-byte read runs past mapped registers).
 *
 * Inputs (Step 12-b): main.c keeps adc / button / presses up to date; i2c_target_read_start()
 * copies all three into a snapshot and the whole read is served from it. A 2-byte read of the
 * ADC therefore always gets both bytes of one conversion, and nothing depends on which bytes
 * are actually read (TXE's preloaded byte included). Two separate reads may see two samples.
 *
 * PROTOCOL_VERSION: high nibble = major, low nibble = minor. Minor goes up when registers or
 * STATUS bits are added (unused addresses read 0xFF before, reserved bits read 0); major goes up
 * when an existing register or the transaction rules change. A reader that knows M.n works with
 * any device reporting M.n or a later M.x. Step 11's firmware has no 0x03 and reads 0xFF there.
 * FW_MAJOR / FW_MINOR change with every firmware release, protocol change or not.
 *
 * docs/register-map.md is the human-readable copy of this file; a test keeps them equal.
 */
#ifndef I2C_TARGET_H
#define I2C_TARGET_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define I2C_TARGET_ADDR 0x42 /* 7-bit address, the project's choice */

/* 0x00-0x0F identification / version, 0x10-0x1F sensor / input,
 * 0x20-0x2F output control, 0x30-0x3F health / watchdog */
#define REG_DEVICE_ID 0x00        /* RO */
#define REG_FW_MAJOR 0x01         /* RO */
#define REG_FW_MINOR 0x02         /* RO */
#define REG_PROTOCOL_VERSION 0x03 /* RO */
#define REG_ADC_LOW 0x10          /* RO: PA0, 12-bit, bits 7:0 */
#define REG_ADC_HIGH 0x11         /* RO: bits 11:8 in bits 3:0, upper bits 0 */
#define REG_BUTTON_STATE 0x12     /* RO: BUTTON_PRESSED while the PA1 button is held */
#define REG_BUTTON_PRESSES 0x13   /* RO: debounced presses since reset, wraps at 256 */
#define REG_LED_CONTROL 0x20      /* RW: 0 = off, 1 = on, reset 0 */
#define REG_STATUS 0x30           /* RW1C: write 1 to a bit to clear it */
#define REG_WATCHDOG_STATUS 0x31  /* RO: placeholder until the watchdog phase */

#define DEVICE_ID_VALUE 0xED
#define FW_VERSION_MAJOR 0
#define FW_VERSION_MINOR 3
#define PROTOCOL_VERSION_VALUE 0x11
#define WATCHDOG_STATUS_VALUE 0x00 /* no watchdog yet */
#define REG_UNMAPPED_VALUE 0xFF

#define BUTTON_PRESSED 0x01 /* BUTTON_STATE bit 0; bits 7:1 read 0 */

/* STATUS bits; bits 4-6 are reserved, read 0, and ignore writes */
#define STATUS_RO_WRITE 0x01       /* a write to a read-only register was dropped */
#define STATUS_UNMAPPED_WRITE 0x02 /* a write to an unmapped register was dropped */
#define STATUS_BAD_VALUE 0x04      /* a value the register does not accept was dropped */
#define STATUS_BUS_ERROR 0x08      /* BERR / ARLO / OVR; I2C1 was reset afterwards */
#define STATUS_RESET 0x80          /* set at power-on / reset: the board restarted */
#define STATUS_DEFINED (STATUS_RO_WRITE | STATUS_UNMAPPED_WRITE | STATUS_BAD_VALUE | \
                        STATUS_BUS_ERROR | STATUS_RESET)

enum i2c_target_state {
    I2C_TARGET_IDLE,     /* between transactions */
    I2C_TARGET_WANT_REG, /* write started: next byte is the register pointer */
    I2C_TARGET_WANT_DATA,
    I2C_TARGET_READING,
};

struct i2c_target {
    uint8_t ptr;    /* stored pointer: the register byte of the last write */
    uint8_t cursor; /* next register of the current transaction */
    uint8_t led;    /* LED_CONTROL; main.c drives PC13 from it */
    uint8_t status; /* STATUS */
    enum i2c_target_state state;
    /* live inputs, written by main.c outside the I2C interrupt (one store each) */
    volatile uint16_t adc;
    volatile uint8_t button;
    volatile uint8_t presses;
    /* the inputs as they were when the current read started */
    uint16_t snap_adc;
    uint8_t snap_button;
    uint8_t snap_presses;
};

void i2c_target_init(struct i2c_target *t);
/* address matched with the write bit (also after a repeated START) */
void i2c_target_write_start(struct i2c_target *t);
/* address matched with the read bit */
void i2c_target_read_start(struct i2c_target *t);
/* one byte received from the controller */
void i2c_target_rx(struct i2c_target *t, uint8_t byte);
/* the next byte to send to the controller (also the one TXE loads ahead) */
uint8_t i2c_target_tx(struct i2c_target *t);
/* STOP or NACK from the controller: the transaction is over */
void i2c_target_stop(struct i2c_target *t);
/* BERR / ARLO / OVR: recorded in STATUS, the transaction is over */
void i2c_target_bus_error(struct i2c_target *t);

#ifdef __cplusplus
}
#endif

#endif
