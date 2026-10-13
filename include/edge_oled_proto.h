/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Step 10-a: the SSD1306 bytes edge_oled.ko sends, the same ones Step 9's
 * tools/ssd1306.h sent from userspace (tests/test_edge_oled_proto.cpp compares
 * them byte by byte). Plain C, so the kernel can include it.
 *
 * Every I2C write is [control byte][stream]: 0x00 = the stream is commands,
 * 0x40 = the stream is GDDRAM data.
 */
#ifndef EDGE_OLED_PROTO_H
#define EDGE_OLED_PROTO_H

#ifdef __KERNEL__
#include <linux/types.h>
#else
#include <stdint.h>
typedef uint8_t u8;
#endif

#define EDGE_OLED_CONTROL_CMD		0x00
#define EDGE_OLED_CONTROL_DATA		0x40
#define EDGE_OLED_CMD_DISPLAY_OFF	0xAE
#define EDGE_OLED_CMD_DISPLAY_ON	0xAF

/* Every setting the frame layout depends on (see tools/ssd1306.h for each). */
static const u8 edge_oled_init_seq[] = {
	EDGE_OLED_CMD_DISPLAY_OFF,
	0xD5, 0x80,	/* clock divide / oscillator (reset value) */
	0xA8, 0x3F,	/* multiplex: 64 rows */
	0xD3, 0x00,	/* display offset 0 */
	0x40,		/* start line 0 */
	0x8D, 0x14,	/* charge pump on */
	0x20, 0x00,	/* horizontal addressing */
	0xA1,		/* segment remap: column 127 -> SEG0 */
	0xC8,		/* COM scan remapped: page 0 at the top */
	0xDA, 0x12,	/* COM pins: alternative (128x64) */
	0x81, 0xCF,	/* contrast */
	0xD9, 0xF1,	/* pre-charge period */
	0xDB, 0x40,	/* VCOMH deselect level */
	0x2E,		/* scrolling off */
	0xA4,		/* pixels follow RAM */
	0xA6,		/* normal, not inverse */
};

/* Columns 0..127, pages 0..7; also moves the address pointer to (0, 0). */
static const u8 edge_oled_window[] = { 0x21, 0x00, 0x7F, 0x22, 0x00, 0x07 };

#endif /* EDGE_OLED_PROTO_H */
