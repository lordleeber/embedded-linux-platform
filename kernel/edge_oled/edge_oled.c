// SPDX-License-Identifier: GPL-2.0
/*
 * edge_oled - I2C client driver for a 128x64 SSD1306 OLED (Step 10-a), the
 * kernel side of what Step 9's oled_probe did from userspace.
 *
 *   DT node oled@3c under gen2_i2c (c240000.i2c = i2c-1, header pins 27/28)
 *     -> I2C core creates client 1-003c at boot
 *     -> insmod: compatible "edge,edge-ssd1306" -> edge_oled_probe():
 *        init sequence, blank frame, display on; then /dev/edge_oled
 *     -> write(1024 bytes) / ioctl CLEAR, FILL: update the frame, send it
 *     -> remove(): no more opens, display off, files still open get -ENODEV
 *
 * Buffer ownership: the driver keeps the last frame sent completely. write()
 * and the ioctls build the next frame in a temporary buffer, send it, and copy
 * it into the frame only when every message got through, so a bad pointer, a
 * wrong size or a failed transfer leaves the frame (and read()) as it was.
 * Every transfer is synchronous under the mutex: there is no timer or work
 * item that could still be pending when the device goes away.
 *
 * Errors: a transfer that fails (no ACK = -EREMOTEIO) is returned to the caller
 * once, not retried. It also clears ->initialized, because the usual cause is
 * the OLED losing power, after which the chip is back at its reset state
 * (display off, charge pump off): the next write sends the init sequence again.
 */
#include <linux/fs.h>
#include <linux/i2c.h>
#include <linux/kref.h>
#include <linux/miscdevice.h>
#include <linux/mod_devicetable.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/uaccess.h>

#include "edge_oled.h"
#include "edge_oled_proto.h"

struct edge_oled {
	struct i2c_client *client;	/* NULL once unbound; under lock */
	struct miscdevice misc;
	struct mutex lock;		/* client, frame, tx, initialized */
	struct kref ref;		/* the binding + one per open file */
	bool initialized;		/* init sequence sent and nothing failed since */
	u8 frame[EDGE_OLED_FRAME_SIZE];
	u8 tx[1 + EDGE_OLED_WIDTH];	/* control byte + one page */
};

static_assert(sizeof(edge_oled_init_seq) <= EDGE_OLED_WIDTH);

static void edge_oled_free(struct kref *ref)
{
	kfree(container_of(ref, struct edge_oled, ref));
}

/* One I2C write: [control][data]. Returns 0 or a negative errno. */
static int edge_oled_send(struct edge_oled *oled, u8 control, const u8 *data, size_t len)
{
	int ret;

	oled->tx[0] = control;
	memcpy(oled->tx + 1, data, len);
	ret = i2c_master_send(oled->client, oled->tx, len + 1);
	if (ret < 0)
		return ret;
	return (size_t)ret == len + 1 ? 0 : -EIO;
}

/* Put the frame src on the panel; first (re)initialise the chip if needed. */
static int edge_oled_flush(struct edge_oled *oled, const u8 *src)
{
	static const u8 on = EDGE_OLED_CMD_DISPLAY_ON;
	bool init = !oled->initialized;
	int page, ret;

	if (!oled->initialized) {
		ret = edge_oled_send(oled, EDGE_OLED_CONTROL_CMD, edge_oled_init_seq,
				     sizeof(edge_oled_init_seq));
		if (ret)
			goto out;
	}
	ret = edge_oled_send(oled, EDGE_OLED_CONTROL_CMD, edge_oled_window,
			     sizeof(edge_oled_window));
	for (page = 0; !ret && page < EDGE_OLED_PAGES; page++)
		ret = edge_oled_send(oled, EDGE_OLED_CONTROL_DATA,
				     src + page * EDGE_OLED_WIDTH, EDGE_OLED_WIDTH);
	/* Display ON after the frame, so the old RAM content never flashes up. */
	if (!ret && init)
		ret = edge_oled_send(oled, EDGE_OLED_CONTROL_CMD, &on, 1);
out:
	oled->initialized = ret == 0;
	return ret;
}

static struct edge_oled *to_oled(struct file *file)
{
	return container_of(file->private_data, struct edge_oled, misc);
}

/* misc_open() holds misc_mtx here, and misc_deregister() takes it: no race with remove. */
static int edge_oled_open(struct inode *inode, struct file *file)
{
	kref_get(&to_oled(file)->ref);
	return 0;
}

static int edge_oled_release(struct inode *inode, struct file *file)
{
	kref_put(&to_oled(file)->ref, edge_oled_free);
	return 0;
}

static ssize_t edge_oled_write(struct file *file, const char __user *buf, size_t count,
			       loff_t *ppos)
{
	struct edge_oled *oled = to_oled(file);
	u8 *next;
	int ret;

	if (count != EDGE_OLED_FRAME_SIZE)
		return -EINVAL;
	next = memdup_user(buf, count);
	if (IS_ERR(next))
		return PTR_ERR(next);

	mutex_lock(&oled->lock);
	if (!oled->client) {
		ret = -ENODEV;
	} else {
		ret = edge_oled_flush(oled, next);
		if (!ret)
			memcpy(oled->frame, next, count);
	}
	mutex_unlock(&oled->lock);
	kfree(next);
	return ret ? ret : (ssize_t)count;
}

