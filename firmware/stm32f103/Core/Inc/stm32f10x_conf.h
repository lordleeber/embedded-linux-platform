/* Step 11: SPL configuration. stm32f10x.h includes this when USE_STDPERIPH_DRIVER is defined;
 * only the four drivers that platformio.ini compiles are listed. */
#ifndef STM32F10X_CONF_H
#define STM32F10X_CONF_H

#include "misc.h"
#include "stm32f10x_gpio.h"
#include "stm32f10x_i2c.h"
#include "stm32f10x_rcc.h"

#define assert_param(expr) ((void)0)

#endif
