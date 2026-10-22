/* Step 11 / 12-a: register protocol of the I2C target; see i2c_target.h. No hardware access here. */
#include "i2c_target.h"

void i2c_target_init(struct i2c_target *t)
{
    t->ptr = REG_DEVICE_ID;
    t->cursor = REG_DEVICE_ID;
    t->led = 0;
    t->status = STATUS_RESET;
    t->state = I2C_TARGET_IDLE;
}

void i2c_target_write_start(struct i2c_target *t)
{
    t->state = I2C_TARGET_WANT_REG;
}

void i2c_target_read_start(struct i2c_target *t)
{
    t->cursor = t->ptr;
    t->state = I2C_TARGET_READING;
}

static int read_only(uint8_t reg)
{
    return reg <= REG_PROTOCOL_VERSION || reg == REG_WATCHDOG_STATUS;
}

static void write_reg(struct i2c_target *t, uint8_t reg, uint8_t value)
{
    if (reg == REG_LED_CONTROL) {
        if (value <= 1)
            t->led = value;
        else
            t->status |= STATUS_BAD_VALUE;
    } else if (reg == REG_STATUS) {
        t->status &= (uint8_t)~(value & STATUS_DEFINED);
    } else {
        t->status |= read_only(reg) ? STATUS_RO_WRITE : STATUS_UNMAPPED_WRITE;
    }
}

void i2c_target_rx(struct i2c_target *t, uint8_t byte)
{
    switch (t->state) {
    case I2C_TARGET_WANT_REG:
        t->ptr = byte;
        t->cursor = byte;
        t->state = I2C_TARGET_WANT_DATA;
        break;
    case I2C_TARGET_WANT_DATA:
        write_reg(t, t->cursor++, byte);
        break;
    case I2C_TARGET_IDLE:
    case I2C_TARGET_READING:
        break;
    }
}

static uint8_t read_reg(const struct i2c_target *t, uint8_t reg)
{
    switch (reg) {
    case REG_DEVICE_ID:
        return DEVICE_ID_VALUE;
    case REG_FW_MAJOR:
        return FW_VERSION_MAJOR;
    case REG_FW_MINOR:
        return FW_VERSION_MINOR;
    case REG_PROTOCOL_VERSION:
        return PROTOCOL_VERSION_VALUE;
    case REG_LED_CONTROL:
        return t->led;
    case REG_STATUS:
        return t->status;
    case REG_WATCHDOG_STATUS:
        return WATCHDOG_STATUS_VALUE;
    default:
        return REG_UNMAPPED_VALUE;
    }
}

uint8_t i2c_target_tx(struct i2c_target *t)
{
    /* Reading has no side effect besides the cursor, so a byte fetched and never sent (the
     * one TXE loads ahead of the NACK) changes nothing the next transaction can see. */
    return read_reg(t, t->cursor++);
}

void i2c_target_stop(struct i2c_target *t)
{
    t->cursor = t->ptr;
    t->state = I2C_TARGET_IDLE;
}

void i2c_target_bus_error(struct i2c_target *t)
{
    t->status |= STATUS_BUS_ERROR;
    i2c_target_stop(t);
}
