// SPDX-License-Identifier: GPL-2.0
/*
 * edge_ctrl - I2C client driver for our own STM32F103 peripheral (Step 13). The Blue
 * Pill's firmware (Steps 11-12-b) answers at 0x42 with register map v1.1; this driver
 * hides the register protocol behind one sysfs file per value.
 *
 *   DT node controller@42 under gen2_i2c (c240000.i2c = i2c-1, header pins 27 / 28)
 *     -> I2C core creates client 1-0042 at boot
 *     -> insmod: compatible "edge,edge-ctrl" matches -> edge_ctrl_probe() checks
 *        DEVICE_ID and PROTOCOL_VERSION
 *     -> the driver core adds edge_ctrl_groups to /sys/bus/i2c/devices/1-0042/
 *     -> cat .../adc: adc_show() -> read_reg(0x10, 2 bytes) -> "2068"
 *     -> echo 1 > .../led: led_store() -> write_reg(0x20, 1) -> PC13 lights up
 *
 * Every access goes to the board (no cache, no polling). A failed transfer reaches the
 * reader as its errno and nothing else happens: when the whole bus times out (Step 11,
 * SCL shorted to GND), that is not this chip's fault, tegra-i2c already logs it, and
 * the next access simply tries again once the bus is back.
 */
#include <linux/device.h>
#include <linux/i2c.h>
#include <linux/kernel.h>
#include <linux/mod_devicetable.h>
#include <linux/module.h>
#include <linux/sysfs.h>

#include "edge_ctrl_regs.h"

/*
 * Pointer write + repeated START + len-byte read, as one i2c_transfer(): the adapter
 * stays locked for both messages, so no other bus user can move the firmware's pointer
 * in between, and every byte of the read comes from one snapshot (register-map.md).
 */
static int read_reg(struct i2c_client *client, u8 reg, u8 *buf, u16 len)
{
	struct i2c_msg msgs[2] = {
		{ .addr = client->addr, .flags = 0, .len = 1, .buf = &reg },
		{ .addr = client->addr, .flags = I2C_M_RD, .len = len, .buf = buf },
	};
	int ret = i2c_transfer(client->adapter, msgs, 2);

	if (ret == 2)
		return 0;
	return ret < 0 ? ret : -EIO;
}

/* The firmware ACKs every byte; a refused value only shows up in STATUS. */
static int write_reg(struct i2c_client *client, u8 reg, u8 value)
{
	u8 buf[2] = { reg, value };
	int ret = i2c_master_send(client, buf, 2);

	if (ret == 2)
		return 0;
	return ret < 0 ? ret : -EIO;
}

static int read_u8(struct device *dev, u8 reg, u8 *val)
{
	return read_reg(to_i2c_client(dev), reg, val, 1);
}

static ssize_t device_id_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	u8 v;
	int ret = read_u8(dev, EDGE_CTRL_REG_DEVICE_ID, &v);

	return ret ? ret : sysfs_emit(buf, "%#04x\n", v);
}

static ssize_t firmware_version_show(struct device *dev, struct device_attribute *attr,
				     char *buf)
{
	u8 v[2];
	int ret = read_reg(to_i2c_client(dev), EDGE_CTRL_REG_FW_MAJOR, v, 2);

	return ret ? ret : sysfs_emit(buf, "%u.%u\n", v[0], v[1]);
}

static ssize_t protocol_version_show(struct device *dev, struct device_attribute *attr,
				     char *buf)
{
	u8 v;
	int ret = read_u8(dev, EDGE_CTRL_REG_PROTOCOL, &v);

	return ret ? ret : sysfs_emit(buf, "%u.%u\n", v >> 4, v & 0x0F);
}

/* LOW and HIGH in one read: two reads may come from two conversions. */
static ssize_t adc_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	u8 v[2];
	int ret = read_reg(to_i2c_client(dev), EDGE_CTRL_REG_ADC_LOW, v, 2);

	return ret ? ret : sysfs_emit(buf, "%u\n", edge_ctrl_adc(v[0], v[1]));
}

static ssize_t button_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	u8 v;
	int ret = read_u8(dev, EDGE_CTRL_REG_BUTTON_STATE, &v);

	return ret ? ret : sysfs_emit(buf, "%d\n", edge_ctrl_pressed(v));
}

static ssize_t button_presses_show(struct device *dev, struct device_attribute *attr,
				   char *buf)
{
	u8 v;
	int ret = read_u8(dev, EDGE_CTRL_REG_BUTTON_PRESSES, &v);

	return ret ? ret : sysfs_emit(buf, "%u\n", v);
}

static ssize_t led_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	u8 v;
	int ret = read_u8(dev, EDGE_CTRL_REG_LED, &v);

	return ret ? ret : sysfs_emit(buf, "%u\n", v);
}

/*
 * Only 0 and 1 go out: anything else the firmware would ACK, drop and flag as
 * BAD_VALUE, and the writer would see success. Refusing it here gives EINVAL instead.
 */