static ssize_t edge_oled_read(struct file *file, char __user *buf, size_t count, loff_t *ppos)
{
	struct edge_oled *oled = to_oled(file);
	ssize_t ret = -ENODEV;

	/*
	 * copy_to_user() may fault and sleep, which a mutex allows; no page fault
	 * needs this lock (there is no mmap), so it cannot deadlock.
	 */
	mutex_lock(&oled->lock);
	if (oled->client)
		ret = simple_read_from_buffer(buf, count, ppos, oled->frame, EDGE_OLED_FRAME_SIZE);
	mutex_unlock(&oled->lock);
	return ret;
}

static long edge_oled_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	struct edge_oled *oled = to_oled(file);
	u8 value, *next;
	int ret;

	switch (cmd) {
	case EDGE_OLED_IOC_CLEAR:
		value = 0;
		break;
	case EDGE_OLED_IOC_FILL:
		if (get_user(value, (u8 __user *)arg))
			return -EFAULT;
		break;
	default:
		return -ENOTTY;
	}

	next = kmalloc(EDGE_OLED_FRAME_SIZE, GFP_KERNEL);
	if (!next)
		return -ENOMEM;
	memset(next, value, EDGE_OLED_FRAME_SIZE);

	mutex_lock(&oled->lock);
	if (!oled->client) {
		ret = -ENODEV;
	} else {
		ret = edge_oled_flush(oled, next);
		if (!ret)
			memcpy(oled->frame, next, EDGE_OLED_FRAME_SIZE);
	}
	mutex_unlock(&oled->lock);
	kfree(next);
	return ret;
}

static const struct file_operations edge_oled_fops = {
	.owner = THIS_MODULE,
	.open = edge_oled_open,
	.release = edge_oled_release,
	.write = edge_oled_write,
	.read = edge_oled_read,
	.unlocked_ioctl = edge_oled_ioctl,
	.compat_ioctl = compat_ptr_ioctl,
	.llseek = default_llseek,
};

static int edge_oled_probe(struct i2c_client *client)
{
	struct edge_oled *oled;
	int ret;

	/* Not devm_: an open file may use it after the binding is gone. */
	oled = kzalloc(sizeof(*oled), GFP_KERNEL);
	if (!oled)
		return -ENOMEM;
	oled->client = client;
	mutex_init(&oled->lock);
	kref_init(&oled->ref);

	/* Nobody at the address fails here with -EREMOTEIO; tried once, no retry. */
	ret = edge_oled_flush(oled, oled->frame);	/* all zero: a blank panel */
	if (ret) {
		kfree(oled);
		return dev_err_probe(&client->dev, ret, "cannot initialise the panel\n");
	}

	oled->misc.minor = MISC_DYNAMIC_MINOR;
	oled->misc.name = "edge_oled";
	oled->misc.fops = &edge_oled_fops;
	oled->misc.parent = &client->dev;
	/* A dev board's display: anyone logged in may draw on it. */
	oled->misc.mode = 0666;
	i2c_set_clientdata(client, oled);
	ret = misc_register(&oled->misc);
	if (ret) {
		static const u8 off = EDGE_OLED_CMD_DISPLAY_OFF;

		/* The flush above turned the display on; nobody will own it now. */
		edge_oled_send(oled, EDGE_OLED_CONTROL_CMD, &off, 1);
		kfree(oled);
		return dev_err_probe(&client->dev, ret, "cannot register /dev/edge_oled\n");
	}

	dev_info(&client->dev, "probed: %dx%d, /dev/%s\n", EDGE_OLED_WIDTH, EDGE_OLED_HEIGHT,
		 oled->misc.name);
	return 0;
}

static int edge_oled_remove(struct i2c_client *client)
{
	struct edge_oled *oled = i2c_get_clientdata(client);
	static const u8 off = EDGE_OLED_CMD_DISPLAY_OFF;

	misc_deregister(&oled->misc);	/* no new opens from here on */

	mutex_lock(&oled->lock);
	/* Dark panel = no driver; a failure here (OLED unplugged) changes nothing. */
	if (edge_oled_send(oled, EDGE_OLED_CONTROL_CMD, &off, 1))
		dev_warn(&client->dev, "display off failed\n");
	oled->client = NULL;		/* open files get -ENODEV */
	mutex_unlock(&oled->lock);

	kref_put(&oled->ref, edge_oled_free);
	dev_info(&client->dev, "removed\n");
	return 0;
}

static const struct of_device_id edge_oled_of_match[] = {
	{ .compatible = "edge,edge-ssd1306" },
	{ }
};
MODULE_DEVICE_TABLE(of, edge_oled_of_match);

static const struct i2c_device_id edge_oled_id[] = {
	{ "edge_oled", 0 },
	{ }
};
MODULE_DEVICE_TABLE(i2c, edge_oled_id);

static struct i2c_driver edge_oled_driver = {
	.driver = {
		.name = "edge_oled",
		.of_match_table = edge_oled_of_match,
	},
	.probe_new = edge_oled_probe,
	.remove = edge_oled_remove,
	.id_table = edge_oled_id,
};
module_i2c_driver(edge_oled_driver);

MODULE_DESCRIPTION("SSD1306 128x64 OLED I2C driver with /dev/edge_oled (Step 10-a)");
MODULE_LICENSE("GPL");
