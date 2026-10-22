/* Step 11 / 12-a: Blue Pill (STM32F103C8T6) as an I2C target at 0x42 with the SPL.
 *
 * I2C1 on PB6 (SCL) / PB7 (SDA) answers the Jetson; the register protocol is in i2c_target.c.
 * Everything happens in the two I2C1 interrupts; main() just spins. The on-board LED on PC13 is
 * active-low (pin low = LED on).
 */
#include "stm32f10x.h"

#include "i2c_target.h"

static struct i2c_target target;

static void led_apply(void)
{
    if (target.led)
        GPIO_ResetBits(GPIOC, GPIO_Pin_13);
    else
        GPIO_SetBits(GPIOC, GPIO_Pin_13);
}

static void led_init(void)
{
    GPIO_InitTypeDef gpio;

    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOC, ENABLE);
    gpio.GPIO_Pin = GPIO_Pin_13;
    gpio.GPIO_Speed = GPIO_Speed_2MHz;
    gpio.GPIO_Mode = GPIO_Mode_Out_PP;
    GPIO_Init(GPIOC, &gpio);
    led_apply();
}

/* I2C1's own registers; also run again after a software reset, which clears all of them. */
static void i2c1_regs_init(void)
{
    I2C_InitTypeDef i2c;

    I2C_StructInit(&i2c);
    i2c.I2C_Mode = I2C_Mode_I2C;
    i2c.I2C_OwnAddress1 = I2C_TARGET_ADDR << 1; /* OAR1 holds the address in bits 7:1 */
    i2c.I2C_Ack = I2C_Ack_Enable;
    i2c.I2C_AcknowledgedAddress = I2C_AcknowledgedAddress_7bit;
    i2c.I2C_ClockSpeed = 100000; /* only used as a controller; I2C_Init requires a value */
    I2C_Init(I2C1, &i2c);
    I2C_ITConfig(I2C1, I2C_IT_EVT | I2C_IT_BUF | I2C_IT_ERR, ENABLE);
}

static void i2c1_target_init(void)
{
    GPIO_InitTypeDef gpio;
    NVIC_InitTypeDef nvic;

    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOB, ENABLE);
    RCC_APB1PeriphClockCmd(RCC_APB1Periph_I2C1, ENABLE);
    /* Open drain: the Jetson's carrier board has the pull-ups on pins 27 / 28. */
    gpio.GPIO_Pin = GPIO_Pin_6 | GPIO_Pin_7;
    gpio.GPIO_Speed = GPIO_Speed_50MHz;
    gpio.GPIO_Mode = GPIO_Mode_AF_OD;
    GPIO_Init(GPIOB, &gpio);

    NVIC_PriorityGroupConfig(NVIC_PriorityGroup_2);
    nvic.NVIC_IRQChannelPreemptionPriority = 1;
    nvic.NVIC_IRQChannelSubPriority = 0;
    nvic.NVIC_IRQChannelCmd = ENABLE;
    nvic.NVIC_IRQChannel = I2C1_EV_IRQn;
    NVIC_Init(&nvic);
    nvic.NVIC_IRQChannel = I2C1_ER_IRQn;
    NVIC_Init(&nvic);

    i2c1_regs_init();
}

void I2C1_EV_IRQHandler(void)
{
    /* Reads SR1 then SR2, which also clears ADDR; SR2 sits in the upper 16 bits. */
    uint32_t ev = I2C_GetLastEvent(I2C1);
    int reading = (ev & ((uint32_t)I2C_SR2_TRA << 16)) != 0;

    /* A data byte still in DR belongs to the transaction before a repeated START in the same
     * snapshot: take it before ADDR starts a new write, or it would become the pointer. */
    if (ev & I2C_SR1_RXNE) {
        i2c_target_rx(&target, I2C_ReceiveData(I2C1));
        led_apply();
    }
    /* ADDR before TXE: the first byte of a read comes from the stored pointer. */
    if (ev & I2C_SR1_ADDR) {
        if (reading)
            i2c_target_read_start(&target);
        else
            i2c_target_write_start(&target);
    }
    /* TXE: DR is empty. TXE also loads one byte ahead of the controller's NACK; that byte is
     * fetched and never sent, and reads do not move the pointer (i2c_target.h). Step 11
     * measured that it never shows up in the next read. */
    if (reading && (ev & I2C_SR1_TXE))
        I2C_SendData(I2C1, i2c_target_tx(&target));
    if (ev & I2C_SR1_STOPF) {
        I2C_Cmd(I2C1, ENABLE); /* a CR1 write after the SR1 read clears STOPF */
        i2c_target_stop(&target);
    }
}

void I2C1_ER_IRQHandler(void)
{
    uint16_t sr1 = I2C1->SR1;

    I2C_ClearITPendingBit(I2C1, I2C_IT_AF | I2C_IT_BERR | I2C_IT_ARLO | I2C_IT_OVR);
    if (sr1 & (I2C_SR1_BERR | I2C_SR1_ARLO | I2C_SR1_OVR)) {
        /* Record it, then reset I2C1 with SWRST; that clears every I2C1 register, so the setup
         * runs again. This is not ES096's full workaround for a stuck BUSY flag (toggle SCL /
         * SDA as GPIO before SWRST): not done. A transaction starting in these few
         * microseconds gets a NACK and fails; retrying is up to the Jetson side. */
        i2c_target_bus_error(&target);
        I2C_SoftwareResetCmd(I2C1, ENABLE);
        I2C_SoftwareResetCmd(I2C1, DISABLE);
        i2c1_regs_init();
    } else if (sr1 & I2C_SR1_AF) {
        /* The controller's NACK after the last byte of a read: the normal end of a read
         * (RM0008: a slave transmitter gets AF, not STOPF). */
        i2c_target_stop(&target);
    }
}

int main(void)
{
    /* SystemInit() in the startup code has already set 72 MHz from the 8 MHz crystal. */
    i2c_target_init(&target);
    led_init();
    i2c1_target_init();
    /* No __WFI() here: after a power cycle clears DBGMCU_CR, an F1 asleep in WFI does not let
     * SWD read memory, and the board can no longer be flashed without BOOT0 (Step 11). */
    for (;;) {
    }
}
