/* Step 11: register protocol of the I2C target; see i2c_target.h. No hardware access here. */
#include "i2c_target.h"

void i2c_target_init(struct i2c_target *t)
{
    t->ptr = REG_DEVICE_ID;
    t->led = 0;
    t->state = I2C_TARGET_IDLE;
}

void i2c_target_write_start(struct i2c_target *t)
{
    t->state = I2C_TARGET_WANT_REG;
}

static void write_reg(struct i2c_target *t, uint8_t reg, uint8_t value)
{
    /* Only LED_CONTROL is writable, and only with 0 or 1; anything else is dropped. */
    if (reg == REG_LED_CONTROL && value <= 1)
        t->led = value;
}

void i2c_target_rx(struct i2c_target *t, uint8_t byte)
{
    switch (t->state) {
    case I2C_TARGET_WANT_REG:
        t->ptr = byte;
        t->state = I2C_TARGET_WANT_DATA;
        break;
    case I2C_TARGET_WANT_DATA:
        write_reg(t, t->ptr, byte);
        t->state = I2C_TARGET_DISCARD;
        break;
    case I2C_TARGET_IDLE:
    case I2C_TARGET_DISCARD:
        break;
    }
}

uint8_t i2c_target_tx(const struct i2c_target *t)
{
    switch (t->ptr) {
    case REG_DEVICE_ID:
        return DEVICE_ID_VALUE;
    case REG_FW_MAJOR:
        return FW_VERSION_MAJOR;
    case REG_FW_MINOR:
        return FW_VERSION_MINOR;
    case REG_LED_CONTROL:
        return t->led;
    default:
        return REG_UNMAPPED_VALUE;
    }
}

void i2c_target_stop(struct i2c_target *t)
{
    t->state = I2C_TARGET_IDLE;
}
