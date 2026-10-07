/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
/*
 * edge_test ioctl interface, shared by the kernel module (kernel/edge_test)
 * and userspace (apps/edge_test_cli.cpp, tests/test_edge_device.cpp).
 *
 * Magic 0xEB: not used by any _IO* definition in this Jetson's uapi headers
 * (L4T R36.4.7, kernel 5.15.148-tegra) and not listed in the upstream v5.15
 * Documentation/userspace-api/ioctl/ioctl-number.rst.
 *
 * The argument is a fixed-size __u32, so 32-bit and 64-bit userspace see the
 * same layout and the same ioctl numbers. These numbers are ABI: never reuse
 * or renumber an existing command, only append new nr values.
 */
#ifndef EDGE_TEST_IOCTL_H
#define EDGE_TEST_IOCTL_H

#include <linux/ioctl.h>
#include <linux/types.h>

#define EDGE_TEST_IOC_MAGIC	0xEB

/* Read the module's 32-bit value into *arg. */
#define EDGE_TEST_GET_VALUE	_IOR(EDGE_TEST_IOC_MAGIC, 0x01, __u32)
/* Replace the module's 32-bit value with *arg. */
#define EDGE_TEST_SET_VALUE	_IOW(EDGE_TEST_IOC_MAGIC, 0x02, __u32)

#endif /* EDGE_TEST_IOCTL_H */
