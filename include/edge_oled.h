/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
/*
 * Step 10-a: the userspace interface of /dev/edge_oled (kernel/edge_oled).
 *
 *   write()  exactly EDGE_OLED_FRAME_SIZE bytes = one whole frame, sent to the
 *            panel before write() returns; any other size is -EINVAL and the
 *            frame is left as it was. The file offset is ignored (not used,
 *            not moved).
 *   read()   the last frame sent completely (SSD1306 cannot be read back over
 *            I2C, so this is the driver's copy, not what the chip holds). A
 *            write that failed half way does not change it, although the panel
 *            may already show part of the new frame. read() follows the file
 *            offset like a regular file: after reading the frame once, lseek()
 *            to 0 or use pread() to read it again.
 *   ioctl    EDGE_OLED_IOC_CLEAR: all pixels off; EDGE_OLED_IOC_FILL: every
 *            frame byte set to the __u8 argument (0xFF = all on).
 *
 * Frame layout = SSD1306 GDDRAM (as tools/ssd1306.h's Frame): byte
 * frame[page * 128 + x] holds column x of rows 8 * page .. 8 * page + 7,
 * bit 0 on top. The panel is fixed at 128x64.
 *
 * Magic 0xEB is shared with edge_test (include/edge_test_ioctl.h, nr 0x01 and
 * 0x02); edge_oled uses nr 0x10 and up. These numbers are ABI.
 */
#ifndef EDGE_OLED_H
#define EDGE_OLED_H

#include <linux/ioctl.h>
#include <linux/types.h>

#define EDGE_OLED_WIDTH		128
#define EDGE_OLED_HEIGHT	64
#define EDGE_OLED_PAGES		(EDGE_OLED_HEIGHT / 8)
#define EDGE_OLED_FRAME_SIZE	(EDGE_OLED_WIDTH * EDGE_OLED_PAGES)

#define EDGE_OLED_IOC_MAGIC	0xEB
#define EDGE_OLED_IOC_CLEAR	_IO(EDGE_OLED_IOC_MAGIC, 0x10)
#define EDGE_OLED_IOC_FILL	_IOW(EDGE_OLED_IOC_MAGIC, 0x11, __u8)

#endif /* EDGE_OLED_H */
