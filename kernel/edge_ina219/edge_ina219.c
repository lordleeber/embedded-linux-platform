// SPDX-License-Identifier: GPL-2.0
/*
 * edge_ina219 - Step 7: our own I2C client driver for the INA219 on the
 * Waveshare UPS Power Module (C).
 *
 *   DT node ina219@41 under hdr40_i2c1 (c250000.i2c = i2c-7)
 *     -> I2C core creates client 7-0041 at boot
 *     -> insmod: compatible "edge,edge-ina219" matches -> edge_ina219_probe()
 *     -> sysfs attributes in /sys/bus/i2c/devices/7-0041/ read the chip on
 *        every access (no cache, no polling)
 *
 * The chip sends every 16-bit register MSB first; an SMBus word is LSB first,
 * so all access goes through the _swapped SMBus helpers. probe() writes the
 * vendor sample's Calibration and Config (include/edge_ina219_conv.h), so the
 * Current and Power registers work after a power cycle too. Conversions read
 * the Calibration back from the chip each time, as ina219_raw does: if someone
 * rewrites it from userspace, both still decode the same way.
 *
 * The attributes are a private interface for this step; Step 8 replaces them
 * with the standard hwmon ones.
 */
#include <linux/device.h>
#include <linux/i2c.h>
#include <linux/kernel.h>
#include <linux/mod_devicetable.h>
#include <linux/module.h>
#include <linux/sysfs.h>

#include "edge_ina219_conv.h"

/* Returns the register value (0..0xFFFF) or a negative errno. */
static int read_reg16(struct i2c_client *client, u8 reg)
{
	return i2c_smbus_read_word_swapped(client, reg);
}

static int write_reg16(struct i2c_client *client, u8 reg, u16 value)
{
	return i2c_smbus_write_word_swapped(client, reg, value);
}

/* Bus voltage in mV, status bits dropped. */
static int read_bus_voltage(struct i2c_client *client, s32 *mv)
{
	int ret = read_reg16(client, EDGE_INA219_REG_BUS);

	if (ret < 0)
		return ret;
	*mv = edge_ina219_bus_mv(ret);
	return 0;
}

/* Shunt voltage in uV, signed. */
static int read_shunt_voltage(struct i2c_client *client, s32 *uv)
{
	int ret = read_reg16(client, EDGE_INA219_REG_SHUNT);

	if (ret < 0)
		return ret;
	*uv = edge_ina219_shunt_uv(ret);
	return 0;
}

/* A register that needs Current_LSB (Current or Power) plus the Calibration. */
static int read_calibrated(struct i2c_client *client, u8 reg, u16 *raw, u16 *cal)
{
	int ret = read_reg16(client, EDGE_INA219_REG_CAL);

	if (ret < 0)
		return ret;
	if (ret == 0)
		return -ENODATA;	/* power-on value: the chip computes nothing */
	*cal = ret;
	ret = read_reg16(client, reg);
	if (ret < 0)
		return ret;
	*raw = ret;
	return 0;
}

static ssize_t registers_show(struct device *dev, struct device_attribute *attr,
			      char *buf)
{
	struct i2c_client *client = to_i2c_client(dev);
	int len = 0;
	u8 reg;

	for (reg = 0; reg < EDGE_INA219_NUM_REGS; reg++) {
		int ret = read_reg16(client, reg);

		if (ret < 0)
			return ret;
		len += sysfs_emit_at(buf, len, "0x%04X%c", ret,
				     reg == EDGE_INA219_NUM_REGS - 1 ? '\n' : ' ');
	}
	return len;
}
static DEVICE_ATTR_RO(registers);

static ssize_t bus_mv_show(struct device *dev, struct device_attribute *attr,
			   char *buf)
{
	s32 mv;
	int ret = read_bus_voltage(to_i2c_client(dev), &mv);

	return ret ? ret : sysfs_emit(buf, "%d\n", mv);
}
static DEVICE_ATTR_RO(bus_mv);

static ssize_t shunt_uv_show(struct device *dev, struct device_attribute *attr,
			     char *buf)
{
	s32 uv;
	int ret = read_shunt_voltage(to_i2c_client(dev), &uv);

	return ret ? ret : sysfs_emit(buf, "%d\n", uv);
}
static DEVICE_ATTR_RO(shunt_uv);

