/* SPDX-License-Identifier: GPL-2.0 */
/*
 * The Blue Pill's I2C register map (v1.1, firmware/stm32f103/docs/register-map.md) as
 * edge_ctrl.ko sees it (Step 13).
 *
 * The firmware keeps its own copy in Core/Inc/i2c_target.h; that one includes <stdint.h>
 * and the target's state machine, which the kernel cannot use. Plain C, usable from the
 * kernel and from userspace: tests/test_edge_ctrl_regs.cpp drives the firmware's
 * i2c_target.c with the driver's transactions and decodes the answers with the helpers
 * below, so the two copies cannot drift apart unnoticed.
 */
#ifndef EDGE_CTRL_REGS_H
#define EDGE_CTRL_REGS_H

/* The driver takes its address from the DT node's reg; this copy is for the vectors. */
#define EDGE_CTRL_ADDR			0x42

#define EDGE_CTRL_REG_DEVICE_ID		0x00	/* 0x00-0x03 read in one go by probe() */
#define EDGE_CTRL_REG_FW_MAJOR		0x01	/* + FW_MINOR, read together */
#define EDGE_CTRL_REG_FW_MINOR		0x02	/* named for the vectors only */
#define EDGE_CTRL_REG_PROTOCOL		0x03
#define EDGE_CTRL_REG_ADC_LOW		0x10	/* + ADC_HIGH at 0x11, little-endian */
#define EDGE_CTRL_REG_BUTTON_STATE	0x12
#define EDGE_CTRL_REG_BUTTON_PRESSES	0x13
#define EDGE_CTRL_REG_LED		0x20
#define EDGE_CTRL_REG_STATUS		0x30	/* write-1-to-clear */

#define EDGE_CTRL_DEVICE_ID		0xED
#define EDGE_CTRL_BUTTON_PRESSED	0x01

/* The map this driver knows: 1.1 (ADC and button). Any 1.x from 1.1 on is compatible. */
#define EDGE_CTRL_PROTOCOL_MAJOR	1
#define EDGE_CTRL_PROTOCOL_MINOR	1

static inline int edge_ctrl_protocol_ok(unsigned int v)
{
	return (v >> 4) == EDGE_CTRL_PROTOCOL_MAJOR && (v & 0x0F) >= EDGE_CTRL_PROTOCOL_MINOR;
}

/* ADC_LOW, ADC_HIGH -> 0..4095; bits 7:4 of ADC_HIGH are not part of the value. */
static inline unsigned int edge_ctrl_adc(unsigned int lo, unsigned int hi)
{
	return (hi & 0x0F) << 8 | lo;
}

static inline int edge_ctrl_pressed(unsigned int state)
{
	return !!(state & EDGE_CTRL_BUTTON_PRESSED);
}

/* LED_CONTROL takes 0 (off) and 1 (on); the firmware drops anything else with BAD_VALUE. */
static inline int edge_ctrl_led_ok(unsigned int v)
{
	return v <= 1;
}

#endif
