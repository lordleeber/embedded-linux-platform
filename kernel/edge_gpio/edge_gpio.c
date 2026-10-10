// SPDX-License-Identifier: GPL-2.0
/*
 * edge_gpio - Step 4: platform driver that drives one LED described by DT.
 *
 * The DT node (dts/edge-gpio-overlay.dts) carries compatible = "edge,gpio-led"
 * and led-gpios. When the platform bus matches it, probe() takes the GPIO
 * through the descriptor API and registers /dev/edge_gpio:
 *
 *   echo 1 > /dev/edge_gpio    LED on   (logical; polarity comes from DT)
 *   echo 0 > /dev/edge_gpio    LED off
 *   cat /dev/edge_gpio         current logical state, "0\n" or "1\n"
 */
#include <linux/fs.h>
#include <linux/gpio/consumer.h>
#include <linux/kernel.h>
#include <linux/miscdevice.h>
#include <linux/mod_devicetable.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/platform_device.h>

struct edge_gpio {
	struct gpio_desc *led;
	struct miscdevice misc;
	struct mutex lock;	/* serialises value and the GPIO write */
	unsigned int value;
};

static struct edge_gpio *to_edge_gpio(struct file *file)
{
	/* misc_open() points private_data at our struct miscdevice. */
	return container_of(file->private_data, struct edge_gpio, misc);
}

static ssize_t edge_gpio_read(struct file *file, char __user *ubuf,
			      size_t count, loff_t *ppos)
{
	struct edge_gpio *eg = to_edge_gpio(file);
	char buf[2];

	mutex_lock(&eg->lock);
	buf[0] = '0' + eg->value;
	mutex_unlock(&eg->lock);
	buf[1] = '\n';

	return simple_read_from_buffer(ubuf, count, ppos, buf, sizeof(buf));
}

static ssize_t edge_gpio_write(struct file *file, const char __user *ubuf,
			       size_t count, loff_t *ppos)
{
	struct edge_gpio *eg = to_edge_gpio(file);
	unsigned int value;
	int ret;

	/* Parses into a local first, so a bad write leaves the LED alone. */
	ret = kstrtouint_from_user(ubuf, count, 10, &value);
	if (ret)
		return ret;
	if (value > 1)
		return -EINVAL;

	mutex_lock(&eg->lock);
	gpiod_set_value_cansleep(eg->led, value);
	eg->value = value;
	mutex_unlock(&eg->lock);

	return count;
}

static const struct file_operations edge_gpio_fops = {
	.owner	= THIS_MODULE,
	.read	= edge_gpio_read,
	.write	= edge_gpio_write,
	.llseek	= no_llseek,
};

static int edge_gpio_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct edge_gpio *eg;
	int ret;

	eg = devm_kzalloc(dev, sizeof(*eg), GFP_KERNEL);
	if (!eg)
		return -ENOMEM;

	/* Looks up "led-gpios"; OUT_LOW is logical off for either polarity. */
	eg->led = devm_gpiod_get(dev, "led", GPIOD_OUT_LOW);
	if (IS_ERR(eg->led))
		return dev_err_probe(dev, PTR_ERR(eg->led), "cannot get led gpio\n");

	mutex_init(&eg->lock);
	eg->misc.minor = MISC_DYNAMIC_MINOR;
	eg->misc.name = "edge_gpio";
	eg->misc.fops = &edge_gpio_fops;
	eg->misc.parent = dev;
	eg->misc.mode = 0666;
	ret = misc_register(&eg->misc);
	if (ret) {
		mutex_destroy(&eg->lock);
		return ret;
	}

	platform_set_drvdata(pdev, eg);
	dev_info(dev, "probed: led gpio acquired (%s)\n",
		 gpiod_is_active_low(eg->led) ? "active-low" : "active-high");
	return 0;
}

static int edge_gpio_remove(struct platform_device *pdev)
{
	struct edge_gpio *eg = platform_get_drvdata(pdev);

	misc_deregister(&eg->misc);
	/* Leave the LED off; devm then releases the GPIO line. */
	gpiod_set_value_cansleep(eg->led, 0);
	mutex_destroy(&eg->lock);
	dev_info(&pdev->dev, "removed\n");
	return 0;
}

static const struct of_device_id edge_gpio_of_match[] = {
	{ .compatible = "edge,gpio-led" },
	{ }
};
MODULE_DEVICE_TABLE(of, edge_gpio_of_match);

static struct platform_driver edge_gpio_driver = {
	.probe	= edge_gpio_probe,
	.remove	= edge_gpio_remove,
	.driver	= {
		.name = "edge_gpio",
		.of_match_table = edge_gpio_of_match,
		/*
		 * No sysfs unbind: eg is freed on unbind while an open file may
		 * still use it. rmmod is safe because .owner pins the module.
		 */
		.suppress_bind_attrs = true,
	},
};
module_platform_driver(edge_gpio_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Step 4: DT-described LED on a GPIO descriptor");