static ssize_t current_ua_show(struct device *dev, struct device_attribute *attr,
			       char *buf)
{
	u16 raw, cal;
	int ret = read_calibrated(to_i2c_client(dev), EDGE_INA219_REG_CURRENT, &raw, &cal);

	if (ret)
		return ret;
	return sysfs_emit(buf, "%lld\n",
			  edge_ina219_current_ua(raw, cal, EDGE_INA219_SHUNT_MOHM));
}
static DEVICE_ATTR_RO(current_ua);

static ssize_t power_uw_show(struct device *dev, struct device_attribute *attr,
			     char *buf)
{
	u16 raw, cal;
	int ret = read_calibrated(to_i2c_client(dev), EDGE_INA219_REG_POWER, &raw, &cal);

	if (ret)
		return ret;
	return sysfs_emit(buf, "%lld\n",
			  edge_ina219_power_uw(raw, cal, EDGE_INA219_SHUNT_MOHM));
}
static DEVICE_ATTR_RO(power_uw);

static struct attribute *edge_ina219_attrs[] = {
	&dev_attr_registers.attr,
	&dev_attr_bus_mv.attr,
	&dev_attr_shunt_uv.attr,
	&dev_attr_current_ua.attr,
	&dev_attr_power_uw.attr,
	NULL,
};
ATTRIBUTE_GROUPS(edge_ina219);

static int edge_ina219_probe(struct i2c_client *client)
{
	int config, cal, ret;

	/* Is anyone there? No ACK at this address fails here with -EREMOTEIO. */
	config = read_reg16(client, EDGE_INA219_REG_CONFIG);
	if (config < 0)
		return dev_err_probe(&client->dev, config, "cannot read Config\n");

	/*
	 * Calibration first: Current and Power use it from the next conversion on,
	 * and writing Config restarts the conversion.
	 */
	ret = write_reg16(client, EDGE_INA219_REG_CAL, EDGE_INA219_CAL);
	if (ret)
		return dev_err_probe(&client->dev, ret, "cannot write Calibration\n");
	ret = write_reg16(client, EDGE_INA219_REG_CONFIG, EDGE_INA219_CONFIG);
	if (ret)
		return dev_err_probe(&client->dev, ret, "cannot write Config\n");

	/*
	 * INA219 has no ID register: an ACK only proves something answers. A chip
	 * that does not hand back what we just wrote is not the one we expect.
	 */
	cal = read_reg16(client, EDGE_INA219_REG_CAL);
	ret = read_reg16(client, EDGE_INA219_REG_CONFIG);
	if (cal < 0 || ret < 0)
		return dev_err_probe(&client->dev, cal < 0 ? cal : ret, "cannot read back\n");
	if (cal != EDGE_INA219_CAL || ret != EDGE_INA219_CONFIG)
		return dev_err_probe(&client->dev, -ENODEV,
				     "read back Cal 0x%04X Config 0x%04X: not an INA219?\n",
				     cal, ret);

	dev_info(&client->dev, "probed: Config 0x%04X -> 0x%04X, Cal %u, shunt %d mohm\n",
		 config, EDGE_INA219_CONFIG, EDGE_INA219_CAL, EDGE_INA219_SHUNT_MOHM);
	return 0;
}

static int edge_ina219_remove(struct i2c_client *client)
{
	/* The chip keeps converting; nothing of ours to free (attributes go with the device). */
	dev_info(&client->dev, "removed\n");
	return 0;
}

static const struct of_device_id edge_ina219_of_match[] = {
	{ .compatible = "edge,edge-ina219" },
	{ }
};
MODULE_DEVICE_TABLE(of, edge_ina219_of_match);

static const struct i2c_device_id edge_ina219_id[] = {
	{ "edge_ina219", 0 },
	{ }
};
MODULE_DEVICE_TABLE(i2c, edge_ina219_id);

static struct i2c_driver edge_ina219_driver = {
	.driver = {
		.name = "edge_ina219",
		.of_match_table = edge_ina219_of_match,
		.dev_groups = edge_ina219_groups,
	},
	.probe_new = edge_ina219_probe,
	.remove = edge_ina219_remove,
	.id_table = edge_ina219_id,
};
module_i2c_driver(edge_ina219_driver);

MODULE_DESCRIPTION("Step 7: INA219 I2C client driver (private sysfs attributes)");
MODULE_LICENSE("GPL");
