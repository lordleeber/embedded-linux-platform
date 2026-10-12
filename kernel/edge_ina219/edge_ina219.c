// SPDX-License-Identifier: GPL-2.0
/*
 * edge_ina219 - our own I2C client driver for the INA219 on the Waveshare UPS
 * Power Module (C). Step 7 wrote the device logic; Step 8 hands the values to
 * the hwmon subsystem instead of private sysfs attributes.
 *
 *   DT node ina219@41 under hdr40_i2c1 (c250000.i2c = i2c-7)
 *     -> I2C core creates client 7-0041 at boot
 *     -> insmod: compatible "edge,edge-ina219" matches -> edge_ina219_probe()
 *     -> devm_hwmon_device_register_with_info() creates hwmonN under 7-0041
 *     -> cat /sys/class/hwmon/hwmonN/in1_input: the hwmon core calls
 *        edge_ina219_read(), which reads the chip on every access (no cache,
 *        no polling) and returns either a value in hwmon units or an errno
 *
 * The chip sends every 16-bit register MSB first; an SMBus word is LSB first,
 * so all access goes through the _swapped SMBus helpers. probe() writes the
 * vendor sample's Calibration and Config (include/edge_ina219_conv.h), so the
 * Current and Power registers work after a power cycle too. Conversions read
 * the Calibration back from the chip each time, as ina219_raw does: if someone
 * rewrites it from userspace, both still decode the same way.
 */
#include <linux/device.h>
#include <linux/err.h>
#include <linux/hwmon.h>
#include <linux/i2c.h>
#include <linux/kernel.h>
#include <linux/mod_devicetable.h>
#include <linux/module.h>

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

/* Shunt voltage in mV (hwmon unit), signed, rounded from the 10 uV steps. */
static int read_shunt_voltage(struct i2c_client *client, s32 *mv)
{
	int ret = read_reg16(client, EDGE_INA219_REG_SHUNT);

	if (ret < 0)
		return ret;
	*mv = edge_ina219_shunt_mv(ret);
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

/* hwmon callbacks: in0 = shunt, in1 = bus (the upstream ina2xx order), curr1, power1. */
static umode_t edge_ina219_is_visible(const void *data, enum hwmon_sensor_types type,
				      u32 attr, int channel)
{
	return 0444;
}

static int edge_ina219_read(struct device *dev, enum hwmon_sensor_types type,
			    u32 attr, int channel, long *val)
{
	struct i2c_client *client = dev_get_drvdata(dev);
	u16 raw, cal;
	s32 mv;
	int ret;

	switch (type) {
	case hwmon_in:		/* mV */
		ret = channel ? read_bus_voltage(client, &mv) : read_shunt_voltage(client, &mv);
		if (ret)
			return ret;
		*val = mv;
		return 0;
	case hwmon_curr:	/* mA */
		ret = read_calibrated(client, EDGE_INA219_REG_CURRENT, &raw, &cal);
		if (ret)
			return ret;
		*val = edge_ina219_current_ma(raw, cal, EDGE_INA219_SHUNT_MOHM);
		return 0;
	case hwmon_power:	/* uW */
		ret = read_calibrated(client, EDGE_INA219_REG_POWER, &raw, &cal);
		if (ret)
			return ret;
		*val = edge_ina219_power_uw(raw, cal, EDGE_INA219_SHUNT_MOHM);
		return 0;
	default:
		return -EOPNOTSUPP;
	}
}

static const char *const edge_ina219_in_labels[] = { "shunt", "bus" };

static int edge_ina219_read_string(struct device *dev, enum hwmon_sensor_types type,
				   u32 attr, int channel, const char **str)
{
	*str = edge_ina219_in_labels[channel];	/* only the in channels have labels */
	return 0;
}

static const struct hwmon_ops edge_ina219_hwmon_ops = {
	.is_visible = edge_ina219_is_visible,
	.read = edge_ina219_read,
	.read_string = edge_ina219_read_string,
};

static const struct hwmon_channel_info *edge_ina219_info[] = {
	HWMON_CHANNEL_INFO(in, HWMON_I_INPUT | HWMON_I_LABEL, HWMON_I_INPUT | HWMON_I_LABEL),
	HWMON_CHANNEL_INFO(curr, HWMON_C_INPUT),
	HWMON_CHANNEL_INFO(power, HWMON_P_INPUT),
	NULL
};

static const struct hwmon_chip_info edge_ina219_chip_info = {
	.ops = &edge_ina219_hwmon_ops,
	.info = edge_ina219_info,
};

static int edge_ina219_probe(struct i2c_client *client)
{
	struct device *hwmon;
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

	/*
	 * devm_: the hwmon device goes away when this binding does (unbind, rmmod,
	 * the adapter disappearing), so no stale hwmonN is left behind.
	 */
	hwmon = devm_hwmon_device_register_with_info(&client->dev, "edge_ina219", client,
						     &edge_ina219_chip_info, NULL);
	if (IS_ERR(hwmon))
		return dev_err_probe(&client->dev, PTR_ERR(hwmon), "cannot register hwmon\n");

	dev_info(&client->dev, "probed: Config 0x%04X -> 0x%04X, Cal %u, shunt %d mohm, %s\n",
		 config, EDGE_INA219_CONFIG, EDGE_INA219_CAL, EDGE_INA219_SHUNT_MOHM,
		 dev_name(hwmon));
	return 0;
}

static int edge_ina219_remove(struct i2c_client *client)
{
	/* The chip keeps converting; nothing of ours to free (devm removes hwmonN). */
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
	},
	.probe_new = edge_ina219_probe,
	.remove = edge_ina219_remove,
	.id_table = edge_ina219_id,
};
module_i2c_driver(edge_ina219_driver);

MODULE_DESCRIPTION("INA219 I2C client driver with hwmon (Steps 7-8)");
MODULE_LICENSE("GPL");