static ssize_t led_store(struct device *dev, struct device_attribute *attr,
			 const char *buf, size_t count)
{
	unsigned int v;
	int ret = kstrtouint(buf, 0, &v);

	if (ret || !edge_ctrl_led_ok(v))
		return -EINVAL;
	ret = write_reg(to_i2c_client(dev), EDGE_CTRL_REG_LED, v);
	return ret ? ret : count;
}

static ssize_t status_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	u8 v;
	int ret = read_u8(dev, EDGE_CTRL_REG_STATUS, &v);

	return ret ? ret : sysfs_emit(buf, "%#04x\n", v);
}

/* Write-1-to-clear, passed through: "echo 0x01" clears RO_WRITE, "echo 0xff" all. */
static ssize_t status_store(struct device *dev, struct device_attribute *attr,
			    const char *buf, size_t count)
{
	unsigned int v;
	int ret = kstrtouint(buf, 0, &v);

	if (ret || v > 0xFF)
		return -EINVAL;
	ret = write_reg(to_i2c_client(dev), EDGE_CTRL_REG_STATUS, v);
	return ret ? ret : count;
}

static DEVICE_ATTR_RO(device_id);
static DEVICE_ATTR_RO(firmware_version);
static DEVICE_ATTR_RO(protocol_version);
static DEVICE_ATTR_RO(adc);
static DEVICE_ATTR_RO(button);
static DEVICE_ATTR_RO(button_presses);
static DEVICE_ATTR_RW(led);
static DEVICE_ATTR_RW(status);

static struct attribute *edge_ctrl_attrs[] = {
	&dev_attr_device_id.attr,
	&dev_attr_firmware_version.attr,
	&dev_attr_protocol_version.attr,
	&dev_attr_adc.attr,
	&dev_attr_button.attr,
	&dev_attr_button_presses.attr,
	&dev_attr_led.attr,
	&dev_attr_status.attr,
	NULL
};
ATTRIBUTE_GROUPS(edge_ctrl);

static int edge_ctrl_probe(struct i2c_client *client)
{
	u8 id[4], status;
	int ret;

	/* DEVICE_ID, FW_MAJOR, FW_MINOR, PROTOCOL_VERSION; no ACK fails with -EREMOTEIO. */
	ret = read_reg(client, EDGE_CTRL_REG_DEVICE_ID, id, 4);
	if (ret)
		return dev_err_probe(&client->dev, ret, "cannot read DEVICE_ID\n");
	if (id[0] != EDGE_CTRL_DEVICE_ID)
		return dev_err_probe(&client->dev, -ENODEV, "DEVICE_ID 0x%02x, not 0x%02x\n",
				     id[0], EDGE_CTRL_DEVICE_ID);
	if (!edge_ctrl_protocol_ok(id[3]))
		return dev_err_probe(&client->dev, -ENODEV,
				     "register map %u.%u, need %u.x from %u.%u on\n",
				     id[3] >> 4, id[3] & 0x0F, EDGE_CTRL_PROTOCOL_MAJOR,
				     EDGE_CTRL_PROTOCOL_MAJOR, EDGE_CTRL_PROTOCOL_MINOR);

	/* STATUS is left alone: its flags (RESET included) belong to whoever reads them. */
	ret = read_reg(client, EDGE_CTRL_REG_STATUS, &status, 1);
	if (ret)
		return dev_err_probe(&client->dev, ret, "cannot read STATUS\n");

	dev_info(&client->dev, "probed: FW %u.%u, register map %u.%u, STATUS 0x%02x\n",
		 id[1], id[2], id[3] >> 4, id[3] & 0x0F, status);
	return 0;
}

static int edge_ctrl_remove(struct i2c_client *client)
{
	/* The attributes leave with the binding; the board keeps its LED state. */
	dev_info(&client->dev, "removed\n");
	return 0;
}

static const struct of_device_id edge_ctrl_of_match[] = {
	{ .compatible = "edge,edge-ctrl" },
	{ }
};
MODULE_DEVICE_TABLE(of, edge_ctrl_of_match);

static const struct i2c_device_id edge_ctrl_id[] = {
	{ "edge_ctrl", 0 },
	{ }
};
MODULE_DEVICE_TABLE(i2c, edge_ctrl_id);

static struct i2c_driver edge_ctrl_driver = {
	.driver = {
		.name = "edge_ctrl",
		.of_match_table = edge_ctrl_of_match,
		.dev_groups = edge_ctrl_groups,
	},
	.probe_new = edge_ctrl_probe,
	.remove = edge_ctrl_remove,
	.id_table = edge_ctrl_id,
};
module_i2c_driver(edge_ctrl_driver);

MODULE_DESCRIPTION("I2C client driver for the project's STM32F103 peripheral (Step 13)");
MODULE_LICENSE("GPL");
