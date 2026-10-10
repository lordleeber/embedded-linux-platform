/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
/*
 * Step 5-b: one record returned by read() on /dev/edge_button.
 *
 * Shared by kernel/edge_button/edge_button.c and userspace. Fixed-size fields
 * only, 64-bit member first, so 32- and 64-bit programs see the same 16 bytes.
 */
#ifndef EDGE_BUTTON_H
#define EDGE_BUTTON_H

#include <linux/types.h>

struct edge_button_event {
	__u64 timestamp_ns;	/* CLOCK_MONOTONIC when the debounced state was taken */
	__u32 seq;		/* 1, 2, 3 ... per state change since load; a gap = lost events */
	__u32 pressed;		/* 1 = pressed, 0 = released */
};

#endif /* EDGE_BUTTON_H */
