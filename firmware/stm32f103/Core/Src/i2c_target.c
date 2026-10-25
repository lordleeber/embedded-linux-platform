/* Step 11 / 12-a / 12-b: register protocol of the I2C target; see i2c_target.h. No hardware access
 * here. */
#include "i2c_target.h"

void i2c_target_init(struct i2c_target *t)
{
    t->ptr = REG_DEVICE_ID;
    t->cursor = REG_DEVICE_ID;
    t->led = 0;
    t->status = STATUS_RESET;
    t->state = I2C_TARGET_IDLE;
    t->adc = 0;
    t->button = 0;
    t->presses = 0;
    t->snap_adc = 0;
    t->snap_button = 0;
    t->snap_presses = 0;
}

void i2c_target_write_start(struct i2c_target *t)
{
    t->state = I2C_TARGET_WANT_REG;
}

void i2c_target_read_start(struct i2c_target *t)
{
    t->cursor = t->ptr;
    t->state = I2C_TARGET_READING;
    /* One snapshot per read, whatever bytes it turns out to read. */
    t->snap_adc = t->adc;
    t->snap_button = t->button;
    t->snap_presses = t->presses;
}

static uint8_t get_device_id(const struct i2c_target *t) { (void)t; return DEVICE_ID_VALUE; }
static uint8_t get_fw_major(const struct i2c_target *t) { (void)t; return FW_VERSION_MAJOR; }
static uint8_t get_fw_minor(const struct i2c_target *t) { (void)t; return FW_VERSION_MINOR; }
static uint8_t get_protocol(const struct i2c_target *t) { (void)t; return PROTOCOL_VERSION_VALUE; }
static uint8_t get_adc_low(const struct i2c_target *t) { return (uint8_t)(t->snap_adc & 0xFF); }
static uint8_t get_adc_high(const struct i2c_target *t) { return (uint8_t)(t->snap_adc >> 8); }
static uint8_t get_button(const struct i2c_target *t) { return t->snap_button; }
static uint8_t get_presses(const struct i2c_target *t) { return t->snap_presses; }
static uint8_t get_led(const struct i2c_target *t) { return t->led; }
static uint8_t get_status(const struct i2c_target *t) { return t->status; }
static uint8_t get_watchdog(const struct i2c_target *t) { (void)t; return WATCHDOG_STATUS_VALUE; }

/* The register map in one place (PR #21 review): every mapped address, whether it can be
 * written, and where a read gets its value. Anything not listed is unmapped. */
static const struct reg_def {
    uint8_t addr;
    uint8_t writable;
    uint8_t (*get)(const struct i2c_target *t);
} REGS[] = {
    {REG_DEVICE_ID, 0, get_device_id},
    {REG_FW_MAJOR, 0, get_fw_major},
    {REG_FW_MINOR, 0, get_fw_minor},
    {REG_PROTOCOL_VERSION, 0, get_protocol},
    {REG_ADC_LOW, 0, get_adc_low},
    {REG_ADC_HIGH, 0, get_adc_high},
    {REG_BUTTON_STATE, 0, get_button},
    {REG_BUTTON_PRESSES, 0, get_presses},
    {REG_LED_CONTROL, 1, get_led},
    {REG_STATUS, 1, get_status},
    {REG_WATCHDOG_STATUS, 0, get_watchdog},
};

static const struct reg_def *find_reg(uint8_t reg)
{
    unsigned i;

    for (i = 0; i < sizeof(REGS) / sizeof(REGS[0]); i++)
        if (REGS[i].addr == reg)
            return &REGS[i];
    return 0;
}

static void write_reg(struct i2c_target *t, uint8_t reg, uint8_t value)
{
    const struct reg_def *r = find_reg(reg);

    if (!r) {
        t->status |= STATUS_UNMAPPED_WRITE;
    } else if (!r->writable) {
        t->status |= STATUS_RO_WRITE;
    } else if (reg == REG_LED_CONTROL) {
        if (value <= 1)
            t->led = value;
        else
            t->status |= STATUS_BAD_VALUE;
    } else { /* REG_STATUS */
        t->status &= (uint8_t)~(value & STATUS_DEFINED);
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
    const struct reg_def *r = find_reg(reg);

    return r ? r->get(t) : REG_UNMAPPED_VALUE;
}

uint8_t i2c_target_tx(struct i2c_target *t)
{
    /* Reading has no side effect besides the cursor, so a byte fetched and never sent (the
     * one TXE loads ahead of the NACK) changes nothing the next transaction can see. */
    return read_reg(t, t->cursor++);
}

void i2c_target_stop(struct i2c_target *t)
{
    /* The cursor is left where it is: read_start() is the one place that puts it back on the
     * pointer, so a read cannot work by accident when read_start() is not called. */
    t->state = I2C_TARGET_IDLE;
}

void i2c_target_bus_error(struct i2c_target *t)
{
    t->status |= STATUS_BUS_ERROR;
    i2c_target_stop(t);
}
